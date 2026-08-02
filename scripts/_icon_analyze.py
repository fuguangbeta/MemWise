# 分析 preview 图：边缘锐度 / 暗圈 / M 对比度 / ASCII 预览
import sys, os, struct, zlib

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_png(path):
    d = open(path, "rb").read()
    assert d[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(d):
        ln = struct.unpack(">I", d[pos:pos+4])[0]
        typ = d[pos+4:pos+8]
        if typ == b"IHDR":
            w, h = struct.unpack(">II", d[pos+8:pos+16])
        elif typ == b"IDAT":
            idat += d[pos+8:pos+8+ln]
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * 4 + 1
    px = bytearray(w * h * 4)
    prev = bytearray(w * 4)
    for y in range(h):
        row = raw[y*stride:(y+1)*stride]
        f = row[0]
        line = bytearray(row[1:])
        if f == 1:
            for i in range(4, len(line)): line[i] = (line[i] + line[i-4]) & 255
        elif f == 2:
            for i in range(len(line)): line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(len(line)):
                a = line[i-4] if i >= 4 else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(len(line)):
                a = line[i-4] if i >= 4 else 0
                b_ = prev[i]
                c = prev[i-4] if i >= 4 else 0
                p = a + b_ - c
                pa, pb_, pc = abs(p-a), abs(p-b_), abs(p-c)
                pr = a if (pa <= pb_ and pa <= pc) else (b_ if pb_ <= pc else c)
                line[i] = (line[i] + pr) & 255
        px[y*w*4:(y+1)*w*4] = line
        prev = line
    return w, h, bytes(px)

def analyze(tag, path):
    w, h, px = load_png(path)
    # alpha 边缘过渡宽度（从上到下扫描中心列）
    c = w // 2
    alphas = [px[(y*w+c)*4+3] for y in range(h)]
    # 找 alpha 从 255 开始下降的位置
    edge_in = None; edge_out = None
    for y in range(1, h):
        if alphas[y] < 255 and alphas[y-1] == 255 and edge_in is None:
            edge_in = y
        if alphas[y] == 0 and alphas[y-1] > 0 and edge_out is None:
            edge_out = y
    # 暗圈：圆内但离边缘 1px 的平均亮度 vs 圆心亮度
    cx2 = cy2 = w // 2
    R = w // 2 - 2
    inner = []
    ring = []
    for y in range(h):
        for x in range(w):
            d = ((x-cx2)**2 + (y-cy2)**2) ** 0.5
            a = px[(y*w+x)*4+3]
            lum = (px[(y*w+x)*4] + px[(y*w+x)*4+1] + px[(y*w+x)*4+2]) // 3
            if a > 250 and d < R - 2:
                inner.append(lum)
            elif a > 250 and d > R - 2.5:
                ring.append(lum)
    # M 区对比度：圆内最亮与最暗
    print(f"== {tag} ==")
    print(f"  边缘过渡: in@{edge_in} out@{edge_out} (锐=间距小)")
    print(f"  圆心均亮 {sum(inner)//max(1,len(inner))} / 边缘环均亮 {sum(ring)//max(1,len(ring))} (差大=暗圈脏)")
    return (edge_out or 0) - (edge_in or 0)

def ascii_art(tag, path, invert=False):
    w, h, px = load_png(path)
    chars = " .:-=+*#%@"
    print(f"== {tag} ==")
    for y in range(h):
        row = ""
        for x in range(w):
            i = (y*w+x)*4
            a = px[i+3]
            if a < 40:
                row += " "
                continue
            lum = (px[i] + px[i+1] + px[i+2]) // 3
            idx = int(lum / 256 * len(chars))
            row += chars[min(idx, len(chars)-1)]
        print(row)

if __name__ == "__main__":
    for size in (16, 32):
        for tag, fn in (("A", f"preview_A_{size}.png"), ("B", f"preview_B_{size}.png")):
            analyze(tag + str(size), os.path.join(BASE, fn))
    print()
    for size in (16, 32):
        print(f"########## {size}px ##########")
        ascii_art(f"A{size}", os.path.join(BASE, f"preview_A_{size}.png"))
        ascii_art(f"B{size}", os.path.join(BASE, f"preview_B_{size}.png"))
