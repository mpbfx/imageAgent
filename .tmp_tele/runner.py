import sys, os, traceback
os.chdir('/gemini/platform/public/aigc/aigc_image/zangxh/teleedit_mask_v3/codes')
sys.path.insert(0, '.')
import utils.util as _u
_orig = _u.load_yaml
def _patched(path):
    d = _orig(path)
    try:
        d['device']['edit_config'] = 'cuda:0'
        d['device']['trans_config'] = 'cuda:0'
        d['preprocess']['enable_preprocess'] = False
    except Exception as e:
        print("[patch] warn:", e)
    return d
_u.load_yaml = _patched
from utils.file_operating import base64_to_image, image_to_base64
import main as _main
_main.load_yaml = _patched
from main import TeleEdit_Mask
img = open('/tmp/gc_img_b64.txt').read().strip()
mask = open('/tmp/gc_mask_b64.txt').read().strip()
print("[runner] constructing ...", flush=True)
te = TeleEdit_Mask()
te.args.preprocess.enable_preprocess = False
print("[runner] running edit ...", flush=True)
try:
    out = te.run(img, mask,
                 "古朴典雅的宣纸纹理背景，米黄色做旧质感，朱砂红边框装饰",
                 seed=50, batch_size=1, num_inference_steps=8,
                 true_cfg_scale=4.0, guidance_scale=1.0, max_try=2)
except Exception as e:
    print("[runner] RUN FAILED:", type(e).__name__, str(e)[:500]); traceback.print_exc(); sys.exit(4)
res_b64 = out[1] if isinstance(out,(list,tuple)) and len(out)>=2 else (out[0] if isinstance(out,(list,tuple)) else out)
base64_to_image(res_b64).save('/tmp/gc_result.png')
print("[runner] DONE -> /tmp/gc_result.png", flush=True)
