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
    excludes=['ssl','email','http','urllib','xml','unittest','pydoc','asyncio','multiprocessing'],
    noarchive=False,
    optimize=2,
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
    # 2026-09-11（F32）：不再用 uac_admin=True（requireAdministrator 会让标准账户被系统直接拒绝、
    # 连界面都看不到）。改为 asInvoker + 程序启动时**显式请求提权**（管理员账户照旧弹 UAC；
    # 取消或标准账户则以受限模式启动并获明确提示）。清单里的执行级别会被打包工具按本参数改写，
    # 故 MemWise.manifest 只保留兼容性声明，两者必须保持一致。
    manifest='MemWise.manifest',
    icon=['assets\\icon.ico'],
)
