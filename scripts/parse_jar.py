#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_jar.py - 从接口拉取 JSON，提取 .jar 下载地址，下载到 jar/aowu.jar
"""

import requests
import json
import sys
import os

# ========== 配置区（按你实际情况改） ==========
JSON_URL = "https://你的接口地址/aowu.json"   # ← 改成你真实的 JSON 接口
# ==============================================

def main():
    print("=" * 50)
    print("开始拉取 JSON 接口...")
    print("=" * 50)

    # 1. 拉取 JSON
    try:
        r = requests.get(JSON_URL, timeout=30)
        r.encoding = "utf-8"
        r.raise_for_status()
    except Exception as e:
        print(f"❌ 拉取 JSON 失败: {e}")
        sys.exit(1)

    data = r.json()

    # 2. 调试：打印完整 JSON 结构（调通后可注释掉）
    print("\n📋 JSON 完整结构：")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print()

    # 3. 提取 .jar 下载地址（兼容多种常见结构）
    jar_url = None

    if isinstance(data, dict):
        # 常见字段名逐个尝试
        for key in ["url", "download", "jar", "download_url", "file_url", "link"]:
            val = data.get(key)
            if val and ".jar" in str(val):
                jar_url = val
                break

        # 嵌套结构尝试
        if not jar_url:
            for sub_key in ["data", "result", "body", "response"]:
                sub = data.get(sub_key)
                if isinstance(sub, dict):
                    for key in ["url", "download", "jar", "download_url"]:
                        val = sub.get(key)
                        if val and ".jar" in str(val):
                            jar_url = val
                            break

    elif isinstance(data, list) and len(data) > 0:
        # 数组结构：取第一个元素
        first = data[0]
        if isinstance(first, dict):
            for key in ["url", "download", "jar"]:
                val = first.get(key)
                if val and ".jar" in str(val):
                    jar_url = val
                    break

    if not jar_url:
        print("❌ JSON 中未找到 .jar 地址，请检查接口结构")
        print("💡 提示：上面已打印完整 JSON，对照字段名修改脚本第 3 步的提取逻辑")
        sys.exit(1)

    print(f"✅ 找到 jar 地址: {jar_url}")

    # 4. 下载 jar 文件
    print("\n开始下载 jar 文件...")
    try:
        jar_r = requests.get(jar_url, timeout=60, stream=True)
        jar_r.raise_for_status()
    except Exception as e:
        print(f"❌ 下载 jar 失败: {e}")
        sys.exit(1)

    # 确保 jar/ 目录存在
    os.makedirs("jar", exist_ok=True)
    jar_path = "jar/aowu.jar"

    with open(jar_path, "wb") as f:
        for chunk in jar_r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    file_size = os.path.getsize(jar_path)
    print(f"✅ 下载完成: {jar_path} ({file_size / 1024 / 1024:.2f} MB)")

    if file_size < 1024:
        print("⚠️ 文件太小，可能不是有效的 jar 包，请检查下载链接")
        sys.exit(1)

    print("\n🎉 全部完成！")

if __name__ == "__main__":
    main()
