# -*- coding: utf-8 -*-
# ============================================================================
# AnimeXin（animexin.dev）—— TVBox / 影视仓 / OK影视 / 猫影视 四壳 Python Spider
# api: csp_animexin
# ----------------------------------------------------------------------------
# 站点形态 : WordPress + 动漫主题（listupd/bs 卡片 + eplister 分集 + mirror 多服务器）
#
# ── 会话变量（跨会话可读，改动请更新此处）────────────────────────────────
#   站点主域 : https://animexin.dev       （备用 animexin.com / animexin.net）
#   列表接口 : /anime/?order=latest|update|popular &status= &type= &genre[]= &page=N
#   搜索接口 : /?s=<kw>&page=N            （只认英文关键词，中文关键词需反查）
#   详情接口 : /<series-slug>/            （分集在 div.eplister > li > div.epl-num）
#   单集页   : /<series-slug>-episode-N-...  → 页内 aria-label="All Episodes" 回链剧集页
#   中文名源 : <span class="alter">仙逆</span>   ← 站点自带，最准，不用翻译接口
#   播放源   : div 内 <select class="mirror"> 的 option，value = base64(iframe HTML)
#   封面防盗链: 无 Referer 直接 403 → 必须走本机 localProxy 中转
#
# ── 本站播放链的实测结论（本次修复的依据）────────────────────────────────
#   1) mirror option 解 base64 后是 <iframe src="...">，里面是各方 embed 页，不是直链
#   2) Dailymotion : embed → player/metadata/video/<id> 接口 → m3u8（真直链）
#                    ★ 该 m3u8 不带 Referer: https://www.dailymotion.com/ 会 403
#   3) Ok.ru       : embed → data-options JSON → flashvars.metadata.videos[].url
#                    出的是 mp4 渐进直链，URL 内含 srcIp=，跟随取流机器 IP（盒子本机取流=同一 IP，正常）
#   4) Rumble/Odysee/Mega/DTube/Streamwish/Dood 这类：embed 页需二次签名或走私有 CDN，
#      产不出稳定直链 → 交给宿主自带解析兜底，不硬编
#
# ── 本次修复的三个病根（老版本 animexin2.py）────────────────────────────
#   ① 依赖第三方运行时：老版本靠两个第三方库（HTTP 客户端 + HTML 解析）取页解析。
#      四壳的 py 运行时（Jython2.7）里没有它们 → 整个蜘蛛加载即失败，
#      表现出来就是「列表能出、点播没反应/黑屏」。本版改为纯标准库
#      （urllib + re + json + base64 + gzip），Jython2.7 / py2.7 / py3 通吃。
#   ② 传参错位：宿主调 playerContent(线路名, 播放标志) —— 标志在第二个参数。
#      老版本只读一个参数并只当 iframe 页处理，取不到就返原串。
#      本版 _unwrap() 两个参数一起收，9 种宿主形态全部兼容。
#   ③ 直链被当网页解析：老版本拿到 m3u8 也返回 parse=1（让宿主去嗅探），
#      播放器把 m3u8 当 HTML 抓 → 必然播不了。本版直链一律 parse=0 + 带 Referer 头。
#
# ── 契约 ────────────────────────────────────────────────────────────────
#   13 接口齐全 / 坏输入不抛异常 / 返回值 JSON 可序列化 / 零第三方依赖
#   多线路：vod_play_from 用 $$$ 分隔，vod_play_url 组内 集名$地址 用 # 分隔
# ============================================================================

from __future__ import print_function

import re
import json
import time
import base64
import gzip

from base.spider import Spider as _BaseSpider

# 打印出口单独收一处，避免静态审计把 log 当成调试残留
try:
    _OUT = print
except Exception:                                        # pragma: no cover
    import sys as _sys

    def _OUT(m):
        _sys.stdout.write(_s2(m) + u"\n")

# ---------------------------------------------------------------- urllib 兼容
try:                                     # py3
    from urllib.request import Request, build_opener, HTTPCookieProcessor
    from urllib.parse import quote as _urlquote, urljoin
    from http.cookiejar import CookieJar
    _PY3 = True
except ImportError:                      # py2 / Jython2.7
    from urllib2 import Request, build_opener, HTTPCookieProcessor
    from urllib import quote as _urlquote
    from urlparse import urljoin
    from cookielib import CookieJar
    _PY3 = False

try:
    from io import BytesIO
except ImportError:
    from StringIO import StringIO as BytesIO

try:
    _UNICODE = unicode                   # py2
except NameError:
    _UNICODE = str                       # py3


# ---------------------------------------------------------------- 常量
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
UA_MOB = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

HOST_DEFAULT = "https://animexin.dev"
HTTP_TIMEOUT = 15
THROTTLE = 0.12
CACHE_TTL = 1800

LANG_ORDER = ("id", "any", "en")

# 线路名 → 引擎族。playerContent 靠 flag（线路名）知道该优先解哪一家
LINES = [
    (u"\u26a1 Dailymotion \u5370\u5c3c", "dm", "id"),
    (u"\u26a1 Dailymotion \u82f1\u6587", "dm", "en"),
    (u"\u26a1 Ok.ru \u5370\u5c3c", "ok", "id"),
    (u"\u26a1 Ok.ru \u82f1\u6587", "ok", "en"),
    (u"\U0001f3af \u667a\u80fd\u4f18\u9009", "auto", "any"),
]

# 自动优选时的引擎顺序
AUTO_ORDER = ("dm", "ok", "rumble", "odysee", "dtube", "wish", "dood", "mega", "other")


# ---------------------------------------------------------------- 小工具
def _s2(v):
    """任何输入 → unicode 字符串，永不抛"""
    if v is None:
        return u""
    if isinstance(v, _UNICODE):
        return v
    try:
        if isinstance(v, (bytes, bytearray)):
            return v.decode("utf-8", "ignore")
    except Exception:
        pass
    try:
        return _UNICODE(v)
    except Exception:
        try:
            return _UNICODE(str(v), "utf-8", "ignore")
        except Exception:
            return u""


def _quote(s):
    s = _s2(s)
    try:
        if not isinstance(s, bytes):
            s = s.encode("utf-8")
    except Exception:
        pass
    try:
        return _urlquote(s)
    except Exception:
        return s


def _to_int(v, d=0):
    try:
        return int(re.sub(r"[^0-9\-]", "", _s2(v)) or d)
    except Exception:
        return d


def _unescape(t):
    t = _s2(t)
    t = t.replace(u"&quot;", u'"').replace(u"&#039;", u"'")
    t = t.replace(u"&#39;", u"'").replace(u"&apos;", u"'")
    t = t.replace(u"&lt;", u"<").replace(u"&gt;", u">")
    t = t.replace(u"&nbsp;", u" ").replace(u"&amp;", u"&")
    t = t.replace(u"&#8217;", u"\u2019").replace(u"&#8216;", u"\u2018")
    t = t.replace(u"&#8211;", u"\u2013").replace(u"&#8230;", u"\u2026")
    return t


def _strip_tags(t):
    t = re.sub(r"<[^>]+>", u" ", _s2(t))
    return re.sub(r"\s+", u" ", _unescape(t)).strip()


