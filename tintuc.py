#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tin Tức — trình đọc báo RSS cho muOS (Anbernic RG40XXH, 640x480).

Chỉ dùng thư viện chuẩn của Python 3 + SDL2 / SDL2_ttf qua ctypes
(cả hai đều có sẵn trên muOS), không cần cài thêm gói nào.

Điều khiển:
  D-pad lên/xuống  : di chuyển / cuộn
  D-pad trái/phải  : lật trang
  A                : mở
  B                : quay lại (ở màn hình chính: thoát)
  X                : tải lại
  Y                : lưu / bỏ lưu bài
  L1 / R1          : đổi chuyên mục (danh sách) — bài trước/sau (khi đọc)
  SELECT           : đổi cỡ chữ
  START            : đổi giao diện sáng / tối
  MENU             : thoát
"""

import ctypes
import ctypes.util
import email.utils
import gzip
import hashlib
import html
import json
import os
import queue
import re
import ssl
import sys
import threading
import time
import traceback
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from collections import OrderedDict
from html.parser import HTMLParser

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
CACHE_DIR = os.path.join(APP_DIR, "cache")
LOG_PATH = os.path.join(APP_DIR, "tintuc.log")

W, H = 640, 480
HEADER_H = 40
FOOTER_H = 30
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
# Dùng khi lần tải đầu không ra tin
ALT_USER_AGENTS = [
    "Mozilla/5.0 (compatible; TinTucMuOS/1.1; RSS reader)",
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Mobile Safari/537.36",
]


def log(*a):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Lưu trữ
# ---------------------------------------------------------------------------

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        log("save_json lỗi", path, e)


def h(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


DEFAULT_CONFIG = {
    "utc_offset_hours": 7,        # múi giờ hiển thị
    "refresh_minutes": 10,        # tự tải lại chuyên mục sau bao lâu
    "swap_ab": False,             # đảo nút A/B nếu thấy ngược
    "fullscreen": True,
    "insecure_ssl_fallback": False,  # chỉ bật nếu máy lỗi chứng chỉ SSL
    "debug_input": False,         # hiện mã nút bấm ở chân màn hình
    "raw_buttons": {              # dùng khi tay cầm không được SDL nhận là GameController
        "A": 3, "B": 4, "X": 6, "Y": 5, "L1": 7, "R1": 8,
        "SELECT": 9, "START": 10, "MENU": 11, "L2": 13, "R2": 14
    }
}


# ---------------------------------------------------------------------------
# Mạng
# ---------------------------------------------------------------------------

class Net:
    def __init__(self, cfg):
        self.cfg = cfg
        self.ctx = None
        cafile = os.path.join(APP_DIR, "cacert.pem")
        try:
            if os.path.exists(cafile):
                self.ctx = ssl.create_default_context(cafile=cafile)
            else:
                self.ctx = ssl.create_default_context()
        except Exception as e:
            log("SSL context lỗi", e)
            self.ctx = ssl.create_default_context()

    def _opener(self, ctx):
        import http.cookiejar
        if not hasattr(self, "_jar"):
            self._jar = http.cookiejar.CookieJar()
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar),
            urllib.request.HTTPSHandler(context=ctx))

    def fetch(self, url, timeout=20, ua=None):
        """Trả về (data, content_type, url_cuối_cùng)."""
        req = urllib.request.Request(url, headers={
            "User-Agent": ua or USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.7",
        })
        try:
            resp = self._opener(self.ctx).open(req, timeout=timeout)
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLError) and self.cfg.get("insecure_ssl_fallback"):
                log("SSL lỗi, dùng chế độ không xác minh:", url)
                resp = self._opener(ssl._create_unverified_context()).open(req, timeout=timeout)
            else:
                raise
        with resp:
            data = resp.read()
            enc = (resp.headers.get("Content-Encoding") or "").lower()
            ctype = resp.headers.get("Content-Type") or ""
            final = resp.geturl() or url
        if enc == "gzip" or data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        elif enc == "deflate":
            try:
                data = zlib.decompress(data)
            except zlib.error:
                data = zlib.decompress(data, -zlib.MAX_WBITS)
        return data, ctype, final


def decode_html(data, ctype):
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I)
    cs = m.group(1) if m else None
    if not cs:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", data[:4000], re.I)
        cs = m.group(1).decode("ascii", "ignore") if m else "utf-8"
    try:
        return data.decode(cs, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def friendly_error(e):
    s = str(e)
    if isinstance(e, urllib.error.HTTPError):
        return "Máy chủ trả lỗi HTTP %d" % e.code
    if "CERTIFICATE" in s.upper() or isinstance(getattr(e, "reason", None), ssl.SSLError):
        return "Lỗi chứng chỉ SSL — kiểm tra ngày giờ của máy"
    if "timed out" in s or "timeout" in s.lower():
        return "Hết thời gian chờ — mạng chậm hoặc mất kết nối"
    if "Name or service not known" in s or "getaddrinfo" in s or "Temporary failure" in s:
        return "Không có mạng — hãy bật Wi-Fi trong Settings"
    return "Lỗi: " + s[:120]


# ---------------------------------------------------------------------------
# Xử lý văn bản
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Font không có emoji / ký hiệu lạ -> bỏ để không hiện ô vuông
_BAD_CHARS = re.compile("[\U0001F000-\U0010FFFF​-‏⁠﻿️]")


def clean_text(s):
    if not s:
        return ""
    s = html.unescape(_TAG_RE.sub(" ", s))
    s = _BAD_CHARS.sub("", s)
    return _WS_RE.sub(" ", s).strip()


class ParaExtractor(HTMLParser):
    """Trích đoạn văn chính của bài báo: tìm khối chứa nhiều chữ trong <p> nhất."""
    SKIP = {"script", "style", "noscript", "svg", "iframe", "form", "button",
            "template", "figcaption", "nav", "footer", "aside", "select", "video", "audio"}
    VOID = {"br", "img", "meta", "link", "input", "hr", "source", "wbr", "area",
            "base", "col", "embed", "param", "track"}
    BLOCKS = {"p", "h2", "h3", "h4", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []        # [(tag, id)]
        self.next_id = 1
        self.skip = 0
        self.blocks = []       # [(kind, text, ancestors_tuple)]
        self.cur = None        # [kind, [parts], ancestors]

    def _close_block(self):
        if self.cur is not None:
            t = _WS_RE.sub(" ", "".join(self.cur[1])).strip()
            if t:
                self.blocks.append((self.cur[0], t, self.cur[2]))
            self.cur = None

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            if tag == "br" and self.cur is not None:
                self.cur[1].append(" ")
            return
        if self.skip or tag in self.SKIP:
            self.skip += 1
            self.stack.append((tag, -1))
            return
        if tag in self.BLOCKS:
            self._close_block()
            anc = tuple(i for _, i in self.stack if i > 0)
            self.cur = [tag, [], anc]
        self.stack.append((tag, self.next_id))
        self.next_id += 1

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        # pop tới thẻ khớp (HTML ngoài đời hay thiếu thẻ đóng)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for t, ident in self.stack[i:]:
                    if ident == -1:
                        self.skip = max(0, self.skip - 1)
                    if t in self.BLOCKS:
                        self._close_block()
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self.skip == 0 and self.cur is not None:
            self.cur[1].append(data)

    def result(self):
        self._close_block()
        score = {}
        for kind, text, anc in self.blocks:
            if kind != "p" or len(text) < 25:
                continue
            n = len(text)
            if anc:
                score[anc[-1]] = score.get(anc[-1], 0) + n
            if len(anc) > 1:
                score[anc[-2]] = score.get(anc[-2], 0) + n * 0.6
        if not score:
            return []
        best = max(score, key=score.get)
        out = []
        for kind, text, anc in self.blocks:
            if best in anc:
                t = _BAD_CHARS.sub("", text)
                if t:
                    out.append(("h" if kind in ("h2", "h3", "h4") else "p", t))
        return out


def extract_article(html_text):
    p = ParaExtractor()
    try:
        p.feed(html_text)
    except Exception as e:
        log("parse html lỗi", e)
    return p.result()


def parse_date(s):
    if not s:
        return 0
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
        return d.timestamp()
    except Exception:
        pass
    try:
        from datetime import datetime
        s2 = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s2).timestamp()
    except Exception:
        return 0


ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


def parse_feed(data, source_name):
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    text = text.lstrip("﻿ \r\n\t")
    items = []
    root = None
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        # Sửa vài lỗi XML hay gặp rồi thử lại
        fixed = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text)
        fixed = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", fixed)
        try:
            root = ET.fromstring(fixed.encode("utf-8"))
        except ET.ParseError:
            root = None

    def mk(title, link, desc, date, content=""):
        title = clean_text(title)
        link = (link or "").strip()
        if not title or not link:
            return
        it = {"id": link, "title": title, "link": link,
              "summary": clean_text(desc)[:600], "ts": parse_date(date),
              "source": source_name}
        if content and len(content) > 400:
            paras = extract_article("<div>" + content + "</div>")
            if paras:
                it["paras"] = paras
        items.append(it)

    if root is not None:
        for it in root.iter("item"):
            mk(it.findtext("title"), it.findtext("link") or it.findtext("guid"),
               it.findtext("description"), it.findtext("pubDate") or
               it.findtext("{http://purl.org/dc/elements/1.1/}date"),
               it.findtext(CONTENT) or "")
        for e in root.iter(ATOM + "entry"):
            link = ""
            for l in e.findall(ATOM + "link"):
                if l.get("rel", "alternate") == "alternate":
                    link = l.get("href", "")
                    break
            mk(e.findtext(ATOM + "title"), link,
               e.findtext(ATOM + "summary") or "",
               e.findtext(ATOM + "published") or e.findtext(ATOM + "updated"),
               e.findtext(ATOM + "content") or "")
    else:
        # Bất đắc dĩ: dùng regex
        for m in re.finditer(r"<item\b.*?</item>", text, re.S | re.I):
            blk = m.group(0)

            def g(tag):
                mm = re.search(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), blk, re.S | re.I)
                if not mm:
                    return ""
                v = mm.group(1)
                v = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", v, flags=re.S)
                return v
            mk(g("title"), clean_text(g("link")), g("description"), g("pubDate"))
    return items


# ---------------------------------------------------------------------------
# Công việc nền
# ---------------------------------------------------------------------------

def looks_like_html(data):
    head = data[:2000].lower() if isinstance(data, bytes) else data[:2000].lower().encode()
    return b"<html" in head or b"<!doctype html" in head


def home_of(url):
    from urllib.parse import urlsplit
    p = urlsplit(url)
    return "%s://%s/" % (p.scheme, p.netloc) if p.netloc else None


def dump_debug(url, data, ctype):
    """Ghi lại phản hồi lạ để dễ chẩn đoán."""
    try:
        d = os.path.join(CACHE_DIR, "debug")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, h(url) + ".txt")
        with open(path, "wb") as f:
            f.write(("URL: %s\nContent-Type: %s\nĐộ dài: %d\n\n" % (url, ctype, len(data))).encode("utf-8"))
            f.write(data[:20000])
        log("không có nội dung:", url, "-> đã lưu", path)
    except Exception:
        pass


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []   # (href, text, title_attr)
        self.cur = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        elif tag == "a":
            a = dict(attrs)
            if a.get("href"):
                self.cur = [a["href"], [], a.get("title") or ""]

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        elif tag == "a" and self.cur:
            self.links.append((self.cur[0], "".join(self.cur[1]), self.cur[2]))
            self.cur = None

    def handle_data(self, data):
        if self.cur is not None and not self.skip:
            self.cur[1].append(data)


_ARTICLE_URL = re.compile(r"(\d{5,}[^/]*\.(html?|vnp|htm)$)|(-post\d+\.html$)|(/\d{6,}\.html?$)|(\.(html?|vnp)$)", re.I)
_BAD_URL = re.compile(r"(/tag/|/tags/|/video|/podcast|/tim-kiem|/search|/rss|/lien-he|/gioi-thieu|login|/author|/tac-gia|/su-kien/)", re.I)


def parse_html_links(text, base_url, source, pattern=None):
    """Lấy danh sách bài từ trang chủ / trang chuyên mục (khi không có RSS)."""
    from urllib.parse import urljoin, urlsplit
    p = LinkExtractor()
    try:
        p.feed(text)
    except Exception as e:
        log("parse link lỗi", e)
    host = urlsplit(base_url).netloc.lower()
    root = host[4:] if host.startswith("www.") else host
    rx = re.compile(pattern) if pattern else None
    seen = OrderedDict()
    for href, txt, title_attr in p.links:
        url = urljoin(base_url, href.strip()).split("#")[0]
        sp = urlsplit(url)
        if sp.scheme not in ("http", "https"):
            continue
        hn = sp.netloc.lower()
        if not (hn == root or hn.endswith("." + root)):
            continue
        if rx:
            if not rx.search(url):
                continue
        elif not _ARTICLE_URL.search(sp.path) or _BAD_URL.search(sp.path):
            continue
        title = clean_text(txt)
        if len(title) < 20:
            title = clean_text(title_attr) if len(clean_text(title_attr)) > len(title) else title
        if len(title) < 20 or len(title.split()) < 4:
            continue
        if url not in seen or len(title) > len(seen[url]):
            seen[url] = title
    return [{"id": u, "title": t, "link": u, "summary": "", "ts": 0, "source": source}
            for u, t in list(seen.items())[:80]]


class Worker:
    def __init__(self, net, n=2):
        self.net = net
        self.jobs = queue.Queue()
        self.results = queue.Queue()
        self.pending = set()
        self.lock = threading.Lock()
        for _ in range(n):
            t = threading.Thread(target=self._run, daemon=True)
            t.start()

    def submit(self, kind, key, **kw):
        with self.lock:
            if (kind, key) in self.pending:
                return
            self.pending.add((kind, key))
        self.jobs.put((kind, key, kw))

    def busy(self):
        with self.lock:
            return bool(self.pending)

    def _load_feed(self, feed, source):
        """Tải chuyên mục, thử nhiều cách cho tới khi có tin."""
        url = feed["url"]
        kind = feed.get("type", "rss")
        tried = []

        http_err = []

        def attempt(u, mode, ua=None):
            try:
                data, ctype, final = self.net.fetch(u, ua=ua)
            except urllib.error.HTTPError as e:  # 403/404... -> thử cách khác
                tried.append("%s [%s] -> HTTP %d" % (u, mode, e.code))
                http_err.append(e)
                return []
            text = decode_html(data, ctype) if mode == "html" else data
            if mode == "rss":
                items = parse_feed(data, source)
                if not items and looks_like_html(data):
                    # Máy chủ trả trang web thay vì RSS -> lấy link bài từ trang đó
                    items = parse_html_links(decode_html(data, ctype), final, source, feed.get("pattern"))
            else:
                items = parse_html_links(text, final, source, feed.get("pattern"))
            tried.append("%s [%s] -> %d tin, %s, %d byte" % (u, mode, len(items), ctype, len(data)))
            if not items:
                dump_debug(u, data, ctype)
            return items

        items = attempt(url, kind)
        if not items and kind == "rss":
            for ua in ALT_USER_AGENTS:
                items = attempt(url, "rss", ua)
                if items:
                    break
        if not items:
            fb = feed.get("fallback") or home_of(url)
            if fb and fb != url:
                items = attempt(fb, "html")
        log("tải chuyên mục:", " | ".join(tried))
        if not items and http_err:
            raise http_err[0]
        return items

    def _run(self):
        while True:
            kind, key, kw = self.jobs.get()
            res, err = None, None
            try:
                if kind == "feed":
                    res = self._load_feed(kw.get("feed") or {"url": key}, kw.get("source", ""))
                    if not res:
                        err = "Nguồn không trả về tin nào (chi tiết trong tintuc.log)"
                elif kind == "article":
                    data, ctype, _ = self.net.fetch(key)
                    res = extract_article(decode_html(data, ctype))
                    if not res:
                        dump_debug(key, data, ctype)
            except Exception as e:
                log("job lỗi", kind, key, repr(e))
                err = friendly_error(e)
            with self.lock:
                self.pending.discard((kind, key))
            self.results.put((kind, key, res, err))


# ---------------------------------------------------------------------------
# SDL2 qua ctypes
# ---------------------------------------------------------------------------

def _load(names):
    dirs = [os.environ.get("TINTUC_SDL_DIR", ""), APP_DIR, os.path.join(APP_DIR, "lib")]
    for d in dirs:
        if not d:
            continue
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ctypes.CDLL(p)
    for n in names:
        try:
            return ctypes.CDLL(n)
        except OSError:
            pass
    raise OSError("Không tìm thấy thư viện: " + ", ".join(names))


class SDL_Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int),
                ("w", ctypes.c_int), ("h", ctypes.c_int)]


class SDL_Color(ctypes.Structure):
    _fields_ = [("r", ctypes.c_uint8), ("g", ctypes.c_uint8),
                ("b", ctypes.c_uint8), ("a", ctypes.c_uint8)]


vp, ci, cu32, cu8, cp = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_uint8, ctypes.c_char_p
PI = ctypes.POINTER(ctypes.c_int)


class SDL:
    def __init__(self):
        L = _load(["libSDL2-2.0.so.0", "libSDL2-2.0.so", "libSDL2.so"])
        T = _load(["libSDL2_ttf-2.0.so.0", "libSDL2_ttf-2.0.so", "libSDL2_ttf.so"])
        self.L, self.T = L, T

        def f(lib, name, res, args):
            fn = getattr(lib, name)
            fn.restype = res
            fn.argtypes = args
            setattr(self, name, fn)

        f(L, "SDL_Init", ci, [cu32])
        f(L, "SDL_Quit", None, [])
        f(L, "SDL_GetError", cp, [])
        f(L, "SDL_SetHint", ci, [cp, cp])
        f(L, "SDL_CreateWindow", vp, [cp, ci, ci, ci, ci, cu32])
        f(L, "SDL_DestroyWindow", None, [vp])
        f(L, "SDL_CreateRenderer", vp, [vp, ci, cu32])
        f(L, "SDL_DestroyRenderer", None, [vp])
        f(L, "SDL_RenderSetLogicalSize", ci, [vp, ci, ci])
        f(L, "SDL_SetRenderDrawColor", ci, [vp, cu8, cu8, cu8, cu8])
        f(L, "SDL_SetRenderDrawBlendMode", ci, [vp, ci])
        f(L, "SDL_RenderClear", ci, [vp])
        f(L, "SDL_RenderFillRect", ci, [vp, ctypes.POINTER(SDL_Rect)])
        f(L, "SDL_RenderCopy", ci, [vp, vp, ctypes.POINTER(SDL_Rect), ctypes.POINTER(SDL_Rect)])
        f(L, "SDL_RenderPresent", None, [vp])
        f(L, "SDL_RenderReadPixels", ci, [vp, ctypes.POINTER(SDL_Rect), cu32, vp, ci])
        f(L, "SDL_CreateTextureFromSurface", vp, [vp, vp])
        f(L, "SDL_DestroyTexture", None, [vp])
        f(L, "SDL_QueryTexture", ci, [vp, ctypes.POINTER(cu32), PI, PI, PI])
        f(L, "SDL_FreeSurface", None, [vp])
        f(L, "SDL_CreateRGBSurfaceWithFormat", vp, [cu32, ci, ci, ci, cu32])
        f(L, "SDL_RWFromFile", vp, [cp, cp])
        f(L, "SDL_SaveBMP_RW", ci, [vp, vp, ci])
        f(L, "SDL_PollEvent", ci, [vp])
        f(L, "SDL_Delay", None, [cu32])
        f(L, "SDL_GetTicks", cu32, [])
        f(L, "SDL_ShowCursor", ci, [ci])
        f(L, "SDL_NumJoysticks", ci, [])
        f(L, "SDL_IsGameController", ci, [ci])
        f(L, "SDL_GameControllerOpen", vp, [ci])
        f(L, "SDL_GameControllerGetJoystick", vp, [vp])
        f(L, "SDL_GameControllerAddMapping", ci, [cp])
        f(L, "SDL_JoystickOpen", vp, [ci])
        f(L, "SDL_JoystickInstanceID", ci, [vp])
        f(L, "SDL_JoystickGetDeviceInstanceID", ci, [ci])

        f(T, "TTF_Init", ci, [])
        f(T, "TTF_Quit", None, [])
        f(T, "TTF_OpenFont", vp, [cp, ci])
        f(T, "TTF_CloseFont", None, [vp])
        f(T, "TTF_RenderUTF8_Blended", vp, [vp, cp, SDL_Color])
        f(T, "TTF_SizeUTF8", ci, [vp, cp, PI, PI])
        f(T, "TTF_FontHeight", ci, [vp])
        f(T, "TTF_FontLineSkip", ci, [vp])
        f(T, "TTF_GlyphIsProvided", ci, [vp, ctypes.c_uint16])


# Mã sự kiện SDL2
EV_QUIT = 0x100
EV_KEYDOWN, EV_KEYUP = 0x300, 0x301
EV_JAXIS, EV_JHAT, EV_JBDOWN, EV_JBUP, EV_JADDED = 0x600, 0x602, 0x603, 0x604, 0x605
EV_CAXIS, EV_CBDOWN, EV_CBUP, EV_CADDED = 0x650, 0x651, 0x652, 0x653

# Nút GameController -> hành động
CB_MAP = {0: "A", 1: "B", 2: "X", 3: "Y", 4: "SELECT", 5: "MENU", 6: "START",
          9: "L1", 10: "R1", 11: "UP", 12: "DOWN", 13: "LEFT", 14: "RIGHT"}

# Bàn phím (để thử trên PC)
KEY_MAP = {
    0x40000052: "UP", 0x40000051: "DOWN", 0x40000050: "LEFT", 0x4000004F: "RIGHT",
    13: "A", 8: "B", 27: "B", ord("x"): "X", ord("y"): "Y", ord("q"): "L1", ord("e"): "R1",
    ord("s"): "SELECT", ord("t"): "START", 0x4000004A: "UP", 0x4000004D: "DOWN",
    0x4000004B: "LEFT", 0x4000004E: "RIGHT", ord("m"): "MENU",
}

REPEATABLE = {"UP", "DOWN", "LEFT", "RIGHT"}

THEMES = {
    "dark": {
        "bg": (20, 22, 26), "panel": (32, 35, 42), "sel": (52, 82, 140), "text": (232, 234, 238),
        "dim": (150, 156, 168), "read": (120, 125, 135), "accent": (255, 196, 64),
        "head": (14, 16, 20), "err": (255, 120, 110), "line": (55, 60, 70),
    },
    "light": {
        "bg": (246, 242, 232), "panel": (232, 226, 212), "sel": (196, 214, 245), "text": (28, 28, 30),
        "dim": (105, 100, 92), "read": (140, 136, 128), "accent": (176, 60, 30),
        "head": (225, 218, 200), "err": (190, 40, 30), "line": (205, 198, 182),
    },
}

READER_SIZES = [18, 20, 22, 24, 27]


class Gfx:
    """Lớp vẽ đơn giản: chữ (có cache texture), hình chữ nhật."""

    def __init__(self, sdl, ren):
        self.s, self.ren = sdl, ren
        self.fonts = {}
        self.tex = OrderedDict()
        self.measure_cache = OrderedDict()
        self.glyph_ok = {}
        self.reg = os.path.join(APP_DIR, "font", "BeVietnamPro-Regular.ttf")
        self.bold = os.path.join(APP_DIR, "font", "BeVietnamPro-Bold.ttf")
        if not os.path.exists(self.bold):
            self.bold = self.reg

    def font(self, size, bold=False):
        k = (size, bold)
        if k not in self.fonts:
            f = self.s.TTF_OpenFont((self.bold if bold else self.reg).encode(), size)
            if not f:
                raise RuntimeError("Không mở được font: " + self.s.SDL_GetError().decode(errors="replace"))
            self.fonts[k] = f
        return self.fonts[k]

    def line_h(self, size, bold=False):
        return self.s.TTF_FontLineSkip(self.font(size, bold))

    def measure(self, size, bold, text):
        k = (size, bold, text)
        v = self.measure_cache.get(k)
        if v is not None:
            return v
        w, hh = ctypes.c_int(), ctypes.c_int()
        self.s.TTF_SizeUTF8(self.font(size, bold), text.encode("utf-8"), ctypes.byref(w), ctypes.byref(hh))
        v = w.value
        self.measure_cache[k] = v
        if len(self.measure_cache) > 8000:
            self.measure_cache.popitem(last=False)
        return v

    def fit(self, size, bold, text, max_w):
        if self.measure(size, bold, text) <= max_w:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.measure(size, bold, text[:mid].rstrip() + "…") <= max_w:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "…"

    def wrap(self, size, bold, text, max_w):
        lines, cur = [], ""
        for word in text.split(" "):
            if not word:
                continue
            cand = cur + " " + word if cur else word
            if self.measure(size, bold, cand) <= max_w:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            if self.measure(size, bold, word) <= max_w:
                cur = word
            else:  # từ quá dài (URL...) -> cắt theo ký tự
                cur = ""
                for ch in word:
                    if self.measure(size, bold, cur + ch) > max_w and cur:
                        lines.append(cur)
                        cur = ch
                    else:
                        cur += ch
        if cur:
            lines.append(cur)
        return lines

    def supported(self, text):
        """Thay ký tự font không có bằng khoảng trắng (tránh ô vuông)."""
        out = []
        for ch in text:
            ok = self.glyph_ok.get(ch)
            if ok is None:
                o = ord(ch)
                ok = o < 0x80 or (o <= 0xFFFF and bool(self.s.TTF_GlyphIsProvided(self.font(18), o)))
                self.glyph_ok[ch] = ok
            out.append(ch if ok else " ")
        return "".join(out)

    def text(self, size, bold, text, x, y, color, max_w=None, align="left"):
        if not text:
            return 0
        text = self.supported(text)
        if max_w is not None:
            text = self.fit(size, bold, text, max_w)
        k = (size, bold, text, color)
        e = self.tex.get(k)
        if e is None:
            surf = self.s.TTF_RenderUTF8_Blended(self.font(size, bold), text.encode("utf-8"), SDL_Color(*color, 255))
            if not surf:
                return 0
            t = self.s.SDL_CreateTextureFromSurface(self.ren, surf)
            self.s.SDL_FreeSurface(surf)
            w, hh = ctypes.c_int(), ctypes.c_int()
            self.s.SDL_QueryTexture(t, None, None, ctypes.byref(w), ctypes.byref(hh))
            e = (t, w.value, hh.value)
            self.tex[k] = e
            if len(self.tex) > 500:
                _, old = self.tex.popitem(last=False)
                self.s.SDL_DestroyTexture(old[0])
        else:
            self.tex.move_to_end(k)
        t, tw, th = e
        if align == "right":
            x -= tw
        elif align == "center":
            x -= tw // 2
        self.s.SDL_RenderCopy(self.ren, t, None, ctypes.byref(SDL_Rect(int(x), int(y), tw, th)))
        return tw

    def rect(self, x, y, w, hh, color, alpha=255):
        self.s.SDL_SetRenderDrawColor(self.ren, color[0], color[1], color[2], alpha)
        self.s.SDL_RenderFillRect(self.ren, ctypes.byref(SDL_Rect(int(x), int(y), int(w), int(hh))))


# ---------------------------------------------------------------------------
# Ứng dụng
# ---------------------------------------------------------------------------

class App:
    def __init__(self, sdl=None, ren=None, net=None):
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(os.path.join(CACHE_DIR, "feeds"), exist_ok=True)
        os.makedirs(os.path.join(CACHE_DIR, "articles"), exist_ok=True)
        self.cfg = dict(DEFAULT_CONFIG)
        user_cfg = load_json(os.path.join(APP_DIR, "config.json"), {})
        if isinstance(user_cfg, dict):
            self.cfg.update(user_cfg)
        self.sources = load_json(os.path.join(APP_DIR, "sources.json"), {}).get("sources", [])
        self.settings = load_json(os.path.join(DATA_DIR, "settings.json"), {"theme": "dark", "size": 1})
        self.bookmarks = load_json(os.path.join(DATA_DIR, "bookmarks.json"), [])
        self.read = set(load_json(os.path.join(DATA_DIR, "read.json"), []))
        self.sdl, self.ren = sdl, ren
        self.g = Gfx(sdl, ren) if sdl else None
        self.worker = Worker(net or Net(self.cfg))
        self.running = True
        self.toast = None  # (text, until_ms, is_err)
        self.debug = ""
        self.dirty = True
        # Ngăn xếp màn hình
        self.screen = "home"
        self.home_sel = 0
        self.home_top = 0
        self.src = None
        self.feed_idx = 0
        self.feed_state = {}  # url -> dict(items, sel, top, err, fetched)
        self.reader = None    # dict(item, lines, scroll, size, loading, err)

    # ---- tiện ích ------------------------------------------------------
    @property
    def th(self):
        return THEMES.get(self.settings.get("theme"), THEMES["dark"])

    def now_ms(self):
        return self.sdl.SDL_GetTicks() if self.sdl else int(time.time() * 1000)

    def show_toast(self, text, err=False, ms=2500):
        self.toast = (text, self.now_ms() + ms, err)
        self.dirty = True

    def fmt_time(self, ts):
        if not ts:
            return ""
        t = time.gmtime(ts + self.cfg["utc_offset_hours"] * 3600)
        now = time.gmtime(time.time() + self.cfg["utc_offset_hours"] * 3600)
        if t.tm_yday == now.tm_yday and t.tm_year == now.tm_year:
            return time.strftime("%H:%M", t)
        return time.strftime("%H:%M %d/%m", t)

    def save_state(self):
        save_json(os.path.join(DATA_DIR, "settings.json"), self.settings)
        save_json(os.path.join(DATA_DIR, "bookmarks.json"), self.bookmarks)
        save_json(os.path.join(DATA_DIR, "read.json"), list(self.read)[-3000:])

    def is_bookmarked(self, item):
        return any(b["id"] == item["id"] for b in self.bookmarks)

    def toggle_bookmark(self, item):
        if self.is_bookmarked(item):
            self.bookmarks = [b for b in self.bookmarks if b["id"] != item["id"]]
            self.show_toast("Đã bỏ lưu")
        else:
            b = {k: v for k, v in item.items() if k != "paras"}
            self.bookmarks.insert(0, b)
            # lưu luôn nội dung nếu đã có để đọc offline
            self.show_toast("Đã lưu bài — đọc được cả khi không có mạng")
        self.save_state()

    # ---- dữ liệu chuyên mục -------------------------------------------
    def home_entries(self):
        ent = [{"kind": "saved", "name": "Bài đã lưu", "desc": "%d bài — đọc được khi không có mạng" % len(self.bookmarks)}]
        for s in self.sources:
            ent.append({"kind": "src", "name": s.get("name", "?"), "desc": s.get("desc", ""), "src": s})
        return ent

    def feeds(self):
        if self.src == "saved":
            return [{"name": "Bài đã lưu", "url": "__saved__"}]
        return self.src.get("feeds", []) if self.src else []

    def cur_feed(self):
        f = self.feeds()
        return f[self.feed_idx] if f else None

    def fstate(self, url):
        st = self.feed_state.get(url)
        if st is None:
            cached = load_json(os.path.join(CACHE_DIR, "feeds", h(url) + ".json"), None)
            st = {"items": [], "sel": 0, "top": 0, "err": None, "fetched": 0}
            if cached:
                st["items"] = cached.get("items", [])
                st["fetched"] = cached.get("fetched", 0)
            self.feed_state[url] = st
        return st

    def items(self):
        f = self.cur_feed()
        if not f:
            return []
        if f["url"] == "__saved__":
            return self.bookmarks
        return self.fstate(f["url"])["items"]

    def open_feed(self, force=False):
        f = self.cur_feed()
        if not f or f["url"] == "__saved__":
            return
        st = self.fstate(f["url"])
        age = time.time() - st["fetched"]
        if force or not st["items"] or age > self.cfg["refresh_minutes"] * 60:
            st["err"] = None
            self.worker.submit("feed", f["url"], source=self.src.get("name", ""), feed=f)
        self.dirty = True

    # ---- đọc bài -------------------------------------------------------
    def open_article(self, item, force=False):
        size = READER_SIZES[self.settings.get("size", 1) % len(READER_SIZES)]
        self.reader = {"item": item, "paras": None, "lines": None, "scroll": 0,
                       "size": size, "loading": False, "err": None}
        self.read.add(item["id"])
        cpath = os.path.join(CACHE_DIR, "articles", h(item["link"]) + ".json")
        paras = None if force else (item.get("paras") or load_json(cpath, None))
        if paras:
            self.reader["paras"] = [tuple(p) for p in paras]
        else:
            self.reader["loading"] = True
            self.worker.submit("article", item["link"])
        self.screen = "reader"
        self.layout_reader()
        self.save_state()

    def layout_reader(self):
        r = self.reader
        if not r or not self.g:
            return
        g, th = self.g, self.th
        size = r["size"]
        maxw = W - 2 * 22 - 8
        lines = []  # (size, bold, text, colorkey, y)
        y = 14

        def add(sz, bold, text, ck, gap_after):
            nonlocal y
            lh = g.line_h(sz, bold)
            for ln in g.wrap(sz, bold, text, maxw):
                lines.append((sz, bold, ln, ck, y))
                y += lh
            y += gap_after

        it = r["item"]
        add(size + 5, True, it["title"], "text", 6)
        meta = " · ".join(x for x in [it.get("source", ""), self.fmt_time(it.get("ts", 0))] if x)
        add(max(14, size - 4), False, meta, "accent", 14)
        paras = r["paras"]
        if it.get("summary") and not (paras and paras[0][1][:40] == it["summary"][:40]):
            add(size, True, it["summary"], "text", 14)
        if r["loading"]:
            add(size, False, "Đang tải nội dung bài viết…", "dim", 10)
        elif r["err"]:
            add(size, False, r["err"], "err", 8)
            add(max(14, size - 3), False, "Nhấn X để thử lại. Bạn vẫn có thể đọc tóm tắt ở trên.", "dim", 10)
        elif paras is not None and not paras:
            add(max(14, size - 3), False, "(Không trích được toàn văn — trang có thể dùng định dạng đặc biệt. Nội dung tóm tắt ở trên.)", "dim", 10)
        for kind, text in (paras or []):
            if kind == "h":
                add(size + 1, True, text, "text", 10)
            else:
                add(size, False, text, "text", int(size * 0.7))
        add(14, False, it["link"], "dim", 20)
        r["lines"] = lines
        r["height"] = y
        self.dirty = True

    def reader_view_h(self):
        return H - HEADER_H - FOOTER_H

    def scroll_reader(self, dy):
        r = self.reader
        maxs = max(0, r["height"] - self.reader_view_h())
        r["scroll"] = max(0, min(maxs, r["scroll"] + dy))
        self.dirty = True

    # ---- xử lý kết quả nền --------------------------------------------
    def poll_results(self):
        while True:
            try:
                kind, key, res, err = self.worker.results.get_nowait()
            except queue.Empty:
                break
            self.dirty = True
            if kind == "feed":
                st = self.fstate(key)
                if err:
                    st["err"] = err
                    self.show_toast(err, err=True, ms=4000)
                else:
                    res.sort(key=lambda x: x.get("ts", 0), reverse=True)
                    old_id = st["items"][st["sel"]]["id"] if st["items"] and st["sel"] < len(st["items"]) else None
                    st["items"], st["err"], st["fetched"] = res, None, time.time()
                    st["sel"], st["top"] = 0, 0
                    if old_id:
                        for i, it in enumerate(res):
                            if it["id"] == old_id:
                                st["sel"] = i
                                break
                    save_json(os.path.join(CACHE_DIR, "feeds", h(key) + ".json"),
                              {"items": res, "fetched": st["fetched"]})
            elif kind == "article":
                if res:
                    save_json(os.path.join(CACHE_DIR, "articles", h(key) + ".json"), res)
                r = self.reader
                if r and r["item"]["link"] == key:
                    r["loading"] = False
                    if err:
                        r["err"] = err
                    else:
                        r["paras"] = [tuple(p) for p in (res or [])]
                    keep = r["scroll"]
                    self.layout_reader()
                    r["scroll"] = keep

    # ---- điều khiển ----------------------------------------------------
    def list_move(self, sel, top, n, delta, visible):
        if n == 0:
            return 0, 0
        sel = max(0, min(n - 1, sel + delta))
        if sel < top:
            top = sel
        elif sel >= top + visible:
            top = sel - visible + 1
        return sel, top

    HOME_ROW = 58
    FEED_ROW = 75
    TAB_H = 34

    def home_visible(self):
        return (H - HEADER_H - FOOTER_H) // self.HOME_ROW

    def feed_visible(self):
        return (H - HEADER_H - FOOTER_H - self.TAB_H) // self.FEED_ROW

    def handle(self, act):
        self.dirty = True
        if act == "MENU":
            self.running = False
            return
        if act == "START":
            self.settings["theme"] = "light" if self.settings.get("theme") == "dark" else "dark"
            self.g and self.layout_reader()
            self.save_state()
            return
        if act == "SELECT":
            self.settings["size"] = (self.settings.get("size", 1) + 1) % len(READER_SIZES)
            self.save_state()
            if self.screen == "reader":
                r = self.reader
                frac = r["scroll"] / max(1, r["height"])
                r["size"] = READER_SIZES[self.settings["size"]]
                self.layout_reader()
                r["scroll"] = int(frac * r["height"])
                self.scroll_reader(0)
            self.show_toast("Cỡ chữ khi đọc: %d" % READER_SIZES[self.settings["size"]], ms=1200)
            return

        if self.screen == "home":
            ent = self.home_entries()
            vis = self.home_visible()
            if act in ("UP", "DOWN", "LEFT", "RIGHT"):
                d = {"UP": -1, "DOWN": 1, "LEFT": -vis, "RIGHT": vis}[act]
                self.home_sel, self.home_top = self.list_move(self.home_sel, self.home_top, len(ent), d, vis)
            elif act == "A" and ent:
                e = ent[self.home_sel]
                self.src = "saved" if e["kind"] == "saved" else e["src"]
                self.feed_idx = 0
                self.screen = "feed"
                self.open_feed()
            elif act == "B":
                self.running = False

        elif self.screen == "feed":
            items = self.items()
            f = self.cur_feed()
            if f["url"] == "__saved__":
                st = self.feed_state.setdefault("__saved__", {"sel": 0, "top": 0})
            else:
                st = self.fstate(f["url"])
            vis = self.feed_visible()
            if act in ("UP", "DOWN", "LEFT", "RIGHT"):
                d = {"UP": -1, "DOWN": 1, "LEFT": -vis, "RIGHT": vis}[act]
                st["sel"], st["top"] = self.list_move(st["sel"], st["top"], len(items), d, vis)
            elif act in ("L1", "R1"):
                n = len(self.feeds())
                if n > 1:
                    self.feed_idx = (self.feed_idx + (1 if act == "R1" else -1)) % n
                    self.open_feed()
            elif act == "X":
                if f["url"] != "__saved__":
                    self.open_feed(force=True)
                    self.show_toast("Đang tải lại…", ms=1200)
            elif act == "Y" and items:
                self.toggle_bookmark(items[min(st["sel"], len(items) - 1)])
                if f["url"] == "__saved__":
                    st["sel"], st["top"] = self.list_move(st["sel"], st["top"], len(self.bookmarks), 0, vis)
            elif act == "A" and items:
                self.open_article(items[min(st["sel"], len(items) - 1)])
            elif act == "B":
                self.screen = "home"

        elif self.screen == "reader":
            r = self.reader
            lh = self.g.line_h(r["size"]) if self.g else 24
            page = self.reader_view_h() - lh * 2
            if act == "UP":
                self.scroll_reader(-lh)
            elif act == "DOWN":
                self.scroll_reader(lh)
            elif act == "LEFT":
                self.scroll_reader(-page)
            elif act == "RIGHT":
                self.scroll_reader(page)
            elif act in ("L1", "R1"):
                items = self.items()
                ids = [i["id"] for i in items]
                if r["item"]["id"] in ids:
                    i = ids.index(r["item"]["id"]) + (1 if act == "R1" else -1)
                    if 0 <= i < len(items):
                        f = self.cur_feed()
                        st = self.feed_state.get(f["url"]) if f else None
                        if st is not None:
                            st["sel"], st["top"] = self.list_move(i, st["top"], len(items), 0, self.feed_visible())
                        self.open_article(items[i])
                    else:
                        self.show_toast("Hết danh sách", ms=1000)
            elif act == "X":
                self.open_article(r["item"], force=True)
            elif act == "Y":
                self.toggle_bookmark(r["item"])
            elif act == "B":
                self.screen = "feed"

    # ---- vẽ ------------------------------------------------------------
    def draw(self):
        g, th = self.g, self.th
        s = self.sdl
        s.SDL_SetRenderDrawColor(self.ren, *th["bg"], 255)
        s.SDL_RenderClear(self.ren)
        if self.screen == "home":
            self.draw_home()
            title = "Tin Tức"
            hints = "A Mở   B Thoát   START Sáng/Tối   SELECT Cỡ chữ"
        elif self.screen == "feed":
            self.draw_feed()
            title = "Bài đã lưu" if self.src == "saved" else self.src.get("name", "")
            hints = "A Đọc  Y Lưu  X Tải lại  L1/R1 Chuyên mục  B Về"
        else:
            self.draw_reader()
            title = self.reader["item"].get("source", "") or "Đọc bài"
            hints = "Lên/Xuống Cuộn  Trái/Phải Trang  L1/R1 Bài khác  Y Lưu  B Về"
        # Header
        g.rect(0, 0, W, HEADER_H, th["head"])
        g.text(22, True, title, 14, 6, th["accent"], max_w=400)
        clock = time.strftime("%H:%M", time.gmtime(time.time() + self.cfg["utc_offset_hours"] * 3600))
        right = W - 14
        g.text(18, True, clock, right, 9, th["text"], align="right")
        if self.worker.busy():
            dots = "." * (1 + (self.now_ms() // 300) % 3)
            g.text(15, False, "Đang tải" + dots, right - 70, 11, th["dim"], align="right")
        # Footer
        g.rect(0, H - FOOTER_H, W, FOOTER_H, th["head"])
        if self.debug and self.cfg.get("debug_input"):
            g.text(14, False, self.debug, 12, H - FOOTER_H + 6, th["err"])
        else:
            corner = ""
            if self.screen == "reader":
                corner = "%d%%" % self.reader.get("pct", 0)
            elif self.screen == "feed" and self.items():
                f = self.cur_feed()
                st = self.feed_state.get("__saved__" if f["url"] == "__saved__" else f["url"], {"sel": 0})
                corner = "%d/%d" % (min(st["sel"], len(self.items()) - 1) + 1, len(self.items()))
            cw = g.text(14, True, corner, W - 12, H - FOOTER_H + 6, th["accent"], align="right") if corner else 0
            g.text(14, False, hints, 12, H - FOOTER_H + 6, th["dim"], max_w=W - 36 - cw)
        # Toast
        if self.toast and self.now_ms() < self.toast[1]:
            txt = self.toast[0]
            tw = min(W - 40, g.measure(17, True, txt) + 28)
            x = (W - tw) // 2
            y = H - FOOTER_H - 52
            g.rect(x, y, tw, 38, th["panel"])
            g.rect(x, y, 4, 38, th["err"] if self.toast[2] else th["accent"])
            g.text(17, True, txt, W // 2, y + 8, th["err"] if self.toast[2] else th["text"],
                   max_w=tw - 24, align="center")
        elif self.toast:
            self.toast = None
        s.SDL_RenderPresent(self.ren)

    def draw_scrollbar(self, y0, hgt, pos, total, view):
        if total <= view:
            return
        th = self.th
        self.g.rect(W - 6, y0, 4, hgt, th["line"])
        bh = max(20, int(hgt * view / total))
        by = y0 + int((hgt - bh) * pos / max(1, total - view))
        self.g.rect(W - 6, by, 4, bh, th["accent"])

    def draw_home(self):
        g, th = self.g, self.th
        ent = self.home_entries()
        vis = self.home_visible()
        y = HEADER_H
        for i in range(self.home_top, min(len(ent), self.home_top + vis)):
            e = ent[i]
            if i == self.home_sel:
                g.rect(0, y, W, self.HOME_ROW, th["sel"])
                g.rect(0, y, 5, self.HOME_ROW, th["accent"])
            g.text(21, True, e["name"], 22, y + 7, th["accent"] if e["kind"] == "saved" else th["text"], max_w=W - 50)
            g.text(15, False, e["desc"], 22, y + 34, th["dim"], max_w=W - 50)
            g.rect(16, y + self.HOME_ROW - 1, W - 32, 1, th["line"])
            y += self.HOME_ROW
        self.draw_scrollbar(HEADER_H, H - HEADER_H - FOOTER_H, self.home_top, len(ent), vis)

    def draw_feed(self):
        g, th = self.g, self.th
        feeds = self.feeds()
        # Thanh chuyên mục
        y0 = HEADER_H
        g.rect(0, y0, W, self.TAB_H, th["panel"])
        widths = [g.measure(16, True, f["name"]) + 26 for f in feeds]
        x = 10
        start = 0
        total_to_cur = sum(widths[: self.feed_idx + 1]) + 10
        if total_to_cur > W - 20:
            acc = total_to_cur
            while acc > W - 20 and start < self.feed_idx:
                acc -= widths[start]
                start += 1
        for i in range(start, len(feeds)):
            if x > W:
                break
            wdt = widths[i]
            if i == self.feed_idx:
                g.rect(x, y0 + 4, wdt, self.TAB_H - 8, th["sel"])
                g.rect(x, y0 + self.TAB_H - 4, wdt, 3, th["accent"])
            g.text(16, True, feeds[i]["name"], x + 13, y0 + 7,
                   th["text"] if i == self.feed_idx else th["dim"])
            x += wdt
        # Danh sách bài
        f = self.cur_feed()
        items = self.items()
        st = self.feed_state.get("__saved__", {"sel": 0, "top": 0}) if f["url"] == "__saved__" else self.fstate(f["url"])
        top_y = HEADER_H + self.TAB_H
        if not items:
            if f["url"] == "__saved__":
                msg, ck = "Chưa có bài nào. Nhấn Y khi xem danh sách hoặc đang đọc để lưu.", "dim"
            elif st.get("err"):
                msg, ck = st["err"], "err"
            else:
                msg, ck = "Đang tải tin…", "dim"
            yy = top_y + 60
            for ln in g.wrap(19, False, msg, W - 80):
                g.text(19, False, ln, W // 2, yy, th[ck], align="center")
                yy += g.line_h(19)
            if ck == "err":
                g.text(15, False, "Nhấn X để thử lại", W // 2, yy + 10, th["dim"], align="center")
            return
        vis = self.feed_visible()
        st["sel"] = min(st["sel"], len(items) - 1)
        y = top_y
        tw = W - 44
        for i in range(st["top"], min(len(items), st["top"] + vis)):
            it = items[i]
            sel = i == st["sel"]
            if sel:
                g.rect(0, y, W, self.FEED_ROW, th["sel"])
                g.rect(0, y, 5, self.FEED_ROW, th["accent"])
            read = it["id"] in self.read
            col = th["read"] if (read and not sel) else th["text"]
            lines = g.wrap(18, True, it["title"], tw)
            if len(lines) > 2:
                lines = [lines[0], g.fit(18, True, " ".join(lines[1:]), tw)]
            ly = y + 6
            for ln in lines:
                g.text(18, True, ln, 20, ly, col)
                ly += 24
            meta = self.fmt_time(it.get("ts", 0))
            if self.src == "saved":
                meta = (it.get("source", "") + " · " + meta).strip(" ·")
            mx = 20
            if self.is_bookmarked(it):
                g.rect(mx, y + self.FEED_ROW - 18, 8, 10, th["accent"])
                mx += 8 + g.text(14, True, " Đã lưu ·", mx + 8, y + self.FEED_ROW - 22, th["accent"]) + 4
            g.text(14, False, meta, mx, y + self.FEED_ROW - 22, th["accent"] if sel else th["dim"])
            g.rect(16, y + self.FEED_ROW - 1, W - 32, 1, th["line"])
            y += self.FEED_ROW
        self.draw_scrollbar(top_y, H - top_y - FOOTER_H, st["top"], len(items), vis)

    def draw_reader(self):
        g, th = self.g, self.th
        r = self.reader
        if r["lines"] is None:
            self.layout_reader()
        y0 = HEADER_H
        vh = self.reader_view_h()
        sc = r["scroll"]
        for (sz, bold, text, ck, y) in r["lines"]:
            yy = y - sc
            if yy + 40 < 0:
                continue
            if yy + sz * 1.25 > vh:  # không vẽ dòng bị cắt ở chân màn hình
                break
            if yy < -2:
                continue
            g.text(sz, bold, text, 22, y0 + yy, th[ck])
        # che phần tràn lên header
        self.draw_scrollbar(y0, vh, sc, r["height"], vh)
        r["pct"] = int(100 * min(1.0, (sc + vh) / max(1, r["height"])))

    # ---- vòng lặp chính -----------------------------------------------
    def screenshot(self, path):
        surf = self.sdl.SDL_CreateRGBSurfaceWithFormat(0, W, H, 32, 0x16362004)  # ARGB8888
        # pixels nằm ở offset 32 trong SDL_Surface (64-bit), pitch ở 24
        pitch = ctypes.c_int.from_address(surf + 24).value
        pixels = ctypes.c_void_p.from_address(surf + 32).value
        self.sdl.SDL_RenderReadPixels(self.ren, None, 0x16362004, pixels, pitch)
        self.sdl.SDL_SaveBMP_RW(surf, self.sdl.SDL_RWFromFile(path.encode(), b"wb"), 1)
        self.sdl.SDL_FreeSurface(surf)


def run():
    log("=== khởi động ===")
    sdl = SDL()
    sdl.SDL_SetHint(b"SDL_RENDER_SCALE_QUALITY", b"1")
    sdl.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
    INIT_VIDEO, INIT_JOY, INIT_GC = 0x20, 0x200, 0x2000
    if sdl.SDL_Init(INIT_VIDEO | INIT_JOY | INIT_GC) != 0:
        raise RuntimeError("SDL_Init: " + sdl.SDL_GetError().decode(errors="replace"))
    if sdl.TTF_Init() != 0:
        raise RuntimeError("TTF_Init lỗi")

    # Nạp thêm mapping tay cầm nếu có
    dbp = os.path.join(APP_DIR, "gamecontrollerdb.txt")
    if os.path.exists(dbp):
        for line in open(dbp, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if line and not line.startswith("#"):
                sdl.SDL_GameControllerAddMapping(line.encode())

    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_json(os.path.join(APP_DIR, "config.json"), {}) or {})
    windowed = os.environ.get("TINTUC_WINDOWED") == "1" or not cfg.get("fullscreen", True)
    flags = 0x4 if windowed else 0x1001  # SHOWN | FULLSCREEN_DESKTOP
    win = sdl.SDL_CreateWindow("Tin Tuc".encode(), 0x2FFF0000, 0x2FFF0000, W, H, flags)
    if not win:
        raise RuntimeError("CreateWindow: " + sdl.SDL_GetError().decode(errors="replace"))
    ren = sdl.SDL_CreateRenderer(win, -1, 0x2 | 0x4)  # ACCELERATED | PRESENTVSYNC
    if not ren:
        ren = sdl.SDL_CreateRenderer(win, -1, 0x1)    # SOFTWARE
    sdl.SDL_RenderSetLogicalSize(ren, W, H)
    sdl.SDL_SetRenderDrawBlendMode(ren, 1)
    sdl.SDL_ShowCursor(0)

    app = App(sdl, ren)
    swap = app.cfg.get("swap_ab")
    raw_map = {v: k for k, v in (app.cfg.get("raw_buttons") or {}).items()}
    controllers = {}   # instance_id -> handle
    joysticks = {}

    def open_devices():
        for i in range(sdl.SDL_NumJoysticks()):
            iid = sdl.SDL_JoystickGetDeviceInstanceID(i)
            if iid in controllers or iid in joysticks:
                continue
            if sdl.SDL_IsGameController(i):
                c = sdl.SDL_GameControllerOpen(i)
                if c:
                    controllers[iid] = c
                    log("Mở GameController", i, iid)
                    continue
            j = sdl.SDL_JoystickOpen(i)
            if j:
                joysticks[iid] = j
                log("Mở Joystick (raw)", i, iid)

    open_devices()

    held = {}           # action -> (pressed_ms, next_repeat_ms)
    axis_state = {}     # (src, which, axis) -> action or None
    hat_state = {}
    ev = ctypes.create_string_buffer(64)
    u32 = lambda o: int.from_bytes(ev.raw[o:o + 4], "little")
    i32 = lambda o: int.from_bytes(ev.raw[o:o + 4], "little", signed=True)
    u8 = lambda o: ev.raw[o]
    i16 = lambda o: int.from_bytes(ev.raw[o:o + 2], "little", signed=True)
    combo = set()

    def press(act):
        if not act:
            return
        if swap and act in ("A", "B"):
            act = "B" if act == "A" else "A"
        combo.add(act)
        if {"SELECT", "START"} <= combo:
            app.running = False
            return
        now = sdl.SDL_GetTicks()
        if act in REPEATABLE:
            held[act] = (now, now + 380)
        app.handle(act)

    def release(act):
        if swap and act in ("A", "B"):
            act = "B" if act == "A" else "A"
        held.pop(act, None)
        combo.discard(act)

    def axis_dir(key, value, neg, pos):
        prev = axis_state.get(key)
        cur = neg if value < -16000 else pos if value > 16000 else None
        if cur != prev:
            if prev:
                release(prev)
            if cur:
                press(cur)
            axis_state[key] = cur

    HAT = {1: "UP", 2: "RIGHT", 4: "DOWN", 8: "LEFT"}
    last_frame = 0
    while app.running:
        while sdl.SDL_PollEvent(ev):
            t = u32(0)
            if t == EV_QUIT:
                app.running = False
            elif t == EV_KEYDOWN:
                if u8(13) == 0:  # bỏ qua auto-repeat của hệ điều hành
                    press(KEY_MAP.get(i32(20)))
            elif t == EV_KEYUP:
                a = KEY_MAP.get(i32(20))
                a and release(a)
            elif t in (EV_CBDOWN, EV_CBUP):
                b = u8(12)
                app.debug = "GC nút %d" % b
                a = CB_MAP.get(b)
                if a:
                    press(a) if t == EV_CBDOWN else release(a)
            elif t == EV_CAXIS:
                axis, val = u8(12), i16(16)
                which = i32(8)
                if axis in (4, 5):  # L2 / R2
                    k = ("c", which, axis)
                    on = val > 16000
                    act = "L2" if axis == 4 else "R2"
                    if on and not axis_state.get(k):
                        press(act)
                    elif not on and axis_state.get(k):
                        release(act)
                    axis_state[k] = act if on else None
                elif axis == 0:
                    axis_dir(("c", which, 0), val, "LEFT", "RIGHT")
                elif axis == 1:
                    axis_dir(("c", which, 1), val, "UP", "DOWN")
            elif t in (EV_JBDOWN, EV_JBUP):
                which, b = i32(8), u8(12)
                if which in controllers:
                    continue
                app.debug = "Joystick nút %d" % b
                a = raw_map.get(b)
                if a:
                    press(a) if t == EV_JBDOWN else release(a)
            elif t == EV_JHAT:
                which, val = i32(8), u8(13)
                if which in controllers:
                    continue
                prev = hat_state.get(which, 0)
                for bit, a in HAT.items():
                    if (val & bit) and not (prev & bit):
                        press(a)
                    elif (prev & bit) and not (val & bit):
                        release(a)
                hat_state[which] = val
            elif t == EV_JAXIS:
                which, axis, val = i32(8), u8(12), i16(16)
                if which in controllers or axis > 1:
                    continue
                if axis == 0:
                    axis_dir(("j", which, 0), val, "LEFT", "RIGHT")
                else:
                    axis_dir(("j", which, 1), val, "UP", "DOWN")
            elif t in (EV_JADDED, EV_CADDED):
                open_devices()

        now = sdl.SDL_GetTicks()
        for act, (t0, nxt) in list(held.items()):
            if now >= nxt:
                held[act] = (t0, now + (45 if app.screen == "reader" else 75))
                app.handle(act)

        app.poll_results()
        busy = app.worker.busy()
        if app.dirty or busy or app.toast or now - last_frame > 1000:
            app.draw()
            app.dirty = False
            last_frame = now
            sdl.SDL_Delay(8 if held else 25)  # nhẹ CPU, đỡ tốn pin
        else:
            sdl.SDL_Delay(16)

    app.save_state()
    sdl.TTF_Quit()
    sdl.SDL_DestroyRenderer(ren)
    sdl.SDL_DestroyWindow(win)
    sdl.SDL_Quit()
    log("=== thoát ===")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        log(traceback.format_exc())
        raise
