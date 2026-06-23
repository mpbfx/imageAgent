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
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from genclaw.config import ProviderConfig, ProviderNotConfiguredError
from genclaw.generators.base import GenerationResult, ImageGenerator

# 环境变量名常量——集中定义,避免「字符串魔法」散落各处。
ENV_HOST = "GENCLAW_TELE_SSH_HOST"
ENV_PORT = "GENCLAW_TELE_SSH_PORT"
ENV_USER = "GENCLAW_TELE_SSH_USER"
ENV_KEY = "GENCLAW_TELE_SSH_KEY"
ENV_MODEL_PATH = "GENCLAW_TELE_MODEL_PATH"
ENV_PYTHON = "GENCLAW_TELE_PYTHON"
ENV_GPU = "GENCLAW_TELE_GPU"
ENV_STEPS = "GENCLAW_TELE_STEPS"

# 一次性服务端 runner:从文件读 sketch base64,跑纯 img2img,写结果 PNG。
# 这个脚本只放在 /tmp,不进项目树;在调用方用完就尝试 rm 掉。
_RUNNER = r'''
import sys, base64, io, traceback
from PIL import Image
import torch
from diffusers import QwenImageEditPlusPipeline

model_path = sys.argv[1]
img_b64_path = sys.argv[2]
prompt = sys.argv[3]
out_path = sys.argv[4]
steps = int(sys.argv[5]) if len(sys.argv) > 5 else 30
cfg = float(sys.argv[6]) if len(sys.argv) > 6 else 4.0

img = Image.open(io.BytesIO(base64.b64decode(open(img_b64_path).read().strip()))).convert("RGB")
pipe = QwenImageEditPlusPipeline.from_pretrained(model_path, torch_dtype=torch.bfloat16).to("cuda:0")
out = pipe(image=img, prompt=prompt, true_cfg_scale=cfg, num_inference_steps=steps,
           num_images_per_prompt=1,
           generator=torch.Generator(device="cuda:0").manual_seed(50))
out.images[0].save(out_path)
print("OK", out_path, flush=True)
'''

# 文字密集型任务:用更「温柔」的指令与 cfg,保住代码画出来的字形。
# QwenImageEditPlusPipeline 没有 ``strength`` 参数,rerender 强度靠 prompt
# 措辞 + true_cfg_scale 间接调(已实测验证)。强 rerender 会把平面的矢量
# 草图变成写实场景,但会扰动细字形,所以按任务族缩放强度。
_TEXT_TASKS = {"long_text"}


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
            raise RuntimeError(
                f"remote command failed (rc={proc.returncode}): "
                f"{proc.stderr.strip()[-400:]}"
            )
        return proc.stdout

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
        r_runner = f"/tmp/gc_{tag}_runner.py"
        r_out = f"/tmp/gc_{tag}_out.png"
        target = f"{self.user.split(' ')[-1]}" if False else self.user

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            # 1) 把 sketch 编码成 base64 文件
            b64 = base64.b64encode(sketch_path.read_bytes()).decode()
            (tdp / "img.b64").write_text(b64)
            (tdp / "runner.py").write_text(_RUNNER)
            # 2) 把 sketch + runner 传到服务器 /tmp
            self._scp(str(tdp / "img.b64"), f"{self.user}:{r_img}")
            self._scp(str(tdp / "runner.py"), f"{self.user}:{r_runner}")
            # 3) 在空闲 GPU 上跑 img2img。按 task family 选 rerender 强度:
            #    文字密集 -> 温柔(保住字形);其它 -> 强写实。
            task = (constraints or {}).get("task_type", "")
            instr, cfg, steps = _instruction_for(prompt, task, constraints)
            shell_prompt = instr.replace("'", "'\\''")
            remote = (
                f"CUDA_VISIBLE_DEVICES={self.gpu} "
                f"PYTORCH_ALLOC_CONF=expandable_segments:True "
                f"{self.python} {r_runner} '{self.model_path}' {r_img} "
                f"'{shell_prompt}' {r_out} {steps} {cfg}"
            )
            self._ssh_run(remote, timeout=600)
            # 4) 把结果 PNG 拷回本地
            self._scp(f"{self.user}:{r_out}", str(output_path))
            # best-effort:服务端 /tmp 临时文件清掉(失败不影响主流程)
            try:
                self._ssh_run(f"rm -f {r_img} {r_runner} {r_out}", timeout=30)
            except Exception:
                pass

        return GenerationResult(
            final_path=output_path,
            provider=self.name,
            sketch_path=sketch_path,
            metadata={
                "model": "QwenImageEditPlusPipeline (self-hosted)",
                "mode": "pure-img2img",
                "host": self.host,
                "task_type": task,
                "cfg": cfg,
                "steps": steps,
                "prompt": prompt,
            },
        )


def _instruction_for(prompt: str, task: str, constraints: dict | None) -> tuple[str, float, int]:
    """根据任务族构造 ``(instruction, cfg, steps)``。

    文字密集任务给「保住字形」的温柔指令;材质/场景任务给「把平面矢量变
    写实照片」的强指令(更高 cfg + 更高 steps),经验证可以有效把
    「卡通感」压下去,又保留构图。
    """
    if task in _TEXT_TASKS:
        instr = (
            "Add realistic paper texture, subtle lighting, and material depth to this "
            "design. Keep ALL text characters, numbers, and layout EXACTLY as drawn; "
            "do not redraw, move, or regenerate any text. Result: " + prompt
        )
        cfg, steps = 4.0, 30
    else:
        instr = (
            "Transform this flat vector illustration into a fully photorealistic "
            "photograph. Render real materials, surfaces, lighting, reflections, and "
            "natural detail so nothing looks like a drawing. Keep the same composition, "
            "object counts, positions, and layout as drawn. Scene: " + prompt
        )
        cfg, steps = 7.0, 40
    if constraints:
        # task_type 已经用来切档,不要重复塞进 prompt
        extra = {k: v for k, v in constraints.items() if k != "task_type"}
        if extra:
            instr += f"\nConstraints: {extra}"
    return instr, cfg, steps