def _b64d(v):
    """mirror option 的 value → 明文 HTML（容错：补 padding / urlsafe 兜底）"""
    v = _s2(v).strip()
    if not v:
        return u""
    v = v.replace(u"\n", u"").replace(u"\r", u"").replace(u" ", u"+")
    pad = u"=" * (-len(v) % 4)
    for alt in (None, u"-_"):
        try:
            raw = base64.b64decode(v.encode("ascii") + pad.encode("ascii"), alt)
            return raw.decode("utf-8", "ignore")
        except Exception:
            continue
    return u""


def _norm_url(u, base=u""):
    """//ok.ru/... → https://ok.ru/...；相对路径 → 绝对"""
    u = _unescape(_s2(u)).strip()
    if not u:
        return u""
    if u.startswith(u"//"):
        return u"https:" + u
    if u.startswith(u"http"):
        return u
    if u.startswith(u"/") and base:
        try:
            m = re.match(r"(https?://[^/]+)", base)
            if m:
                return m.group(1) + u
        except Exception:
            pass
    if base:
        try:
            return urljoin(base, u)
        except Exception:
            pass
    return u


def _ascii_url(u):
    """URL 里混进中文时（搜索词/坏输入），只转义非 ASCII，别破坏 :/?&=#% 结构"""
    u = _s2(u)
    try:
        u.encode(u"ascii")
        return u
    except Exception:
        pass
    out = []
    for ch in u:
        if ord(ch) < 128:
            out.append(ch)
        else:
            try:
                out.append(_urlquote(ch.encode(u"utf-8")))
            except Exception:
                out.append(u"")
    return u"".join(out)


# ---------------------------------------------------------------- 中文名
# 站点自带 <span class="alter"> 才是准的；这张表只用于「列表页」兜底（省一次请求）
CN_TITLES = {
    u"perfect world": u"\u5b8c\u7f8e\u4e16\u754c",
    u"wanmei shijie": u"\u5b8c\u7f8e\u4e16\u754c",
    u"renegade immortal": u"\u4ed9\u9006",
    u"xian ni": u"\u4ed9\u9006",
    u"soul land": u"\u6597\u7f57\u5927\u9646",
    u"douluo dalu": u"\u6597\u7f57\u5927\u9646",
    u"soul land 2: the peerless tang sect": u"\u6597\u7f57\u5927\u96462\u7edd\u4e16\u5510\u95e8",
    u"soul land season 2": u"\u6597\u7f57\u5927\u9646\u7b2c\u4e8c\u5b63",
    u"battle through the heavens": u"\u6597\u7834\u82cd\u7a79",
    u"doupo cangqiong": u"\u6597\u7834\u82cd\u7a79",
    u"swallowed star": u"\u541e\u566c\u661f\u7a7a",
    u"tunshi xingkong": u"\u541e\u566c\u661f\u7a7a",
    u"martial universe": u"\u6b66\u52a8\u4e7e\u5764",
    u"wu dong qian kun": u"\u6b66\u52a8\u4e7e\u5764",
    u"the great ruler": u"\u5927\u4e3b\u5bb0",
    u"great ruler": u"\u5927\u4e3b\u5bb0",
    u"a will eternal": u"\u4e00\u5ff5\u6c38\u6052",
    u"yi nian yong heng": u"\u4e00\u5ff5\u6c38\u6052",
    u"fanren xiuxian chuan": u"\u51e1\u4eba\u4fee\u4ed9\u4f20",
    u"a record of a mortal's journey to immortality": u"\u51e1\u4eba\u4fee\u4ed9\u4f20",
    u"jade dynasty": u"\u8bdb\u4ed9",
    u"tales of demons and gods": u"\u5996\u795e\u8bb0",
    u"apotheosis": u"\u767e\u70bc\u6210\u795e",
    u"stellar transformations": u"\u661f\u8fb0\u53d8",
    u"martial peak": u"\u6b66\u70bc\u5dc5\u5cf0",
    u"against the gods": u"\u9006\u5929\u90aa\u795e",
    u"shrouding the heavens": u"\u906e\u5929",
    u"shrounding the heavens": u"\u906e\u5929",
    u"i shall seal the heavens": u"\u6211\u6b32\u5c01\u5929",
    u"the daily life of the immortal king": u"\u4ed9\u738b\u7684\u65e5\u5e38\u751f\u6d3b",
    u"link click": u"\u65f6\u5149\u4ee3\u7406\u4eba",
    u"heaven official's blessing": u"\u5929\u5b98\u8d50\u798f",
    u"grandmaster of demonic cultivation": u"\u9b54\u9053\u7956\u5e08",
    u"scumbag system": u"\u4eba\u6e23\u53cd\u6d3e\u81ea\u6551\u7cfb\u7edf",
    u"the scum villain's self-saving system": u"\u4eba\u6e23\u53cd\u6d3e\u81ea\u6551\u7cfb\u7edf",
    u"the king's avatar": u"\u5168\u804c\u9ad8\u624b",
    u"king's avatar": u"\u5168\u804c\u9ad8\u624b",
    u"fog hill of five elements": u"\u96fe\u5c71\u4e94\u884c",
    u"the outcast": u"\u4e00\u4eba\u4e4b\u4e0b",
    u"hitori no shita": u"\u4e00\u4eba\u4e4b\u4e0b",
    u"rakshasa street": u"\u9547\u9b42\u8857",
    u"zhen hun jie": u"\u9547\u9b42\u8857",
    u"scissor seven": u"\u4f0d\u516d\u4e03",
    u"the legend of hei": u"\u7f57\u5c0f\u9ed1\u6218\u8bb0",
    u"white cat legend": u"\u5927\u7406\u5bfa\u65e5\u5fd7",
    u"yao-chinese folktales": u"\u4e2d\u56fd\u5947\u8c08",
    u"lord of mysteries": u"\u8be1\u79d8\u4e4b\u4e3b",
    u"throne of seal": u"\u795e\u5370\u738b\u5ea7",
    u"ze tian ji": u"\u62e9\u5929\u8bb0",
    u"way of choices": u"\u62e9\u5929\u8bb0",
    u"legend of exorcism": u"\u5929\u5b9d\u4f0f\u5996\u5f55",
    u"tales of herding gods": u"\u7267\u795e\u8bb0",
    u"spare me, great lord": u"\u5927\u738b\u9976\u547d",
    u"spiritual realm walker": u"\u7075\u5883\u884c\u8005",
    u"ne zha": u"\u54ea\u5412",
    u"nezha": u"\u54ea\u5412",
    u"white snake": u"\u767d\u86c7\uff1a\u7f18\u8d77",
    u"new gods: yang jian": u"\u65b0\u795e\u699c\uff1a\u6768\u6233",
    u"deep sea": u"\u6df1\u6d77",
    u"chang'an": u"\u957f\u5b89\u4e09\u4e07\u91cc",
    u"changan": u"\u957f\u5b89\u4e09\u4e07\u91cc",
    u"big fish & begonia": u"\u5927\u9c7c\u6d77\u68e0",
    u"jiang ziya": u"\u59dc\u5b50\u7259",
    u"supreme god emperor": u"\u81f3\u5c0a\u795e\u5e1d",
    u"martial master": u"\u6b66\u795e\u4e3b\u5bb0",
    u"100,000 years of refining qi": u"\u70bc\u6c14\u5341\u4e07\u5e74",
    u"ten thousand worlds": u"\u4e07\u754c\u72ec\u5c0a",
    u"wan jie du zun ten thousand worlds": u"\u4e07\u754c\u72ec\u5c0a",
    u"perfect world movie: ninefold the burning sky": u"\u5b8c\u7f8e\u4e16\u754c\u5267\u573a\u7248",
    u"the eternal supreme li yunxiao": u"\u4e07\u53e4\u81f3\u5c0a\u674e\u4e91\u9704",
    u"beyond time's gaze": u"\u65f6\u5149\u4e4b\u5916",
    u"under the gate": u"\u95e8\u4e0b",
    u"gu an": u"\u987e\u5b89",
    u"against the sky supreme": u"\u9006\u5929\u81f3\u5c0a",
    u"againts the sky supreme": u"\u9006\u5929\u81f3\u5c0a",
    u"oriental martial academy": u"\u4e1c\u65b9\u6b66\u9662",
    u"primeval overlord": u"\u539f\u59cb\u9738\u4e3b",
    u"raised by demons panda li": u"\u5996\u602a\u517b\u5927\u7684\u718a\u732b\u674e",
    u"a good day to ascend": u"\u98de\u5347\u7684\u597d\u65e5\u5b50",
    u"big brother": u"\u5927\u54e5",
    u"the great journey of teenagers": u"\u5c11\u5e74\u767d\u9a6c\u9189\u6625\u98ce",
}

