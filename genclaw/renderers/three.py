"""Three.js renderer (plan task 8).

Compiles a physical/geometric ``structured`` :class:`~genclaw.schemas.CanvasPlan`
into an HTML host page that builds a Three.js scene. Three is the backend for
geometry, physics, and viewpoint tasks.

Source compilation is pure and browser-free (it emits the HTML+JS scene from the
plan's object ``attributes``); PNG rasterization is delegated to the Playwright
helper with the swiftshader flags and frame-ready wait validated by the task 7.5
WebGL spike, and is only attempted when a browser is available. The PNG path
stays gated behind the ``render`` marker until the spike confirms stable Windows
headless WebGL capture.

Object kinds map to scene elements via ``attributes``:

* ``plane`` / ``mirror`` -- a PlaneGeometry mesh (position, rotation, size, color)
* ``sphere``             -- a SphereGeometry mesh (position, radius, color)
* ``directional_light``  -- a DirectionalLight (position, intensity)
* ``camera``             -- the PerspectiveCamera (position, look_at, fov)
"""

from __future__ import annotations

import json
from pathlib import Path

from genclaw.renderers.base import RenderedCanvas, Renderer
from genclaw.schemas import CanvasBackend, CanvasPlan, ObjectSpec

# Pinned Three.js via CDN module import. Offline runs (no network in the
# headless browser) will fail PNG capture loudly; source compilation is
# unaffected. Version recorded here so the dependency is auditable.
THREE_CDN = "https://unpkg.com/three@0.160.0/build/three.module.js"


def _vec(values, default=(0, 0, 0)) -> list:
    return list(values) if values is not None else list(default)


def _mesh_js(obj: ObjectSpec) -> str:
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
    """Compiles a physical/geometric CanvasPlan to a Three.js HTML scene."""

    backend = CanvasBackend.three

    def compile_source(self, plan: CanvasPlan) -> str:
        """Compile ``plan`` to a Three.js host HTML page. Pure; no browser."""
        w, h = plan.size.width, plan.size.height
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

  // Signal frame-readiness so the rasterizer screenshots a painted frame
  // (task 7.5 strategy), never an empty canvas.
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
    try:
        from genclaw.renderers.playwright_render import render_html_to_png
    except Exception:
        return False
    try:
        # Wait for several animation frames so WebGL has actually painted.
        render_html_to_png(html, png_path, width=width, height=height, wait_for_frames=5)
    except Exception:
        return False
    return True
