#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
import json
import base64
import html as html_lib
import urllib.request
import urllib.parse
from urllib.parse import urlparse, quote, unquote
import http.cookiejar
import gzip
import zlib
import ssl

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"

class Spider(SpiderBase):
    def __init__(self):
        super(Spider, self).__init__()
        self.targetSiteName = "rouAV"
        self.cacheKey = "rouav_live_host"
        self.navUrls = ["https://x99dh.net", "https://x99dh.lat"]
        self.defaultHost = "https://rou123.ws"
        self.siteUrl = self.defaultHost
        self.tgGroup = "https://t.me/+3t5XRPPo9mlkZDRl"
        self.brandActor = "📺TG群: https://t.me/+3t5XRPPo9mlkZDRl"
        self.brandDirector = "📺ZakaTV"
        self._ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        self.options = {}

        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}

        self._refresh_site_url_from_nav()
        return True

    def getName(self):
        return "Zaka·肉视频(动态自愈版)"

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".avi", ".ts", ".mpd", "index.png"))

    def manualVideoCheck(self):
        return False

    def _decompress(self, raw, enc=""):
        if not raw:
            return b""
        if raw.startswith(b"\x1f\x8b") or enc == "gzip":
            try:
                return gzip.decompress(raw)
            except Exception:
                pass
        elif enc == "deflate":
            try:
                return zlib.decompress(raw)
            except Exception:
                try:
                    return zlib.decompress(raw, -zlib.MAX_WBITS)
                except Exception:
                    pass
        return raw

    def _refresh_site_url_from_nav(self):
        headers = {
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Cache-Control": "max-age=0",
            "Connection": "close",
            "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }

        for nav in self.navUrls:
            raw = b""
            enc = ""
            try:
                req = urllib.request.Request(nav, headers=headers)
                with self.opener.open(req, timeout=8) as resp:
                    raw = resp.read()
                    enc = getattr(resp, "headers", {}).get("Content-Encoding", "")
            except urllib.error.HTTPError as e:
                try:
                    raw = e.read()
                    enc = getattr(e, "headers", {}).get("Content-Encoding", "")
                except Exception:
                    raw = b""
            except Exception:
                continue

            if not raw:
                continue

            decomp = self._decompress(raw, enc)
            try:
                html_text = decomp.decode("utf-8")
            except Exception:
                html_text = decomp.decode("latin1", errors="ignore")

            if not html_text:
                continue

            b64_blocks = re.findall(r'["\']([A-Za-z0-9+/=]{100,})["\']', html_text)
            for b in b64_blocks:
                try:
                    dec = base64.b64decode(b).decode("utf-8", errors="ignore")
                    unq = urllib.parse.unquote(dec)
                    if "[" in unq and "{" in unq and self.targetSiteName.lower() in unq.lower():
                        site_list = json.loads(unq)
                        if isinstance(site_list, list):
                            for item in site_list:
                                if str(item.get("name", "")).strip().lower() == self.targetSiteName.lower():
                                    direct_target_url = item.get("url", "").strip()
                                    if direct_target_url:
                                        parsed = urllib.parse.urlparse(direct_target_url)
                                        base_host = "%s://%s" % (parsed.scheme, parsed.netloc)
                                        self.siteUrl = base_host
                                        self.setCache(self.cacheKey, base_host)
                                        return True
                except Exception:
                    continue

        cached_host = self.getCache(self.cacheKey)
        if cached_host and str(cached_host).startswith("http"):
            self.siteUrl = str(cached_host).strip().rstrip("/")
            return True

        self.siteUrl = self.defaultHost
        return False

    def _fetch(self, target_url, referer="", check_host=True):
        if not target_url:
            return {"code": 0, "text": "", "bytes": b"", "err": "", "final_url": "", "headers": {}}
        if target_url.startswith("//"):
            target_url = "https:" + target_url
        elif target_url.startswith("/"):
            target_url = self.siteUrl + target_url

        headers = {
            "User-Agent": self._ua,
            "Referer": referer if referer else (self.siteUrl + "/"),
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }

        last_err = ""
        for attempt in range(2):
            try:
                req = urllib.request.Request(target_url, headers=headers)
                with self.opener.open(req, timeout=12) as resp:
                    code = resp.getcode()
                    final_url = resp.geturl()
                    raw = resp.read()
                    resp_headers = dict(resp.headers)
                    enc = resp_headers.get("Content-Encoding", "").lower()
                    decomp = self._decompress(raw, enc)
                    try:
                        text = decomp.decode("utf-8")
                    except Exception:
                        text = decomp.decode("latin1", errors="ignore")
                    return {
                        "code": code,
                        "text": text,
                        "bytes": decomp,
                        "err": "",
                        "final_url": final_url,
                        "headers": resp_headers
                    }
            except urllib.error.HTTPError as e:
                last_err = "HTTP %s" % e.code
                if e.code in (404, 451, 502, 503) and check_host and attempt == 0:
                    old_host = urllib.parse.urlparse(self.siteUrl).netloc
                    self.delCache(self.cacheKey)
                    if self._refresh_site_url_from_nav():
                        new_host = urllib.parse.urlparse(self.siteUrl).netloc
                        target_url = target_url.replace(old_host, new_host)
                        continue
                if e.code in (451, 403, 429) and attempt == 0:
                    continue
                err_raw = ""
                try:
                    err_decomp = self._decompress(e.read(), getattr(e, "headers", {}).get("Content-Encoding", ""))
                    err_raw = err_decomp.decode("utf-8", errors="ignore")
                except Exception:
                    pass
                return {
                    "code": e.code,
                    "text": err_raw,
                    "bytes": b"",
                    "err": str(e),
                    "final_url": target_url,
                    "headers": dict(getattr(e, "headers", {}))
                }
            except Exception as e:
                last_err = str(e)
                if check_host and attempt == 0:
                    old_host = urllib.parse.urlparse(self.siteUrl).netloc
                    self.delCache(self.cacheKey)
                    if self._refresh_site_url_from_nav():
                        new_host = urllib.parse.urlparse(self.siteUrl).netloc
                        target_url = target_url.replace(old_host, new_host)
                        continue
                if attempt == 0:
                    continue
                return {"code": -1, "text": "", "bytes": b"", "err": str(e), "final_url": target_url, "headers": {}}

        return {"code": -1, "text": "", "bytes": b"", "err": last_err, "final_url": target_url, "headers": {}}

    def homeContent(self, filter):
        result = {
            "class": [
                {"type_name": "国产AV", "type_id": "7"},
                {"type_name": "日本", "type_id": "3"},
                {"type_name": "自拍流出", "type_id": "6"},
                {"type_name": "探花", "type_id": "5"},
                {"type_name": "OnlyFans", "type_id": "4"},
                {"type_name": "其他", "type_id": "1"}
            ]
        }
        if filter:
            result["filters"] = {}
        return result

    def homeVideoContent(self):
        return {"list": []}

    def _parse_card_title(self, a_tag_html, surround_block_html):
        t_attr = re.search(r'(?:title|alt)=["\']([^"\']+)["\']', a_tag_html, re.I)
        if t_attr:
            val = html_lib.unescape(t_attr.group(1)).strip()
            if len(val) > 2 and not re.match(r'^\d+:\d+$', val) and not re.search(r'\d+月\d+日', val):
                return val

        h_tag = re.search(r'<(?:h[2-6]|p|div)[^>]+class=["\'][^"\']*(?:title|name)[^"\']*["\'][^>]*>([\s\S]*?)</(?:h[2-6]|p|div)>', surround_block_html, re.I)
        if h_tag:
            val = re.sub(r'<[^>]+>', '', h_tag.group(1)).strip()
            val = html_lib.unescape(val)
            if val and not re.search(r'\d+月\d+日', val):
                return val

        raw_text = re.sub(r'<[^>]+>', '\n', surround_block_html if surround_block_html else a_tag_html)
        raw_text = html_lib.unescape(raw_text)
        lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

        candidates = []
        for line in lines:
            if re.match(r'^\d+:\d+(?::\d+)?$', line):
                continue
            if re.search(r'\d+月\d+日', line) or " | " in line:
                continue
            if line in ("国产AV", "日本", "自拍流出", "探花", "OnlyFans", "其他", "HD", "高清"):
                continue
            candidates.append(line)

        return candidates[0] if candidates else (lines[0] if lines else "肉视频")

    def categoryContent(self, tid, pg, filter, extend):
        del filter, extend
        slug = str(tid).strip("/")
        page_num = int(pg) if pg else 1
        page_url = "/vodtype/%s-%s.html" % (slug, page_num) if page_num > 1 else ("/vodtype/%s.html" % slug)

        res = self._fetch(self.siteUrl + page_url)
        html = res.get("text", "")

        vod_list = []
        seen_links = set()

        chunks = re.split(r'(?=<div[^>]+class=["\'][^"\']*(?:col-|myui-vodlist__box|item)[^"\']*["\'])', html)
        if len(chunks) <= 1:
            chunks = [html]

        for chunk in chunks:
            link_m = re.search(r'<a[^>]+href=["\'](/vodplay/\d+-[\d-]+?\.html)["\'][^>]*>([\s\S]*?)</a>', chunk, re.I)
            if not link_m:
                continue

            href = link_m.group(1).strip()
            if href in seen_links:
                continue
            seen_links.add(href)

            inner = link_m.group(2)
            pic_m = re.search(r'(?:data-original|data-src|src)=["\']([^"\']+)["\']', chunk, re.I)
            if not pic_m:
                continue
            pic_url = pic_m.group(1).strip()
            if pic_url.startswith("//"):
                pic_url = "https:" + pic_url

            title = self._parse_card_title(inner, chunk)

            vod_list.append({
                "vod_id": href,
                "vod_name": title,
                "vod_pic": pic_url,
                "vod_remarks": "ZakaTV",
                "style": {"type": "rect", "ratio": 1.78}
            })

        return {
            "page": page_num,
            "pagecount": (page_num + 1) if len(vod_list) >= 15 else page_num,
            "limit": len(vod_list),
            "total": 9999,
            "list": vod_list
        }

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        play_path = raw_id if raw_id.startswith("/") else ("/" + raw_id)
        target_url = self.siteUrl + play_path

        res = self._fetch(target_url)
        html = res.get("text", "")

        title_m = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', html, re.I)
        if title_m:
            vod_name = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
        else:
            t_fallback = re.search(r'<title>(.*?)</title>', html, re.I)
            vod_name = t_fallback.group(1).split("-")[0].strip() if t_fallback else "肉视频"

        player_m = re.search(r'<script[^>]*>\s*var\s+player_aaaa\s*=\s*(\{[\s\S]*?\})\s*</script>', html)
        api_route = ""
        if player_m:
            try:
                p_info = json.loads(player_m.group(1))
                b64_url = p_info.get("url", "")
                if b64_url:
                    decoded = base64.b64decode(b64_url).decode("utf-8")
                    url_json = json.loads(decoded)
                    ss = url_json.get("ss", [])
                    if ss and isinstance(ss[0], (list, tuple)) and len(ss[0]) > 1:
                        api_route = ss[0][1]
            except Exception:
                pass

        if not api_route:
            api_match = re.search(r'["\'](/api/v/[a-zA-Z0-9_-]+)["\']', html)
            if api_match:
                api_route = api_match.group(1)

        dispatch_url = (self.siteUrl + api_route) if api_route else target_url
        vod_play_url = "正片$%s" % dispatch_url

        full_desc = (
            "【🔥 官方交流群: %s】\n"
            "【当前动态主站: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "片名：%s\n"
            "线路：肉视频自愈极速专线，已穿透调度端点支持高速拖拽播放。"
        ) % (self.tgGroup, self.siteUrl, vod_name)

        escaped_desc = full_desc.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        return {
            "list": [{
                "vod_id": raw_id,
                "vod_name": vod_name,
                "vod_pic": "",
                "vod_actor": self.brandActor,
                "vod_director": self.brandDirector,
                "vod_remarks": "ZakaTV",
                "vod_content": escaped_desc,
                "vod_play_from": "肉视频自愈线",
                "vod_play_url": vod_play_url
            }]
        }

    def playerContent(self, flag, id, vipFlags):
        raw_url = str(id).strip()

        if "/api/v/" in raw_url:
            api_res = self._fetch(raw_url, referer=self.siteUrl + "/")
            try:
                api_json = json.loads(api_res.get("text", "{}"))
                video_url = api_json.get("video", {}).get("videoUrl", "")
                if video_url:
                    hls_res = self._fetch(video_url, referer=self.siteUrl + "/")
                    final_url = hls_res.get("final_url", video_url)
                    headers_dict = hls_res.get("headers", {})

                    if final_url == video_url:
                        loc = headers_dict.get("Location") or headers_dict.get("location")
                        if loc:
                            final_url = loc if loc.startswith("http") else urllib.parse.urljoin(video_url, loc)

                    return {
                        "parse": 0,
                        "playUrl": "",
                        "url": final_url,
                        "header": {
                            "User-Agent": self._ua,
                            "Referer": self.siteUrl + "/",
                            "Origin": self.siteUrl,
                            "Connection": "keep-alive"
                        },
                        "position": 1
                    }
            except Exception:
                pass

        return {
            "parse": 0,
            "playUrl": "",
            "url": raw_url,
            "header": {
                "User-Agent": self._ua,
                "Referer": self.siteUrl + "/",
                "Origin": self.siteUrl,
                "Connection": "keep-alive"
            },
            "position": 1
        }

    def searchContent(self, key, quick, pg="1"):
        page_num = int(pg) if pg else 1
        query_encoded = quote(key)
        search_path = "/vodsearch/%s----------%s---.html" % (query_encoded, page_num) if page_num > 1 else ("/vodsearch/-------------.html?wd=%s" % query_encoded)
        res = self._fetch(self.siteUrl + search_path)
        html = res.get("text", "")

        vod_list = []
        seen_links = set()

        chunks = re.split(r'(?=<div[^>]+class=["\'][^"\']*(?:col-|myui-vodlist__box|item)[^"\']*["\'])', html)
        if len(chunks) <= 1:
            chunks = [html]

        for chunk in chunks:
            link_m = re.search(r'<a[^>]+href=["\'](/vodplay/\d+-[\d-]+?\.html)["\'][^>]*>([\s\S]*?)</a>', chunk, re.I)
            if not link_m:
                continue

            href = link_m.group(1).strip()
            if href in seen_links:
                continue
            seen_links.add(href)

            inner = link_m.group(2)
            pic_m = re.search(r'(?:data-original|data-src|src)=["\']([^"\']+)["\']', chunk, re.I)
            pic_url = ""
            if pic_m:
                pic_url = pic_m.group(1).strip()
                if pic_url.startswith("//"):
                    pic_url = "https:" + pic_url

            title = self._parse_card_title(inner, chunk)

            vod_list.append({
                "vod_id": href,
                "vod_name": title,
                "vod_pic": pic_url,
                "vod_remarks": "ZakaTV",
                "style": {"type": "rect", "ratio": 1.78}
            })

        return {
            "page": page_num,
            "pagecount": (page_num + 1) if len(vod_list) >= 15 else page_num,
            "limit": len(vod_list),
            "total": 9999,
            "list": vod_list
        }

    def action(self, action):
        if action == "toast":
            return {"msg": "当前有效主站: %s" % self.siteUrl}
        return {"msg": "ok"}

    def liveContent(self):
        return ""

    def localProxy(self, params):
        return [404, "text/plain; charset=utf-8", "Proxy not configured"]

    def destroy(self):
        self.options = {}
