# -*- coding: utf-8 -*-
"""生成 core/icon_baked.py：把运行时图标渲染结果预编码成 PNG 常量（2026-11-06）。

为什么：_draw_memwise_pixels_hq 是纯 Python 逐像素渲染（32px ≈ 42ms/个）。
启动时窗口小图标 + 托盘 5 种状态色最多要渲染 7 次（~300ms，全在 Tk 线程上）。
预烘焙后运行时只做 decode_png + create_hicon_from_rgba（实测 0.68ms/个，≈60× 快）；
解码失败时 GUI 自动回退到动态渲染，所以烘焙数据损坏不会导致无图标。

⚠ 改了图标渲染参数（_draw_memwise_pixels_hq / 默认色 / 尺寸）后必须重跑本脚本。

用法: python scripts/_icon_bake.py
"""
import base64
import ctypes
import os
import struct
import sys
import zlib

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core.winapi import _draw_memwise_pixels_hq

# 与 memwise_gui.py 的图标常量保持一致（托盘 5 档）
COMBOS = [
    ("tray_idle", 32, (70, 130, 180), False, 0.12),
    ("tray_low",  32, (60, 160, 60),  False, 0.12),
    ("tray_mid",  32, (200, 180, 40), False, 0.12),
    ("tray_mid2", 32, (220, 140, 0),  False, 0.12),
    ("tray_high", 32, (200, 60, 60),  False, 0.12),
    ("win32",     32, (45, 45, 50),    True, 0.47),   # 对话框大图标（create_memwise_icon(32) 默认）
    ("win16",     16, (45, 45, 50),    True, 0.47),   # 窗口小图标 / 对话框小图标
]


def render_bgra(size, color, shadow, gradient):
    buf = (ctypes.c_ubyte * (size * size * 4))()
    _draw_memwise_pixels_hq(size, buf, color, off_mult=0.75, shadow=shadow, gradient=gradient)
    return bytes(buf)


def bgra_to_rgba(bgra):
    out = bytearray(len(bgra))
    for i in range(0, len(bgra), 4):
        out[i] = bgra[i + 2]
        out[i + 1] = bgra[i + 1]
        out[i + 2] = bgra[i]
        out[i + 3] = bgra[i + 3]
    return bytes(out)


def png_encode(size, rgba):
    raw = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))

    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    from core.icon_flat import decode_png
    entries = []
    for name, size, color, shadow, gradient in COMBOS:
        bgra = render_bgra(size, color, shadow, gradient)
        png = png_encode(size, bgra_to_rgba(bgra))
        # 往返自检：解码回来的 BGRA 必须与渲染结果逐字节一致（否则图标会变色/错位）
        w, h, back = decode_png(png)
        if (w, h) != (size, size) or back != bgra:
            raise SystemExit("roundtrip mismatch: " + name)
        entries.append((name, size, base64.b64encode(png).decode("ascii")))
        print("%-10s %2dpx  png=%d B  b64=%d B" % (name, size, len(png), len(entries[-1][2])))

    lines = [
        "# -*- coding: utf-8 -*-",
        '"""预烘焙图标（自动生成，勿手改）——2026-11-06',
        "",
        "为什么：_draw_memwise_pixels_hq 是纯 Python 逐像素渲染（32px 约 42ms/个），",
        "启动时窗口小图标 + 托盘 5 种状态色最多渲染 7 次（约 300ms，全在 Tk 线程）。",
        "这里把同一渲染结果预编码成 PNG，运行时只做 decode_png + create_hicon_from_rgba",
        "（实测 0.68ms/个，约 60 倍快）；解码失败时 GUI 自动回退动态渲染。",
        "",
        "重新生成：python scripts/_icon_bake.py（改了图标设计/渲染参数后必须重跑）",
        '"""',
        "import base64",
        "",
        "BAKED = {",
    ]
    for name, size, b64 in entries:
        lines.append('    "%s": (' % name)
        for i in range(0, len(b64), 100):
            lines.append('        "%s"' % b64[i:i + 100])
        lines.append("    ),")
    lines += [
        "}",
        "",
        "",
        "def png_for(name):",
        '    """取预烘焙 PNG 字节；未知名称返回 None（调用方回退动态渲染）。"""',
        "    raw = BAKED.get(name)",
        "    return base64.b64decode(raw) if raw else None",
        "",
    ]
    out = os.path.join(BASE, "core", "icon_baked.py")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print("written", out, os.path.getsize(out), "B")


if __name__ == "__main__":
    main()
