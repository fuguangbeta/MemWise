# 生成 assets/icon.ico：全帧 PNG 压缩格式
# 大帧（48/64/128/256）= 立体母版渲染（off_mult=0.81）；小帧（16/24/32）= 扁平简化渲染
# 用法: python scripts/_icon_build_ico.py
import sys, os, ctypes, struct, zlib
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core.winapi import _draw_memwise_pixels_hq


def render(size):
    """任务栏帧（24/32/48）用大尺寸立体渲染后缩小（细节更清晰）；16 保持 flat；64+ 直接立体"""
    buf = (ctypes.c_ubyte * (size * size * 4))()
    _draw_memwise_pixels_hq(size, buf, (62, 62, 72), off_mult=0.81, shadow=True, gradient=0.47)
    return bytes(buf)


def downscale(px, src, dst):
    """整数倍 box 缩小"""
    k = src // dst
    out = bytearray(dst * dst * 4)
    for y in range(dst):
        for x in range(dst):
            rs = gs = bs = as_ = 0
            for sy in range(k):
                for sx in range(k):
                    i = ((y * k + sy) * src + (x * k + sx)) * 4
                    bs += px[i]; gs += px[i + 1]; rs += px[i + 2]; as_ += px[i + 3]
            nn = k * k
            j = (y * dst + x) * 4
            out[j] = bs // nn; out[j + 1] = gs // nn; out[j + 2] = rs // nn
            out[j + 3] = as_ // nn
    return bytes(out)


def png_encode(size, px):
    raw = b"".join(b"\x00" + px[y * size * 4:(y + 1) * size * 4] for y in range(size))

    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def build():
    sizes = (16, 24, 32, 48, 64, 128, 256)
    frames = []
    for sz in sizes:
        if sz == 16:
            px = render(sz)  # flat（小尺寸分支）
        elif sz in (24, 32, 48):
            # 任务栏帧：直接渲染立体（4x 超采样，边缘锐利）——不缩图，避免 box 平均发糊
            buf = (ctypes.c_ubyte * (sz * sz * 4))()
            _draw_memwise_pixels_hq(sz, buf, (62, 62, 72), off_mult=0.81, shadow=True, gradient=0.47, force_large=True)
            px = bytes(buf)
        else:
            px = render(sz)  # 立体
        frames.append((sz, png_encode(sz, px)))
    header = struct.pack("<HHH", 0, 1, len(frames))
    entries = b""
    offset = 6 + 16 * len(frames)
    for sz, data in frames:
        entries += struct.pack("<BBBBHHII",
                               sz if sz < 256 else 0, sz if sz < 256 else 0,
                               0, 0, 1, 32, len(data), offset)
        offset += len(data)
    blob = header + entries + b"".join(d for _, d in frames)
    out = os.path.join(BASE, "assets", "icon.ico")
    with open(out, "wb") as f:
        f.write(blob)
    print(f"已生成 {out} ({len(blob)} B, {len(frames)} 帧)")


if __name__ == "__main__":
    build()
