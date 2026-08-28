"""列出 SiliconFlow 可用的文生图模型。"""
import json
import urllib.request
import sys

sys.path.insert(0, ".")
from core.config import config

req = urllib.request.Request(
    "https://api.siliconflow.cn/v1/models",
    headers={"Authorization": f"Bearer {config.image_api_key}"},
)
with urllib.request.urlopen(req, timeout=15) as r:
    data = json.loads(r.read().decode())

models = data.get("data", [])
# SiliconFlow 的模型对象里通常有 type / created / id 等；文生图一般 id 含
# Kolors / FLUX / SD / SDXL / Stable / Playground / Hunyuan / Wan / CogView 等关键词
keywords = ("kolors", "flux", "sdxl", "sd-", "stable", "playground", "hunyuan", "wan", "cogview", "image", "diffusion", "schnell", "dev")
hits = [m for m in models if any(k in m.get("id", "").lower() for k in keywords)]
print(f"候选图像模型 {len(hits)} 个：")
for m in sorted(hits, key=lambda x: x.get("id", "")):
    print("  ", m.get("id"))
