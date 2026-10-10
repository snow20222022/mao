# -*- coding: utf-8 -*-
"""
後宮電影院（20jack.com）· TVBox Python 插件
========================================================================
【站情 · 2026-10-03 实地探站】
  WordPress 7.x + retroTube(wp-script) 主题 + clean-tube-player 插件。
  无盾、无登录墙、无会员墙，直连 200。
  站子本身是**采集站**：缩略图三种来源混着来（xvideos CDN / 本站 uploads / 老图床 18jenny），
  正片走 third-party 嵌入播放器。

【链路（实测）】
  首页/最新  /?filter=latest              第 N 页 &paged=N
  分类       /?cat=<id>                   第 N 页 &paged=N
  搜索       /?s=<词>                     第 N 页 &paged=N
  详情       /?p=<id>                     og:title / og:image / h1 / itemprop=uploadDate
  播放       详情页里 clean-tube-player 的 q（Base64）→ 解出 tag 里的 iframe src

【★ 三个必踩的坑（都已在代码里绕开）】
  ① **有的分类页卡片没有 id="post-N" 属性**，id 只写在 class 里
     （class="loop-video … post-111761 …"），缩略图也改走 data-main-thumb 懒加载。
     只认 id="post-N" 会让 ?cat=6365 / ?cat=819 这两页**整页丢成 2~4 条**
     （实测踩到过：36 张卡只出 2 张）。所以 id 走三级回退、封面走四级回退。
  ② q 解出来是 **URL 编码**的 `post_id=…&type=iframe&tag=<iframe src="…">`，
     真源在 tag 的 src 里 —— 不用去请求 player-x.php，省一跳。
  ③ 抽样 8/8 的嵌入页都是 xvideos embedframe；页面 html5player 明文给三条流
     （HLS / 360p / 240p）。**三条都带 secure=…,<过期时间戳>**，所以详情页只存嵌入页地址，
     直链留到 playerContent 现抓现解。

【取流结论】
  m3u8 裸取 200（application/vnd.apple.mpegurl）、mp4 裸取 206（video/mp4），都不带防盗链。
  站点是采集站，老片可能在源站已被删 —— 那种如实回空，不编地址。

【纯标准库】无第三方依赖，按手机壳真实条件写。
自检: python3 後宮電影院-TVBox插件.py
"""

import base64
import json
import re
import time
import urllib.parse
import urllib.request

try:                                              # TVBox 壳内基类
    from base.spider import Spider as _Spider
except Exception:
    class _Spider(object):                        # 原生 python 下自检用
        def init(self, *a, **kw):
            return self

# ---------------------------------------------------------------- 常量
SITE_NAME = '後宮電影院'
UA = ('Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36')

POOL = ['https://20jack.com']

# 站方「影片分類」页列出的全部分类（id, 名）
CLASSES = [
    ('6364', '日本無碼'),
    ('788', '歐美短片'),
    ('3419', '國語長片'),
    ('6365', '日本有碼'),
    ('4071', '卡通短片'),
    ('6404', '其它短片'),
    ('819', '其他長片'),
    ('5346', '卡通長片'),
    ('5422', '歐美長片'),
]

PAGE_SIZE = 36

_HDR = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
}


def _http(url, timeout=20, ref=None, headers=None, binary=False):
    h = dict(_HDR)
    if headers:
        h.update(headers)
    if ref:
        h['Referer'] = ref
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except Exception:
        return b'' if binary else ''
    if binary:
        return raw
    for enc in ('utf-8', 'gbk', 'big5'):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode('utf-8', 'replace')


def _ent(s):
    if not s:
        return ''
    t = (s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
          .replace('&quot;', '"').replace('&#039;', "'").replace('&apos;', "'")
          .replace('&nbsp;', ' ').replace('&hellip;', '…').replace('&mdash;', '—')
          .replace('&ndash;', '–').replace('&rsquo;', '’').replace('&lsquo;', '‘')
          .replace('&ldquo;', '“').replace('&rdquo;', '”').replace('&middot;', '·'))
    return re.sub(r'&#(x?)([0-9a-fA-F]+);',
                  lambda m: chr(int(m.group(2), 16) if m.group(1) else int(m.group(2))), t)


def _strip(h):
    if not h:
        return ''
    s = re.sub(r'(?is)<script.*?</script>', ' ', h)
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', _ent(s).replace('\u00a0', ' ')).strip()


def _probe():
    now = time.time()
    hit = _probe.cache
    if hit and now - hit[0] < 1800:
        return hit[1]
    for h in POOL:
        t = _http(h + '/?filter=latest', timeout=15, ref=h + '/')
        if t and 'data-post-id' in t:
            _probe.cache = (now, h)
            return h
    _probe.cache = (now, POOL[0])
    return POOL[0]


_probe.cache = None

