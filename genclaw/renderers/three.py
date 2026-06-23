"""Three.js renderer(plan task 8)。

把物理/几何 ``structured`` :class:`~genclaw.schemas.CanvasPlan` 编译成一
个会构建 Three.js 场景的 HTML 宿主页。Three 是几何 / 物理 / 视角任务的
后端。

源码编译纯函数、无浏览器(从 plan 的 object ``attributes`` 拼出 HTML+JS
场景);PNG 光栅化交给 Playwright 辅助函数,带 swiftshader flags 和 frame
wait(task 7.5 WebGL spike 验证),只在浏览器可用时尝试。PNG 路径在
spike 确认 Windows 端 headless WebGL capture 稳定前,都是「标 render
但拿不到 PNG」的灰态。

object kind -> 场景元素通过 ``attributes`` 映射:

* ``plane`` / ``mirror`` -- 一个 PlaneGeometry mesh(位置、旋转、大小、颜色)
* ``sphere``             -- 一个 SphereGeometry mesh(位置、半径、颜色)
* ``directional_light``  -- 一盏 DirectionalLight(位置、强度)
* ``camera``             -- PerspectiveCamera(位置、look_at、fov)
"""

# 中文补充说明:
# Three.js 用 CDN 拉取 0.160.0(写死版本,审计好追溯)。offline 环境无法
# 拉 CDN 时,源码编译仍然成功,但 PNG 截屏会失败——失败是显式的,不会假成功。
# __gcRendered 是给 Playwright 的「渲染好」信号旗:连续 3 帧后才置 true,
# Playwright 端才允许截图(task 7.5 的经验:不 wait 就只能截到空白 canvas)。
# mirror vs plane 的差别在 material(metalness=1 / roughness=0.05),
# 是按物理上「镜面反射」的近似写的,够用就好。

from __future__ import annotations

import json
from pathlib import Path

from genclaw.renderers.base import RenderedCanvas, Renderer
from genclaw.schemas import CanvasBackend, CanvasPlan, ObjectSpec

# Three.js 用 CDN module import 拉。离线跑(headless 浏览器没网)PNG 截屏
# 会显式失败;源码编译不受影响。版本写死,便于审计。
THREE_CDN = "https://unpkg.com/three@0.160.0/build/three.module.js"


def _vec(values, default=(0, 0, 0)) -> list:
    """把 None / 可迭代 / 缺省 统一成 list。"""
    return list(values) if values is not None else list(default)


def _mesh_js(obj: ObjectSpec) -> str:
    """把一个 object 翻译成 Three.js 场景的添加代码。"""
    a = obj.attributes
    color = json.dumps(a.get("color", "#cccccc"))
    pos = _vec(a.get("position"))
    if obj.kind in ("plane", "mirror"):
        size = _vec(a.get("size", [10, 10]), (10, 10))[:2]
        rot = _vec(a.get("rotation"))
        return (
            f"  {{\n"
            f"    const geo = new THREE.PlaneGeometry({size[0]}, {size[1]});\n"
            f"    const mat = new THREE.MeshStandardMaterial({{ color: {color}, "
            f"side: THREE.DoubleSide, "
            f"metalness: {1.0 if obj.kind == 'mirror' else 0.0}, "
            f"roughness: {0.05 if obj.kind == 'mirror' else 0.9} }});\n"
            f"    const mesh = new THREE.Mesh(geo, mat);\n"
            f"    mesh.position.set({pos[0]}, {pos[1]}, {pos[2]});\n"
            f"    mesh.rotation.set({rot[0]}, {rot[1]}, {rot[2]});\n"
            f"    mesh.name = {json.dumps(obj.id)};\n"
            f"    scene.add(mesh);\n"
            f"  }}\n"
        )
    if obj.kind == "sphere":
        radius = a.get("radius", 1.0)
        return (
            f"  {{\n"
            f"    const geo = new THREE.SphereGeometry({radius}, 32, 32);\n"
            f"    const mat = new THREE.MeshStandardMaterial({{ color: {color} }});\n"
            f"    const mesh = new THREE.Mesh(geo, mat);\n"
            f"    mesh.position.set({pos[0]}, {pos[1]}, {pos[2]});\n"
            f"    mesh.name = {json.dumps(obj.id)};\n"
            f"    scene.add(mesh);\n"
            f"  }}\n"
        )
    if obj.kind == "directional_light":
        intensity = a.get("intensity", 1.0)
        return (
            f"  {{\n"
            f"    const light = new THREE.DirectionalLight(0xffffff, {intensity});\n"
            f"    light.position.set({pos[0]}, {pos[1]}, {pos[2]});\n"
            f"    scene.add(light);\n"
            f"  }}\n"
        )
    return f"  // unsupported kind: {obj.kind}\n"