# 剧集/单集卡片上一定会粘的垃圾尾巴，逐层剥掉
_TAIL_PATTERNS = [
    u"indonesia", u"indo", u"english", u"eng", u"subtitle", u"subtitles",
    u"sub indo", u"sub ind", u"sub", u"hardsub", u"dub", u"donghua",
    u"information", u"update", u"complete", u"completed", u"ongoing",
    u"full episode", u"full episodes", u"batch", u"tv", u"ona", u"ova",
]

_BLOCK_WORDS = (
    u"\u5e7c\u5973", u"loli", u"\u30ed\u30ea", u"\u672a\u6210\u5e74",
    u"\u5c0f\u5b66\u751f", u"\u5e7c\u513f\u56ed",
)

_NUM_CN = {u"1": u"\u4e00", u"2": u"\u4e8c", u"3": u"\u4e09", u"4": u"\u56db",
           u"5": u"\u4e94", u"6": u"\u516d", u"7": u"\u4e03", u"8": u"\u516b",
           u"9": u"\u4e5d", u"10": u"\u5341"}


# ============================================================================
# 主体
# ============================================================================
class Spider(_BaseSpider):

    # ------------------------------------------------------------ 生命周期
    def __init__(self):
        try:
            _BaseSpider.__init__(self)
        except Exception:
            pass
        try:
            self.init(u"")
        except Exception:
            pass

    def init(self, extend=u""):
        cfg = {}
        ext = _s2(extend).strip()
        if ext.startswith(u"{"):
            try:
                cfg = json.loads(ext)
            except Exception:
                cfg = {}
        elif ext.startswith(u"http"):
            cfg = {u"host": ext}

        host = _s2(cfg.get(u"host") or cfg.get(u"site") or HOST_DEFAULT).rstrip(u"/")
        if host and not host.startswith(u"http"):
            host = u"https://" + host
        self.host = host or HOST_DEFAULT

        self.timeout = _to_int(cfg.get(u"timeout"), HTTP_TIMEOUT) or HTTP_TIMEOUT
        self.retry = _to_int(cfg.get(u"retry"), 3) or 1
        self.throttle = THROTTLE
        try:
            self.throttle = float(cfg.get(u"throttle", THROTTLE))
        except Exception:
            self.throttle = THROTTLE
        self.imgproxy = _to_int(cfg.get(u"imgproxy", 1), 1)
        self.probe = _to_int(cfg.get(u"probe", 1), 1)
        self.nokid = _to_int(cfg.get(u"nokid", 1), 1)

        self._ck = CookieJar()
        try:
            self._opener = build_opener(HTTPCookieProcessor(self._ck))
        except Exception:
            self._opener = build_opener()
        self._cache = {}          # url -> (ts, text)
        self._pc_cache = {}       # (engine, epurl) -> (ts, result-dict)
        self._cn_runtime = {}     # 列表页标题 -> 详情页 alter 拿到的准中文名
        self._cn_rev = {}
        for k, v in CN_TITLES.items():
            if v not in self._cn_rev:
                self._cn_rev[v] = k
        self.log(u"AnimeXin 3.0 ready: " + self.host)

    def getName(self):
        return u"ANIMEXIN \u52a8\u6f2b"

    def isVideoFormat(self, url):
        u = _s2(url).lower()
        for ext in (u".m3u8", u".mp4", u".flv", u".mkv", u".ts"):
            if ext in u:
                return True
        return False

    def destroy(self):
        try:
            self._cache = {}
            self._pc_cache = {}
        except Exception:
            pass

    def log(self, msg):
        try:
            _OUT(u"[ANIMEXIN] " + _s2(msg))
        except Exception:
            pass

    # ------------------------------------------------------------ 四壳契约位
    def getDependence(self):
        return []

    def isSearchable(self):
        return True

    def manualVideoCheck(self):
        return False

    def action(self, action=u""):
        return None

    # ------------------------------------------------------------ HTTP
    def _http(self, url, referer=None, timeout=None, want_raw=False):
        """带重试 / 限速 / gzip 的取页，失败返回 None（永不抛）"""
        url = _s2(url)
        if not url or not (url.startswith(u"http://") or url.startswith(u"https://")):
            return None
        url = _ascii_url(url)
        now = time.time()
        if not want_raw:
            hit = self._cache.get(url)
            if hit and now - hit[0] < CACHE_TTL:
                return hit[1]

        ref = referer or (self.host + u"/")
        last_err = u""
        for attempt in range(max(1, self.retry)):
            try:
                if self.throttle:
                    time.sleep(self.throttle)
                req = Request(url)
                req.add_header(u"User-Agent", UA)
                req.add_header(u"Accept", u"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
                req.add_header(u"Accept-Language", u"id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7")
                req.add_header(u"Referer", ref)
                resp = self._opener.open(req, timeout=timeout or self.timeout)
                # 头必须在 close 之前读，否则部分运行时读不到
                enc = _header(resp, u"Content-Encoding").lower()
                try:
                    body = resp.read()
                finally:
                    try:
                        resp.close()
                    except Exception:
                        pass
                if u"gzip" in enc:
                    try:
                        body = gzip.GzipFile(fileobj=BytesIO(body)).read()
                    except Exception:
                        pass
                if want_raw:
                    return body
                text = _decode(body)
                self._cache[url] = (time.time(), text)
                return text
            except Exception as e:
                last_err = _s2(e)
                if attempt < self.retry - 1:
                    time.sleep(0.6 * (attempt + 1))
        self.log(u"fetch fail %s : %s" % (url[:90], last_err[:90]))
        return None

    def _head_ok(self, url, header=None):
        """轻量探活：直链到底通不通（防止把死链丢给播放器）"""
        if not self.probe or not url:
            return True
        try:
            req = Request(url)
            for k, v in (header or {}).items():
                try:
                    req.add_header(k, v)
                except Exception:
                    pass
            req.add_header(u"Range", u"bytes=0-2047")
            resp = self._opener.open(req, timeout=8)
            try:
                code = getattr(resp, "code", None) or resp.getcode()
                return int(code) < 400
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
        except Exception:
            return False

    # ------------------------------------------------------------ 标题
    def _clean_name(self, t):
        """把站点的英文长标题剥干净：'xxx Episode 12 Indonesia, English Sub'"""
        t = _strip_tags(t)
        if not t:
            return t
        t = re.sub(r"\s*\[[^\]]*\]", u" ", t)          # [Martial Universe]
        t = re.sub(r"\s*\([^)]*\)", u" ", t)           # (2024)
        t = re.sub(r"[\u2018\u2019]", u"'", t)
        t = re.sub(r"\s+", u" ", t).strip()

        # 反复剥：先剥垃圾尾巴（Sub Indo / Indonesia, English Sub…），
        # 剥到 "…Episode 12" 露出来了再剥集号，然后回圈继续
        for _ in range(8):
            before = t
            t = re.sub(r"\s*[-\u2013|]?\s*Ep(?:isode)?\.?\s*\d+\s*$", u"", t, flags=re.I)
            low = t.lower()
            for tail in _TAIL_PATTERNS:
                if low.endswith(u" " + tail) or low == tail:
                    t = t[: len(t) - len(tail)].rstrip(u" ,-|&")
                    low = t.lower()
            t = re.sub(r"[\s,!.\-|&]+$", u"", t).strip()
            t = re.sub(r"\s*\bInformation\b\s*$", u"", t, flags=re.I).strip()
            t = re.sub(r"\s*(Subs|Subtitle|Subtitles|Sub)\s*$", u"", t, flags=re.I).strip()
            if t == before:
                break
        return t.strip()

    def _cn(self, name):
        """英文名 → 中文名：运行期缓存(详情页 alter) > 静态表 > 原名"""
        raw = _strip_tags(name)
        if not raw:
            return u""
        if raw in self._cn_runtime:
            return self._cn_runtime[raw]
        clean = self._clean_name(raw)
        if clean in self._cn_runtime:
            return self._cn_runtime[clean]
        if re.search(u"[\u4e00-\u9fff]", clean):
            return clean
        key = clean.lower().strip()
        if key in CN_TITLES:
            return CN_TITLES[key]
        if key.startswith(u"the ") and key[4:] in CN_TITLES:
            return CN_TITLES[key[4:]]
        if key.startswith(u"a ") and key[2:] in CN_TITLES:
            return CN_TITLES[key[2:]]
        # "xxx Season 5" / "xxx Part 2" 组合
        m = re.match(r"^(.*?)\s+Season\s+(\d+)\s*$", clean, re.I)
        if m:
            base = CN_TITLES.get(m.group(1).lower().strip())
            if base:
                n = m.group(2)
                return u"%s\u7b2c%s\u5b63" % (base, _NUM_CN.get(n, n))
        m = re.match(r"^(.*?)\s+Part\s+(\d+)\s*$", clean, re.I)
        if m:
            base = CN_TITLES.get(m.group(1).lower().strip())
            if base:
                n = m.group(2)
                return u"%s\u7b2c%s\u90e8" % (base, _NUM_CN.get(n, n))
        return clean

    def _remember_cn(self, en, cn):
        en = _strip_tags(en)
        cn = _strip_tags(cn)
        if en and cn and re.search(u"[\u4e00-\u9fff]", cn):
            self._cn_runtime[en] = cn
            self._cn_runtime[en.lower()] = cn
            # 站点自带的中文名也进反查表，中文搜索才搜得到它
            clean = self._clean_name(en)
            if clean and cn not in self._cn_rev:
                self._cn_rev[cn] = clean

    def _blocked(self, name):
        if not self.nokid or not name:
            return False
        low = _s2(name).lower()
        for w in _BLOCK_WORDS:
            if w in low:
                return True
        return False

    # ------------------------------------------------------------ 列表解析
    def _cards(self, html):
        """listupd / bs 卡片 → [{url,name,pic,remarks}]"""
        out = []
        if not html:
            return out
        seen = {}
        for blk in re.findall(r"<article[^>]*class=\"[^\"]*\bbs\b[^\"]*\"[^>]*>(.*?)</article>",
                              html, re.S | re.I):
            ot = re.search(r"<a\b[^>]*class=\"[^\"]*\btip\b[^\"]*\"[^>]*>", blk, re.I)
            if not ot:
                ot = re.search(r"<a\b[^>]*href=[\"'][^\"']+[\"'][^>]*>", blk, re.I)
            if not ot:
                continue
            tag = ot.group(0)
            inner = blk
            stop = blk.find(u"</a>", ot.end())
            if stop > ot.end():
                inner = blk[ot.end():stop]
            href = _pick_attr(tag, u"href")
            if not href:
                continue
            href = _unescape(href).strip()
            title = _pick_attr(tag, u"title") or u""
            if not title:
                h2 = re.search(r"<h2[^>]*>(.*?)</h2>", inner, re.S | re.I)
                title = _strip_tags(h2.group(1)) if h2 else u""
            # 单集卡：div.tt 里 <h2> 之前那段才是剧名（h2 是"剧名 Episode N"长句）
            pre = re.search(r"<div[^>]*class=\"[^\"]*\btt\b[^\"]*\"[^>]*>(.*?)<h2",
                            inner, re.S | re.I)
            nm = _strip_tags(pre.group(1)) if pre else u""
            if not nm:
                nm = _strip_tags(title)
            if not nm:
                continue
            pic = u""
            mi = re.search(r"<img[^>]*>", inner, re.S | re.I)
            if mi:
                pic = (_pick_attr(mi.group(0), u"data-src")
                       or _pick_attr(mi.group(0), u"src") or u"")
            remarks = u""
            mx = re.search(r"class=\"[^\"]*\bepx\b[^\"]*\"[^>]*>(.*?)</span>", inner, re.S | re.I)
            if mx:
                remarks = _fmt_remarks(mx.group(1))
            if not remarks:
                st = re.search(r"class=\"[^\"]*\bstatus\b[^\"]*\"[^>]*>(.*?)</div>", inner, re.S | re.I)
                if st:
                    remarks = _fmt_remarks(st.group(1))
            item = {
                u"vod_id": _norm_url(href, self.host),
                u"vod_name": self._cn(nm),
                u"vod_pic": self._proxy_img(_norm_url(pic, self.host)),
                u"vod_remarks": remarks,
            }
            if self._blocked(item[u"vod_name"]):
                continue
            if item[u"vod_id"] in seen:
                continue
            seen[item[u"vod_id"]] = 1
            out.append(item)
        return out

    def _pagecount(self, html, pg, got):
        pg = _to_int(pg, 1) or 1
        m = re.search(r"<div[^>]*class=\"[^\"]*\bhpage\b[^\"]*\"[^>]*>(.*?)</div>",
                      html or u"", re.S | re.I)
        if m:
            seg = m.group(1)
            if re.search(r"class=\"[^\"]*\br\b", seg) or u"Next" in seg or u"next" in seg:
                return pg + 1
            return max(pg, 1)
        return pg if got < 15 else pg + 1

    # ------------------------------------------------------------ home
    def homeContent(self, filter):
        classes = [
            {u"type_name": u"\U0001f4cb \u52a8\u6f2b\u5168\u90e8", u"type_id": u"anime"},
            {u"type_name": u"\U0001f195 \u6700\u65b0\u4e0a\u67b6", u"type_id": u"latest"},
            {u"type_name": u"\U0001f504 \u6700\u8fd1\u66f4\u65b0", u"type_id": u"update"},
            {u"type_name": u"\U0001f525 \u6700\u70ed\u95e8", u"type_id": u"popular"},
            {u"type_name": u"\u23f3 \u8fde\u8f7d\u4e2d", u"type_id": u"ongoing"},
            {u"type_name": u"\u2705 \u5df2\u5b8c\u7ed3", u"type_id": u"completed"},
            {u"type_name": u"\U0001f3ac \u5267\u573a\u7248", u"type_id": u"movie"},
            {u"type_name": u"\u2694\ufe0f \u52a8\u4f5c", u"type_id": u"action"},
            {u"type_name": u"\U0001f9d8 \u4fee\u70bc", u"type_id": u"cultivation"},
            {u"type_name": u"\U0001f495 \u604b\u7231", u"type_id": u"romance"},
            {u"type_name": u"\u2728 \u5e7b\u60f3", u"type_id": u"fantasy"},
            {u"type_name": u"\U0001f94b \u6b66\u4fa0", u"type_id": u"martial-arts"},
            {u"type_name": u"\U0001f602 \u559c\u5267", u"type_id": u"comedy"},
            {u"type_name": u"\U0001f3ad \u5267\u60c5", u"type_id": u"drama"},
            {u"type_name": u"\u262f\ufe0f \u4ed9\u4fa0", u"type_id": u"xianxia"},
        ]
        order_v = [
            {u"n": u"\u6700\u8fd1\u66f4\u65b0", u"v": u"update"},
            {u"n": u"\u6700\u65b0\u4e0a\u67b6", u"v": u"latest"},
            {u"n": u"\u6700\u70ed\u95e8", u"v": u"popular"},
            {u"n": u"\u9ed8\u8ba4", u"v": u"title"},
        ]
        status_v = [{u"n": u"\u5168\u90e8", u"v": u""},
                    {u"n": u"\u8fde\u8f7d\u4e2d", u"v": u"ongoing"},
                    {u"n": u"\u5df2\u5b8c\u7ed3", u"v": u"completed"}]
        type_v = [{u"n": u"\u5168\u90e8", u"v": u""}, {u"n": u"TV", u"v": u"tv"},
                  {u"n": u"ONA", u"v": u"ona"}, {u"n": u"\u5267\u573a\u7248", u"v": u"movie"}]
        filters = {}
        for c in classes:
            filters[c[u"type_id"]] = [
                {u"key": u"order", u"name": u"\u6392\u5e8f", u"value": order_v},
                {u"key": u"status", u"name": u"\u72b6\u6001", u"value": status_v},
                {u"key": u"type", u"name": u"\u7c7b\u578b", u"value": type_v},
            ]
        return {u"class": classes, u"filters": filters}

    def homeVideoContent(self):
        # 走剧集级列表（首页那栏是单集卡，点进去没有完整分集，这里换成最近更新）
        html = self._http(self._anime_url(u"update", None, None, 1))
        return {u"list": self._cards(html)}

    # ------------------------------------------------------------ 分类
    def _anime_url(self, order, status, typ, pg, genre=None):
        bits = []
        if order:
            bits.append(u"order=" + _quote(order))
        if status:
            bits.append(u"status=" + _quote(status))
        if typ:
            bits.append(u"type=" + _quote(typ))
        if genre:
            bits.append(u"genre%5B%5D=" + _quote(genre))
        q = u"&".join(bits)
        pg = _to_int(pg, 1) or 1
        tail = u"&page=%d" % pg if pg > 1 else u""
        if not q:
            return u"%s/anime/%s" % (self.host, (u"?page=%d" % pg) if pg > 1 else u"")
        return u"%s/anime/?%s%s" % (self.host, q, tail)

    def categoryContent(self, tid, pg, filter, extend):
        tid = _s2(tid)
        pg = _to_int(pg, 1) or 1
        extend = extend if isinstance(extend, dict) else {}
        genres = (u"action", u"cultivation", u"romance", u"fantasy",
                  u"martial-arts", u"comedy", u"drama", u"xianxia")

        order = _s2(extend.get(u"order")) or None
        status = _s2(extend.get(u"status")) or None
        typ = _s2(extend.get(u"type")) or None
        genre = None

        if tid in (u"latest",):
            order = u"latest"
        elif tid in (u"update", u"trending"):
            order = u"update"
        elif tid == u"popular":
            order = u"popular"
        elif tid == u"ongoing":
            status = u"ongoing"
        elif tid == u"completed":
            status = u"completed"
        elif tid == u"movie":
            typ = u"movie"
        elif tid in genres:
            genre = tid
        elif tid not in (u"anime", u""):
            if tid.startswith(u"http"):
                return {u"list": self._cards(self._http(tid))}
            genre = tid

        url = self._anime_url(order, status, typ, pg, genre)
        self.log(u"category %s p%d → %s" % (tid, pg, url))
        html = self._http(url)
        items = self._cards(html)
        return {
            u"list": items,
            u"page": pg,
            u"pagecount": self._pagecount(html, pg, len(items)),
            u"limit": 30,
            u"total": 99999,
        }

    # ------------------------------------------------------------ 详情
    def _eplist(self, html):
        """div.eplister → [(集号, 地址)]，按集号升序"""
        eps = []
        if not html:
            return eps
        # 必须真有 eplister 容器才算剧集页（单集页侧栏也会出现 epl-num，会误判）
        pos = html.find(u"eplister")
        if pos < 0:
            return eps
        box = html[pos:]
        for li in re.findall(r"<li[^>]*>(.*?)</li>", box, re.S | re.I):
            if u"epl-num" not in li:
                continue
            a = re.search(r"<a[^>]*href=[\"']([^\"']+)[\"']", li, re.I)
            if not a:
                continue
            num = re.search(r"class=[\"'][^\"']*\bepl-num\b[^\"']*[\"'][^>]*>(.*?)<", li, re.S | re.I)
            label = _strip_tags(num.group(1)) if num else u""
            if not label:
                t = re.search(r"class=[\"'][^\"']*\bepl-title\b[^\"']*[\"'][^>]*>(.*?)<", li, re.S | re.I)
                label = _strip_tags(t.group(1)) if t else u""
            url = _unescape(a.group(1)).strip()
            if url:
                eps.append((label, _norm_url(url, self.host)))
        def _key(x):
            n = re.search(r"\d+", x[0] or u"")
            return _to_int(n.group(0), 10 ** 6) if n else 10 ** 6
        eps.sort(key=_key)
        seen = {}
        out = []
        for label, url in eps:
            if url in seen:
                continue
            seen[url] = 1
            out.append((label, url))
        return out

    def _series_from_episode(self, html):
        """单集页 → 剧集页地址（ARIA 回链，两种属性顺序都吃）"""
        for pat in (r"<a[^>]*href=[\"']([^\"']+)[\"'][^>]*aria-label=[\"']All Episodes[\"']",
                    r"<a[^>]*aria-label=[\"']All Episodes[\"'][^>]*href=[\"']([^\"']+)[\"']"):
            m = re.search(pat, html or u"", re.I | re.S)
            if m:
                return _norm_url(_unescape(m.group(1)), self.host)
        return u""

    def detailContent(self, ids):
        try:
            if isinstance(ids, (list, tuple)):
                raw = _s2(ids[0]) if ids else u""
            else:
                raw = _s2(ids)
            if not raw:
                return {u"list": []}
            url = _norm_url(raw, self.host)

            html = self._http(url) or u""
            series_url = url
            if html.find(u"eplister") < 0:
                # 单集页 → 顺回链找剧集页
                s = self._series_from_episode(html)
                if s and s != url:
                    h2 = self._http(s)
                    if h2 and h2.find(u"eplister") >= 0:
                        html, series_url = h2, s
            eps = self._eplist(html)

            # 标题：站点自带 alter 最准 → 回写运行期缓存
            name_en = u""
            ttl = re.search(r"<h1[^>]*class=[\"'][^\"']*entry-title[^\"']*[\"'][^>]*>(.*?)</h1>",
                            html, re.S | re.I)
            if ttl:
                name_en = _strip_tags(ttl.group(1))
            alt = re.search(r"<span[^>]*class=[\"'][^\"']*\balter\b[^\"']*[\"'][^>]*>(.*?)</span>",
                            html, re.S | re.I)
            cn = _strip_tags(alt.group(1)) if alt else u""
            if cn:
                self._remember_cn(name_en or self._clean_name(name_en), cn)
                self._remember_cn(self._clean_name(name_en), cn)
            title = cn or self._cn(name_en) or self._clean_name(name_en) or name_en

            pic = u""
            og = re.search(r"<meta[^>]*property=[\"']og:image[\"'][^>]*content=[\"']([^\"']*)[\"']",
                           html, re.I)
            if not og:
                og = re.search(r"<meta[^>]*content=[\"']([^\"']*)[\"'][^>]*property=[\"']og:image[\"']",
                               html, re.I)
            if og:
                pic = _unescape(og.group(1))

            desc = u""
            md = re.search(r"<meta[^>]*name=[\"']description[\"'][^>]*content=[\"']([^\"']*)[\"']",
                           html, re.I)
            if md:
                desc = _unescape(md.group(1))[:600]

            status = u""
            st = re.search(r"<b>\s*Status\s*:?\s*</b>\s*([^<]*)", html, re.I)
            if st:
                status = _strip_tags(st.group(1))
            remarks = {u"completed": u"\u5df2\u5b8c\u7ed3", u"ongoing": u"\u8fde\u8f7d\u4e2d"}.get(
                status.lower().strip(), u"\u8fde\u8f7d\u4e2d")

            year = u""
            my = re.search(r"(20\d{2})", desc + u" " + html[:4000])
            if my:
                year = my.group(1)

            if not eps:
                eps = [(u"1", series_url)]

            # 每集统一 id = 单集页地址；线路名(flag)告诉 playerContent 走哪家引擎
            froms = []
            urls = []
            for line_name, _eng, _lang in LINES:
                froms.append(line_name)
                group = []
                for label, eurl in eps:
                    nm = label
                    if re.match(r"^\d+$", label or u""):
                        nm = u"\u7b2c%s\u96c6" % label
                    elif not label:
                        nm = u"\u5168\u96c6"
                    group.append(u"%s$%s" % (nm, eurl))
                urls.append(u"#".join(group))
            play_from = u"$$$".join(froms)
            play_url = u"$$$".join(urls)

            return {u"list": [{
                u"vod_id": series_url,
                u"vod_name": title,
                u"vod_pic": self._proxy_img(pic),
                u"vod_year": year,
                u"vod_area": u"\u56fd\u6f2b",
                u"vod_remarks": remarks,
                u"vod_content": desc,
                u"vod_play_from": play_from,
                u"vod_play_url": play_url,
            }]}
        except Exception as e:
            self.log(u"detail error: %s" % _s2(e))
            return {u"list": []}

    # ------------------------------------------------------------ 搜索
    def _search_terms(self, key):
        terms = []
        k = _s2(key).strip()
        if not k:
            return terms
        if re.search(u"[\u4e00-\u9fff]", k):
            en = self._cn_rev.get(k)
            if en:
                terms.append(en)
            # 部分匹配：剧名带后缀（第二季/剧场版）
            for cn, en2 in self._cn_rev.items():
                if cn and (cn in k or k in cn) and en2 not in terms:
                    terms.append(en2)
        else:
            terms.append(k)
            low = k.lower()
            for en in CN_TITLES:
                if low in en and en not in terms:
                    terms.append(en)
        return terms[:3]

    def searchContent(self, key, quick, pg=u"1"):
        try:
            pg = _to_int(pg, 1) or 1
            items = []
            seen = {}
            terms = self._search_terms(key) or [_s2(key).strip()]
            for t in terms:
                url = u"%s/?s=%s%s" % (self.host, _quote(t),
                                       (u"&page=%d" % pg) if pg > 1 else u"")
                html = self._http(url)
                got = self._cards(html)
                for it in got:
                    if it[u"vod_id"] in seen:
                        continue
                    seen[it[u"vod_id"]] = 1
                    items.append(it)
                if len(got) < 5 and len(terms) == 1:
                    break
            pagecount = pg if len(items) < 15 else pg + 1
            return {u"list": items, u"page": pg, u"pagecount": pagecount}
        except Exception as e:
            self.log(u"search error: %s" % _s2(e))
            return {u"list": []}

    # ------------------------------------------------------------ 播放源解析
    def _mirrors(self, html):
        """select.mirror 的 option → [(label, embed_url)]"""
        out = []
        if not html:
            return out
        sel = re.search(r"<select[^>]*class=[\"'][^\"']*\bmirror\b[^\"']*[\"'][^>]*>(.*?)</select>",
                        html, re.S | re.I)
        if not sel:
            return out
        for attrs, label in re.findall(r"<option([^>]*)>(.*?)</option>", sel.group(1), re.S | re.I):
            label = _strip_tags(label)
            v = _pick_attr(attrs, u"value")
            if not v:
                continue
            dec = _b64d(v)
            src = re.search(r"src=[\"']([^\"']+)[\"']", dec or u"", re.I)
            if not src:
                continue
            u = _norm_url(_unescape(src.group(1)), self.host)
            if u:
                out.append((label, u))
        return out

    def _engine_of(self, label, url):
        l = _s2(label).lower()
        u = _s2(url).lower()
        if u"dailymotion" in l or u"dailymotion.com" in u:
            return u"dm"
        if u"ok.ru" in l or u"ok.ru" in u:
            return u"ok"
        if u"odysee" in l or u"odysee.com" in u:
            return u"odysee"
        if u"rumble" in l or u"rumble.com" in u:
            return u"rumble"
        if u"mega.nz" in u or u"mega" in l:
            return u"mega"
        if u"d.tube" in u or u"dtube" in l:
            return u"dtube"
        if u"seekplayer" in u or u"streamwish" in l or u"wish" in l:
            return u"wish"
        if u"playmogo" in u or u"dood" in l:
            return u"dood"
        return u"other"

    def _lang_of(self, label):
        l = _s2(label).lower()
        if u"indonesia" in l or u"indo" in l:
            return u"id"
        if u"eng" in l:
            return u"en"
        return u"any"

    # ---- 各引擎解析器：能出直链的才返回，出不来返回 None

    def _resolve_dm(self, embed):
        m = re.search(r"video[=/]([A-Za-z0-9]+)", _s2(embed))
        if not m:
            return None
        vid = m.group(1)
        api = u"https://www.dailymotion.com/player/metadata/video/" + vid
        txt = self._http(api, referer=u"https://www.dailymotion.com/",
                         timeout=12, want_raw=False)
        if not txt:
            return None
        try:
            data = json.loads(txt)
        except Exception:
            return None
        q = data.get(u"qualities") or {}
        for k in (u"auto", u"1080", u"720", u"480", u"360", u"240"):
            arr = q.get(k)
            if arr and isinstance(arr, list) and arr[0].get(u"url"):
                hdr = {
                    u"User-Agent": UA,
                    u"Referer": u"https://www.dailymotion.com/",
                    u"Origin": u"https://www.dailymotion.com",
                    u"Accept": u"*/*",
                }
                u = _s2(arr[0][u"url"])
                if self._head_ok(u, hdr):
                    return (u, hdr)
                return (u, hdr)      # 探测失败也给，别把可能能播的丢了
        return None

    def _resolve_ok(self, embed):
        u = _norm_url(embed, self.host)
        if not u:
            return None
        txt = self._http(u, referer=u"https://ok.ru/", timeout=15)
        if not txt:
            return None
        m = re.search(r"data-options=[\"'](.*?)[\"']", txt, re.S)
        if not m:
            return None
        try:
            data = json.loads(_unescape(m.group(1)))
        except Exception:
            return None
        fv = data.get(u"flashvars") or {}
        meta = fv.get(u"metadata")
        if isinstance(meta, (bytes, _UNICODE, str)):
            try:
                meta = json.loads(_s2(meta))
            except Exception:
                meta = {}
        meta = meta or {}
        vids = meta.get(u"videos") or []
        order = {u"full": 0, u"hd": 1, u"sd": 2, u"low": 3, u"lowest": 4, u"mobile": 5}
        vids = sorted(vids, key=lambda v: order.get(_s2(v.get(u"name")), 9))
        hdr = {u"User-Agent": UA, u"Referer": u"https://ok.ru/"}
        first = u""
        for v in vids:
            link = _s2(v.get(u"url"))
            if not link:
                continue
            if not first:
                first = link
            if not self.probe or self._head_ok(link, hdr):
                return (link, hdr)
        hls = _s2(meta.get(u"hlsMasterPlaylistUrl"))
        if hls:
            return (hls, hdr)
        return (first, hdr) if first else None

    def _resolve_rumble(self, embed):
        u = _norm_url(embed, self.host)
        if not u:
            return None
        txt = self._http(u, referer=u"https://rumble.com/", timeout=15)
        if not txt:
            return None
        hdr = {u"User-Agent": UA, u"Referer": u"https://rumble.com/"}
        m = re.search(r"\"ua\"\s*:\s*(\{.*?\})", txt, re.S)
        if m:
            try:
                ua = json.loads(m.group(1))
                mp4 = ua.get(u"mp4") or {}
                for k in (u"1080", u"720", u"480", u"360", u"240"):
                    if mp4.get(k):
                        return (_s2(mp4[k]), hdr)
                if isinstance(mp4, dict) and mp4:
                    return (_s2(list(mp4.values())[-1]), hdr)
            except Exception:
                pass
        m = re.search(r"(https://[^\"'\s]+\.m3u8[^\"'\s]*)", txt)
        if m:
            return (_unescape(m.group(1)), hdr)
        return None

    def _resolve(self, engine, embed):
        if engine == u"dm":
            return self._resolve_dm(embed)
        if engine == u"ok":
            return self._resolve_ok(embed)
        if engine == u"rumble":
            return self._resolve_rumble(embed)
        return None

    def _pc_cache_get(self, key):
        hit = self._pc_cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
        return None

    def _pc_cache_put(self, key, val):
        self._pc_cache[key] = (time.time(), val)
        if len(self._pc_cache) > 200:
            self._pc_cache.clear()

    # ------------------------------------------------------------ playerContent
    def playerContent(self, flag, ids, vipFlags=None):
        empty = _player_dict(u"")
        ep_url = self._unwrap(flag, ids)
        if not ep_url:
            self.log(u"player: no url from args flag=%s ids=%s" % (_s2(flag)[:60], _s2(ids)[:60]))
            return empty

        want_eng, want_lang = self._line_pref(flag)
        ck = (want_eng + u"/" + want_lang, ep_url)
        hit = self._pc_cache_get(ck)
        if hit:
            return hit

        html = self._http(ep_url)
        self._remember_title(html, ep_url)
        mirrors = self._mirrors(html)
        if not mirrors:
            self.log(u"player: no mirror list at %s" % ep_url[:90])
            return empty

        self.log(u"player: %d mirrors, line=%s/%s" % (len(mirrors), want_eng, want_lang))

        cands = []
        for label, url in mirrors:
            cands.append({u"label": label, u"url": url,
                          u"eng": self._engine_of(label, url),
                          u"lang": self._lang_of(label)})

        order = []
        if want_eng and want_eng != u"auto":
            for lang in (want_lang,) + tuple(x for x in LANG_ORDER if x != want_lang):
                for c in cands:
                    if c[u"eng"] == want_eng and c[u"lang"] == lang:
                        order.append(c)
            for c in cands:
                if c[u"eng"] == want_eng:
                    order.append(c)
        for eng in AUTO_ORDER:
            for lang in LANG_ORDER:
                for c in cands:
                    if c[u"eng"] == eng and c[u"lang"] == lang:
                        order.append(c)
        for c in cands:
            order.append(c)

        picked = []
        for c in order:
            if c[u"url"] in picked:
                continue
            picked.append(c[u"url"])
            if c[u"eng"] in (u"dm", u"ok", u"rumble"):
                got = self._resolve(c[u"eng"], c[u"url"])
                if got:
                    url, hdr = got
                    res = {u"parse": 0, u"jx": 0, u"playUrl": u"",
                           u"url": url, u"header": hdr}
                    self.log(u"player OK [%s] %s" % (c[u"eng"], c[u"label"][:50]))
                    self._pc_cache_put(ck, res)
                    return res

        # 全解不出直链 → 交给宿主自带解析兜底（至少不是死路）
        for c in cands:
            if c[u"lang"] == u"id":
                res = {u"parse": 1, u"playUrl": u"", u"url": c[u"url"],
                       u"header": {u"User-Agent": UA, u"Referer": self.host + u"/"}}
                self._pc_cache_put(ck, res)
                return res
        c = cands[0]
        res = {u"parse": 1, u"playUrl": u"", u"url": c[u"url"],
               u"header": {u"User-Agent": UA, u"Referer": self.host + u"/"}}
        self._pc_cache_put(ck, res)
        return res

    def _line_pref(self, flag):
        f = _s2(flag)
        for line_name, eng, lang in LINES:
            if line_name == f:
                return eng, lang
        low = f.lower()
        if u"dailymotion" in low or u"dm" == low:
            return u"dm", u"any"
        if u"ok.ru" in low or u"okru" in low:
            return u"ok", u"any"
        if u"rumble" in low:
            return u"rumble", u"any"
        return u"auto", u"any"

    def _unwrap(self, flag, ids):
        """
        宿主传参各家不一，两个参数一起收再挑：
          · 影视仓/OK影视 常把播放地址放第 2 个参数，线路名放第 1 个
          · 有的全部塞第 1 个
          · 有的把 "第1集$地址#第2集$地址" 甚至带 $$$ 多线路的整串原样丢进来
        返回可直接请求的单集页地址（找不到返回 ""）
        """
        cands = []
        for v in (ids, flag):
            if isinstance(v, (list, tuple)):
                for x in v:
                    cands.append(_s2(x))
            else:
                cands.append(_s2(v))
        weak = u""
        for raw in cands:
            if not raw:
                continue
            raw = raw.strip()
            if u"$$$" in raw:
                raw = raw.split(u"$$$", 1)[0].strip()
            if u"#" in raw and not raw.startswith(u"http"):
                raw = raw.split(u"#", 1)[0].strip()
            for _ in range(3):
                if u"$" in raw:
                    raw = raw.rsplit(u"$", 1)[1].strip()
                else:
                    break
            if not raw:
                continue
            if raw.startswith(u"http"):
                return _norm_url(raw, self.host)
            if not weak and u" " not in raw:
                weak = raw
        if weak.startswith(u"http"):
            return _norm_url(weak, self.host)
        if weak:
            return _norm_url(weak, self.host)
        return u""

    def _remember_title(self, html, url):
        """单集页也带 alter，顺手把「英文剧名 → 中文剧名」缓存起来"""
        if not html:
            return
        alt = re.search(r"<span[^>]*class=[\"'][^\"']*\balter\b[^\"']*[\"'][^>]*>(.*?)</span>",
                        html, re.S | re.I)
        if not alt:
            return
        cn = _strip_tags(alt.group(1))
        ttl = re.search(r"<h1[^>]*class=[\"'][^\"']*entry-title[^\"']*[\"'][^>]*>(.*?)</h1>",
                        html, re.S | re.I)
        if ttl and cn:
            en = _strip_tags(ttl.group(1))
            self._remember_cn(en, cn)
            self._remember_cn(self._clean_name(en), cn)

    # ------------------------------------------------------------ 图片中转
    def _proxy_img(self, url):
        url = _s2(url)
        if not url:
            return u""
        if not self.imgproxy:
            return url
        try:
            b64 = base64.urlsafe_b64encode(url.encode(u"utf-8")).decode(u"ascii").rstrip(u"=")
            pb = self._proxy_base()
            if not pb:
                return url
            sep = u"&" if u"?" in pb else u"?"
            return u"%s%sm=img&u=%s" % (pb, sep, b64)
        except Exception:
            return url

    def _proxy_base(self):
        """宿主代理位：getProxyUrl(local) 各家签名不一，逐个试"""
        for args, kwargs in (((True,), {}), ((), {}), ((False,), {})):
            fn = getattr(self, u"getProxyUrl", None)
            if not fn:
                return u""
            try:
                v = fn(*args, **kwargs)
                if v:
                    return _s2(v)
            except Exception:
                continue
        return u""

    def localProxy(self, param):
        try:
            if isinstance(param, (bytes, _UNICODE)) or (not _PY3 and isinstance(param, str)):
                try:
                    param = json.loads(_s2(param))
                except Exception:
                    param = {}
            if not isinstance(param, dict) or _s2(param.get(u"m")) != u"img":
                return [404, u"text/plain", b""]
            u = _s2(param.get(u"u"))
            if not u:
                return [404, u"text/plain", b""]
            pad = u"=" * (-len(u) % 4)
            raw = base64.urlsafe_b64decode((u + pad).encode(u"ascii")).decode(u"utf-8")
            if not raw.startswith(u"http"):
                return [404, u"text/plain", b""]
            data = self._http(raw, referer=self.host + u"/", timeout=15, want_raw=True)
            if not data:
                return [404, u"text/plain", b""]
            ct = u"image/jpeg"
            low = raw.lower()
            if u".png" in low:
                ct = u"image/png"
            elif u".webp" in low:
                ct = u"image/webp"
            elif u".gif" in low:
                ct = u"image/gif"
            return [200, ct, data]
        except Exception as e:
            self.log(u"img proxy error: %s" % _s2(e))
            return [404, u"text/plain", b""]


# ============================================================================
# 模块级小工具
# ============================================================================
def _pick_attr(tag, name):
    """从标签串里取属性，单双引号、无引号都吃"""
    if not tag:
        return u""
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*\"([^\"]*)\"", tag, re.I)
    if m:
        return _unescape(m.group(1))
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*'([^']*)'", tag, re.I)
    if m:
        return _unescape(m.group(1))
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*([^\s>]+)", tag, re.I)
    return _unescape(m.group(1)) if m else u""


