import sys, os, base64, io, traceback
from PIL import Image
import torch
from diffusers import QwenImageEditPlusPipeline
MODEL="/gemini/platform/public/aigc/aigc_image/zangxh/teleedit_mask_v3/models/base_model/"
def b2i(b): return Image.open(io.BytesIO(base64.b64decode(b))).convert("RGB")
img = b2i(open('/tmp/gc_img_b64.txt').read().strip())
print("[i2i] loading pipeline ...", flush=True)
pipe = QwenImageEditPlusPipeline.from_pretrained(MODEL, torch_dtype=torch.bfloat16).to("cuda:0")
print("[i2i] running pure img2img (no mask) ...", flush=True)
prompt=("Turn this into a photorealistic photo of colorful balloons held in a hand against a "
        "blue sky. Keep the exact number, colors, and left-to-right arrangement of the balloons "
        "and the strings converging to the hand. Add realistic glossy balloon material, soft "
        "highlights, and natural sky lighting.")
out = pipe(image=img, prompt=prompt, true_cfg_scale=4.0, num_inference_steps=30,
           num_images_per_prompt=1, generator=torch.Generator(device="cuda:0").manual_seed(50))
out.images[0].save('/tmp/gc_i2i_result.png')
print("[i2i] DONE", flush=True)
