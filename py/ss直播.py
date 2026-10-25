# -*- coding: utf-8 -*-
"""
ss直播 - Python 版
由 drpy 规则文件 ss直播.js 转写而来，接口于 2026-10-25 验证可用。

原规则:
    host:    http://api.hclyz.com:81/mf
    一级(平台列表): GET /mf/json.txt        -> {"pingtai":[{title,xinimg,Number,address},...]}
    二级(频道列表): GET /mf/<address>       -> {"zhubo":[{title,img,address},...]}

用法:
    python ss直播.py                # 交互模式：选平台 -> 选频道 -> 播放
    python ss直播.py --m3u out.m3u  # 导出全部频道的 M3U 播放列表
    python ss直播.py --list         # 仅列出平台
    python ss直播.py --platform 3   # 直接进入第 3 个平台（序号从 1 开始）

依赖: 无（仅用标准库）。播放需本机装有 mpv / ffplay / VLC 任一播放器，
      没有播放器时会打印直链地址，可自行复制到任意播放器打开。
"""

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
import gzip
import io
from urllib.parse import urljoin

# ---------------- 配置（与原规则一致） ----------------
HOST = "http://api.hclyz.com:81/mf"
HOME_URL = HOST + "/json.txt"
UA = ("Mozilla/5.0 (Linux; Android 11; MI 11) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36")
TIMEOUT = 10          # 原规则 timeout:5000ms，这里放宽到 10s 提高成功率
LIMIT = 200           # 原规则 limit:200


def request_text(url: str, retries: int = 3) -> str:
    """带重试和限流退避的 GET，返回响应文本。处理 gzip 并统一编码。"""
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Encoding": "gzip",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                # 接口为中文内容，依次尝试 utf-8 / gbk
                for enc in ("utf-8", "gbk"):
                    try:
                        return raw.decode(enc)
                    except UnicodeDecodeError:
                        continue
                return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (403, 429) and attempt < retries:
                wait = (attempt + 1) * 10  # 限流：10s/20s/30s 递增等待
                time.sleep(wait)
                continue
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries:
                time.sleep(1)
    raise RuntimeError(f"请求失败: {url} ({last_err})")


def request_json(url: str):
    """GET 并解析 JSON；容错处理 BOM、单引号等脏数据。"""
    text = request_text(url).strip().lstrip("\ufeff")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 兼容不规范 JSON：键加引号、单引号转双引号的简单兜底
        import re
        fixed = re.sub(r",\s*([}\]])", r"\1", text)          # 去尾逗号
        fixed = re.sub(r"(?<![\w\"'])('(?=[^']*'\s*[,:}\]]))", '"', fixed)
        return json.loads(fixed)


# ---------------- 一级：平台列表 ----------------
def get_platforms():
    """对应原规则 一级:'json:pingtai;title;xinimg;Number;address'"""
    data = request_json(HOME_URL)
    platforms = data.get("pingtai") or []
    result = []
    for p in platforms[:LIMIT]:
        title = (p.get("title") or "").strip()
        addr = (p.get("address") or "").strip()
        if not addr:
            continue
        if not addr.startswith("http"):
            addr = HOST + "/" + addr.lstrip("/")
        result.append({
            "title": title,
            "img": (p.get("xinimg") or "").strip(),
            "number": p.get("Number", ""),
            "url": addr,
        })
    return result


# ---------------- 二级：频道列表 ----------------
def get_channels(platform_url: str):
    """对应原规则 二级：解析 zhubo 数组的 title/address"""
    data = request_json(platform_url)
    zhubo = data.get("zhubo") or []
    channels = []
    for z in zhubo:
        title = (z.get("title") or "").strip()
        addr = (z.get("address") or "").strip()
        if title and addr:
            channels.append({"title": title, "img": z.get("img", ""), "url": addr})
    return channels


# ---------------- 画质探测与最佳画质选择 ----------------
def _amf_number_after(body: bytes, key: bytes):
    """在 AMF0 数据体里按字节模式找 key 后面的 number 值（key + 类型0x00 + 8字节double）"""
    idx = body.find(key + b'\x00')
    if idx < 0 or idx + len(key) + 1 + 8 > len(body):
        return None
    try:
        return struct.unpack('>d', body[idx + len(key) + 1: idx + len(key) + 9])[0]
    except struct.error:
        return None


