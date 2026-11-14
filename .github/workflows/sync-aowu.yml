import json
import sys
import os
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ==============================================
JSON_URL = "https://9763.kstore.vip/aowu.json"   # ← 保持你的真实接口
SAVE_DIR = "jar"
# ==============================================

def fetch_json(url):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except (URLError, HTTPError, json.JSONDecodeError) as e:
        print(f"❌ 拉取 JSON 失败: {e}")
        sys.exit(1)

def extract_image_url(data):
    """精准提取 spider 字段中的 png 图片（清洗 md5 后缀）"""
    if isinstance(data, dict):
        spider_val = data.get("spider")
        if spider_val:
            val = str(spider_val)
            # 格式如：url.png;md5;xxxx，取分号前部分
            if ";" in val:
                val = val.split(";")[0]
            if val.startswith("http") and (".png" in val.lower() or ".jpg" in val.lower()):
                return val.strip()
            # 若 spider 本身是嵌套对象
            if isinstance(spider_val, dict):
                for k in ["url", "img", "image", "src"]:
                    if k in spider_val:
                        v = str(spider_val[k])
                        if ";" in v: v = v.split(";")[0]
                        if v.startswith("http"): return v.strip()
    return None

def download_file(url, save_path):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=60) as resp:
            data = resp.read()
        os.makedirs(SAVE_DIR, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(data)
        size = os.path.getsize(save_path)
        print(f"✅ 下载完成: {save_path} ({size / 1024:.2f} KB)")
        if size < 1024:
            print("⚠️ 文件太小，可能不是有效图片")
            sys.exit(1)
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        sys.exit(1)

def main():
    print("=" * 50)
    print("开始拉取 JSON 接口...")
    print("=" * 50)

    data = fetch_json(JSON_URL)

    # 调试用（调通后可注释）
    # print("\n📋 JSON 完整结构：")
    # print(json.dumps(data, ensure_ascii=False, indent=2))

    img_url = extract_image_url(data)
    if not img_url:
        print("❌ 未从 spider 字段提取到有效图片地址")
        sys.exit(1)

    print(f"✅ 找到图片地址: {img_url}")

    # 后缀判断（spider 里是 png，默认 png）
    if ".jpg" in img_url.lower() or ".jpeg" in img_url.lower():
        ext = ".jpg"
    else:
        ext = ".png"

    save_path = os.path.join(SAVE_DIR, f"aowu{ext}")

    print("\n开始下载图片...")
    download_file(img_url, save_path)

    print("\n🎉 全部完成！")

if __name__ == "__main__":
    main()
