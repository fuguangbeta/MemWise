# MemWise v3.1.5 发布脚本 — 上传 exe 资产（uploads.github.com）
import json, ssl, urllib.request, urllib.error, os, shutil, tempfile, time

import os
TOKEN = os.environ.get('GITHUB_TOKEN') or open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.gh_token')).read().strip()
OWNER, REPO = 'fuguangbeta', 'MemWise'
RELEASE_ID = 363707261
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

src = r'D:\我的文件\memwise\dist\MemWise.exe'
print('exe 大小:', os.path.getsize(src))

# 文件被锁时复制到 %TEMP% 再传
tmp = os.path.join(tempfile.gettempdir(), 'MemWise_v301.exe')
try:
    shutil.copy2(src, tmp)
    path = tmp
except Exception:
    path = src

url = f'https://uploads.github.com/repos/{OWNER}/{REPO}/releases/{RELEASE_ID}/assets?name=MemWise.exe'
for attempt in range(4):
    try:
        with open(path, 'rb') as f:
            data = f.read()
        r = urllib.request.Request(url, method='POST', data=data)
        r.add_header('Authorization', f'token {TOKEN}')
        r.add_header('Accept', 'application/vnd.github+json')
        r.add_header('User-Agent', 'memwise-release')
        r.add_header('Content-Type', 'application/octet-stream')
        with urllib.request.urlopen(r, context=ctx) as resp:
            d = json.load(resp)
            print('上传成功: name=', d['name'], 'size=', d['size'], 'browser_download_url=', d['browser_download_url'])
            break
    except urllib.error.HTTPError as e:
        print(f'尝试 {attempt+1}: HTTP {e.code} {e.read()[:200]}')
        time.sleep(3)
    except Exception as e:
        print(f'尝试 {attempt+1}: {e}')
        time.sleep(3)