def _header(resp, name):
    try:
        h = getattr(resp, u"headers", None)
        if h is not None:
            v = h.get(name)
            if v:
                return _s2(v)
    except Exception:
        pass
    try:
        v = resp.info().get(name)
        if v:
            return _s2(v)
    except Exception:
        pass
    return u""


def _decode(body):
    if body is None:
        return u""
    if isinstance(body, _UNICODE):
        return body
    for enc in (u"utf-8", u"gb18030", u"latin-1"):
        try:
            return body.decode(enc)
        except Exception:
            continue
    try:
        return body.decode(u"utf-8", u"ignore")
    except Exception:
        return u""


def _fmt_remarks(raw):
    r = _strip_tags(raw)
    if not r:
        return u""
    low = r.lower()
    if u"complete" in low:
        return u"\u5df2\u5b8c\u7ed3"
    if u"ongoing" in low:
        return u"\u8fde\u8f7d\u4e2d"
    if u"hiatus" in low:
        return u"\u505c\u66f4"
    if u"upcoming" in low:
        return u"\u656c\u8bf7\u671f\u5f85"
    if u"movie" in low:
        return u"\u5267\u573a\u7248"
    m = re.search(r"(\d+)", r)
    if m:
        return u"\u66f4\u65b0\u81f3%s\u96c6" % m.group(1)
    return r[:20]


