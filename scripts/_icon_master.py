# 大图标母版：winapi 渲染（与 hq6 同源）——hq6 的 M 位置 off_mult=2.01(中心偏上-32.2px)
# → 下移 19.2px 至参考图 hq10 的 M 位置(中心偏上-13px)：off_mult = 0.81
# 光照/渐变/阴影参数与 hq6 完全相同，仅 M 骨架位置不同
# 用法: python scripts/_icon_master.py —— 生成 icon_master_256.png / icon_master_128.png
import sys, os, ctypes
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core.winapi import _draw_memwise_pixels_hq
from scripts._icon_preview import save_png


def composite(size=256):
    buf = (ctypes.c_ubyte * (size * size * 4))()
    _draw_memwise_pixels_hq(size, buf, (62, 62, 72), off_mult=0.81, shadow=True, gradient=0.47)
    return bytes(buf)


ICON_DIR = os.path.join(BASE, 'assets', 'icons')


if __name__ == '__main__':
    px = composite(256)
    save_png(os.path.join(ICON_DIR, 'icon_master_256.png'), 256, px)
    # 128 母版：4x 盒式缩小
    k = 2
    s = 128
    small = bytearray(s * s * 4)
    for y in range(s):
        for x in range(s):
            rs = gs = bs = as_ = 0
            for sy in range(k):
                for sx in range(k):
                    i = ((y * k + sy) * 256 + (x * k + sx)) * 4
                    bs += px[i]; gs += px[i + 1]; rs += px[i + 2]; as_ += px[i + 3]
            nn = k * k
            i = (y * s + x) * 4
            small[i] = bs // nn; small[i + 1] = gs // nn; small[i + 2] = rs // nn
            small[i + 3] = as_ // nn
    save_png(os.path.join(ICON_DIR, 'icon_master_128.png'), s, bytes(small))
    print('已生成 assets/icons/icon_master_256.png / icon_master_128.png')