# ---------------------------------------------------------------- 列表解析
_RE_ID1 = re.compile(r'id="post-(\d+)"')
_RE_ID2 = re.compile(r'class="[^"]*\bpost-(\d+)\b')       # ★ 有的页只写在 class 里
_RE_ID3 = re.compile(r'data-post-id="(\d+)"')
_RE_HREF = re.compile(r'<a[^>]*href="([^"]*\?p=(\d+))"')
_RE_TITLE = re.compile(r'<a[^>]*title="([^"]{1,400})"')
_RE_IMG = re.compile(r'<img[^>]*class="[^"]*video-main-thumb[^"]*"[^>]*>')
_RE_SRC = re.compile(r'src="([^"]+)"')
_RE_LAZY = re.compile(r'data-src="([^"]+)"')
_RE_MAIN = re.compile(r'data-main-thumb="([^"]+)"')
_RE_THUMBS = re.compile(r'data-thumbs="([^"]+)"')
_RE_VIEWS = re.compile(r'<span class="views">(.*?)</span>', re.S)
_RE_DUR = re.compile(r'<span class="duration">(.*?)</span>', re.S)


def _cards(html):
    """列表页 → 卡片数组。按 <article 切块，逐块抠字段"""
    out = []
    if not html or 'data-post-id' not in html and '?p=' not in html:
        return out
    for seg in html.split('<article')[1:]:
        s = seg[:4000]
        m = _RE_ID1.search(s) or _RE_ID2.search(s) or _RE_ID3.search(s)
        if not m:
            continue
        pid = m.group(1)
        mh = _RE_HREF.search(s)
        if not mh:                                   # 没有 ?p= 链接的是分类墙，不是影片卡
            continue
        title = ''
        mt = _RE_TITLE.search(s)
        if mt:
            title = _ent(mt.group(1))
        pic = ''
        mi = _RE_IMG.search(s)
        if mi:
            tag = mi.group(0)
            ms = _RE_SRC.search(tag) or _RE_LAZY.search(tag)
            if ms:
                pic = ms.group(1)
        if not pic:
            mm = _RE_MAIN.search(s)
            if mm:
                pic = mm.group(1)
        if not pic:
            mt2 = _RE_THUMBS.search(s)
            if mt2:
                pic = mt2.group(1).split(',')[0]
        if not pic:
            for u in _RE_SRC.findall(s):
                if 'xvideos-cdn' in u or '/wp-content/uploads/' in u or '18jenny' in u:
                    pic = u
                    break
        views = ''
        mv = _RE_VIEWS.search(s)
        if mv:
            views = _strip(mv.group(1)).replace('views', '').strip()
        dur = ''
        mdu = _RE_DUR.search(s)
        if mdu:
            dur = _strip(mdu.group(1))
        remark = dur
        if views:
            remark = (remark + ' · ' if remark else '') + views + '次'
        out.append({
            'vod_id': pid,
            'vod_name': title or ('影片 ' + pid),
            'vod_pic': pic,
            'vod_remarks': remark,
        })
    return out


# ---------------------------------------------------------------- 播放解析
def _b64e(s):
    try:
        return base64.urlsafe_b64encode((s or '').encode('utf-8')).decode('ascii').rstrip('=')
    except Exception:
        return ''


def _unwrap(v):
    """播放参数统一是 B64(嵌入页地址)；也兼容直接给明文地址或原始 q"""
    v = (v or '').strip().lstrip('$')
    if v.startswith('http'):
        return v
    d = _b64(v)
    if d.startswith('http'):
        return d
    if 'post_id=' in d or '<iframe' in d:
        return embed_url(v)
    return ''


def _b64(s):
    for fn in (lambda x: __import__('base64').urlsafe_b64decode(x + '=' * (-len(x) % 4)),
               lambda x: __import__('base64').b64decode(x + '=' * (-len(x) % 4))):
        try:
            return fn(s).decode('utf-8', 'replace')
        except Exception:
            continue
    return ''


def embed_url(q):
    """clean-tube-player 的 q → 真嵌入页地址。q = Base64("post_id=…&type=iframe&tag=<iframe src=…>")"""
    if not q or len(q) < 12:
        return ''
    d = _b64(q)
    if not d:
        return ''
    try:
        d = urllib.parse.unquote(d)
    except Exception:
        pass
    m = re.search(r'src="([^"]+)"', d)
    if m:
        return m.group(1).strip()
    m2 = re.search(r'(https?://[^"\'\s<>]+)', d)
    return m2.group(1) if m2 else ''


def _pick(body, rx):
    m = re.search(rx, body or '')
    if not m:
        return ''
    v = m.group(1).replace('\\/', '/')
    return ('https:' + v) if v.startswith('//') else v


