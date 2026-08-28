"""逐个探测候选模型的真实可用性：尝试一次最小文生图请求，看是否报错/成功。"""
import json
import sys
import urllib.request

sys.path.insert(0, ".")
from core.config import config

CANDIDATES = [
    "Kwai-Kolors/Kolors",  # 现状对照
    "Qwen/Qwen-Image",
    "Tongyi-MAI/Z-Image",
    "Tongyi-MAI/Z-Image-Turbo",
    "baidu/ERNIE-Image-Turbo",
]

payload = {
    "model": "",
    "prompt": "一只趴在窗台上的橘猫，午后阳光，治愈系插画",
    "image_size": "1024x1024",
    "batch_size": 1,
    "num_inference_steps": 20,
    "seed": 42,
}

for mid in CANDIDATES:
    payload["model"] = mid
    req = urllib.request.Request(
        "https://api.siliconflow.cn/v1/images/generations",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {config.image_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
            urls = [x.get("url", "") for x in data.get("data", []) if isinstance(x, dict)]
            print(f"OK    {mid} -> {len(urls)} 张图, url[:60]={urls[0][:60] if urls else ''}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:160].replace("\n", " ")
        print(f"FAIL  {mid} -> HTTP {e.code}: {body}")
    except Exception as e:
        print(f"ERR   {mid} -> {type(e).__name__}: {str(e)[:120]}")
