# -*- coding: utf-8 -*-
"""任务栏扁平图标（simple_flat_48.png 内嵌，冷启动 exe 无需外部文件）"""
import base64
import struct
import zlib

FLAT_48_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAEKUlEQVR42u2aW0gUURjHvdUqZpsJGVluaVkEKvhg4IOrFGFK+OAl"
    "Iy/RQ5KyCyq5XcTAIgjEp7Qo1ocoS2FMl1TIzDBBCBYzkSS7uG09lS9aFqzr9D82yurszvXspuTA/22+md/vnNndOedbP7/1g3+E"
    "aDR+W7XaDYgGCUY2hoWG+q9a4G0REcEHYmJikhMSjmakphqQBuQ+0o48Rh4hN5HqlKSk7Pi4uINRkZFhQYGBdEG0Wm1AQ0ND0dTU"
    "VJfT6XzBMEyNTqcL9TDKAYDefTglpYQDHEemESfCesg8MotMIt1IJWTiyWyp5Vk4rFZrPU5kXYPiocTExPDFczBq/rjpPty8BnmN"
    "/BYAFosD+Yg0YvYO4TELcoEPBE+jG55BSGh48MXFxbE4wbGywFUC074FI17KgTtUgLubGTIr1zCrOg6+yR0LSXNzcwlPoLa29qSn"
    "AhLb5ORIblYWg5v8oAjOm5HMtLSB57293UIsfX19t90JFAoVkYyNjrKQ8BY8C3jW0t7OinFA4K4iAW9KSIVXLeANCTnwVARoSsiF"
    "pyZAQ0IJPFUBNRJK4akLKJFQA69IYG5ujpqEVHihe8oWGBocZL/a7aolpMLPzs6yXZ2d9AS6LRa2KC9PlYQc+IuVleyNujp5AhdM"
    "JkEBAqFUQi48qRES6Onp4QucKy09KyagREIJvJhAa0tLC0/AVFVVI0VAroQSeDEB8DzjCaDgllQBORJK4CUIjCxbBJE1LApa5QjQ"
    "kPAEL0FgAmuTzUsCxAYFT+QKqJEQgpcgYNur0213FdCg4KkSASUSYvASBL5AINpVIBgFvUoF5EhIgZcooHMV2IiCbjUCUiSkwksQ"
    "+AyBHUsCZNMJBYxaASEJOfASBD7ooqLCV36NmmkILEjk5rLDVivrcDgW6u02G1ttNMq6hojAGHnslwlcNpmu0hJYTGFODnu6oIDN"
    "TE+XXSsiMMDb1TOWl5fTFlATIQGmra2N90tcUVFRtFYEOjs6zLJfp1eTgKL1wLrAusB/IHBqTQsYjUa9p4J7ZrPPBc4bDJ5/Bxjm"
    "Ck8AL3dBaGQMrzx5ZmaGLcnP97lAFn69342PuxOYzs7O3uO2xYQuTDQk+p1/D3LyREVZ2R1c8LuvBZBfeKd6aLfbX7ryoJOUJtbo"
    "89Pr9TuRWDIreFPVcG0luw/hSbOwHsvGiJU8irqXpPmG9uhxXPSVSBeSRj5hwAxo3W6i2oIlb3/oTu7HDZqQb14A/4lYMFB6bDIE"
    "eq2pjffwEH1y8jHcjOE+G/MqwUnTcACjfgaLlAifdefJtgZG6wjXgX/DPbdSZUiz+z3SgsE4geVhJPWuvZzPB3q7uyCTAaBLyAOk"
    "n+slv+U6+KPIIDdr1wGdSx5H8heFVfe/CbLHRGaH7NuQrQ+ye0AW4GQNS5aB/2ykV+vxB6qCe6oFN2aPAAAAAElFTkSuQmCC"
)

def decode_png(png):
    """解码 PNG → (width, height, BGRA bytes)。支持 color type 2(RGB)/6(RGBA)、8bit、filter 0-4"""
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "非 PNG 数据"
    pos, w, h, bit, ctype, idat = 8, 0, 0, 8, 0, b""
    while pos < len(png):
        ln, typ = struct.unpack(">I4s", png[pos:pos + 8])
        data = png[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, bit, ctype, comp, filt, interlace = struct.unpack(">IIBBBBB", data)
            assert comp == 0 and filt == 0 and interlace == 0 and bit == 8 and ctype in (2, 6)
        elif typ == b"IDAT":
            idat += data
        elif typ == b"IEND":
            break
        pos += 12 + ln
    raw = zlib.decompress(idat)
    ch = 3 if ctype == 2 else 4
    stride = w * ch
    out = bytearray(h * w * 4)
    prev = bytearray(stride)
    for y in range(h):
        base = y * (stride + 1)
        f = raw[base]
        line = bytearray(raw[base + 1:base + 1 + stride])
        if f == 1:  # Sub
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:  # Average
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:  # Paeth
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        for x in range(w):
            o = (y * w + x) * 4
            if ctype == 6:
                r, g, b, a = line[x * 4:x * 4 + 4]
            else:
                r, g, b = line[x * 3:x * 3 + 3]
                a = 255
            out[o] = b; out[o + 1] = g; out[o + 2] = r; out[o + 3] = a
        prev = line
    return w, h, bytes(out)
