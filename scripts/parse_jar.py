#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 aowu.json 里解析出 .jar 地址并下载到 jar/aowu.jar"""
import json
import os
import sys
import urllib.request

JSON_FILE = "aowu.json"
JAR_DIR = "jar"
JAR_NAME = "aowu.jar"


def find_jar_url(data):
    """依次尝试常见字段，返回第一个含 .jar 的地址"""
    if not isinstance(data, dict):
        return None

    # 1. 顶层常见字段
    for key in ("spider", "jar", "parser", "spiderJar"):
        v = data.get(key, "")
        if isinstance(v, str) and ".jar" in v:
            return v.split(";")[0].strip()

    # 2. sites 列表
    for site in data.get("sites", []):
        if not isinstance(site, dict):
            continue
        for key in ("jar", "spider", "spiderJar"):
            v = site.get(key, "")
            if isinstance(v, str) and ".jar" in v:
                return v.split(";")[0].strip()

    # 3. 兜底：递归扫所有字符串
    def walk(obj):
        if isinstance(obj, dict):
            for val in obj.values():
                yield from walk(val)
        elif isinstance(obj, list):
            for item in obj:
                yield from walk(item)
        elif isinstance(obj, str):
            if obj.strip().endswith(".jar"):
                yield obj.strip().split(";")[0]

    for url in walk(data):
        return url

    return None


def main():
    if not os.path.exists(JSON_FILE):
        print("❌ 找不到 %s，请先 curl 拉取" % JSON_FILE)
        sys.exit(1)

    with open(JSON_FILE, encoding="utf-8") as f:
        data = json.load(f)

    jar_url = find_jar_url(data)
    if not jar_url:
        print("❌ JSON 中未找到 .jar 地址，请检查接口结构")
        sys.exit(1)
    print("✅ 找到 jar 地址:", jar_url)

    os.makedirs(JAR_DIR, exist_ok=True)
    req = urllib.request.Request(
        jar_url, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        content = r.read()

    # jar 本质是 zip，合法文件头为 PK (0x504B)
    if content[:2] != b"PK":
        print("❌ 下载内容不是合法 jar（文件头非 PK），疑似被拦截或链接失效")
        sys.exit(1)

    save_path = os.path.join(JAR_DIR, JAR_NAME)
    with open(save_path, "wb") as out:
        out.write(content)
    print("✅ 已写入 %s，大小: %d 字节" % (save_path, len(content)))


if __name__ == "__main__":
    main()