def resolve(embed, want_mp4=False):
    """嵌入页 → 可播直链（xvideos 优先，其它域通用兜底）"""
    if not embed or len(embed) < 12:
        return ''
    if embed.startswith('//'):
        embed = 'https:' + embed
    try:
        host = urllib.parse.urlparse(embed).netloc
    except Exception:
        host = ''
    ref = 'https://%s/' % host if host else ''
    body = _http(embed, timeout=20, ref=ref)
    if not body or len(body) < 500:
        return ''
    hls = _pick(body, r'setVideoHLS\(\s*["\']([^"\']+)["\']')
    high = _pick(body, r'setVideoUrlHigh\(\s*["\']([^"\']+)["\']')
    low = _pick(body, r'setVideoUrlLow\(\s*["\']([^"\']+)["\']')
    order = (high, low, hls) if want_mp4 else (hls, high, low)
    for u in order:
        if u and len(u) > 12:
            return u
    g = _pick(body, r'["\'](https?://[^"\'\s<>]+?\.m3u8[^"\'\s<>]*)["\']')
    if g:
        return g
    return _pick(body, r'["\'](https?://[^"\'\s<>]+?\.mp4[^"\'\s<>]*)["\']')


class Spider(_Spider):

    def __init__(self, *args, **kwargs):
        self.host = ''
        self._cache = {}

    def init(self, extend=''):
        self.host = ''
        ext = (extend or '').strip()
        if ext.startswith('{'):
            try:
                h = (json.loads(ext).get('host') or '').strip()
                if len(h) > 6:
                    self.host = (h if h.startswith('http') else 'https://' + h).rstrip('/')
            except Exception:
                pass
        elif ext.startswith('http'):
            self.host = ext.rstrip('/')
        return self

    def getName(self):
        return SITE_NAME

    def isVideoFormat(self, url):
        u = (url or '').lower()
        return '.m3u8' in u or '.mp4' in u

    def manualVideoCheck(self):
        return False

    def _base(self):
        return self.host if self.host else _probe()

    def _get(self, path):
        base = self._base()
        u = path if path.startswith('http') else base + path
        hit = self._cache.get(u)
        if hit and time.time() - hit[0] < 1800:
            return hit[1]
        t = _http(u, timeout=20, ref=base + '/')
        if t and len(t) > 1200:
            self._cache[u] = (time.time(), t)
            return t
        return t or ''

    # ---------------- 首页 / 分类 / 搜索
    def homeContent(self, filter=False):
        cls = [{'type_name': '最新影片', 'type_id': 'home'}]
        cls += [{'type_name': n, 'type_id': t} for t, n in CLASSES]
        return {'class': cls, 'list': _cards(self._get('/?filter=latest'))}

    def homeVideoContent(self):
        return {'list': _cards(self._get('/?filter=latest'))}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        t = (tid or '').strip()
        try:
            page = max(1, int(str(pg).strip()))
        except Exception:
            page = 1
        base = '/?filter=latest' if (not t or t == 'home') else '/?cat=' + t
        body = self._get(base + ('&paged=%d' % page if page > 1 else ''))
        lst = _cards(body)
        pc = page + 1
        nums = [int(x) for x in re.findall(r'paged=(\d+)"', body or '')]
        if nums:
            pc = max(nums)
        return {'page': page, 'pagecount': pc, 'limit': PAGE_SIZE,
                'total': pc * PAGE_SIZE, 'list': lst}

    def searchContent(self, key, quick=False, pg='1'):
        try:
            page = max(1, int(str(pg).strip()))
        except Exception:
            page = 1
        path = '/?s=' + urllib.parse.quote(key or '') + ('&paged=%d' % page if page > 1 else '')
        lst = _cards(self._get(path))
        return {'page': page, 'pagecount': page + 1 if len(lst) >= PAGE_SIZE else page,
                'limit': PAGE_SIZE, 'total': page * PAGE_SIZE, 'list': lst}

    # ---------------- 详情
    def detailContent(self, ids):
        target = ids[0] if isinstance(ids, (list, tuple)) and ids else str(ids or '')
        pid = ''.join(ch for ch in str(target) if ch.isdigit())
        if not pid:
            return {'list': []}
        html = self._get('/?p=%s' % pid)

        def meta(prop):
            m = (re.search(r'<meta[^>]*(?:property|name)="' + re.escape(prop) + r'"[^>]*content="([^"]*)"', html or '')
                 or re.search(r'<meta[^>]*content="([^"]*)"[^>]*(?:property|name)="' + re.escape(prop) + r'"', html or ''))
            return _ent(m.group(1)) if m else ''

        name = meta('og:title')
        if not name:
            m = re.search(r'<h1[^>]*>(.*?)</h1>', html or '', re.S)
            if m:
                name = _ent(_strip(m.group(1)))
        pic = meta('og:image')
        desc = meta('description')
        date = ''
        m = re.search(r'itemprop="uploadDate"[^>]*content="([^"]+)"', html or '')
        if m:
            date = m.group(1)
        q = ''
        mq = re.search(r'player-x\.php\?q=([A-Za-z0-9+/=]+)', html or '')
        if mq:
            q = mq.group(1)
        if not name:
            name = '後宮 #' + pid

        froms, urls = [], []
        embed = embed_url(q) if q else ''
        if embed:
            tag64 = _b64e(embed)
            for tag in ('線路①HLS', '線路②MP4'):
                froms.append(tag)
                urls.append('正片$' + tag64)

        vod = {
            'vod_id': str(target),
            'vod_name': name,
            'vod_pic': pic,
            'vod_year': date[:4] if len(date) >= 4 else '',
            'vod_content': desc,
            'vod_remarks': date[5:10] if len(date) >= 10 else '',
            'vod_play_from': '$$$'.join(froms),
            'vod_play_url': '$$$'.join(urls),
        }
        return {'list': [vod]}

    # ---------------- 播放
    def playerContent(self, flag, vid, vipFlags=None):
        embed = _unwrap(vid)
        want_mp4 = 'MP4' in (flag or '').upper()
        url = resolve(embed, want_mp4) if embed else ''
        if url:
            return {'parse': 0, 'jx': 0, 'url': url, 'playUrl': '', 'header': {'User-Agent': UA}}
        return {'parse': 1, 'jx': 0, 'url': embed, 'playUrl': '', 'header': {'User-Agent': UA}}


