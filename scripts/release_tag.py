# MemWise v3.1.5 发布脚本 — 创建 tag + release
import json, ssl, urllib.request, urllib.error, sys

import os
TOKEN = os.environ.get('GITHUB_TOKEN') or open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.gh_token')).read().strip()
OWNER, REPO = 'fuguangbeta', 'MemWise'
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

def req(method, url, data=None):
    r = urllib.request.Request(url, method=method, data=data)
    r.add_header('Authorization', f'token {TOKEN}')
    r.add_header('Accept', 'application/vnd.github+json')
    r.add_header('User-Agent', 'memwise-release')
    return urllib.request.urlopen(r, context=ctx)

# 1) 获取 main HEAD
with req('GET', f'https://api.github.com/repos/{OWNER}/{REPO}/commits/main') as resp:
    head_sha = json.load(resp)['sha']
print('main HEAD:', head_sha)

# 2) 创建 tag（已存在则跳过）
try:
    body = json.dumps({'ref': 'refs/tags/v3.1.5', 'sha': head_sha}).encode()
    with req('POST', f'https://api.github.com/repos/{OWNER}/{REPO}/git/refs', body) as resp:
        print('tag v3.1.5: OK', json.load(resp)['ref'])
except urllib.error.HTTPError as e:
    print('tag: HTTP', e.code, e.read()[:200])

# 3) 创建 release（占位 body，稍后 PATCH 完整版）
body = json.dumps({
    'tag_name': 'v3.1.5',
    'name': 'MemWise v3.1.5',
    'body': 'v3.1.5 发布中...',
    'draft': False,
    'prerelease': False,
}).encode()
try:
    with req('POST', f'https://api.github.com/repos/{OWNER}/{REPO}/releases', body) as resp:
        d = json.load(resp)
        print('release: OK id=', d['id'], 'url=', d['html_url'])
except urllib.error.HTTPError as e:
    print('release: HTTP', e.code, e.read()[:300])
