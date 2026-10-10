import sys
import ssl
import time
import json
import re
import urllib.request
import urllib.parse
from http.cookiejar import CookieJar

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass

def _dec(s):
    import base64
    try:
        return base64.b64decode(s).decode("utf-8")
    except Exception:
        return ""

_WORKER = _dec("aHR0cHM6Ly84ODQ1MTUxMjEyMTIxMjY1MjYyNjIzMzk4NTk2MjMxMjIxLnBhZ2VzLmRldg==")

_AES_SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16]
_AES_INV_SBOX = [0] * 256
for _i, _v in enumerate(_AES_SBOX):
    _AES_INV_SBOX[_v] = _i
_AES_RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]

def _xtime(a):
    return ((a << 1) ^ 0x1b) & 0xff if a & 0x80 else (a << 1) & 0xff

def _gmul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r

def _aes_key_expansion(key):
    w = [int.from_bytes(key[i*4:(i+1)*4], "big") for i in range(4)]
    for i in range(4, 44):
        t = w[i-1]
        if i % 4 == 0:
            t = (_AES_SBOX[(t >> 16) & 0xff] << 24 |
                 _AES_SBOX[(t >> 8) & 0xff] << 16 |
                 _AES_SBOX[t & 0xff] << 8 |
                 _AES_SBOX[(t >> 24) & 0xff]) ^ (_AES_RCON[i // 4 - 1] << 24)
        w.append(w[i-4] ^ t)
    return [b"".join(x.to_bytes(4, "big") for x in w[i:i+4])
            for i in range(0, 44, 4)]

def _aes_decrypt_block(rks, block):
    s = [block[i] ^ rks[10][i] for i in range(16)]
    for rnd in range(9, 0, -1):
        s = [_AES_INV_SBOX[b] for b in
             (s[0],s[13],s[10],s[7],s[4],s[1],s[14],s[11],
              s[8],s[5],s[2],s[15],s[12],s[9],s[6],s[3])]
        rk = rks[rnd]
        s = [s[i] ^ rk[i] for i in range(16)]
        for c in range(4):
            a0,a1,a2,a3 = s[4*c],s[4*c+1],s[4*c+2],s[4*c+3]
            s[4*c]   = _gmul(a0,0x0e)^_gmul(a1,0x0b)^_gmul(a2,0x0d)^_gmul(a3,0x09)
            s[4*c+1] = _gmul(a0,0x09)^_gmul(a1,0x0e)^_gmul(a2,0x0b)^_gmul(a3,0x0d)
            s[4*c+2] = _gmul(a0,0x0d)^_gmul(a1,0x09)^_gmul(a2,0x0e)^_gmul(a3,0x0b)
            s[4*c+3] = _gmul(a0,0x0b)^_gmul(a1,0x0d)^_gmul(a2,0x09)^_gmul(a3,0x0e)
    s = [_AES_INV_SBOX[b] for b in
         (s[0],s[13],s[10],s[7],s[4],s[1],s[14],s[11],
          s[8],s[5],s[2],s[15],s[12],s[9],s[6],s[3])]
    return bytes(s[i] ^ rks[0][i] for i in range(16))

def _pkcs7_unpad(data):
    if not data:
        return data
    pad = data[-1]
    if 1 <= pad <= 16 and len(data) >= pad \
            and data[-pad:] == bytes([pad]) * pad:
        return data[:-pad]
    return data

def _aes_ecb_decrypt(key, data):
    data = data[:len(data) - len(data) % 16]
    if len(data) < 16:
        return b""
    try:
        from Crypto.Cipher import AES
        pt = AES.new(key, AES.MODE_ECB).decrypt(data)
    except Exception:
        rks = _aes_key_expansion(key)
        pt = b"".join(_aes_decrypt_block(rks, data[i:i+16])
                      for i in range(0, len(data), 16))
    return _pkcs7_unpad(pt)

class Spider(BaseSpider):
    def __init__(self):
        self.site_url = "https://anxiety.xdnwqmeex.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": self.site_url + "/",
        }
        self.cookie_jar = CookieJar()
        self.opener = self._build_opener()

        self.cats = [
            ("cat@now_month_hot", "热门排行"),
            ("cat@original", "国产原创"),
            ("kw@吃瓜 黑料 爆料", "吃瓜爆料"),
            ("kw@熟女", "熟女做爱"),
            ("kw@萝莉", "可爱萝莉"),
            ("kw@动漫", "成人动漫"),
            ("kw@黑人", "大屌黑人"),
            ("kw@巨乳", "童颜巨乳"),
            ("kw@换妻", "少妇换妻"),
            ("kw@内射", "内射中出"),
            ("kw@按摩", "会所按摩"),
            ("kw@探花", "探花"),
        ]
        self._throttle = 0.5
        self._last_req = 0.0

        self._cover_key = b"525202f9149e061d"

        self._worker = _WORKER
        self._pic_cache = {}

    def _build_opener(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        https_handler = urllib.request.HTTPSHandler(context=ctx)
        cookie_handler = urllib.request.HTTPCookieProcessor(self.cookie_jar)
        return urllib.request.build_opener(https_handler, cookie_handler)

    def init(self, extend=""):
        try:
            cfg = json.loads(extend) if extend and extend.strip() else {}
            host = str(cfg.get("host", "")).strip().rstrip("/")
            if host:
                self.site_url = host
                self.headers["Referer"] = host + "/"
            worker = str(cfg.get("worker", "")).strip().rstrip("/")
            if worker:
                self._worker = worker
        except Exception:
            pass

    def getName(self):
        return "白嫖之王"

    def _decode(self, raw, enc=""):
        import gzip, zlib
        if not raw:
            return ""
        if isinstance(raw, str):
            return raw
        if "gzip" in enc:
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        elif "deflate" in enc:
            try:
                raw = zlib.decompress(raw)
            except Exception:
                pass
        for cs in ("utf-8", "gbk", "gb2312"):
            try:
                return raw.decode(cs)
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")

    def _fetch(self, url, timeout=15, retries=2, referer=None, extra_headers=None):
        import http.client
        gap = time.time() - self._last_req
        if gap < self._throttle:
            time.sleep(self._throttle - gap)
        self._last_req = time.time()
        headers = dict(self.headers)
        if referer:
            headers["Referer"] = referer
        if extra_headers:
            headers.update(extra_headers)
        last_err = ""
        for i in range(retries + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                with self.opener.open(req, timeout=timeout) as resp:
                    raw = resp.read()
                    enc = resp.headers.get("Content-Encoding", "").lower()
                    return {"success": True, "html": self._decode(raw, enc)}
            except http.client.IncompleteRead as e:
                if e.partial:
                    return {"success": True, "html": self._decode(e.partial)}
                last_err = str(e)
            except Exception as e:
                last_err = str(e)
                if i < retries:
                    time.sleep(0.5)
        return {"success": False, "html": "", "error": last_err}

    def _fetch_html(self, url, must_contain=None, referer=None):
        html_data = ""
        for _ in range(3):
            res = self._fetch(url, referer=referer)
            html_data = res.get("html", "")
            if res.get("success") and (not must_contain
                                       or must_contain in html_data):
                return html_data
        return html_data

    @staticmethod
    def _clean(t):
        import html as hm
        if not t:
            return ""
        return re.sub(r"<[^>]+>", "", hm.unescape(t)).strip()

    def _abs(self, u):
        if not u:
            return ""
        u = u.strip()
        if u.startswith("http"):
            return u
        if u.startswith("//"):
            return "https:" + u
        return urllib.parse.urljoin(self.site_url + "/", u)

    def _fetch_bytes(self, url, timeout=20):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": self.headers["User-Agent"],
                "Referer": self.site_url + "/"})
            with self.opener.open(req, timeout=timeout) as resp:
                return resp.read()
        except Exception:
            return b""

    @staticmethod
    def _mime(data):
        if not data or len(data) < 12:
            return ""
        if data[:2] == b"\xff\xd8":
            return "image/jpeg"
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        if data[:4] == b"\x00\x00\x01\x00":
            return "image/x-icon"
        return ""

    def _decrypt_cover(self, raw):
        if not raw:
            return b""
        if raw[:2] == b"\xff\xd8" or raw[:8] == b"\x89PNG\r\n\x1a\n":
            return raw
        try:
            pt = _aes_ecb_decrypt(self._cover_key, raw)
            if pt[:2] == b"\xff\xd8":
                return pt
        except Exception:
            pass
        return b""

    def _proxy_pic_url(self, pic):
        if not pic or pic.startswith("http://127.0.0.1"):
            return pic
        if self._worker:
            return "%s?url=%s" % (self._worker,
                                  urllib.parse.quote(pic, safe=""))
        base = ""
        try:
            base = self.getProxyUrl() or ""
        except Exception:
            pass
        if not base:
            base = "http://127.0.0.1:9978/proxy"
        return "%s?do=py&type=pic&url=%s" % (
            base, urllib.parse.quote(pic, safe=""))

    def localProxy(self, params):

        try:
            if params.get("type") == "pic":
                url = params.get("url", "")
                if url:
                    if url in self._pic_cache:
                        return self._pic_cache[url]
                    raw = self._fetch_bytes(url, timeout=20)
                    img = self._decrypt_cover(raw)
                    if img:
                        mime = self._mime(img) or "image/jpeg"
                        res = [200, mime, img, ""]
                        if len(self._pic_cache) < 60:
                            self._pic_cache[url] = res
                        return res
        except Exception:
            pass
        return [200, "text/plain; charset=utf-8", ""]

    @staticmethod
    def _unpack(packed):
        try:
            m = re.search(r"\}\('(.*)',(\d+),(\d+),'(.*?)'\.split\('\|'\)",
                          packed, re.S)
            if not m:
                return ""
            p, a, c = m.group(1), int(m.group(2)), int(m.group(3))
            k = m.group(4).split("|")

            def enc(n):
                if n == 0:
                    return "0"
                s = ""
                while n > 0:
                    d = n % a
                    if d > 35:
                        s = chr(d + 29) + s
                    else:
                        s = "0123456789abcdefghijklmnopqrstuvwxyz"[d] + s
                    n //= a
                return s

            for i in range(c - 1, -1, -1):
                w = enc(i)
                p = re.sub(r"\b" + re.escape(w) + r"\b",
                           k[i] if i < len(k) else w, p)
            return p
        except Exception:
            return ""

    def _parse_vod_list(self, html_data):
        cards, seen = [], set()
        if not html_data:
            return cards
        for m in re.finditer(
                r'<div[^>]*class="[^"]*video-item[^"]*"[^>]*>(.*?)'
                r'(?=<div[^>]*class="[^"]*video-item[^"]*"|$)',
                html_data, re.S):
            block = m.group(1)
            am = re.search(r'href="(/comic/index/(?:avdetail|detail)\?video_key=[^"]+)"', block)
            if not am:
                continue
            url = self._abs(am.group(1))
            key = am.group(1)
            if key in seen:
                continue
            seen.add(key)
            title = ""
            tm = re.search(r'alt="([^"]+)"', block)
            if tm:
                title = tm.group(1).strip()
            if not title:
                hm = re.search(r'line-clamp-2[^"]*"[^>]*>(.*?)</div>', block, re.S)
                if hm:
                    title = self._clean(hm.group(1))
            pic = ""
            pm = re.search(r'data-src="([^"]+)"', block)
            if pm:
                pic = self._abs(pm.group(1).strip())
            if not pic:
                pm = re.search(r'<img[^>]+src="(?!/static)([^"]+)"', block)
                if pm:
                    pic = self._abs(pm.group(1).strip())
            remark = ""
            dm = re.search(r'rounded-large[^"]*"[^>]*>\s*([\d:]+)\s*</div>', block)
            if dm:
                remark = dm.group(1).strip()
            cards.append({
                "vod_id": url,
                "vod_name": title or key,
                "vod_pic": self._proxy_pic_url(pic),
                "vod_remarks": remark,
                "style": {"type": "rect", "ratio": 1.78},
            })
        return cards

    def _detail_play_url(self, detail_html):
        try:
            for m in re.finditer(r"(eval\(function\(p,a,c,k,e,d\).*?</script>)",
                                 detail_html, re.S):
                up = self._unpack(m.group(1))
                if "detail_play" not in up:
                    continue
                img = re.search(r"img=(%2F[^&]*)", up)
                u = re.search(r'encodeURIComponent\("([0-9a-f]+)"\)', up)
                if img and u:
                    t = str(int(time.time() / 1800))
                    return ("%s/index/detail_play?img=%s&ads=&u=%s&t=%s"
                            % (self.site_url, img.group(1), u.group(1), t))
            return ""
        except Exception:
            return ""

    def _m3u8_from_detail(self, detail_url):
        try:
            html_data = self._fetch_html(detail_url, must_contain="video_key",
                                         referer=self.site_url + "/")
            if not html_data:
                return ""
            dp_url = self._detail_play_url(html_data)
            if not dp_url:
                return ""
            res = self._fetch(dp_url, referer=detail_url)
            if not res.get("success"):
                return ""
            up = self._unpack(res["html"])
            if not up:
                return ""
            m3 = re.search(r"""url\s*:\s*['"]([^'"]+\.m3u8[^'"]*)['"]""", up)
            if not m3:
                m3 = re.search(r"(/[^\s'\"]+\.m3u8[^\s'\"]*)", up)
            if not m3:
                return ""
            return self._abs(m3.group(1))
        except Exception:
            return ""

    @staticmethod
    def _detail_title(html_data):
        m = re.search(r'property="og:title"[^>]*content="([^"]+)"', html_data)
        title = m.group(1).strip() if m else ""
        if not title:
            m = re.search(r"const _detail_ = (\{.*?\});", html_data, re.S)
            if m:
                try:
                    title = json.loads(m.group(1)).get("title", "").strip()
                except Exception:
                    pass
        if not title:
            m = re.search(r"<title>(.*?)</title>", html_data, re.S | re.I)
            if m:
                title = m.group(1).strip()
        title = re.sub(r"\s*[-–—|]\s*白嫖之王.*$", "", title).strip()
        return title

    def _pagecount(self, cards, pg, per_page=20):
        return pg + 1 if len(cards) >= per_page else pg

    def homeContent(self, filter):
        return {"class": [{"type_id": t, "type_name": n} for t, n in self.cats],
                "filters": {}}

    def homeVideoContent(self):
        html_data = self._fetch_html(self.site_url + "/index/av",
                                     must_contain="video-item")
        return {"list": self._parse_vod_list(html_data)[:20]}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        tid = str(tid).strip()
        if "@" in tid:
            kind, val = tid.split("@", 1)
        else:
            kind, val = "cat", tid
        if kind == "kw":
            url = "%s/index/search?keyword=%s" % (
                self.site_url, urllib.parse.quote_plus(val))
        else:
            url = "%s/index/video?category=%s" % (
                self.site_url, urllib.parse.quote(val))
        if pg > 1:
            url += "&page=%d" % pg
        html_data = self._fetch_html(url, must_contain="video-item")
        cards = self._parse_vod_list(html_data)
        return {"list": cards, "page": pg,
                "pagecount": self._pagecount(cards, pg),
                "limit": len(cards), "total": 0}

    def detailContent(self, ids):
        raw = ids[0] if isinstance(ids, list) and ids else str(ids)
        vod = {"vod_id": raw, "vod_name": raw, "vod_pic": "",
               "vod_remarks": "", "vod_content": "",
               "vod_play_from": "在线播放", "vod_play_url": ""}
        if not raw:
            return {"list": [vod]}
        detail_url = raw if raw.startswith("http") else self._abs(raw)
        try:
            html_data = self._fetch_html(detail_url, must_contain="video_key",
                                         referer=self.site_url + "/")
            if not html_data:
                return {"list": [vod]}
            title = self._detail_title(html_data)
            if title:
                vod["vod_name"] = title
                vod["vod_content"] = title
            pm = re.search(r'property="og:image"[^>]*content="([^"]+)"', html_data)
            if pm:
                vod["vod_pic"] = self._proxy_pic_url(self._abs(pm.group(1)))
            vm = re.search(r'property="og:description"[^>]*content="([^"]+)"',
                           html_data)
            if vm:
                vod["vod_remarks"] = self._clean(vm.group(1))[:40]
            m3u8 = self._m3u8_from_detail(detail_url)
            if m3u8:
                vod["vod_play_url"] = "正片$%s" % m3u8
            else:
                vod["vod_play_url"] = "正片$%s" % detail_url
        except Exception:
            pass
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        raw_id = str(id).strip()
        header = {"User-Agent": self.headers["User-Agent"],
                  "Referer": self.site_url + "/"}
        if raw_id.startswith("http") and self.isVideoFormat(raw_id):
            return {"parse": 0, "url": raw_id, "header": header}
        try:
            detail_url = raw_id if raw_id.startswith("http") else self._abs(raw_id)
            m3u8 = self._m3u8_from_detail(detail_url)
            if m3u8:
                return {"parse": 0, "url": m3u8, "header": header}
        except Exception:
            pass
        return {"parse": 1, "url": raw_id, "header": header}

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        url = "%s/index/search?keyword=%s" % (
            self.site_url, urllib.parse.quote_plus(str(key).strip()))
        if pg > 1:
            url += "&page=%d" % pg
        html_data = self._fetch_html(url, must_contain="video-item")
        cards = self._parse_vod_list(html_data)
        return {"list": cards, "page": pg,
                "pagecount": self._pagecount(cards, pg),
                "limit": len(cards), "total": 0}

    def action(self, action):
        return None

    def liveContent(self):
        return {}

    def isVideoFormat(self, url):
        u = (url or "").lower()
        return u.endswith(".m3u8") or ".m3u8?" in u or u.endswith(".mp4")

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

if __name__ == "__main__":
    sp = Spider()
    sp.init()
    ok = True

    def check(name, cond, extra=""):
        global ok
        print(("PASS " if cond else "FAIL ") + name +
              (" | " + str(extra) if extra else ""))
        if not cond:
            ok = False

    import ast as _ast
    _ast.parse(open(__file__, encoding="utf-8").read())
    check("syntax", True)

    p1 = ("eval(function(p,a,c,k,e,d){e=function(c){return c.toString(36)};"
          "if(!''.replace(/^/,String)){while(c--){d[c.toString(a)]=k[c]||c.toString(a)}"
          "k=[function(e){return d[e]}];e=function(){return'\\\\w+'};c=1};"
          "while(c--){if(k[c]){p=p.replace(new RegExp('\\\\b'+e(c)+'\\\\b','g'),k[c])}}"
          "return p}('0 1',2,2,'hello|world'.split('|'),0,{}))")
    check("unpack_v1", sp._unpack(p1) == "hello world", sp._unpack(p1)[:40])
    p2 = ("eval(function(p,a,c,k,e,d){e=function(c){return(c<a?'':e(parseInt(c/a)))"
          "+((c=c%a)>35?String.fromCharCode(c+29):c.toString(36))};"
          "if(!''.replace(/^/,String)){while(c--){d[e(c)]=k[c]||e(c)}"
          "k=[function(e){return d[e]}];e=function(){return'\\\\w+'};c=1};"
          "while(c--){if(k[c]){p=p.replace(new RegExp('\\\\b'+e(c)+'\\\\b','g'),k[c])}}"
          "return p}('0 1',2,2,'foo|bar'.split('|'),0,{}))")
    check("unpack_v2", sp._unpack(p2) == "foo bar", sp._unpack(p2)[:40])

    hc = sp.homeContent(True)
    check("homeContent", len(hc["class"]) == 12, "%d分类" % len(hc["class"]))

    r = sp.categoryContent("cat@original", "1", None, None)
    check("category", len(r["list"]) > 0, "%d条" % len(r["list"]))
    pics = sum(1 for v in r["list"] if v["vod_pic"] and "url=" in v["vod_pic"])
    check("covers_proxy", pics == len(r["list"]) and pics > 0,
          "%d/%d 走中转" % (pics, len(r["list"])))

    if r["list"]:
        import urllib.parse as _up
        purl = r["list"][0]["vod_pic"]
        real = _up.unquote(purl.split("url=", 1)[1])
        pr = sp.localProxy({"type": "pic", "url": real})
        ok_img = pr[0] == 200 and pr[1].startswith("image/") \
            and isinstance(pr[2], bytes) and pr[2][:2] == b"\xff\xd8"
        check("cover_decrypt", ok_img,
              "%s %d字节" % (pr[1], len(pr[2]) if isinstance(pr[2], bytes) else 0))

        pr2 = sp.localProxy({"type": "pic", "url": real})
        check("cover_cache", pr2[2] == pr[2], "内存缓存命中")
    titles = sum(1 for v in r["list"] if v["vod_name"] and "video_key" not in v["vod_name"])
    check("titles", titles == len(r["list"]), "%d/%d" % (titles, len(r["list"])))

    rk = sp.categoryContent("kw@熟女", "1", None, None)
    check("category_kw", len(rk["list"]) > 0, "%d条" % len(rk["list"]))

    r2 = sp.categoryContent("cat@original", "2", None, None)
    ids1 = {v["vod_id"] for v in r["list"]}
    ids2 = {v["vod_id"] for v in r2["list"]}
    check("page_no_overlap", len(r2["list"]) > 0 and not (ids1 & ids2),
          "p2=%d条" % len(r2["list"]))

    s = sp.searchContent("萝莉", False, "1")
    check("search", len(s["list"]) > 0, "%d条" % len(s["list"]))

    h = sp.homeVideoContent()
    check("home", len(h["list"]) > 0, "%d条" % len(h["list"]))

    if r["list"]:
        detail_url = r["list"][0]["vod_id"]
        d = sp.detailContent([detail_url])
        v = d["list"][0]
        has_m3u8 = ".m3u8" in v["vod_play_url"]
        check("detail", bool(v["vod_name"]) and "video_key" not in v["vod_name"]
              and has_m3u8, "%s... m3u8=%s" % (v["vod_name"][:30], has_m3u8))
        if has_m3u8:
            ep = v["vod_play_url"].split("$", 1)[1]
            p = sp.playerContent("在线播放", ep, "")
            check("player", p["parse"] == 0 and ".m3u8" in p["url"]
                  and isinstance(p.get("header"), dict) and "playUrl" not in p,
                  p["url"][:80])

        d2 = sp.detailContent(["/comic/index/avdetail?video_key=kByXgGOvZM"])
        v2 = d2["list"][0]
        check("detail_avdetail", ".m3u8" in v2["vod_play_url"],
              "%s..." % v2["vod_name"][:20])

    print("ALL PASS" if ok else "SOME FAILED")
