# MemWise 全量同步脚本 — 推送本地工作区规则内全部文件到 main（更新/新增/删除）
import json, base64, ssl, urllib.request, urllib.error, os, time, sys

import os
TOKEN = os.environ.get('GITHUB_TOKEN') or open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.gh_token')).read().strip()
OWNER, REPO, BRANCH = 'fuguangbeta', 'MemWise', 'main'
BASE = r'D:\我的文件\memwise'
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

def req(method, url, data=None, headers=None):
    r = urllib.request.Request(url, method=method, data=data)
    r.add_header('Authorization', f'token {TOKEN}')
    r.add_header('Accept', 'application/vnd.github+json')
    r.add_header('User-Agent', 'memwise-sync')
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    return urllib.request.urlopen(r, context=ctx)

def get_sha(path):
    try:
        with req('GET', f'https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}?ref={BRANCH}') as resp:
            return json.load(resp)['sha']
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f'  GET {path}: HTTP {e.code}'); return None

def put_file(path):
    """PUT 更新或新增；返回 True/False"""
    content = open(os.path.join(BASE, path), 'rb').read()
    body = {'message': f'sync: {path}', 'content': base64.b64encode(content).decode(), 'branch': BRANCH}
    sha = get_sha(path)
    if sha:
        body['sha'] = sha
    for attempt in range(4):
        try:
            with req('PUT', f'https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}', json.dumps(body).encode()) as resp:
                d = json.load(resp)
                print(f'  PUT {path}: OK {d["content"]["sha"][:8]}')
                return True
        except urllib.error.HTTPError as e:
            print(f'  PUT {path}: 尝试{attempt+1} HTTP {e.code} {"..." if attempt < 3 else e.read()[:120]}')
            if attempt < 3:
                time.sleep(3)
    return False

def delete_file(path):
    sha = get_sha(path)
    if not sha:
        print(f'  DELETE {path}: 远程不存在，跳过')
        return True
    body = json.dumps({'message': f'sync: remove {path}', 'sha': sha}).encode()
    try:
        with req('DELETE', f'https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}', body) as resp:
            print(f'  DELETE {path}: OK')
            return True
    except urllib.error.HTTPError as e:
        print(f'  DELETE {path}: HTTP {e.code} {e.read()[:120]}')
        return False

# ── 更新（远程已有）──
UPDATES = [
    'README.md', 'memwise.py', 'memwise_gui.py',
    'core/cleaner.py', 'core/config.py', 'core/efis.py', 'core/judger.py',
    'core/kalman.py', 'core/learner.py', 'core/meta.py', 'core/policy.py',
    'core/prior.py', 'core/sniffer.py', 'core/winapi.py',
    'scripts/_validate.py', 'scripts/build_exe.bat', 'scripts/memwise.bat',
    'scripts/memwise_gui.bat', 'assets/icon.ico', 'assets/memwise.ico',
]
# ── 新增（远程缺失）──
NEWS = [
    '.gitignore',
    'scripts/test_v2.6.py',
    'scripts/release_body.py', 'scripts/release_push.py',
    'scripts/release_replace_asset.py', 'scripts/release_tag.py',
    'scripts/release_upload.py', 'scripts/release_sync.py',
]
# ── 删除（远程残留、本地已移除的旧模块）──
DELETES = ['core/causal.py', 'core/hippocampus.py', 'core/temporal.py']

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    ok = True
    if mode in ('all', 'update'):
        print(f'== 更新 {len(UPDATES)} 个文件 ==')
        for p in UPDATES:
            ok = put_file(p) and ok
    if mode in ('all', 'new'):
        print(f'== 新增 {len(NEWS)} 个文件 ==')
        for p in NEWS:
            ok = put_file(p) and ok
    if mode in ('all', 'delete'):
        print(f'== 删除 {len(DELETES)} 个旧模块 ==')
        for p in DELETES:
            ok = delete_file(p) and ok
    print('SYNC DONE' if ok else 'SYNC 有失败，请重跑对应模式')