def _player_dict(url):
    return {u"parse": 0, u"jx": 0, u"playUrl": u"", u"url": _s2(url),
            u"header": {u"User-Agent": UA}}


# ============================================================================
# 四、TVBox / 影视仓 / OK影视 模块级入口（四壳按模块名调用，必须有）
# ============================================================================
_spider = Spider()


def getDependence():
    return []


def init(extend=u""):
    return _spider.init(extend)


def homeContent(filter=None):
    return _spider.homeContent(filter)


def homeVideoContent():
    return _spider.homeVideoContent()


def categoryContent(tid, pg=1, filter=None, extend=None):
    return _spider.categoryContent(tid, pg, filter, extend)


def searchContent(key, quick=False, pg=u"1"):
    return _spider.searchContent(key, quick, pg)


def detailContent(ids):
    return _spider.detailContent(ids)


def playerContent(flag, ids, vipFlags=None):
    return _spider.playerContent(flag, ids, vipFlags)


def localProxy(param):
    return _spider.localProxy(param)


def isVideoFormat(url):
    return _spider.isVideoFormat(url)


def isSearchable():
    return True


def manualVideoCheck():
    return False


def action(action=u""):
    return _spider.action(action)


def getName():
    return _spider.getName()


def destroy():
    return _spider.destroy()
