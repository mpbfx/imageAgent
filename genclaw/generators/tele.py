"""TeleImage img2img 生成器(通过 SSH 调用自托管 Qwen-Image-Edit)。

跟所有其它 ImageGenerator 一样的接口:``generate(prompt, sketch_path, output_path)``,
但底层走的是自托管在远端 GPU 机器上的 ``QwenImageEditPlusPipeline``
(TeleEdit 背后的模型),而不是托管 HTTP API。SSH 桥接流程:

1. 本地 base64 编码 code sketch
2. 把 sketch + 一次性 runner 脚本传到服务器的 ``/tmp``（绝不碰远端项目树）
3. 在一块空闲 GPU 上跑纯 image-to-image（``pipe(image=sketch, prompt=...)``,
   **不**用 mask）在服务器上跑
4. 把生成的 PNG 拷回本地

为什么是「纯 img2img」而不是「mask inpainting」——已经验证：
纯 img2img 把整张 sketch 当条件,保结构+加材质/光照;mask 模式会重绘
区域,在这里是错误的工具(它是「上色工」,不是「画家」)。

环境变量(从 .env 加载,跟其它 provider 一致):
- GENCLAW_TELE_SSH_HOST / _PORT / _USER / _KEY -- SSH 目标与身份
- GENCLAW_TELE_MODEL_PATH  -- 服务器上 base_model 目录
- GENCLAW_TELE_PYTHON      -- 服务器上要执行的 python(配 venv)
- GENCLAW_TELE_GPU         -- CUDA_VISIBLE_DEVICES 值(默认 "1")
- GENCLAW_TELE_STEPS       -- num_inference_steps(默认 30)

安全/环境注意:本模块会 shell out 到 ssh/scp 并在远端跑模型。只用于受信任的
自托管 GPU 服务器。凭据/host 全部走环境变量,绝不硬编码。
"""

# 中文补充说明：
# TeleImg2ImgGenerator 是「自托管 GPU 后端」的接入点。设计上做了三件事
# 让它能安全地塞进统一 pipeline:
#   1) 接口与 mock / Gemini 完全一致 -> pipeline 编排无感切换
#   2) 所有文件操作只走 /tmp + 一次性 runner 脚本,不污染服务器项目树
#   3) 任务族(文字 / 材质)决定 rerender 强度：长文字任务要「轻」,否则
#      代码画出来的字形会被改坏;材质任务要「重」,否则还是「矢量画」既视感。

from __future__ import annotations

import base64
import io
import json
import os
import posixpath
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Optional

from genclaw.config import ProviderConfig, ProviderNotConfiguredError
from genclaw.generators.base import GenerationResult, ImageGenerator
from genclaw.generators.external import _instruction, _rerender_strength

# 环境变量名常量——集中定义,避免「字符串魔法」散落各处。
ENV_HOST = "GENCLAW_TELE_SSH_HOST"
ENV_PORT = "GENCLAW_TELE_SSH_PORT"
ENV_USER = "GENCLAW_TELE_SSH_USER"
ENV_KEY = "GENCLAW_TELE_SSH_KEY"
ENV_MODEL_PATH = "GENCLAW_TELE_MODEL_PATH"
ENV_PYTHON = "GENCLAW_TELE_PYTHON"
ENV_GPU = "GENCLAW_TELE_GPU"
ENV_STEPS = "GENCLAW_TELE_STEPS"
ENV_WORKDIR = "GENCLAW_TELE_WORKDIR"
ENV_SERVICE_PORT = "GENCLAW_TELE_SERVICE_PORT"
DEFAULT_RENDER_STEPS = 28
DEFAULT_RENDER_TRUE_CFG = 4.5
DEFAULT_RENDER_GUIDANCE = 1.0
RERENDER_PARAMS = {
    "low": {
        "num_inference_steps": 24,
        "true_cfg_scale": 3.5,
        "guidance_scale": 1.0,
    },
    "medium": {
        "num_inference_steps": 32,
        "true_cfg_scale": 5.0,
        "guidance_scale": 1.1,
    },
    "high": {
        "num_inference_steps": 52,
        "true_cfg_scale": 7.5,
        "guidance_scale": 1.8,
    },
}


