# MemWise v3.0.1 发布脚本 — 替换 release 资产（删旧传新，模板修复版）
import json, ssl, urllib.request, urllib.error, os, shutil, tempfile, time

import os
TOKEN = os.environ.get('GITHUB_TOKEN') or open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.gh_token')).read().strip()
OWNER, REPO = 'fuguangbeta', 'MemWise'
RELEASE_ID = 363555174
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

def req(method, url, data=None, headers=None):
    r = urllib.request.Request(url, method=method, data=data)
    r.add_header('Authorization', f'token {TOKEN}')
    r.add_header('Accept', 'application/vnd.github+json')
    r.add_header('User-Agent', 'memwise-release')
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    return urllib.request.urlopen(r, context=ctx)

# 1) 获取 release 资产列表
with req('GET', f'https://api.github.com/repos/{OWNER}/{REPO}/releases/{RELEASE_ID}') as resp:
    rel = json.load(resp)
for a in rel.get('assets', []):
    print('现有资产:', a['id'], a['name'], a['size'])
    if a['name'] == 'MemWise.exe':
        try:
            with req('DELETE', f'https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/{a["id"]}') as r:
                print('已删除旧资产', a['id'], 'status', r.status)
        except urllib.error.HTTPError as e:
            print('删除失败 HTTP', e.code, e.read()[:200])

# 2) 上传新 exe（模板修复版）
src = r'D:\我的文件\memwise\dist\MemWise.exe'
print('新 exe 大小:', os.path.getsize(src))
tmp = os.path.join(tempfile.gettempdir(), 'MemWise_v301_fixed.exe')
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
        with req('POST', url, data, {'Content-Type': 'application/octet-stream'}) as resp:
            d = json.load(resp)
            print('上传成功: name=', d['name'], 'size=', d['size'])
            print('下载链接:', d['browser_download_url'])
            break
    except urllib.error.HTTPError as e:
        print(f'尝试 {attempt+1}: HTTP {e.code} {e.read()[:200]}')
        time.sleep(3)
    except Exception as e:
        print(f'尝试 {attempt+1}: {e}')
        time.sleep(3)
