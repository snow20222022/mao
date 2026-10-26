# -*- coding: utf-8 -*-
"""
ss直播 - drpy Spider 版
由 ss直播.js 规则（http://api.hclyz.com:81/mf）转写为 drpy Spider 类格式，
接口于 2026-10-25 验证可用。

原规则:
    一级(平台列表): GET /mf/json.txt   -> {"pingtai":[{title,xinimg,Number,address},...]}
    二级(频道列表): GET /mf/<address>  -> {"zhubo":[{title,img,address},...]}

结构参照: 直播录屏TG群：@tvshare23.py（Spider 类标准骨架 + 请求兜底 + 图片补全）
"""

import re, json, ssl
from urllib.parse import urljoin, urlencode

try:
    from base.spider import Spider
except ImportError:
    import gzip as _gzip
    import io as _io
    import urllib.request as _urq

    class _Resp:
        def __init__(self, raw):
            if raw[:2] == b'\x1f\x8b':
                raw = _gzip.GzipFile(fileobj=_io.BytesIO(raw)).read()
            self.content = raw
            self.text = raw.decode('utf-8', 'ignore')
            self.status_code = 200

    class Spider:
        def fetch(self, url, headers=None, **kw):
            try:
                h = dict(headers or {})
                h.setdefault('User-Agent', 'Mozilla/5.0 (Linux; Android 11) Chrome/126.0 Mobile Safari/537.36')
                req = _urq.Request(url, headers=h)
                with _urq.urlopen(req, timeout=kw.get('timeout', 10)) as r:
                    return _Resp(r.read())
            except Exception:
                return None

        def post(self, url, data, headers=None):
            try:
                h = dict(headers or {})
                h.setdefault('User-Agent', 'Mozilla/5.0 (Linux; Android 11) Chrome/126.0 Mobile Safari/537.36')
                req = _urq.Request(url, data=urlencode(data).encode(), headers=h)
                with _urq.urlopen(req, timeout=10) as r:
                    return _Resp(r.read())
            except Exception:
                return None


