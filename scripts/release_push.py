# MemWise v3.1.5 发布脚本 — 推送 README + CHANGELOG 到 main
import json, base64, ssl, urllib.request, urllib.error, sys

import os
TOKEN = os.environ.get('GITHUB_TOKEN') or open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.gh_token')).read().strip()
OWNER, REPO, BRANCH = 'fuguangbeta', 'MemWise', 'main'
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

def req(method, url, data=None):
    r = urllib.request.Request(url, method=method, data=data)
    r.add_header('Authorization', f'token {TOKEN}')
    r.add_header('Accept', 'application/vnd.github+json')
    r.add_header('User-Agent', 'memwise-release')
    return urllib.request.urlopen(r, context=ctx)

def get_sha(path):
    try:
        with req('GET', f'https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}?ref={BRANCH}') as resp:
            return json.load(resp)['sha']
    except Exception:
        return None

def push(path):
    content = open(path, 'rb').read()
    sha = get_sha(path)
    body = {'message': f'docs: {path} v3.1.5', 'content': base64.b64encode(content).decode(), 'branch': BRANCH}
    if sha:
        body['sha'] = sha
    try:
        with req('PUT', f'https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}', json.dumps(body).encode()) as resp:
            d = json.load(resp)
            print(f'{path}: OK sha={d["content"]["sha"][:8]}')
    except urllib.error.HTTPError as e:
        print(f'{path}: HTTP {e.code} {e.read()[:300]}')

if __name__ == '__main__':
    for p in sys.argv[1:]:
        push(p)
