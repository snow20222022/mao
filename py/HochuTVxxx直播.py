# coding=utf-8
# 三站合一成人直播 (api: py_3live)
# 分類：HochuTV（hochu.tv 即時抓取 65 台）/ OXAX（內嵌 39 台，parse=1 嗅探）/ Klubnichka（內嵌 60 台，點播現抓 m3u8）
# 三個來源的原始蜘蛛邏輯原封保留為內部類，外層以 id 前綴（hochu| / oxax| / klub|）分流。
# 宸龍相容，支援搜尋（三站一起搜）。
import re
import sys
import json
import time
import urllib.parse
sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider:
        def __init__(self):
            pass
try:
    import requests
except Exception:
    requests = None
try:
    import requests as _rq
except Exception:
    _rq = None
try:
    from urllib.parse import quote as _quote, unquote as _unquote, urljoin as _urljoin
except ImportError:
    from urllib import quote as _quote, unquote as _unquote
    from urlparse import urljoin as _urljoin


class _HochuSpider:
    def __init__(self):
        self.site = "https://hochu.tv"
        self.name = "HochuTV"
        self.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.header = {"User-Agent": self.ua, "Referer": self.site + "/",
                       "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                       "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"}
        self.s = self.session = self.sess = _rq.Session() if _rq else None
        self._extend = {}
        self.cat_scope = None
        self.cat_href_re = None
        self.list_scope = None
        self.detail_tpl = None
        self.play_tpl = None
        self.m3u8_var = None
        self.search_tpl = None
        self.page_mode = None
        self._chans = []
        self._chans_at = 0.0
        self._stream_urls = {}
        self._stream_at = {}

    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        if not url:
            return False
        u = str(url).lower()
        return u.endswith((".m3u8", ".mp4", ".flv", ".ts")) or "m3u8" in u

    def destroy(self):
        pass

    def action(self, action):
        return {}

    def _fetch(self, url, headers=None, timeout=20):
        h = dict(self.header)
        if headers:
            h.update(headers)
        if self.s is not None:
            try:
                r = self.s.get(url, headers=h, timeout=timeout)
                return r.status_code, r.content
            except Exception:
                pass
        try:
            import urllib.request
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.getcode(), resp.read()
        except Exception:
            return 0, b""

    def _get_text(self, url, headers=None, timeout=20):
        code, data = self._fetch(url, headers, timeout)
        if code != 200 or not data:
            return ""
        try:
            return data.decode("utf-8", "ignore")
        except Exception:
            return ""

    def _channels(self):
        now = time.time()
        if self._chans and now - self._chans_at < 3600:
            return self._chans
        chs = []
        try:
            html = self._get_text(self.site + "/")
            for m in re.finditer(r'href="(/[\w\-]+\.html)"><img[^>]*src="(/images/[^"]+)"[^>]*/?>\s*<div class="titchan">([^<]+)</div>', html):
                p, img, nm = m.groups()
                nm = (nm or "").strip()
                if not nm or not p:
                    continue
                chs.append({"id": p, "name": nm, "pic": self.site + img})
        except Exception:
            pass
        if chs:
            self._chans, self._chans_at = chs, now
        return self._chans or chs

    def _item(self, c):
        return {"vod_id": c["id"], "vod_name": c["name"], "vod_pic": c["pic"], "vod_remarks": "直播"}

    def _desc(self, path):
        try:
            html = self._get_text(self.site + path)
            m = re.search(r'id="content-2">(.*?)</div>\s*</div>', html, re.S)
            if not m:
                return ""
            txt = re.sub(r"<[^>]+>", " ", m.group(1))
            return re.sub(r"\s+", " ", txt).strip()[:500]
        except Exception:
            return ""

    def _resolve(self, path):
        """解析出频道对应的 m3u8 直链列表（通常两个：主/备）"""
        now = time.time()
        if path in self._stream_urls and now - self._stream_at.get(path, 0) < 120:
            return self._stream_urls[path]
        urls = []
        try:
            page_url = self.site + path
            html = self._get_text(page_url)
            m = re.search(r'<iframe[^>]+src="(/iframes/[^"]+)"', html)
            if m:
                ifr_url = self.site + m.group(1)
                h2 = {"Referer": page_url, "Sec-Fetch-Dest": "iframe", "Sec-Fetch-Mode": "navigate",
                      "Sec-Fetch-Site": "same-origin", "Upgrade-Insecure-Requests": "1"}
                html2 = self._get_text(ifr_url, h2)
                m2 = re.search(r'player/playerjs\.php\?ch=(\d+)', html2)
                if m2:
                    pjs = self.site + "/player/playerjs.php?ch=" + m2.group(1)
                    html3 = self._get_text(pjs, {"User-Agent": self.ua, "Referer": ifr_url})
                    m3 = re.search(r'generatedFile\s*=\s*"([^"]+)"', html3)
                    if m3:
                        gf = m3.group(1).replace("\\/", "/")
                        urls = [u.strip() for u in gf.split(" or ") if u.strip().startswith("http")]
        except Exception:
            urls = []
        if urls:
            self._stream_urls[path] = urls
            self._stream_at[path] = now
        return urls

    def _pick_m3u8(self, path, line):
        """按线路取 m3u8 直链，并验证可访问；失效则刷新一次"""
        ref = self.site + path
        for attempt in (0, 1):
            urls = self._resolve(path)
            if not urls:
                break
            mu = urls[1] if (line and len(urls) > 1) else urls[0]
            txt = self._get_text(mu, {"User-Agent": self.ua, "Referer": ref})
            if "#EXTM3U" in txt:
                return mu, ref
            # 签名失效，清缓存重试
            self._stream_at[path] = 0
        return "", ref

    def init(self, extend=""):
        self._extend = {}
        if isinstance(extend, dict):
            self._extend = extend
        elif isinstance(extend, str) and extend.strip():
            try:
                e = json.loads(extend)
                if isinstance(e, dict):
                    self._extend = e
            except Exception:
                pass

    def homeContent(self, filter=None):
        chs = self._channels()
        return {"class": [{"type_id": "all", "type_name": "全部频道"}],
                "filters": {},
                "list": [self._item(c) for c in chs[:12]]}

    def homeVideoContent(self):
        return {"list": [self._item(c) for c in self._channels()]}

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        chs = self._channels()
        items = [self._item(c) for c in chs]
        return {"list": items, "page": 1, "pagecount": 1, "limit": len(items), "total": len(items)}

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = str(vid or "").strip()
        if "$" in vid:
            vid = vid.split("$")[-1].strip()
        vid = _unquote(vid)
        ch = None
        for c in self._channels():
            if c["id"] == vid:
                ch = c
                break
        if ch is None:
            return {"list": []}
        return {"list": [{"vod_id": ch["id"], "vod_name": ch["name"], "vod_pic": ch["pic"],
                           "vod_content": self._desc(ch["id"]), "type_name": "电视直播",
                           "vod_play_from": "HochuTV",
                           "vod_play_url": "直播$%s#备用线路$%s|bk" % (ch["id"], ch["id"])}]}

    def searchContent(self, key, quick=False, pg="1"):
        kw = str(key or "").strip().lower()
        items = [self._item(c) for c in self._channels() if kw and kw in c["name"].lower()]
        return {"list": items, "page": 1, "pagecount": 1, "limit": len(items), "total": len(items)}

    def playerContent(self, flag, ids, vipFlags=None):
        """
        参考 OXAX.py：直接返回 video:// 真实 m3u8 直链，交由播放器处理。
        播放器请求 m3u8 / 分片时会带上 header 中的 Referer，满足站点校验。
        """
        u = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        u = str(u or "").strip()
        if "$" in u:
            u = u.split("$")[-1].strip()
        u = _unquote(u)
        line = 1 if u.endswith("|bk") else 0
        path = u[:-3] if line else u
        if not path.startswith("/"):
            return {"parse": 0, "url": "", "header": {}}

        m3u8, ref = self._pick_m3u8(path, line)
        if not m3u8:
            # 解析失败时退回 localProxy（部分客户端仍可用）
            proxy = "http://127.0.0.1:9978/proxy?do=py&type=live&url=" + _quote(path, safe="") + "&line=%d" % line
            return {"parse": 0, "url": proxy, "header": {}}

        header = {
            "User-Agent": self.ua,
            "Referer": ref,
            "Origin": self.site,
            "Accept": "*/*",
        }
        return {"parse": 0, "url": m3u8, "header": header}

    # ------- 以下 localProxy 保留作为兜底，正常播放不再依赖 -------
    def _proxy_live(self, path, line):
        ref = self.site + path
        m3u8, ref2 = self._pick_m3u8(path, line)
        if not m3u8:
            return [502, "text/plain", b"", {}]
        ref = ref2 or ref
        txt = self._get_text(m3u8, {"User-Agent": self.ua, "Referer": ref})
        if "#EXTM3U" not in txt:
            return [502, "text/plain", b"", {}]
        base = m3u8.split("?")[0].rsplit("/", 1)[0] + "/"
        sign = m3u8.split("?", 1)[1] if "?" in m3u8 else ""
        out = []
        for ln in txt.splitlines():
            s = (ln or "").strip()
            if not s or s.startswith("#"):
                out.append(ln)
                continue
            seg = _urljoin(base, s)
            if sign:
                seg += ("&" if "?" in seg else "?") + sign
            out.append("http://127.0.0.1:9978/proxy?do=py&type=ts&url=" + _quote(seg, safe="") +
                       "&ref=" + _quote(ref, safe=""))
        body = ("\n".join(out) + "\n").encode("utf-8")
        return [200, "application/vnd.apple.mpegurl", body, {"Content-Length": str(len(body))}]

    def _proxy_ts(self, u, ref):
        code, data = self._fetch(u, {"User-Agent": self.ua, "Referer": ref or self.site + "/", "Accept": "*/*"}, 30)
        if code != 200 or not data:
            return [502, "text/plain", b"", {}]
        head = data[:16].lstrip()
        if head.startswith((b"<html", b"<!DOC", b"{", b"403", b"404")):
            return [502, "text/plain", b"", {}]
        return [200, "video/mp2t", data, {"Content-Length": str(len(data)), "Accept-Ranges": "bytes"}]

    def localProxy(self, param):
        try:
            p = json.loads(param) if isinstance(param, str) else (param or {})
            t = p.get("type", "")
            if t == "live":
                return self._proxy_live(_unquote(p.get("url", "")), int(p.get("line", 0) or 0))
            if t == "ts":
                return self._proxy_ts(_unquote(p.get("url", "")), _unquote(p.get("ref", "")))
            return [502, "text/plain", b"", {}]
        except Exception:
            return [502, "text/plain", b"", {}]

class _OxaxSpider(BaseSpider):
    def __init__(self):
        super().__init__()
        self.base_url = "http://oxax.tv"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Referer': self.base_url,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })

        # Updated channel list with actual image URLs where available (fetched from alternative sources since oxax.tv is currently down)
        # Images are logos from public sources like Wikimedia, channel sites, or stock images
        self.all_channels = [
            {"title": "ОХ-АХ HD", "href": "/oh-ah.html", "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQSQ3gk-W-dl9-V-RPH-TFaJv1Eg6IbtRb3ENCiHdUXihMU0Qg-9IUMyUJV8_RtlT9LSY8&usqp=CAU"},
            {"title": "CineMan XXX HD", "href": "/sl-hot1.html", "image": "https://yt3.ggpht.com/ytc/AKedOLR8CSuliVmhPyo9nxofgZWCI9fZKrqL-PFki3b8=s900-c-k-c0x00ffffff-no-rj"},
            {"title": "CineMan XXX2 HD", "href": "/sl-hot2.html", "image": "https://yt3.ggpht.com/ytc/AKedOLR8CSuliVmhPyo9nxofgZWCI9fZKrqL-PFki3b8=s900-c-k-c0x00ffffff-no-rj"},
            {"title": "Brazzers TV Europe", "href": "/brazzers-tv-europe.html", "image": "https://vpnpick.com/wp-content/uploads/2019/05/Unblock-Brazzers-TV.jpg"},
            {"title": "Brazzers TV", "href": "/brazzers-tv.html", "image": "https://vpnpick.com/wp-content/uploads/2019/05/Unblock-Brazzers-TV.jpg"},
            {"title": "Red Lips", "href": "/red-lips.html", "image": "https://s.tmimgcdn.com/scr/1200x750/172200/red-lips-logo-template_172226-original.jpg"},
            {"title": "KinoXXX", "href": "/kino-xxx.html", "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRc7KHiV3wAZTd3fxOPdRhiwsaIV_Rseyhetw&usqp=CAU"},
            {"title": "XY Max HD", "href": "/xy-max-hd.html", "image": "https://tvonline.bg/wp-content/uploads/XY-Max-tv.png"},
            {"title": "XY Plus HD", "href": "/xy-plus-hd.html", "image": "https://1.bp.blogspot.com/-a_cEapx6Kn8/XCmysO6lFsI/AAAAAAAAGUA/tYPpA4natrUSP9TzOcYEq9hntj6F6I1uQCLcBGAs/s1600/XYPlus.png"},
            {"title": "XY Mix HD", "href": "/xy-mix-hd.html", "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSqBz7zcnA_-3Uzc5tyziaXHYHXRKQzCbiUsBVHlMoelOkDoWubhvc58JIwTwquwhhKBhw&usqp=CAU"},
            {"title": "Barely legal", "href": "/barely-legal.html", "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQQtEzEFznJo6dHBs6xljoBEYDUOFvFS29f3nthDqB0qbNVUCBMxE2CaUgdtgaBQbut7Bc&usqp=CAU"},
            {"title": "Playboy TV", "href": "/playboy-tv.html", "image": "https://seeklogo.com/images/P/playboy-tv-logo-8447C82DEB-seeklogo.com.png"},
            {"title": "Vivid Red HD", "href": "/vivid-red.html", "image": "https://www.videosatservice.eu/wp-content/uploads/2017/01/VIVID-EUROPE-TOUCH-FINAL-1.png"},
            {"title": "Exxxotica HD", "href": "/hot-pleasure.html", "image": "https://www.lyngsat.com/logo/tv/ee/exxxotica-ru.png"},
            {"title": "Babes TV", "href": "/babes-tv.html", "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRzNRbMyt8e8auGhD8bWHBrsGbQxLdaWbQe7H6cM5GNmmHtksLqxZyapdmncJt_f3moNdA&usqp=CAU"},
            {"title": "Русская ночь", "href": "/russkaya-noch.html", "image": "https://new.strah.tv/uploads/posts/2019-02/medium/1549285137_extasy_big.png"},
            {"title": "Pink O TV", "href": "/pink-o.html", "image": "https://adult-tv-channels.com/wp-content/uploads/2021/09/redlight-hd-logo.png"},
            {"title": "Erox HD", "href": "/erox-hd.html", "image": "http://okporntv.com/wp-content/uploads/e8e83fc0ec61b284c54d5ac01a282145-321x211.jpeg"},
            {"title": "Eroxxx HD", "href": "/eroxxx-hd.html", "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTVg050bKmSjWZ5SARnx7qseE2UibjbnI3QAZC0BIKAI2Oiu6BewbQKFBRyjUIv54dvRVA&usqp=CAU"},
            {"title": "Hustler HD", "href": "/hustler-hd.html", "image": "https://upload.wikimedia.org/wikipedia/en/c/c0/HUSTLER_TV_HD.png"},
            {"title": "Private TV", "href": "/private-tv.html", "image": "https://adult-tv-channels.com/wp-content/uploads/2021/09/redlight-hd-logo.png"},
            {"title": "Redlight HD", "href": "/redlight-hd.html", "image": "https://adult-tv-channels.com/wp-content/uploads/2021/09/redlight-hd-logo.png"},
            {"title": "Penthouse Gold HD", "href": "/penthouse-gold.html", "image": "https://penthousegold.com/images/logo_phGold.png"},
            {"title": "Penthouse Quickies", "href": "/penthouse-2.html", "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSQdOI0kcO2OwMdiy_TaWnwO7b4VuYh7H4HNxObeZz7fQ5NOXNLfWmj6F9PpYdb5KkS8Fo&usqp=CAU"},
            {"title": "O-la-la", "href": "/o-la-la.html", "image": "https://s.tmimgcdn.com/scr/1200x750/172200/red-lips-logo-template_172226-original.jpg"},
            {"title": "Blue Hustler", "href": "/blue-hustler.html", "image": "https://static.wikia.nocookie.net/tvfanon6528/images/8/80/Blue_Hustler_%282001-.n.v.%29.png/revision/latest?cb=20180312091828"},
            {"title": "Шалун", "href": "/shalun.html", "image": "https://vpnpick.com/wp-content/uploads/2019/05/Unblock-Brazzers-TV.jpg"},
            {"title": "Dorcel TV", "href": "/dorcel-tv.html", "image": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b6/Dorcel_TV.svg/2560px-Dorcel_TV.svg.png"},
            {"title": "Extasy HD", "href": "/extasyhd.html", "image": "https://new.strah.tv/uploads/posts/2019-02/medium/1549285137_extasy_big.png"},
            {"title": "XXL", "href": "/xxl.html", "image": "https://tvonline.bg/wp-content/uploads/XY-Max-tv.png"},
            {"title": "FAP TV 2", "href": "/fap-tv-2.html", "image": "https://i.pinimg.com/474x/60/99/76/609976515a6060808317d4652ac63a3e.jpg"},
            {"title": "FAP TV 3", "href": "/fap-tv-3.html", "image": "http://okteve.com/wp-content/uploads/media/1cfd26a1b4f7dfb8023ff3d4c7f36ec5-520x293.jpeg"},
            {"title": "FAP TV 4", "href": "/fap-tv-4.html", "image": "http://okteve.com/wp-content/uploads/media/cd1153aece771a6d5c6be0dcfe188245-520x293.jpeg"},
            {"title": "FAP TV Parody", "href": "/fap-tv-parody.html", "image": "https://i.pinimg.com/236x/95/36/54/953654df639272bbce26ccaad434644a.jpg"},
            {"title": "FAP TV Compilation", "href": "/fap-tv-compilation.html", "image": "http://okteve.com/wp-content/uploads/media/59eb09001a388f2d691a9b1c83c0f088-520x293.jpeg"},
            {"title": "FAP TV Anal", "href": "/fap-tv-anal.html", "image": "http://okteve.com/wp-content/uploads/media/df180a1f2f441b6282ce427ecfc7ff3a-520x293.jpeg"},
            {"title": "FAP TV Teens", "href": "/fap-tv-teens.html", "image": "https://i.pinimg.com/236x/20/87/bb/2087bb0876b99a08fe7a122ab9c0ba6f.jpg"},
            {"title": "FAP TV Lesbian", "href": "/fap-tv-lesbian.html", "image": "http://okteve.com/wp-content/uploads/media/c449b41987c74cf9cc0dea2ab692b893-520x293.jpeg"},
            {"title": "FAP TV BBW", "href": "/fap-tv-bbw.html", "image": "https://adult-tv-channels.com/wp-content/uploads/2021/09/Fap-TV-logo.png"},
            {"title": "FAP TV Trans", "href": "/fap-tv-trans.html", "image": "https://adult-tv-channels.com/wp-content/uploads/2021/09/Fap-TV-logo.png"},
        ]

    def _abs_url(self, base, url):
        if not url:
            return ''
        if url.startswith('http'):
            return url
        if url.startswith('//'):
            return 'http:' + url
        if url.startswith('/'):
            return self.base_url + url
        return base.rsplit('/', 1)[0] + '/' + url

    def _get_channel_image(self, channel_name):
        color_map = {
            'brazzers': 'FFD700', 'playboy': 'FF69B4', 'hustler': 'DC143C',
            'penthouse': '9370DB', 'vivid': 'FF1493', 'private': '8B008B',
            'dorcel': 'FF6347', 'cineman': '4169E1', 'fap': 'FF4500',
            'xy': 'DA70D6', 'erox': 'FF00FF', 'kino': '8A2BE2',
        }
        color = '1E90FF'
        name_lower = channel_name.lower()
        for key, col in color_map.items():
            if key in name_lower:
                color = col
                break
        text = urllib.parse.quote(channel_name[:20])
        return f"https://via.placeholder.com/400x225/{color}/FFFFFF?text={text}"

    def getName(self):
        return "OXAX直播"

    def init(self, extend):
        pass

    def homeContent(self, filter):
        return {
            'class': [
                {'type_name': '全部频道', 'type_id': 'all'},
                {'type_name': 'HD频道', 'type_id': 'hd'},
                {'type_name': 'FAP系列', 'type_id': 'fap'},
            ]
        }

    def homeVideoContent(self):
        videos = []
        for ch in self.all_channels:
            videos.append({
                'vod_id': ch['href'],
                'vod_name': ch['title'],
                'vod_pic': ch.get('image', self._get_channel_image(ch['title'])),
                'vod_remarks': '直播',
            })
        return {'list': videos}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg)
        items_per_page = 30
        if tid == 'hd':
            channels = [ch for ch in self.all_channels if 'HD' in ch['title'].upper()]
        elif tid == 'fap':
            channels = [ch for ch in self.all_channels if 'FAP' in ch['title'].upper()]
        else:
            channels = self.all_channels
        start = (pg - 1) * items_per_page
        end = start + items_per_page
        page_channels = channels[start:end]
        videos = []
        for ch in page_channels:
            videos.append({
                'vod_id': ch['href'],
                'vod_name': ch['title'],
                'vod_pic': ch.get('image', self._get_channel_image(ch['title'])),
                'vod_remarks': '直播',
            })
        return {
            'list': videos,
            'page': pg,
            'pagecount': max(1, (len(channels) + items_per_page - 1) // items_per_page),
            'limit': items_per_page,
            'total': len(channels),
        }

    def detailContent(self, array):
        if not array or not array[0]:
            return {'list': []}
        relative_path = array[0]
        detail_url = self._abs_url(self.base_url, relative_path)
        title = relative_path.replace('.html', '').replace('/', '').replace('-', ' ').title()
        image = self._get_channel_image(title)
        for ch in self.all_channels:
            if ch['href'] == relative_path:
                title = ch['title']
                image = ch.get('image', image)
                break
        vod = {
            'vod_id': relative_path,
            'vod_name': title,
            'vod_pic': image,
            'vod_remarks': '直播',
            'vod_content': '成人电视直播频道',
            'vod_play_from': 'OXAX',
            'vod_play_url': f'{title}${detail_url}',
        }
        return {'list': [vod]}

    def searchContent(self, key, quick, page='1'):
        if not key:
            return {'list': []}
        key_lower = key.lower()
        results = []
        for ch in self.all_channels:
            if key_lower in ch['title'].lower():
                results.append({
                    'vod_id': ch['href'],
                    'vod_name': ch['title'],
                    'vod_pic': ch.get('image', self._get_channel_image(ch['title'])),
                    'vod_remarks': '直播',
                })
        return {'list': results}

    def playerContent(self, flag, id, vipFlags):
        result = {
            "parse": 1,
            "playUrl": "",
            "url": "",
            "header": {
                "User-Agent": self.session.headers.get('User-Agent'),
                "Referer": self.base_url
            }
        }
        if not id:
            return result
        try:
            url = id
            if '$' in url:
                url = url.split('$')[1]
            # parse=1：交給 App 內建嗅探（宸龍/螞蟻通用），不再用 video:// 前綴
            result["url"] = url
        except Exception as e:
            print(f"[ERROR] 播放器解析失败: {e}")
        return result

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return {}

BASE_URL = "https://klubnichka.live"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

CHANNELS = [
    {"name": 'Dorcel TV', "url": '/dorcel-tv', "logo": 'https://klubnichka.live/images/dorcel-tv.png'},
    {"name": 'Hustler HD', "url": '/hustler-hd', "logo": 'https://klubnichka.live/images/hustler-hd.png'},
    {"name": 'Private TV', "url": '/private-tv', "logo": 'https://klubnichka.live/images/private-tv.png'},
    {"name": 'Brazzers TV Europe', "url": '/brazzers-tv-europe', "logo": 'https://klubnichka.live/images/brazzers-tv-europe.png'},
    {"name": 'Babes TV', "url": '/babes-tv', "logo": 'https://klubnichka.live/images/babes-tv.png'},
    {"name": 'SuperOne HD', "url": '/superone-hd', "logo": 'https://klubnichka.live/images/superone-hd.png'},
    {"name": 'XXL', "url": '/xxl', "logo": 'https://klubnichka.live/images/xxl.png'},
    {"name": 'Playboy TV', "url": '/playboy-tv', "logo": 'https://klubnichka.live/images/playboy-tv.png'},
    {"name": 'Penthouse Reality TV', "url": '/penthouse-reality-tv', "logo": 'https://klubnichka.live/images/penthouse-reality-tv.png'},
    {"name": 'Penthouse Gold', "url": '/penthouse-gold', "logo": 'https://klubnichka.live/images/penthouse-gold.png'},
    {"name": 'Erox HD', "url": '/erox-hd', "logo": 'https://klubnichka.live/images/erox-hd.png'},
    {"name": 'Eroxxx HD', "url": '/eroxxx-hd', "logo": 'https://klubnichka.live/images/eroxxx-hd.png'},
    {"name": 'Blue Hustler', "url": '/blue-hustler', "logo": 'https://klubnichka.live/images/blue-hustler.png'},
    {"name": 'Шалун ТВ', "url": '/shalun-tv', "logo": 'https://klubnichka.live/images/shalun-tv.png'},
    {"name": 'ОХ-АХ HD', "url": '/oh-ah-hd', "logo": 'https://klubnichka.live/images/oh-ah-hd.png'},
    {"name": 'KinoXXX', "url": '/kinoxxx', "logo": 'https://klubnichka.live/images/kinoxxx.png'},
    {"name": 'RU Night', "url": '/ru-night', "logo": 'https://klubnichka.live/images/ru-night.png'},
    {"name": 'Barely Legal TV', "url": '/barely-legal-tv', "logo": 'https://klubnichka.live/images/barely-legal-tv.png'},
    {"name": 'CineMan ExExEx', "url": '/cineman-exexex', "logo": 'https://klubnichka.live/images/cineman-exexex.png'},
    {"name": 'CineMan ExExEx TWO', "url": '/cineman-exexex-two', "logo": 'https://klubnichka.live/images/cineman-exexex-two.png'},
    {"name": 'Red Lips', "url": '/red-lips', "logo": 'https://klubnichka.live/images/red-lips.png'},
    {"name": 'Vivid Red HD', "url": '/vivid-red-hd', "logo": 'https://klubnichka.live/images/vivid-red-hd.png'},
    {"name": 'Extasy HD', "url": '/extasy-hd', "logo": 'https://klubnichka.live/images/extasy-hd.png'},
    {"name": 'Redlight HD', "url": '/redlight-hd', "logo": 'https://klubnichka.live/images/redlight-hd.png'},
    {"name": 'PinkO TV', "url": '/pinko-tv', "logo": 'https://klubnichka.live/images/pinko-tv.png'},
    {"name": 'Reality Kings TV', "url": '/reality-kings-tv', "logo": 'https://klubnichka.live/images/reality-kings-tv.png'},
    {"name": 'XY Max', "url": '/xy-max', "logo": 'https://klubnichka.live/images/xy-max.png'},
    {"name": 'XY Mix', "url": '/xy-mix', "logo": 'https://klubnichka.live/images/xy-mix.png'},
    {"name": 'XY Plus', "url": '/xy-plus', "logo": 'https://klubnichka.live/images/xy-plus.png'},
    {"name": 'Кино 18+ International', "url": '/kino-18-int', "logo": 'https://klubnichka.live/images/kino-18-int.png'},
    {"name": 'Fap TV 2', "url": '/fap-tv-2', "logo": 'https://klubnichka.live/images/fap-tv-2.png'},
    {"name": 'Fap TV 3', "url": '/fap-tv-3', "logo": 'https://klubnichka.live/images/fap-tv-3.png'},
    {"name": 'Fap TV 4', "url": '/fap-tv-4', "logo": 'https://klubnichka.live/images/fap-tv-4.png'},
    {"name": 'Fap TV Anal', "url": '/fap-tv-anal', "logo": 'https://klubnichka.live/images/fap-tv-anal.png'},
    {"name": 'Fap TV BBW', "url": '/fap-tv-bbw', "logo": 'https://klubnichka.live/images/fap-tv-bbw.png'},
    {"name": 'Fap TV Compilation', "url": '/fap-tv-compilation', "logo": 'https://klubnichka.live/images/fap-tv-compilation.png'},
    {"name": 'Fap TV Lesbian', "url": '/fap-tv-lesbian', "logo": 'https://klubnichka.live/images/fap-tv-lesbian.png'},
    {"name": 'Fap TV Parody', "url": '/fap-tv-parody', "logo": 'https://klubnichka.live/images/fap-tv-parody.png'},
    {"name": 'Fap TV Teens', "url": '/fap-tv-teens', "logo": 'https://klubnichka.live/images/fap-tv-teens.png'},
    {"name": 'Большие сиськи', "url": '/big-tits', "logo": 'https://klubnichka.live/images/big-tits.png'},
    {"name": 'Большие жопы', "url": '/big-ass', "logo": 'https://klubnichka.live/images/big-ass.png'},
    {"name": 'Большие члены', "url": '/big-dick', "logo": 'https://klubnichka.live/images/big-dick.png'},
    {"name": 'Милфы', "url": '/milf', "logo": 'https://klubnichka.live/images/milf.png'},
    {"name": 'Межрассовое', "url": '/interracial', "logo": 'https://klubnichka.live/images/interracial.png'},
    {"name": 'Русское порно', "url": '/russian', "logo": 'https://klubnichka.live/images/russian.png'},
    {"name": 'Азиатки', "url": '/asian', "logo": 'https://klubnichka.live/images/asian.png'},
    {"name": 'Латинки', "url": '/latina', "logo": 'https://klubnichka.live/images/latina.png'},
    {"name": 'Лесби секс', "url": '/lesbian', "logo": 'https://klubnichka.live/images/lesbian.png'},
    {"name": 'Блондинки', "url": '/blonde', "logo": 'https://klubnichka.live/images/blonde.png'},
    {"name": 'Брюнетки', "url": '/brunette', "logo": 'https://klubnichka.live/images/brunette.png'},
    {"name": 'Порнозвезды', "url": '/pornstars', "logo": 'https://klubnichka.live/images/pornstars.png'},
    {"name": 'Анал', "url": '/anal', "logo": 'https://klubnichka.live/images/anal.png'},
    {"name": 'Жесткое порно', "url": '/hardcore', "logo": 'https://klubnichka.live/images/hardcore.png'},
    {"name": 'Групповуха', "url": '/gangbang', "logo": 'https://klubnichka.live/images/gangbang.png'},
    {"name": 'Грубый секс', "url": '/rough', "logo": 'https://klubnichka.live/images/rough.png'},
    {"name": 'Куколды', "url": '/cuckolds', "logo": 'https://klubnichka.live/images/cuckolds.png'},
    {"name": 'Минет', "url": '/blowjob', "logo": 'https://klubnichka.live/images/blowjob.png'},
    {"name": 'От первого лица', "url": '/pov', "logo": 'https://klubnichka.live/images/pov.png'},
    {"name": 'Секс втроем', "url": '/threesome', "logo": 'https://klubnichka.live/images/threesome.png'},
    {"name": 'Фетиш', "url": '/fetish', "logo": 'https://klubnichka.live/images/fetish.png'},
]



class _KlubSpider(BaseSpider):
    def getName(self):
        return "py_klubnichka"

    def init(self, extend=""):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(m3u8|mp4)(\?|$)", url or "", re.I))

    def manualVideoCheck(self):
        return False

    def homeContent(self, filter):
        return {"class": [{"type_id": "live", "type_name": "成人頻道"}]}

    def categoryContent(self, tid, pg, filter, extend):
        videos = [{"vod_id": c["url"], "vod_name": c["name"],
                   "vod_pic": c["logo"], "vod_remarks": "LIVE"}
                  for c in CHANNELS]
        return {"list": videos, "page": 1, "pagecount": 1,
                "limit": len(videos), "total": len(videos)}

    def detailContent(self, ids):
        href = ids[0]
        name, logo = href, ""
        for c in CHANNELS:
            if c["url"] == href:
                name, logo = c["name"], c["logo"]
                break
        return {"list": [{"vod_id": href, "vod_name": name,
                          "vod_pic": logo,
                          "vod_play_from": "直播",
                          "vod_play_url": f"{name}${href}"}]}

    def _get_m3u8(self, href):
        """頻道頁 → iframe → player → m3u8，點播時現抓"""
        try:
            s = self.session
            # 1. iframe（需 Sec-Fetch + Referer）
            h1 = {
                "Referer": BASE_URL + href,
                "Sec-Fetch-Dest": "iframe",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
            }
            # 從頻道頁找 iframe 路徑
            r0 = s.get(BASE_URL + href, timeout=15)
            m0 = re.search(r'<iframe[^>]+src="([^"]+)"', r0.text)
            if not m0:
                return None
            iframe_path = m0.group(1)

            r1 = s.get(BASE_URL + iframe_path, headers=h1, timeout=15)
            m1 = re.search(r'/player/[^"\']+', r1.text)
            if not m1:
                return None

            # 2. player（Referer=iframe 頁）
            h2 = {
                "Referer": BASE_URL + iframe_path,
                "Sec-Fetch-Dest": "iframe",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
            }
            r2 = s.get(BASE_URL + m1.group(0), headers=h2, timeout=15)
            # 只取第一個 URL，遇到空白/引號就停
            m2 = re.search(r'(https?://[^"\'\s]+\.m3u8\?[^"\'\s]*)', r2.text)
            if not m2:
                m2 = re.search(r'(https?://[^"\'\s]+\.m3u8)', r2.text)
            if m2:
                return m2.group(1).strip()
        except Exception:
            pass
        return None

    def playerContent(self, flag, id, vipFlags):
        url = self._get_m3u8(id)
        if url:
            return {"parse": 0, "url": url,
                    "header": {"Referer": BASE_URL + id + "/", "User-Agent": UA}}
        return {"parse": 0, "url": ""}

    def searchContent(self, key, quick):
        videos = []
        kl = key.lower()
        for c in CHANNELS:
            if kl in c["name"].lower():
                videos.append({"vod_id": c["url"], "vod_name": c["name"],
                               "vod_pic": c["logo"]})
        return {"list": videos}


# ================= 外層分流殼 =================
class Spider(BaseSpider):
    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self._src = {
            "hochu": ("HochuTV", _HochuSpider()),
            "oxax": ("OXAX", _OxaxSpider()),
            "klub": ("Klubnichka", _KlubSpider()),
        }

    def getName(self):
        return "py_3live"

    def init(self, extend=""):
        for _, sp in self._src.values():
            try:
                sp.init(extend)
            except TypeError:
                try:
                    sp.init()
                except Exception:
                    pass
            except Exception:
                pass

    def homeContent(self, filter=None):
        return {"class": [{"type_id": k, "type_name": v[0]} for k, v in self._src.items()], "filters": {}}

    def _list_of(self, key):
        sp = self._src[key][1]
        try:
            if key == "hochu":
                items = sp.homeVideoContent().get("list", [])
            elif key == "oxax":
                items = sp.homeVideoContent().get("list", [])
            else:
                items = sp.categoryContent("live", "1", None, None).get("list", [])
        except Exception:
            items = []
        out = []
        for v in items:
            nv = dict(v)
            nv["vod_id"] = key + "|" + str(v.get("vod_id", ""))
            nv["vod_remarks"] = self._src[key][0]
            out.append(nv)
        return out

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        if tid not in self._src:
            tid = "hochu"
        items = self._list_of(tid)
        return {"list": items, "page": 1, "pagecount": 1, "limit": len(items), "total": len(items)}

    def homeVideoContent(self):
        return {"list": self._list_of("hochu")[:12]}

    def _split(self, vid):
        vid = str(vid or "")
        if "|" in vid:
            k, raw = vid.split("|", 1)
            if k in self._src:
                return k, raw
        return None, vid

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        key, raw = self._split(vid)
        if key is None:
            return {"list": []}
        sp = self._src[key][1]
        try:
            res = sp.detailContent([raw])
        except Exception:
            return {"list": []}
        lst = res.get("list", []) if isinstance(res, dict) else []
        for vod in lst:
            vod["vod_id"] = key + "|" + str(vod.get("vod_id", raw))
            vod["vod_play_from"] = self._src[key][0]
            pu = vod.get("vod_play_url", "")
            segs = []
            for seg in pu.split("#"):
                if "$" in seg:
                    nm, pid = seg.split("$", 1)
                    segs.append(nm + "$" + key + "|" + pid)
                else:
                    segs.append(seg)
            vod["vod_play_url"] = "#".join(segs)
        return {"list": lst}

    def playerContent(self, flag, id, vipFlags=None):
        key, raw = self._split(id)
        if key is None:
            return {"parse": 0, "playUrl": "", "url": "", "header": {}}
        sp = self._src[key][1]
        try:
            return sp.playerContent(flag, raw, vipFlags)
        except TypeError:
            return sp.playerContent(flag, raw)
        except Exception:
            return {"parse": 0, "playUrl": "", "url": "", "header": {}}

    def searchContent(self, key, quick=False, pg="1"):
        out = []
        for k, (_, sp) in self._src.items():
            try:
                res = sp.searchContent(key, quick)
                items = res.get("list", []) if isinstance(res, dict) else []
            except Exception:
                items = []
            for v in items:
                nv = dict(v)
                nv["vod_id"] = k + "|" + str(v.get("vod_id", ""))
                nv["vod_remarks"] = self._src[k][0]
                out.append(nv)
        return {"list": out, "page": 1, "pagecount": 1, "limit": len(out), "total": len(out)}

    def localProxy(self, param):
        # 只有 hochu 會產生 proxy 網址（兜底用），全數交給它處理
        try:
            return self._src["hochu"][1].localProxy(param)
        except Exception:
            return [502, "text/plain", b"", {}]

    def isVideoFormat(self, url):
        if not url:
            return False
        u = str(url).lower()
        return u.endswith((".m3u8", ".mp4", ".flv", ".ts")) or "m3u8" in u

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def action(self, action):
        return {}
