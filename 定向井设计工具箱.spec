# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（由「一键打包成安装包.bat」调用）"""
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [
    ('wj.ico', '.'),
    ('15-寻找最优点/寻找最优点参数.py', '15-寻找最优点'),
    ('15-寻找最优点/寻找最优点参数.md', '15-寻找最优点'),
    ('删COMPASS数据库非实钻设计井.sql', '.'),
]
hiddenimports = ['scipy.optimize', 'pyodbc']
datas += collect_data_files('tkinter')
hiddenimports += collect_submodules('tkinter')
hiddenimports += collect_submodules('matplotlib')


a = Analysis(
    ['定向井设计工具箱.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'torch', 'tensorflow', 'pandas',
              'jinja2', 'lxml', 'chardet', 'cryptography'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='定向井设计工具箱',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['wj.ico'],
    version='version_info.txt',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='定向井设计工具箱',
)
