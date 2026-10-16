# -*- coding: utf-8 -*-
"""MemWise 更新检查与下载（**可选功能**；不开启则一行网络代码都不会执行）。

设计定稿（2026-10-16，用户逐项拍定）：
- **默认不联网**：仅当用户开启 `update_check` 后，本模块才会发起请求。
- 传输用 **WinHTTP + ctypes**：零第三方依赖，且不引入 ssl/http/urllib/email/xml
  （这些都在 MemWise.spec 的 excludes 里）；系统 TLS **证书校验默认开启**，默认自动使用
  系统代理，另可配置自定义代理。实测（本机）：HEAD 3.5s、API 0.5s、资产大小与线上逐字节一致。
- **双通道降级**：
    主 API  `/releases/latest` → tag + 资产 size + **digest(sha256)** + 更新说明（限流 60/时，7 天一次足够）
    降 HEAD `/releases/latest`  → 从最终 URL 的 `/releases/tag/vX.Y.Z` 解析 tag（无哈希 ⇒ 只提示不自动装）
- **校验**：下载后比对 SHA-256 与文件大小，任一不符即丢弃（HTTPS 只保证链路，哈希锚定发布时刻）。
- **版本比较**：`v4.7.026` → (4,7,26) 数值元组；解析失败或本地≥远端 ⇒ 不更新（兼容开发态）。
- 所有失败都返回**结构化原因**，UI 据此降级为"提示 + 打开发布页"。
"""
import ctypes, ctypes.wintypes as w, hashlib, json, os, re, time

OWNER, REPO = "fuguangbeta", "MemWise"
ASSET_NAME = "MemWise.exe"
API_LATEST = "https://api.github.com/repos/%s/%s/releases/latest" % (OWNER, REPO)
HEAD_LATEST = "https://github.com/%s/%s/releases/latest" % (OWNER, REPO)
RELEASES_PAGE = "https://github.com/%s/%s/releases" % (OWNER, REPO)
UA = "MemWise-UpdateCheck/1.0"
TIMEOUT_CONNECT_MS = 8000
TIMEOUT_RECV_MS = 30000
STATE_NAME = "memwise_update.json"     # data/ 下的运行态（last_check / skip_version）