class Spider(Spider):
    host = 'http://api.hclyz.com:81/mf'
    header = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 11; MI 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36',
        'Accept': '*/*',
    }
    LIMIT = 200  # 原规则 limit:200

    def getName(self):
        return 'ss直播'

    def init(self, extend=''):
        if isinstance(extend, list):
            self.extend = ''
        else:
            self.extend = extend or ''
        return {}

    def isVideoFormat(self, url):
        return any(x in url for x in ['.m3u8', '.mp4', '.flv', '.avi', '.mkv'])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def _fetch_text(self, url):
        """GET 请求，返回文本；处理 gzip/编码，失败返回 ''"""
        try:
            h = dict(self.header)
            h['Accept-Encoding'] = 'gzip'
            r = self.fetch(url, headers=h, timeout=10)
            if not r:
                return ''
            t = r.text if hasattr(r, 'text') else r.content.decode('utf-8', 'ignore')
            try:
                t = t.encode('latin-1').decode('utf-8')
            except Exception:
                pass
            return t.strip().lstrip('\ufeff')
        except Exception:
            return ''

    def _fetch_json(self, url):
        """GET 并解析 JSON；容错处理 BOM、尾逗号、单引号等脏数据"""
        t = self._fetch_text(url)
        if not t:
            return {}
        try:
            return json.loads(t)
        except Exception:
            try:
                fixed = re.sub(r",\s*([}\]])", r"\1", t)
                fixed = re.sub(r"(?<![\w\"'])('(?=[^']*'\s*[,:}\]]))", '"', fixed)
                return json.loads(fixed)
            except Exception:
                return {}

    def _wrap_pic(self, pic):
        if not pic:
            return ''
        pic = pic.strip()
        if pic.startswith(('"', "'")) and pic.endswith(('"', "'")):
            pic = pic[1:-1]
        pic = pic.replace('&amp;', '&')
        if '127.0.0.1' in pic or 'proxy' in pic:
            return pic
        if pic.startswith('//'):
            pic = 'http:' + pic
        elif not pic.startswith(('http://', 'https://')):
            pic = (self.host + pic) if pic.startswith('/') else self.host + '/' + pic
        return pic

    def _platform_url(self, addr):
        addr = (addr or '').strip()
        if not addr:
            return ''
        if addr.startswith('http'):
            return addr
        return self.host + '/' + addr.lstrip('/')

    def _get_platforms(self):
        """一级：平台列表，对应原规则 'json:pingtai;title;xinimg;Number;address'"""
        data = self._fetch_json(self.host + '/json.txt')
        result = []
        for p in (data.get('pingtai') or [])[:self.LIMIT]:
            title = (p.get('title') or '').strip()
            addr = self._platform_url(p.get('address'))
            if not title or not addr:
                continue
            result.append({
                'title': title,
                'img': self._wrap_pic(p.get('xinimg') or ''),
                'number': str(p.get('Number', '')),
                'url': addr,
            })
        return result

    def _channels(self, platform_url):
        """二级：频道列表，解析 zhubo 数组的 title/address"""
        data = self._fetch_json(platform_url)
        channels = []
        for z in (data.get('zhubo') or []):
            title = (z.get('title') or '').strip()
            addr = (z.get('address') or '').strip()
            if title and addr:
                channels.append({
                    'title': title,
                    'img': self._wrap_pic(z.get('img') or ''),
                    'url': addr,
                })
        return channels

    def homeContent(self, filter):
        classes = []
        try:
            for p in self._get_platforms():
                # type_id 用平台接口地址（保证唯一），name@url 由二级再解析
                classes.append({'type_name': p['title'], 'type_id': p['url']})
        except Exception:
            pass
        if not classes:
            classes = [{'type_name': 'ss直播', 'type_id': self.host + '/json.txt'}]
        filters = {c['type_id']: [] for c in classes}
        return {'class': classes, 'filters': filters}

    def homeVideoContent(self):
        try:
            plats = self._get_platforms()
            if plats:
                return {'list': self._channel_items(plats[0]['url'], plats[0]['title'])[:24]}
        except Exception:
            pass
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg or 1)
            if pg < 1:
                pg = 1
            # tid 为平台接口地址；直播频道不翻页，仅返回一页
            title = ''
            if tid == self.host + '/json.txt':
                plats = self._get_platforms()
                if pg > 1:
                    return {'page': pg, 'pagecount': 1, 'limit': 0, 'total': 0, 'list': []}
                vod_list = []
                for p in plats:
                    vod_list.extend(self._channel_items(p['url'], p['title']))
            else:
                vod_list = self._channel_items(tid, title)
            return {'page': 1, 'pagecount': 1, 'limit': len(vod_list), 'total': len(vod_list), 'list': vod_list}
        except Exception:
            return {'page': pg, 'pagecount': 1, 'limit': 0, 'total': 0, 'list': []}

    def _channel_items(self, platform_url, platform_title=''):
        items = []
        try:
            for c in self._channels(platform_url):
                # vod_id 编码为 "频道名@播放地址"，详情/播放时再拆开
                items.append({
                    'vod_id': '%s@%s' % (c['title'], c['url']),
                    'vod_name': c['title'][:50],
                    'vod_pic': c['img'],
                    'vod_remarks': '直播',
                })
        except Exception:
            pass
        return items

    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, list) else str(ids)
            if '@' in vid:
                name, url = vid.split('@', 1)
            else:
                name, url = '直播', vid
            vod = {
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': '',
                'vod_remarks': '直播',
                'vod_actor': '',
                'vod_director': '',
                'type_name': '直播频道',
                'vod_year': '',
                'vod_area': '',
                'vod_content': name,
                'vod_play_from': 'ss直播',
                'vod_play_url': '%s$%s' % (name, url),
            }
            return {'list': [vod]}
        except Exception:
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        try:
            raw = str(key).lower()
            items = []
            plats = self._get_platforms()
            for p in plats[:30]:  # 最多遍历前 30 个平台，避免请求过多
                for it in self._channel_items(p['url'], p['title']):
                    if raw not in it['vod_name'].lower():
                        continue
                    if any(x['vod_id'] == it['vod_id'] for x in items):
                        continue
                    items.append(it)
                    if len(items) >= 80:
                        return {'list': items, 'page': 1}
            return {'list': items, 'page': 1}
        except Exception:
            return {'list': [], 'page': 1}

    def searchContentPage(self, key, quick, pg=1):
        return self.searchContent(key, quick, pg)

    def playerContent(self, flag, id, vipFlags):
        try:
            # id 为频道播放地址；HLS 主播放列表时选最高码率变体
            url = str(id)
            if not url:
                return {}
            if '.m3u8' in url.lower():
                url = self._hls_best_variant(url)
            return {
                'parse': 0,
                'url': url,
                'header': {'User-Agent': self.header['User-Agent']},
            }
        except Exception:
            return {}

    def _hls_best_variant(self, url):
        """若为 HLS 主播放列表(含多码率)，返回带宽最高的子流地址；否则原样返回"""
        try:
            if '.m3u8' not in url.lower():
                return url
            text = self._fetch_text(url)
            if not text or '#EXT-X-STREAM-INF' not in text:
                return url
            best_bw, best_uri = -1, None
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if line.startswith('#EXT-X-STREAM-INF'):
                    bw = 0
                    for part in line.split(':')[1].split(','):
                        kv = part.split('=', 1)
                        if len(kv) == 2 and kv[0].strip().upper() == 'BANDWIDTH':
                            try:
                                bw = int(kv[1])
                            except ValueError:
                                pass
                    for j in range(i + 1, len(lines)):
                        nxt = lines[j].strip()
                        if nxt and not nxt.startswith('#'):
                            if bw > best_bw:
                                best_bw, best_uri = bw, nxt
                            break
            if best_uri:
                return urljoin(url, best_uri)
            return url
        except Exception:
            return url

    def localProxy(self, param):
        return []