class TeleImg2ImgGenerator(ImageGenerator):
    """通过 SSH 调度自托管 Qwen-Image-Edit 的 sketch-条件 img2img。"""

    name = "tele-img2img"

    def __init__(self, config: Optional[ProviderConfig] = None, env: Optional[dict] = None):
        self.config = config or ProviderConfig.from_env()
        # 允许测试时显式传入 env dict,避免污染 os.environ。
        e = os.environ if env is None else env
        self.host = e.get(ENV_HOST)
        self.port = e.get(ENV_PORT, "30022")
        self.user = e.get(ENV_USER)
        self.key = e.get(ENV_KEY)
        self.model_path = e.get(ENV_MODEL_PATH)
        self.python = e.get(ENV_PYTHON)
        self.gpu = e.get(ENV_GPU, "1")
        self.steps = e.get(ENV_STEPS, "30")
        self.service_port = e.get(ENV_SERVICE_PORT, "18765")
        self.workdir = e.get(ENV_WORKDIR) or self._infer_workdir(self.model_path)

    def _require(self) -> None:
        """检查必填环境变量;缺哪个就抛带引导信息的 ProviderNotConfiguredError。"""
        missing = [
            n
            for n, v in [
                (ENV_HOST, self.host),
                (ENV_USER, self.user),
                (ENV_KEY, self.key),
                (ENV_MODEL_PATH, self.model_path),
                (ENV_PYTHON, self.python),
            ]
            if not v
        ]
        if missing:
            raise ProviderNotConfiguredError(
                self.name,
                ", ".join(missing),
                "set the self-hosted TeleImage SSH/model env vars in .env "
                "(host, user, key, model path, server python).",
            )

    def _ssh_base(self) -> list[str]:
        """构造共用的 ssh 命令前缀。

        这里堆了一堆 -o 选项,都是有原因的:
          - PubkeyAcceptedAlgorithms / HostkeyAlgorithms: 服务器只支持 ssh-rsa
            老算法(某些自托管 GPU 主机常见),默认会被 OpenSSH 拒绝。
          - BatchMode=yes: 失败时不要弹密码提示,直接挂掉。
          - ConnectTimeout=20: 网络问题别让我们卡半小时。
          - StrictHostKeyChecking=accept-new: 第一次连接受新 host key
            而不是 fail,后续如果 host key 变了(中间人)才会拒绝。
          - LogLevel=ERROR: 不让 ssh 噪音进 stdout/stderr 干扰日志。
        """
        return [
            "ssh", "-i", self.key, "-p", self.port,
            "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
            "-o", "HostkeyAlgorithms=+ssh-rsa",
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "LogLevel=ERROR",
        ]

    def _scp(self, src: str, dst: str) -> None:
        # -O 强制走旧版 scp 协议：某些跳板/账号格式对新版 SFTP 默认实现
        # 会拒;旧协议稳妥。-q 静默 PQ 警告,否则会被算作非零退出。
        cmd = [
            "scp", "-O", "-q", "-i", self.key, "-P", self.port,
            "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
            "-o", "HostkeyAlgorithms=+ssh-rsa",
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "LogLevel=ERROR",
            src, dst,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)

    def _ssh_run(self, remote_cmd: str, timeout: int = 300) -> str:
        cmd = self._ssh_base() + [self.user, remote_cmd]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            stdout = proc.stdout.strip()
            details = []
            if stdout:
                details.append(f"stdout: {stdout[-1200:]}")
            if stderr:
                details.append(f"stderr: {stderr[-1200:]}")
            detail_text = "; ".join(details) if details else "no stdout/stderr captured"
            raise RuntimeError(
                f"remote command failed (rc={proc.returncode}): "
                f"cmd={remote_cmd!r}; {detail_text}"
            )
        return proc.stdout

    def _service_script(self) -> str:
        """常驻远端服务：直接复刻 API 路径的 QwenImageEditPlusPipeline 调用。"""
        script = textwrap.dedent(
            """
            import base64
            import io
            import json
            import sys
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

            from PIL import Image
            import torch
            from diffusers import QwenImageEditPlusPipeline

            pipe = QwenImageEditPlusPipeline.from_pretrained(
                "__MODEL_PATH__", torch_dtype=torch.bfloat16
            ).to("cuda:0")

            class Handler(BaseHTTPRequestHandler):
                def do_POST(self):
                    if self.path != "/generate":
                        self.send_error(404)
                        return
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    image = Image.open(
                        io.BytesIO(base64.b64decode(payload["image"]))
                    ).convert("RGB")
                    prompt = payload["prompt"]
                    generator = torch.Generator(device="cuda:0").manual_seed(
                        int(payload.get("seed", 50))
                    )
                    result = pipe(
                        image,
                        prompt,
                        num_inference_steps=payload.get(
                            "num_inference_steps",
                            __DEFAULT_STEPS__,
                        ),
                        true_cfg_scale=payload.get(
                            "true_cfg_scale",
                            __DEFAULT_TRUE_CFG__,
                        ),
                        guidance_scale=payload.get(
                            "guidance_scale",
                            __DEFAULT_GUIDANCE__,
                        ),
                        num_images_per_prompt=1,
                        generator=generator,
                    )
                    out = io.BytesIO()
                    result.images[0].save(out, format="PNG")
                    output_b64 = base64.b64encode(out.getvalue()).decode("utf-8")
                    body = json.dumps({"image": output_b64}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, fmt, *args):
                    return

            server = ThreadingHTTPServer(("127.0.0.1", __PORT__), Handler)
            server.serve_forever()
            """
        )
        script = script.replace("__PORT__", self.service_port)
        script = script.replace("__MODEL_PATH__", self.model_path or "")
        script = script.replace("__DEFAULT_STEPS__", str(DEFAULT_RENDER_STEPS))
        script = script.replace("__DEFAULT_TRUE_CFG__", str(DEFAULT_RENDER_TRUE_CFG))
        script = script.replace("__DEFAULT_GUIDANCE__", str(DEFAULT_RENDER_GUIDANCE))
        return script

    def _service_client_command(self, payload_path: str, output_json_path: str) -> str:
        return (
            f"{self.python} - '{payload_path}' '{output_json_path}' <<'PY'\n"
            "import json\n"
            "import sys\n"
            "import urllib.request\n"
            "payload_path = sys.argv[1]\n"
            "output_path = sys.argv[2]\n"
            "body = open(payload_path, 'rb').read()\n"
            "req = urllib.request.Request(\n"
            f"    'http://127.0.0.1:{self.service_port}/generate',\n"
            "    data=body,\n"
            "    headers={'Content-Type': 'application/json'},\n"
            "    method='POST',\n"
            ")\n"
            "with urllib.request.urlopen(req, timeout=600) as resp:\n"
            "    data = resp.read()\n"
            "open(output_path, 'wb').write(data)\n"
            "print('OK', output_path, flush=True)\n"
            "PY"
        )

    def _ensure_service(self) -> None:
        if not self.workdir:
            raise RuntimeError("tele service workdir is unknown; set GENCLAW_TELE_WORKDIR")
        service_path = "/tmp/genclaw_tele_service.py"
        launch_cmd = (
            f"cd {self.workdir}\n"
            f"if ! python - <<'PY'\n"
            "import socket, sys\n"
            f"s = socket.socket(); rc = s.connect_ex(('127.0.0.1', {self.service_port})); s.close(); sys.exit(0 if rc == 0 else 1)\n"
            "PY\n"
            "then\n"
            f"cat > {service_path} <<'PY'\n{self._service_script()}PY\n"
            f"nohup env CUDA_VISIBLE_DEVICES={self.gpu} PYTORCH_ALLOC_CONF=expandable_segments:True "
            f"{self.python} {service_path} >/tmp/genclaw_tele_service.log 2>&1 &\n"
            "fi\n"
            "for i in $(seq 1 300); do\n"
            "python - <<'PY'\n"
            "import socket, sys\n"
            f"s = socket.socket(); rc = s.connect_ex(('127.0.0.1', {self.service_port})); s.close(); sys.exit(0 if rc == 0 else 1)\n"
            "PY\n"
            "if [ $? -eq 0 ]; then\n"
            "  exit 0\n"
            "fi\n"
            "sleep 2\n"
            "done\n"
            "echo 'tele service did not become ready in time' >&2\n"
            "exit 1"
        )
        self._ssh_run(launch_cmd, timeout=900)

    @staticmethod
    def _infer_workdir(model_path: Optional[str]) -> Optional[str]:
        """从远端模型路径推导 tele 项目的 codes 目录。"""
        if not model_path:
            return None
        cleaned = model_path.rstrip("/")
        suffix = "/models/base_model"
        if cleaned.endswith(suffix):
            return cleaned[: -len(suffix)] + "/codes"
        model_dir = posixpath.dirname(cleaned)
        if posixpath.basename(model_dir) == "models":
            return posixpath.join(posixpath.dirname(model_dir), "codes")
        return None

    def generate(
        self,
        prompt: str,
        sketch_path: Path,
        output_path: Path,
        constraints: dict | None = None,
    ) -> GenerationResult:
        self._require()
        sketch_path = Path(sketch_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 用 output_path 的 stem 当 tag,让多 run 并发时不撞 /tmp 文件名。
        tag = output_path.stem
        r_img = f"/tmp/gc_{tag}_img.b64"
        r_payload = f"/tmp/gc_{tag}_payload.json"
        r_result = f"/tmp/gc_{tag}_result.json"
        r_out = f"/tmp/gc_{tag}_out.png"

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            # 1) 按重绘强度把 sketch 编码成条件图。
            rerender_strength = _rerender_strength(prompt, constraints)
            params = RERENDER_PARAMS[rerender_strength]
            b64 = base64.b64encode(
                _sketch_bytes_for_rerender(sketch_path, rerender_strength)
            ).decode()
            payload = {
                "image": b64,
                "prompt": _instruction(prompt, constraints),
                "rerender_strength": rerender_strength,
                "num_inference_steps": params["num_inference_steps"],
                "true_cfg_scale": params["true_cfg_scale"],
                "guidance_scale": params["guidance_scale"],
                "seed": 50,
            }
            (tdp / "payload.json").write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            self._scp(str(tdp / "payload.json"), f"{self.user}:{r_payload}")
            self._ensure_service()
            remote = (
                f"cd {self.workdir} && "
                + self._service_client_command(r_payload, r_result)
                + f"\n{self.python} - '{r_result}' '{r_out}' <<'PY'\n"
                "import base64\n"
                "import io\n"
                "import json\n"
                "import sys\n"
                "from PIL import Image\n"
                "result_path = sys.argv[1]\n"
                "out_path = sys.argv[2]\n"
                "payload = json.load(open(result_path, encoding='utf-8'))\n"
                "img = Image.open(io.BytesIO(base64.b64decode(payload['image']))).convert('RGB')\n"
                "img.save(out_path)\n"
                "print('OK', out_path, flush=True)\n"
                "PY"
            )
            self._ssh_run(remote, timeout=600)
            self._scp(f"{self.user}:{r_out}", str(output_path))
            # best-effort:服务端 /tmp 临时文件清掉(失败不影响主流程)
            try:
                self._ssh_run(f"rm -f {r_payload} {r_result} {r_out} {r_img}", timeout=30)
            except Exception:
                pass

        return GenerationResult(
            final_path=output_path,
            provider=self.name,
            sketch_path=sketch_path,
            metadata={
                "model": "QwenImageEditPlusPipeline (self-hosted service)",
                "mode": "remote-service-api-equivalent",
                "host": self.host,
                "service_port": self.service_port,
                "rerender_strength": rerender_strength,
                "num_inference_steps": params["num_inference_steps"],
                "true_cfg_scale": params["true_cfg_scale"],
                "guidance_scale": params["guidance_scale"],
                "prompt": prompt,
            },
        )


def _sketch_bytes_for_rerender(sketch_path: Path, strength: str) -> bytes:
    """Return the image bytes sent to the edit model.

    High redraw should not feed a crisp completed SVG screenshot back to an edit
    model, because the model will preserve it. Instead, send a softened color
    guide: colors still carry semantic constraints, while blur/noise/low contrast
    remove finished vector styling.
    """
    raw = Path(sketch_path).read_bytes()
    if strength == "low":
        return raw

    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    img = Image.open(io.BytesIO(raw)).convert("RGB")
    if strength == "medium":
        img = ImageEnhance.Color(img).enhance(0.25)
        img = ImageEnhance.Contrast(img).enhance(0.85)
    else:
        img = img.filter(ImageFilter.GaussianBlur(radius=4))
        img = ImageEnhance.Sharpness(img).enhance(0.0)
        img = ImageEnhance.Contrast(img).enhance(0.55)
        img = ImageEnhance.Color(img).enhance(0.8)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
