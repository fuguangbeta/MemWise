# 图标对比预览：A=现状(winapi 真函数)  B=建议(参数化副本: 扁平光照+窄柔边+弱阴影)
# 用法: python scripts/_icon_preview.py —— 生成 preview_A/B_{16,32}.png 及 8x 放大图
import sys, os, struct, zlib, math, ctypes

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core.winapi import _draw_memwise_pixels_hq


def save_png(path, size, pixels):
    raw = b"".join(b"\x00" + pixels[y * size * 4:(y + 1) * size * 4] for y in range(size))
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def upscale(pixels, size, k):
    """8x box 放大（看边缘）"""
    out = bytearray(size * k * size * k * 4)
    for y in range(size * k):
        for x in range(size * k):
            x0, y0 = x // k, y // k
            src = (y0 * size + x0) * 4
            dst = (y * size * k + x) * 4
            out[dst:dst + 4] = pixels[src:src + 4]
    return bytes(out)


def _fit(s, off_mult, soft_r, R):
    lo, hi = 0.30, 1.0
    for _ in range(14):
        ms = (lo + hi) / 2
        if math.hypot(6 * ms, 5 * ms + off_mult) * s + soft_r <= R:
            lo = ms
        else:
            hi = ms
    return lo


def render(size, bg, off_mult, shadow, gradient, edge_out, edge_in,
           shade_mid, shade_spread, soft_mult, sh_strength, m_scale=None):
    SS = 4
    cs = size * SS
    n = cs * cs
    canvas = [[0, 0, 0, 0] for _ in range(n)]
    cx = cy = cs // 2
    R = (size // 2 - 2) * SS
    s = size / 16.0

    small = size <= 32
    if small:
        shadow = False
        gradient = 0.0
    edge_out = edge_out * SS
    edge_in = edge_in * SS
    soft_r = soft_mult * s
    if m_scale is None:
        m_scale = _fit(s, off_mult, soft_r, R / SS) if small else 1.0

    for y in range(cs):
        for x in range(cs):
            dx, dy = x - cx, y - cy
            d = math.sqrt(dx * dx + dy * dy)
            if d > R + edge_out:
                continue
            t = min(1.0, d / R)
            lum = 1.0 - gradient * t
            r = int(min(255, bg[0] * lum))
            g = int(min(255, bg[1] * lum))
            b = int(min(255, bg[2] * lum))
            a = 255
            if d > R - edge_in:
                a = max(0, min(255, int(255 * (R + edge_out - d) / (edge_in + edge_out))))
            canvas[y * cs + x] = [b, g, r, a]

    segs = []
    off = -off_mult * s
    lx = -6 * s * m_scale; rx = 6 * s * m_scale
    ty = -5 * s * m_scale + off; by = 5 * s * m_scale + off
    mx = 0; my = 1 * s * m_scale + off
    segs.extend([(lx, ty, lx, by), (lx, ty, mx, my), (mx, my, rx, ty), (rx, ty, rx, by)])
    core_r = 1.1 * s
    soft_r = soft_mult * s

    m_alpha = [0.0] * n
    m_col = [None] * n
    DARK = (125, 135, 150)
    BRIGHT = (255, 255, 255)
    MLX, MLY = -0.7071, -0.7071
    for y in range(cs):
        row = y * cs
        for x in range(cs):
            px, py = (x - cx) / SS, (y - cy) / SS
            best = None
            for sg in segs:
                d, nx_, ny_ = _dist(px, py, *sg)
                if best is None or d < best[0]:
                    best = (d, nx_, ny_)
            d, nx_, ny_ = best
            if d >= soft_r:
                continue
            a = 1.0 if d < core_r else (soft_r - d) / (soft_r - core_r)
            m_alpha[row + x] = a
            if d > 1e-6:
                nx2, ny2 = (px - nx_) / d, (py - ny_) / d
                diff = nx2 * MLX + ny2 * MLY
                shade = shade_mid + shade_spread * diff
            else:
                shade = shade_mid
            r = int(DARK[0] + (BRIGHT[0] - DARK[0]) * shade)
            g = int(DARK[1] + (BRIGHT[1] - DARK[1]) * shade)
            b = int(DARK[2] + (BRIGHT[2] - DARK[2]) * shade)
            m_col[row + x] = (b, g, r)

    tmp = [0.0] * n
    for y in range(cs):
        row = y * cs
        for x in range(cs):
            v = m_alpha[row + x]
            tmp[row + x] = (m_alpha[row + x - 1] if x > 0 else v) + 2 * v + (m_alpha[row + x + 1] if x < cs - 1 else v)
    blurred = [0.0] * n
    for y in range(cs):
        for x in range(cs):
            i = y * cs + x
            v = tmp[i]
            blurred[i] = ((tmp[i - cs] if y > 0 else v) + 2 * v + (tmp[i + cs] if y < cs - 1 else v)) / 16.0

    if shadow:
        ox, oy = int(0.6 * s * SS), int(0.9 * s * SS)
        for y in range(cs):
            sy = y - oy
            if sy < 0 or sy >= cs:
                continue
            row_s = sy * cs
            for x in range(cs):
                sx = x - ox
                if sx < 0 or sx >= cs:
                    continue
                sh = blurred[row_s + sx] * sh_strength
                if sh > 0.01:
                    i = y * cs + x
                    if canvas[i][3] < 250:
                        continue
                    a = int(255 * sh)
                    cb, cg, cr, ca = canvas[i]
                    canvas[i] = [(cb * (255 - a)) // 255, (cg * (255 - a)) // 255,
                                 (cr * (255 - a)) // 255, min(255, ca + a)]

    for y in range(cs):
        row = y * cs
        for x in range(cs):
            a_m = m_alpha[row + x]
            if a_m <= 0:
                continue
            a = int(255 * a_m)
            i = row + x
            mb, mg, mr = m_col[i]
            bg_a = canvas[i][3]
            if bg_a == 0:
                canvas[i] = [mb, mg, mr, a]
            else:
                cb, cg, cr, ca = canvas[i]
                canvas[i] = [(cb * (255 - a) + mb * a) // 255,
                             (cg * (255 - a) + mg * a) // 255,
                             (cr * (255 - a) + mr * a) // 255,
                             min(255, ca + a)]

    out = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            rs = gs = bs = as_ = 0
            for sy in range(SS):
                for sx in range(SS):
                    b, g, r, a = canvas[(y * SS + sy) * cs + (x * SS + sx)]
                    rs += r; gs += g; bs += b; as_ += a
            nn = SS * SS
            i = (y * size + x) * 4
            out[i] = bs // nn; out[i + 1] = gs // nn; out[i + 2] = rs // nn
            out[i + 3] = as_ // nn if as_ else 0
    return bytes(out)


def _dist(px, py, x1, y1, x2, y2):
    vx, vy = x2 - x1, y2 - y1
    wx, wy = px - x1, py - y1
    c1 = vx * wx + vy * wy
    if c1 <= 0:
        return math.hypot(px - x1, py - y1), x1, y1
    c2 = vx * vx + vy * vy
    if c2 <= c1:
        return math.hypot(px - x2, py - y2), x2, y2
    t = c1 / c2
    nx, ny = x1 + t * vx, y1 + t * vy
    return math.hypot(px - nx, py - ny), nx, ny


def render_current(size):
    buf = (ctypes.c_ubyte * (size * size * 4))()
    _draw_memwise_pixels_hq(size, buf, (62, 62, 72), off_mult=0.75, shadow=True, gradient=0.47)
    return bytes(buf)


if __name__ == "__main__":
    # A: 现状（winapi 真实函数）
    # B: 建议 —— 窄柔边 + M 扁平光照 + 收窄 M 软边 + 弱阴影(仅大尺寸)
    for size in (16, 32):
        pa = render_current(size)
        pb = render(size, (62, 62, 72), off_mult=0.75, shadow=True, gradient=0.47,
                    edge_out=0.4, edge_in=0.7, shade_mid=0.78, shade_spread=0.22,
                    soft_mult=1.22, sh_strength=0.26)
        save_png(os.path.join(BASE, f"preview_A_{size}.png"), size, pa)
        save_png(os.path.join(BASE, f"preview_B_{size}.png"), size, pb)
        save_png(os.path.join(BASE, f"preview_A_{size}x8.png"), size * 8, upscale(pa, size, 8))
        save_png(os.path.join(BASE, f"preview_B_{size}x8.png"), size * 8, upscale(pb, size, 8))
    print("已生成 preview_A/B_{16,32}.png + x8 放大图")
