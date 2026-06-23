import sys, base64, io, torch
from PIL import Image
from diffusers import QwenImageEditPlusPipeline
M="/gemini/platform/public/aigc/aigc_image/zangxh/teleedit_mask_v3/models/base_model/"
img=Image.open(io.BytesIO(base64.b64decode(open('/tmp/gc_img_b64.txt').read().strip()))).convert("RGB")
pipe=QwenImageEditPlusPipeline.from_pretrained(M,torch_dtype=torch.bfloat16).to("cuda:0")
prompt=("Transform this flat vector illustration into a fully photorealistic DSLR photograph "
        "of a bright modern airport departure hall. Render real materials: glossy floor "
        "reflections, glass walls, realistic people with natural clothing and skin, metallic "
        "luggage, glowing LED flight-information screen, ceiling skylight daylight. Keep the "
        "same composition and layout, but make everything look like a real photo, not a drawing.")
out=pipe(image=img,prompt=prompt,true_cfg_scale=7.0,num_inference_steps=40,
         num_images_per_prompt=1,generator=torch.Generator(device="cuda:0").manual_seed(7))
out.images[0].save('/tmp/gc_strong.png'); print("OK")
