# MemWise v3.1.5 发布脚本 — 更新 release body（增量版）
import json, ssl, urllib.request, urllib.error

import os
TOKEN = os.environ.get('GITHUB_TOKEN') or open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.gh_token')).read().strip()
OWNER, REPO = 'fuguangbeta', 'MemWise'
RELEASE_ID = 363707261
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

BODY = '''## v3.1.5 (2026年8月)

> v3.0.1 发布后的维护增量：实测发现每轮优化量（200-500MB）与内存实际波动（5%+ 来回震荡）严重不符，对统计链路全面审查后确认两处结构性遗漏——Layer3 阶段 C 的系统释放量完全未计入图表数据源；系统操作按函数级 avail 始末差计释放量，净变化口径系统性低估。本轮以"每个小操作释放量的标量总和"为口径重构统计链路，并确立"释放量 + 净下降"双指标分工制。共 5 项维护，回归测试 37 项全绿。

### 统计链路重构：每轮优化量回归真实
- **逐操作测量**：`_layer1_memreduct` 每个系统操作前后各读一次 avail，>0 标量累加进 `freed_bytes`——替代函数级一次始末差（净变化会吞减释放量）
- **Layer3 释放接入**：`_layer3_deep` 预处理与阶段 C 逐操作测量并累加进 `freed_bytes`——此前每轮数百 MB 只进 `layer3_extra`，图表/统计栏/周期日志完全缺失；`layer3_extra` 保留供 EFIS 使用
- **双指标分工制**：释放量（`freed_bytes` 差分 = 小操作标量总和）为主指标 + 净下降（`net_freed` = 内存真实变化）为附注——手动优化与 CLI 文案统一为"合计释放 X MB · 内存净下降 Y MB"
- **死代码清理**：`cycle_freed_total`/`total_freed`/`opt_done` 死字段删除

### 构建
- 版本号 v3.0.1 → v3.1.5（Mutex/窗口标题/CLI/README/测试同步）
- 发布版 exe = 冷启动默认配置（不打包本机 config.yaml）
- PyInstaller 6.21.0 / Python 3.14.0，产物约 13.3 MB
- 37 项回归测试全绿，零编译错误'''

body = json.dumps({'body': BODY}).encode()
r = urllib.request.Request(f'https://api.github.com/repos/{OWNER}/{REPO}/releases/{RELEASE_ID}', method='PATCH', data=body)
r.add_header('Authorization', f'token {TOKEN}')
r.add_header('Accept', 'application/vnd.github+json')
r.add_header('User-Agent', 'memwise-release')
try:
    with urllib.request.urlopen(r, context=ctx) as resp:
        d = json.load(resp)
        print('body 更新成功:', d['html_url'])
        print('资产:', [(a['name'], a['size']) for a in d.get('assets', [])])
except urllib.error.HTTPError as e:
    print('HTTP', e.code, e.read()[:300])