def flv_resolution(url: str):
    """下载直播流头部（元数据在开头几KB），解析得到真实分辨率 (w, h)；失败返回 None"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            chunk = r.read(65536)
        if chunk[:3] != b'FLV':
            return None
        pos = 13
        for _ in range(6):
            if pos + 11 > len(chunk): break
            tagtype = chunk[pos]
            ds = struct.unpack('>I', b'\x00' + chunk[pos+1:pos+4])[0]
            if tagtype == 18:
                if pos + 11 + ds > len(chunk):
                    ds = len(chunk) - pos - 11  # 元数据被截断时按现有长度解析
                body = chunk[pos+11:pos+11+ds]
                if b'width' not in body:
                    return None
                # 优先 displayWidth/displayHeight（实际显示尺寸），回退 width/height
                w = _amf_number_after(body, b'displayWidth') or _amf_number_after(body, b'width')
                h = _amf_number_after(body, b'displayHeight') or _amf_number_after(body, b'height')
                if w and h:
                    return int(w), int(h)
                return None
            pos += 11 + ds
    except Exception:  # noqa: BLE001
        return None
    return None


def hls_best_variant(url: str):
    """若为 HLS 主播放列表(含多码率)，返回带宽最高的子流地址；否则原样返回"""
    if '.m3u8' not in url.lower():
        return url
    try:
        text = request_text(url)
    except Exception:  # noqa: BLE001
        return url
    if '#EXT-X-STREAM-INF' not in text:
        return url  # 媒体播放列表本身，无更高质量可选
    best_bw, best_uri = -1, None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('#EXT-X-STREAM-INF'):
            bw = 0
            for part in line.split(':')[1].split(','):
                kv = part.split('=', 1)
                if len(kv) == 2 and kv[0].strip().upper() == 'BANDWIDTH':
                    try: bw = int(kv[1])
                    except ValueError: pass
            for j in range(i + 1, len(lines)):
                nxt = lines[j].strip()
                if nxt and not nxt.startswith('#'):
                    if bw > best_bw:
                        best_bw, best_uri = bw, nxt
                    break
    if best_uri:
        return urljoin(url, best_uri)
    return url


def best_quality_url(url: str):
    """统一入口：HLS 选最高码率变体；FLV 保持原样（单码率，画质由主播端决定）"""
    return hls_best_variant(url)


def fmt_res(res):
    if not res:
        return "未知"
    w, h = res
    # 竖屏直播宽<高，统一用短边作为清晰度等级依据
    s = min(w, h)
    if s >= 2160: tag = "4K"
    elif s >= 1080: tag = "1080P"
    elif s >= 720: tag = "720P"
    elif s >= 480: tag = "480P"
    else: tag = "流畅"
    return f"{w}x{h}({tag})"


# ---------------- 播放器探测与播放 ----------------
def find_player():
    """按优先级查找本机可用的播放器，返回 (名称, 命令列表) 或 None"""
    candidates = [
        ("mpv",    ["mpv", "--fullscreen", "--title"]),
        ("ffplay", ["ffplay", "-window_title", "-autoexit"]),
        ("vlc",    ["vlc", "--play-and-exit"]),
    ]
    exe_paths = {
        "mpv": [r"C:\Program Files\mpv\mpv.exe", r"C:\Program Files (x86)\mpv\mpv.exe"],
        "ffplay": [r"C:\Program Files\ffmpeg\bin\ffplay.exe"],
        "vlc": [r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"],
    }
    for name, cmd in candidates:
        found = shutil.which(name)
        if not found:
            for p in exe_paths.get(name, []):
                if os.path.isfile(p):
                    found = p
                    break
        if found:
            return name, [found] + cmd[1:]
    return None


def play_channel(name: str, url: str):
    """选最佳画质后调用本地播放器播放；没有播放器则打印直链。"""
    url = best_quality_url(url)
    res = flv_resolution(url) if '.m3u8' not in url.lower() else None
    print(f"流画质: {fmt_res(res)}" if res else "流画质: 未知（HLS 流由播放器自动选最高码率）")
    player = find_player()
    if player:
        pname, base = player
        cmd = base[:-1] if pname in ("mpv", "ffplay") else base  # 去掉占位的标题参数键
        # mpv: --title <name> / ffplay: -window_title <name> / vlc 无需标题
        if pname == "mpv":
            cmd = [base[0], "--fullscreen", "--title", name, url]
        elif pname == "ffplay":
            cmd = [base[0], "-window_title", name, "-autoexit", url]
        else:
            cmd = [base[0], "--play-and-exit", url]
        print(f"▶ 使用 {pname} 播放: {name}")
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception as e:  # noqa: BLE001
            print(f"播放器调用失败: {e}\n直链: {url}")
    else:
        print("未找到 mpv / ffplay / VLC，请复制以下直链到任意播放器打开：")
        print(url)


# ---------------- M3U 导出 ----------------
def export_m3u(path: str):
    """把全部平台的全部频道导出为 M3U 播放列表。"""
    platforms = get_platforms()
    lines = ["#EXTM3U"]
    total = 0
    for p in platforms:
        try:
            chs = get_channels(p["url"])
        except Exception as e:  # noqa: BLE001
            print(f"[跳过] {p['title']}: {e}", file=sys.stderr)
            continue
        for c in chs:
            lines.append(f'#EXTINF:-1 tvg-logo="{c["img"]}" group-title="{p["title"]}",{c["title"]}')
            lines.append(best_quality_url(c["url"]))
            total += 1
        print(f"[OK] {p['title']}: {len(chs)} 个频道")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n导出完成: {path}（共 {total} 个频道）")


def probe_platform(n: int, limit: int = 30):
    """探测第 n 个平台各频道的真实分辨率，按画质从高到低排序输出"""
    platforms = get_platforms()
    if not 1 <= n <= len(platforms):
        print(f"平台序号需在 1~{len(platforms)} 之间")
        return
    p = platforms[n - 1]
    print(f"正在探测 [{p['title']}] 的频道画质（最多前 {limit} 个，每个约 2~5 秒）...")
    channels = get_channels(p["url"])
    results = []
    for i, c in enumerate(channels[:limit], 1):
        res = flv_resolution(c["url"])
        results.append((res, i, c))
        print(f"  {i:>3}. {c['title']:<24} {fmt_res(res)}")
        time.sleep(1)  # 间隔 1 秒，避免触发服务端限流
    print("\n=== 按画质排序（高 -> 低）===")
    for res, i, c in sorted(results, key=lambda x: (x[0] or (0, 0)), reverse=True):
        print(f"  {i:>3}. {c['title']:<24} {fmt_res(res)}")
    print("\n提示: 分辨率由主播端推流决定，同一平台内不同频道画质可能差异很大；"
          "选择列表里最高的即可获得该源的最佳画质。")


# ---------------- 交互模式 ----------------
def choose(prompt: str, items, fmt) -> int:
    """通用选择器，返回合法序号（0-based）"""
    while True:
        raw = input(prompt).strip()
        if raw.isdigit():
            i = int(raw) - 1
            if 0 <= i < len(items):
                return i
        print(f"请输入 1~{len(items)} 之间的数字")


def interactive(start_index: int = None):
    print("正在获取平台列表...")
    platforms = get_platforms()
    if not platforms:
        print("未获取到任何平台，接口可能已失效。")
        return
    for i, p in enumerate(platforms, 1):
        print(f"{i:>3}. {p['title']:<12} 频道数: {p['number']}")

    idx = start_index - 1 if start_index else choose("\n选择平台序号: ", platforms, None)
    while True:
        p = platforms[idx]
        print(f"\n正在获取 [{p['title']}] 的频道列表...")
        try:
            channels = get_channels(p["url"])
        except Exception as e:  # noqa: BLE001
            print(f"获取失败: {e}")
            return
        if not channels:
            print("该平台暂无频道。")
            return
        for i, c in enumerate(channels, 1):
            print(f"{i:>3}. {c['title']}")
        raw = input(f"选择频道 1~{len(channels)}（0 返回平台列表）: ").strip()
        if raw in ("", "0"):
            idx = choose("选择平台序号: ", platforms, None)
            continue
        if raw.isdigit() and 1 <= int(raw) <= len(channels):
            c = channels[int(raw) - 1]
            play_channel(c["title"], c["url"])
        else:
            print("输入无效")


def main():
    ap = argparse.ArgumentParser(description="ss直播 Python 版（源自 ss直播.js 规则）")
    ap.add_argument("--list", action="store_true", help="仅列出平台")
    ap.add_argument("--platform", type=int, metavar="N", help="直接进入第 N 个平台")
    ap.add_argument("--m3u", metavar="FILE", help="导出 M3U 播放列表")
    ap.add_argument("--probe", type=int, metavar="N", help="探测第 N 个平台各频道的真实分辨率")
    args = ap.parse_args()

    try:
        if args.probe:
            probe_platform(args.probe)
        elif args.m3u:
            export_m3u(args.m3u)
        elif args.list:
            for i, p in enumerate(get_platforms(), 1):
                print(f"{i:>3}. {p['title']:<12} 频道数: {p['number']}")
        else:
            interactive(args.platform)
    except KeyboardInterrupt:
        print("\n已退出")
    except Exception as e:  # noqa: BLE001
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