# ── WinHTTP 绑定（仅本模块使用）──
_wh = ctypes.WinDLL("winhttp")
_H = ctypes.c_void_p
_wh.WinHttpOpen.argtypes = [w.LPCWSTR, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD]; _wh.WinHttpOpen.restype = _H
_wh.WinHttpConnect.argtypes = [_H, w.LPCWSTR, w.WORD, w.DWORD]; _wh.WinHttpConnect.restype = _H
_wh.WinHttpOpenRequest.argtypes = [_H, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, ctypes.c_void_p, w.DWORD]
_wh.WinHttpOpenRequest.restype = _H
_wh.WinHttpSendRequest.argtypes = [_H, w.LPCWSTR, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, w.DWORD]
_wh.WinHttpReceiveResponse.argtypes = [_H, ctypes.c_void_p]
_wh.WinHttpQueryHeaders.argtypes = [_H, w.DWORD, w.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD)]
_wh.WinHttpQueryOption.argtypes = [_H, w.DWORD, ctypes.c_void_p, ctypes.POINTER(w.DWORD)]
_wh.WinHttpSetOption.argtypes = [_H, w.DWORD, ctypes.c_void_p, w.DWORD]
_wh.WinHttpSetTimeouts.argtypes = [_H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
_wh.WinHttpReadData.argtypes = [_H, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
_wh.WinHttpCloseHandle.argtypes = [_H]

ACCESS_DEFAULT_PROXY, ACCESS_NAMED_PROXY, ACCESS_AUTOMATIC_PROXY = 0, 3, 4
FLAG_SECURE = 0x00800000
OPT_REDIRECT_POLICY, OPT_URL = 88, 34
POL_ALWAYS = 2
Q_STATUS, Q_NUM, Q_CONTENT_LENGTH = 19, 0x20000000, 5
CHUNK = 64 * 1024


def _status(req):
    v = w.DWORD(0); s = w.DWORD(4); i = w.DWORD(0)
    return v.value if _wh.WinHttpQueryHeaders(req, Q_STATUS | Q_NUM, None, ctypes.byref(v), ctypes.byref(s), ctypes.byref(i)) else 0


def _final_url(req, n=4096):
    b = ctypes.create_unicode_buffer(n); s = w.DWORD(n * 2)
    return b.value if _wh.WinHttpQueryOption(req, OPT_URL, b, ctypes.byref(s)) else ""


def _normalize_proxy(p):
    """代理串归一（2026-10-16 侧视补）：WinHTTP 只接受 host:port，用户填 http://host:port/ 会失败。"""
    if not p:
        return None
    t = str(p).strip()
    if "://" in t:
        t = t.split("://", 1)[1]
    t = t.split("/", 1)[0].strip()
    return t or None


def _split(url):
    m = re.match(r"(https?)://([^/]+)(/.*)?$", url, re.I)
    if not m:
        return None
    host = m.group(2)
    if ":" in host:
        host, port = host.split(":", 1)
        port = int(port)
    else:
        port = 443 if m.group(1).lower() == "https" else 80
    return m.group(1).lower(), host, port, (m.group(3) or "/")


def _request(url, method="GET", proxy=None, want_body=False, on_chunk=None, cancel=None, max_bytes=None,
             headers=None, ok_statuses=(200,)):
    """单次请求。返回 (ok, status, body_bytes_or_empty, final_url, reason)。

    headers：额外请求头（分段下载用，如 Range）；ok_statuses：可接受的状态码（分段需 206）。
    """
    sp = _split(url)
    if not sp:
        return False, 0, b"", "", "bad_url"
    scheme, host, port, path = sp
    access = ACCESS_NAMED_PROXY if proxy else ACCESS_AUTOMATIC_PROXY
    sess = _wh.WinHttpOpen(UA, access, proxy or None, None, 0)
    if not sess:
        return False, 0, b"", "", "open_failed"
    req = conn = None
    try:
        _wh.WinHttpSetTimeouts(sess, TIMEOUT_CONNECT_MS, TIMEOUT_CONNECT_MS, TIMEOUT_RECV_MS, TIMEOUT_RECV_MS)
        conn = _wh.WinHttpConnect(sess, host, port, 0)
        if not conn:
            return False, 0, b"", "", "connect_failed"
        flags = FLAG_SECURE if scheme == "https" else 0
        req = _wh.WinHttpOpenRequest(conn, method, path, None, None, None, flags)
        if not req:
            return False, 0, b"", "", "request_failed"
        pol = w.DWORD(POL_ALWAYS)
        _wh.WinHttpSetOption(req, OPT_REDIRECT_POLICY, ctypes.byref(pol), 4)
        # 头参数是 LPCWSTR（宽字符）⇒ 传 str，长度按 UTF-16 字节数（2026-10-17 修：此前传 ASCII 字节，
        # 导致 Range 头实际未发出、分段下载静默退化为单连接）
        _hdr = None
        if headers:
            _hdr = "".join("%s: %s\r\n" % (k, v) for k, v in headers.items())
        if not _wh.WinHttpSendRequest(req, _hdr, len(_hdr) if _hdr else 0, None, 0, None, 0):
            return False, 0, b"", "", "send_failed"
        if not _wh.WinHttpReceiveResponse(req, None):
            return False, 0, b"", "", "recv_failed"
        st = _status(req)
        final = _final_url(req)
        if st not in ok_statuses:
            return False, st, b"", final, "http_%d" % st
        if not want_body:
            return True, st, b"", final, ""
        buf = ctypes.create_string_buffer(CHUNK)
        out = bytearray()
        got = w.DWORD(0)
        while True:
            if cancel is not None and cancel():
                return False, st, b"", final, "cancelled"
            if not _wh.WinHttpReadData(req, buf, CHUNK, ctypes.byref(got)) or got.value == 0:
                break
            chunk = buf.raw[:got.value]
            if on_chunk is not None:
                on_chunk(chunk)
            else:
                out += chunk
            if max_bytes is not None and len(out) > max_bytes:
                return False, st, b"", final, "too_large"
        return True, st, bytes(out), final, ""
    except Exception as e:
        return False, 0, b"", "", "exception:%s" % type(e).__name__
    finally:
        for h in (req, conn, sess):
            if h:
                try: _wh.WinHttpCloseHandle(h)
                except Exception: pass


# ── 版本比较（最全面/最不易错的口径）──
def parse_version(s):
    """'v4.7.026' / '4.7.26' / 'v4.7' → (4,7,26) / (4,7,0)。无法解析 ⇒ None。"""
    if not s:
        return None
    nums = re.findall(r"\d+", str(s))
    if not nums:
        return None
    try:
        parts = [int(x) for x in nums[:3]]
    except Exception:
        return None
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote, local):
    """远端是否比本地新（元组比较；任一侧解析失败 ⇒ False，宁可不更新）。"""
    r, l = parse_version(remote), parse_version(local)
    return bool(r and l and r > l)


def is_pe(path):
    """是否为 PE 可执行文件（MZ + PE\0\0 签名）。

    2026-10-16 真机测试补：只比对哈希还不够——若上游发布的资产本身是坏文件，哈希照样匹配，
    替换后 Windows 会弹「不支持的 16 位应用程序」而**进程仍存活**，助手的存活确认会被骗过。
    故"先验哈希、再验形态"，非 PE 直接丢弃，绝不进入替换环节。"""
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"MZ":
                return False
            f.seek(0x3C)
            off = int.from_bytes(f.read(4), "little")
            if off <= 0 or off > (1 << 20):
                return False
            f.seek(off)
            return f.read(4) == b"PE\0\0"
    except Exception:
        return False


def verify_file(path, sha256=None, size=None):
    """校验文件：大小必须匹配（若给出）；sha256 必须匹配（若给出）。返回 (ok, reason)。"""
    try:
        if size is not None and os.path.getsize(path) != int(size):
            return False, "size_mismatch"
        if sha256:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for blk in iter(lambda: f.read(1 << 20), b""):
                    h.update(blk)
            want = sha256.split(":", 1)[-1].strip().lower()
            if h.hexdigest() != want:
                return False, "sha256_mismatch"
        return True, ""
    except Exception as e:
        return False, "verify_error:%s" % type(e).__name__


def check_latest(proxy=None, notes_limit=400, api_url=None, head_url=None):
    """检查最新版本。返回结构化结果（永不抛异常）。

    api_url / head_url 仅供离线测试注入（默认走真实官方渠道）。

    {"ok":True,"source":"api"|"head","tag":..,"version":(4,7,26),"size":int|None,
     "sha256":str|None,"notes":str,"url":str|None,"page":RELEASES_PAGE}
    或 {"ok":False,"reason":str,"page":RELEASES_PAGE}
    """
    ok, st, body, final, why = _request(api_url or API_LATEST, proxy=_normalize_proxy(proxy), want_body=True, max_bytes=1 << 20)
    if ok:
        try:
            d = json.loads(body.decode("utf-8", "ignore"))
            tag = d.get("tag_name") or ""
            ver = parse_version(tag)
            if ver:
                size = sha = url = None
                for a in d.get("assets") or []:
                    if (a.get("name") or "").lower() == ASSET_NAME.lower():
                        size = a.get("size"); sha = a.get("digest"); url = a.get("browser_download_url")
                        break
                return {"ok": True, "source": "api", "tag": tag, "version": ver, "size": size,
                        "sha256": sha, "notes": (d.get("body") or "")[:notes_limit],
                        "url": url, "page": RELEASES_PAGE}
            why = "tag_unparsable"
        except Exception:
            why = "json_invalid"
    # 降级：HEAD /releases/latest（自动跟随重定向，最终 URL 含 /releases/tag/vX.Y.Z）
    ok2, st2, _b, final2, why2 = _request(head_url or HEAD_LATEST, method="HEAD", proxy=_normalize_proxy(proxy))
    if ok2:
        m = re.search(r"/releases/tag/([^/?#]+)", final2 or "")
        ver = parse_version(m.group(1)) if m else None
        if ver:
            return {"ok": True, "source": "head", "tag": m.group(1), "version": ver, "size": None,
                    "sha256": None, "notes": "", "url": None, "page": RELEASES_PAGE}
        why2 = "tag_unparsable"
    return {"ok": False, "reason": (why or why2 or "unknown"), "page": RELEASES_PAGE}


# ── 分段并发下载（2026-10-17）：安全优先——探测到 Range 支持才并发，任何异常/短读/取消
#    都由调用方回退到单连接路径；合并后仍走同一套 SHA-256 + 大小 + PE + 原子改名校验。──
_PARALLEL_MIN_BYTES = 2 << 20   # 小于 2MB 不值得并发（三段各自的固定开销抵不过收益）
_PARALLEL_WORKERS = 3           # 3 段：再多容易触发对端限速，收益反而下降


def _download_ranges(url, dest, total, proxy, progress, cancel):
    """分段并发下载到 dest。返回 (ok, reason)。

    reason="fallback" 表示"对端不支持或某段失败"（调用方应回退单连接）；
    reason="cancelled" 表示用户取消（调用方应终止，不要回退重试）。
    """
    import threading
    parts = []
    try:
        def _discard(_c):
            pass
        # 探测：只要 0-0 一字节。206 ⇒ 支持分段；200/其他 ⇒ 不支持（回退）
        okp, _st, _b, _u, whyp = _request(url, proxy=_normalize_proxy(proxy), want_body=True,
                                         on_chunk=_discard, cancel=cancel, max_bytes=2,
                                         headers={"Range": "bytes=0-0"}, ok_statuses=(206,))
        if not okp:
            return (False, "cancelled") if whyp == "cancelled" else (False, "fallback")
        step = max(1, total // _PARALLEL_WORKERS)
        done = [0]
        lock = threading.Lock()
        errs = []

        def _one(i, a, b):
            path = dest + ".p%d" % i
            parts.append(path)
            got = [0]
            try:
                with open(path, "wb") as pf:
                    def _cb(c, _pf=pf):
                        _pf.write(c)
                        got[0] += len(c)
                        with lock:
                            done[0] += len(c)
                            if progress is not None:
                                try: progress(done[0], total)
                                except Exception: pass
                    okr, _st2, _b2, _u2, whyr = _request(url, proxy=_normalize_proxy(proxy),
                                                         want_body=True, on_chunk=_cb, cancel=cancel,
                                                         max_bytes=(b - a + 1) + 65536,
                                                         headers={"Range": "bytes=%d-%d" % (a, b)},
                                                         ok_statuses=(206,))
                if not okr:
                    errs.append(whyr or "range_failed")
                elif got[0] != (b - a + 1):
                    errs.append("short_part")
            except Exception as e:
                errs.append("part_exc:%s" % type(e).__name__)

        ts = []
        for i in range(_PARALLEL_WORKERS):
            a = i * step
            b = (total - 1) if i == _PARALLEL_WORKERS - 1 else min(a + step - 1, total - 1)
            t = threading.Thread(target=_one, args=(i, a, b), daemon=True)
            t.start()
            ts.append(t)
        for t in ts:
            t.join()
        if errs:
            if any("cancel" in str(x) for x in errs):
                return False, "cancelled"
            return False, "fallback"
        with open(dest, "wb") as out:
            for i in range(_PARALLEL_WORKERS):
                with open(dest + ".p%d" % i, "rb") as pf:
                    shutil.copyfileobj(pf, out)
        return True, ""
    finally:
        for p in parts:
            try: os.remove(p)
            except Exception: pass

def download(url, dest, sha256=None, size=None, proxy=None, progress=None, cancel=None):
    """下载到 dest（内部先写 .part，校验通过后改名转正）。返回 (ok, reason)。

    progress(done, total) 每块回调一次；cancel() 返回 True 则中止。
    """
    tmp = dest + ".part"
    total = int(size) if size else 0
    done = [0]

    def _chunk(c):
        done[0] += len(c)
        f.write(c)
        if progress is not None:
            try: progress(done[0], total)
            except Exception: pass

    f = None
    try:
        try: os.remove(tmp)
        except Exception: pass
        # ① 优先尝试分段并发（≥2MB 且对端支持 Range）；不支持或失败 ⇒ ② 回退单连接（行为与原实现一致）
        _par = False
        if size and int(size) >= _PARALLEL_MIN_BYTES:
            try:
                _okp, _whyp = _download_ranges(url, tmp, int(size), proxy, progress, cancel)
            except Exception:
                _okp, _whyp = False, "fallback"
            if _okp:
                _par = True
            elif _whyp == "cancelled":
                try: os.remove(tmp)
                except Exception: pass
                return False, "cancelled"
        if not _par:
            f = open(tmp, "wb")
            # 已知大小 ⇒ 允许 1MB 余量作为硬上限（防"出错时无限拉取"或对端返回超大文件）
            _cap = (int(size) + (1 << 20)) if size else None
            ok, st, _b, _u, why = _request(url, proxy=_normalize_proxy(proxy), want_body=True,
                                           on_chunk=_chunk, cancel=cancel, max_bytes=_cap)
            f.close(); f = None
            if not ok:
                try: os.remove(tmp)
                except Exception: pass
                return False, why
        ok2, why2 = verify_file(tmp, sha256=sha256, size=size)
        if not ok2 and _par:
            # 分段结果校验不过（例如中间代理/加速器对 Range 处理异常）⇒ **再走一遍单连接**再判失败：
            # 无加速器的普通网络下宁可慢也不能失败（2026-10-17 用户要求）
            try: os.remove(tmp)
            except Exception: pass
            _par = False
            f = open(tmp, "wb")
            _cap = (int(size) + (1 << 20)) if size else None
            ok3, _st3, _b3, _u3, why3 = _request(url, proxy=_normalize_proxy(proxy), want_body=True,
                                                 on_chunk=_chunk, cancel=cancel, max_bytes=_cap)
            f.close(); f = None
            if not ok3:
                try: os.remove(tmp)
                except Exception: pass
                return False, why3
            ok2, why2 = verify_file(tmp, sha256=sha256, size=size)
        if not ok2:
            try: os.remove(tmp)
            except Exception: pass
            return False, why2
        if not is_pe(tmp):
            try: os.remove(tmp)
            except Exception: pass
            return False, "not_pe"
        try: os.remove(dest)
        except Exception: pass
        os.replace(tmp, dest)
        return True, ""
    except Exception as e:
        if f:
            try: f.close()
            except Exception: pass
        try: os.remove(tmp)
        except Exception: pass
        return False, "io_error:%s" % type(e).__name__


# ── 运行态（data/memwise_update.json）：上次检查时间 / 跳过的版本 ──
def state_path(base):
    return os.path.join(base, "data", STATE_NAME)


def load_state(base):
    p = state_path(base)
    d = {"v": 1, "last_check": 0, "skip_version": ""}   # 无死字段：notified 未使用已移除
    try:
        with open(p, encoding="utf-8") as f:
            got = json.load(f)
        if isinstance(got, dict):
            d.update({k: got.get(k, d[k]) for k in d})
    except Exception:
        pass
    return d


def save_state(base, d):
    p = state_path(base)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, p)
        return True
    except Exception:
        return False


