import json
import sys
import os
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ==============================================
JSON_URL = "https://9763.kstore.vip/aowu.json"   # ← 改成你真实的 JSON 接口网址
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
    """从 JSON 中提取 .png / .jpg 地址，兼容多种结构"""
    candidates = ["url", "download", "image", "img", "png", "file_url", "link", "src"]

    if isinstance(data, dict):
        for key in candidates:
            val = data.get(key)
            if val and (".png" in str(val).lower() or ".jpg" in str(val).lower() or ".jpeg" in str(val).lower()):
                return val
        for sub_key in ["data", "result", "body", "response", "info"]:
            sub = data.get(sub_key)
            if isinstance(sub, dict):
                for key in candidates:
                    val = sub.get(key)
                    if val and (".png" in str(val).lower() or ".jpg" in str(val).lower() or ".jpeg" in str(val).lower()):
                        return val

    elif isinstance(data, list) and len(data) > 0:
        first = data[0]
        if isinstance(first, dict):
            for key in candidates:
                val = first.get(key)
                if val and (".png" in str(val).lower() or ".jpg" in str(val).lower() or ".jpeg" in str(val).lower()):
                    return val

    return None

def download_file(url, save_path):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=60) as resp:
            data = resp.read()
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
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

    # 调试：打印完整 JSON（调通后可注释掉）
    print("\n📋 JSON 完整结构：")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print()

    img_url = extract_image_url(data)
    if not img_url:
        print("❌ JSON 中未找到 .png/.jpg 地址，请检查接口结构")
        print("💡 上面已打印完整 JSON，对照字段名修改 extract_image_url")
        sys.exit(1)

    print(f"✅ 找到图片地址: {img_url}")

    # 根据 URL 判断后缀，默认 png
    lower = img_url.lower()
    if ".jpg" in lower or ".jpeg" in lower:
        ext = ".jpg"
    else:
        ext = ".png"

    save_path = os.path.join(SAVE_DIR, f"aowu{ext}")

    print("\n开始下载图片...")
    download_file(img_url, save_path)

    print("\n🎉 全部完成！")

if __name__ == "__main__":
    main()
