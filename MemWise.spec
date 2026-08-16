# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['memwise_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],  # 发布版冷启动：不打包本机配置（exe 首次运行回退 DEFAULT_CFG 默认配置）
    hiddenimports=['yaml'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MemWise',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 2026-08-15 审查：UPX 壳易触发杀软静态误报（卡巴/Defender 双杀软环境），关闭换体积微增换分发安全
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=['assets\\icon.ico'],
)