# ---------------------------------------------------------------- 自检
if __name__ == '__main__':
    import sys

    ok = bad = 0

    def ck(what, cond, extra=''):
        global ok, bad
        if cond:
            ok += 1
            print('  ✅ %s %s' % (what, ('[%s]' % extra) if extra else ''))
        else:
            bad += 1
            print('  ❌ %s %s' % (what, ('[%s]' % extra) if extra else ''))

    sp = Spider().init('{}')
    print('=========== 後宮電影院 插件自检 ===========')
    h = sp.homeContent()
    ck('首页分类', len(h['class']) >= 8, '%d 类' % len(h['class']))
    ck('首页卡片', len(h['list']) >= 20, '%d 张' % len(h['list']))

    for tid, nm in CLASSES:
        c = sp.categoryContent(tid, '1')
        ck('分类有货 ' + nm, len(c['list']) >= 5, '%d 张 · 共%s页' % (len(c['list']), c['pagecount']))
        time.sleep(0.15)

    c1 = sp.categoryContent('6364', '1')
    c2 = sp.categoryContent('6364', '2')
    ck('分类翻页换页', bool(c1['list']) and bool(c2['list'])
       and c1['list'][0]['vod_id'] != c2['list'][0]['vod_id'],
       'p1=%s p2=%s' % (c1['list'][0]['vod_id'], c2['list'][0]['vod_id']))

    s = sp.searchContent('中文')
    ck('搜索', len(s['list']) >= 1, '%d 条' % len(s['list']))

    real = c1['list'][0]['vod_id'] if c1['list'] else ''
    d = sp.detailContent([real])
    if d['list']:
        v = d['list'][0]
        ck('详情标题', len(v['vod_name']) > 2, v['vod_name'][:40])
        ck('详情封面', v['vod_pic'].startswith('http'), v['vod_pic'][:60])
        ck('详情线路两条', len(v['vod_play_from'].split('$$$')) == 2, v['vod_play_from'])
        sofar = v['vod_play_url'].split('$$$')[0]
        b64 = sofar.split('$', 1)[-1]
        embed = _unwrap(b64)
        ck('q 解出嵌入页', 'embedframe' in embed or embed.startswith('http'), embed[:80])
        for flag in ('線路①HLS', '線路②MP4'):
            p = sp.playerContent(flag, b64)
            u = p.get('url', '')
            ck(flag + ' 解出', len(u) > 12, u[:80])
            if '.m3u8' in u:
                raw = _http(u, timeout=20, binary=True)
                txt = raw.decode('utf-8', 'replace') if raw else ''
                ck('HLS 清单真拉', '#EXTM3U' in txt, '%d bytes' % len(raw))
            elif '.mp4' in u:
                req = urllib.request.Request(u, headers={'User-Agent': UA, 'Range': 'bytes=0-199999'})
                try:
                    with urllib.request.urlopen(req, timeout=20) as r:
                        raw = r.read()
                    ck('MP4 真拉首段', len(raw) > 100000, '%d bytes' % len(raw))
                except Exception as e:
                    ck('MP4 真拉首段', False, str(e))
    ck('坏 id 不炸', isinstance(sp.detailContent(['zzz']), dict), '')

    print('---------- 後宮: PASS=%d FAIL=%d ----------' % (ok, bad))
    sys.exit(2 if bad else 0)