def _camera_js(plan: CanvasPlan) -> str:
    """从 plan 里抠出 camera object,生成 PerspectiveCamera 配置代码。

    没有 camera object 时给一组合理默认(略仰视,中景)。
    """
    cams = [o for o in plan.objects if o.kind == "camera"]
    w, h = plan.size.width, plan.size.height
    if cams:
        a = cams[0].attributes
        pos = _vec(a.get("position", [0, 3, 8]), (0, 3, 8))
        look = _vec(a.get("look_at", [0, 0, 0]))
        fov = a.get("fov", 50)
    else:
        pos, look, fov = [0, 3, 8], [0, 0, 0], 50
    return (
        f"  const camera = new THREE.PerspectiveCamera({fov}, {w} / {h}, 0.1, 1000);\n"
        f"  camera.position.set({pos[0]}, {pos[1]}, {pos[2]});\n"
        f"  camera.lookAt({look[0]}, {look[1]}, {look[2]});\n"
    )


class ThreeRenderer(Renderer):
    """把物理/几何 CanvasPlan 编译成 Three.js HTML 场景。"""

    backend = CanvasBackend.three

    def compile_source(self, plan: CanvasPlan) -> str:
        """把 ``plan`` 编译成 Three.js 宿主 HTML。纯函数,无浏览器。"""
        w, h = plan.size.width, plan.size.height
        # camera 单独抽出来,其它 object 走 _mesh_js
        meshes = "".join(_mesh_js(o) for o in plan.objects if o.kind != "camera")
        camera = _camera_js(plan)
        bg = json.dumps(plan.style.get("background", "#101014"))
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <style>* {{ margin: 0; padding: 0; }} body {{ overflow: hidden; }}</style>
</head>
<body>
  <canvas id="scene" width="{w}" height="{h}"></canvas>
  <script type="module">
  import * as THREE from "{THREE_CDN}";

  // 给 rasterizer 一个「帧就绪」信号,确保截到的是已绘帧(task 7.5 经验),
  // 绝不是空白 canvas
  window.__gcRendered = false;

  const canvas = document.getElementById("scene");
  const renderer = new THREE.WebGLRenderer({{ canvas, antialias: true, preserveDrawingBuffer: true }});
  renderer.setSize({w}, {h}, false);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color({bg});
  scene.add(new THREE.AmbientLight(0xffffff, 0.4));

{meshes}{camera}
  let frames = 0;
  function animate() {{
    renderer.render(scene, camera);
    frames += 1;
    if (frames >= 3) {{ window.__gcRendered = true; }}
    requestAnimationFrame(animate);
  }}
  animate();
  </script>
</body>
</html>
"""

    def render(self, plan: CanvasPlan, output_dir: Path) -> RenderedCanvas:
        """写 source + 有可能光栅化 PNG。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        source = self.compile_source(plan)
        source_path = output_dir / "canvas.html"
        source_path.write_text(source, encoding="utf-8")

        png_path = output_dir / "sketch.png"
        rasterized = _try_rasterize(source, png_path, plan.size.width, plan.size.height)

        return RenderedCanvas(
            backend=CanvasBackend.three,
            source_path=source_path,
            png_path=png_path if rasterized else None,
            width=plan.size.width,
            height=plan.size.height,
        )


def _try_rasterize(html: str, png_path: Path, width: int, height: int) -> bool:
    """Playwright 可用就截屏,等几帧让 WebGL 真正画完;否则跳过。"""
    try:
        from genclaw.renderers.playwright_render import render_html_to_png
    except Exception:
        return False
    try:
        # wait_for_frames=5:让 WebGL 真正画完再截图(经验值,3 帧有时不够)
        render_html_to_png(html, png_path, width=width, height=height, wait_for_frames=5)
    except Exception:
        return False
    return True
