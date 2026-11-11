#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
定向井设计工具箱 —— 一键打包脚本
=================================
流程：清理旧产物 -> PyInstaller 打包(带图标/版本信息) -> Inno Setup 生成安装包

用法：
    双击「一键打包成安装包.bat」（推荐）
    或命令行： python build_installer.py [--no-clean] [--no-open]

产物：
    dist\\定向井设计工具箱\\定向井设计工具箱.exe      （绿色版，可直接运行）
    安装包输出\\定向井设计工具箱_v1.0_安装包.exe      （安装包，分发用这个）
"""

from __future__ import annotations

import locale
import os
import re
import shutil
import subprocess
import sys
import time
import ctypes
import datetime
from pathlib import Path

# ----------------------------------------------------------------------
# 控制台编码：保证中文在任何代码页下都不乱码
# ----------------------------------------------------------------------
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT = Path(__file__).resolve().parent
APP_PY = PROJECT / "定向井设计工具箱.py"
SPEC = PROJECT / "定向井设计工具箱.spec"
ISS = PROJECT / "setup.iss"
ICON = PROJECT / "wj.ico"
LANG_ISL = PROJECT / "ChineseSimplified.isl"
VERSION_FILE = PROJECT / "version_info.txt"
DIST_DIR = PROJECT / "dist"
BUILD_DIR = PROJECT / "build"
LOG_FILE = PROJECT / "打包日志.txt"

ARGS = sys.argv[1:]
DO_CLEAN = "--no-clean" not in ARGS
DO_OPEN = "--no-open" not in ARGS


# ----------------------------------------------------------------------
# 输出
# ----------------------------------------------------------------------
def _enable_vt() -> bool:
    try:
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k.SetConsoleMode(h, mode.value | 0x0004))
    except Exception:
        return False


COLOR = _enable_vt()
C = {
    "g": "\033[92m", "r": "\033[91m", "y": "\033[93m",
    "b": "\033[96m", "d": "\033[90m", "w": "\033[97m", "x": "\033[0m",
}
if not COLOR:
    C = {k: "" for k in C}

_logf = open(LOG_FILE, "w", encoding="utf-8", errors="replace")


def log(msg: str = "", color: str = "", echo: bool = True) -> None:
    plain = re.sub(r"\x1b\[[0-9;]*m", "", msg)
    _logf.write(plain + "\n")
    _logf.flush()
    if echo:
        print((C.get(color, "") + msg + C["x"]) if color else msg, flush=True)


def rule(title: str = "") -> None:
    log("")
    if title:
        log(f"{C['b']}{'=' * 66}{C['x']}")
        log(f"{C['b']}  {title}{C['x']}")
        log(f"{C['b']}{'=' * 66}{C['x']}")
    else:
        log(f"{C['d']}{'-' * 66}{C['x']}")


def human(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024:
            return f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} TB"


def _w(s: str) -> int:
    """控制台显示宽度（中文算 2 列）"""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _w(s))


# ----------------------------------------------------------------------
# 子进程：边跑边打印，同时写日志
# ----------------------------------------------------------------------
def _decode(raw: bytes) -> str:
    """ISCC 输出 UTF-8，Python 子进程按本地代码页输出，这里两种都兼容"""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(locale.getpreferredencoding(False) or "mbcs", "replace")


def run(cmd, cwd=None, timeout=None) -> int:
    cmd = [str(c) for c in cmd]
    log(f"{C['d']}$ {' '.join(cmd)}{C['x']}", echo=False)
    log(f"{C['d']}$ {cmd[0]} ...{C['x']}")
    p = subprocess.Popen(
        cmd, cwd=str(cwd or PROJECT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
    )
    start = time.time()
    for raw in iter(p.stdout.readline, b""):
        line = _decode(raw).rstrip("\r\n")
        log(f"   {C['d']}{line}{C['x']}")
        if timeout and time.time() - start > timeout:
            p.kill()
            log("   [超时，已终止]", "r")
            return 124
    return p.wait()


# ----------------------------------------------------------------------
# 清理
# ----------------------------------------------------------------------
def remove_tree(path: Path, tries: int = 3):
    for i in range(tries):
        if not path.exists():
            return None
        try:
            shutil.rmtree(path)
            return None
        except Exception as e:  # 文件被占用
            if i == tries - 1:
                return e
            time.sleep(1.0)
    return None


def step_clean() -> None:
    rule("1/6  清理旧产物")
    for d in (BUILD_DIR, DIST_DIR):
        if not d.exists():
            log(f"   {C['d']}跳过（不存在）: {d.name}{C['x']}")
            continue
        err = remove_tree(d)
        if err:
            log(f"   {C['r']}无法删除 {d}：{err}{C['x']}")
            log("   请先关闭正在运行的「定向井设计工具箱」，或重启后再试。", "y")
            sys.exit(1)
        log(f"   已删除 {d.name}\\")

    out = PROJECT / "安装包输出"
    for f in out.glob("*.exe") if out.exists() else []:
        try:
            f.unlink()
            log(f"   已删除旧安装包 {f.name}")
        except Exception:
            log(f"   {C['y']}旧安装包被占用，跳过：{f.name}{C['x']}")


# ----------------------------------------------------------------------
# 环境检查
# ----------------------------------------------------------------------
def step_env() -> dict:
    rule("0/6  环境检查")
    problems = []

    if sys.version_info < (3, 9):
        problems.append(f"Python 版本过低：{sys.version.split()[0]}，需要 3.9+")
    log(f"   Python      {sys.version.split()[0]}  ({sys.executable})")

    for p, label in ((APP_PY, "主程序"), (SPEC, "spec 文件"), (ISS, "安装脚本"),
                     (ICON, "图标 wj.ico"), (LANG_ISL, "中文语言文件")):
        if p.exists():
            log(f"   {pad(label, 14)}OK  {p.name}")
        else:
            problems.append(f"缺少文件：{p.name}")
            log(f"   {pad(label, 14)}{C['r']}缺失  {p.name}{C['x']}")

    # 语言文件缺失时，尝试从常见位置补一份
    if not LANG_ISL.exists():
        for cand in (Path(r"D:\TEMP\ChineseSimplified.isl"),
                     Path.home() / "ChineseSimplified.isl"):
            if cand.exists():
                shutil.copy2(cand, LANG_ISL)
                problems = [x for x in problems if "ChineseSimplified" not in x]
                log(f"   已自动补入语言文件：{cand}")
                break

    # PyInstaller
    try:
        import PyInstaller  # noqa: F401
        ver = getattr(PyInstaller, "__version__", "?")
        log(f"   PyInstaller  {ver}")
    except Exception:
        log(f"   PyInstaller  {C['y']}未安装，正在安装 ...{C['x']}")
        rc = run([sys.executable, "-m", "pip", "install", "-U", "pyinstaller",
                  "--disable-pip-version-check"])
        if rc != 0:
            problems.append("PyInstaller 安装失败，请检查网络后重试")
        else:
            log("   PyInstaller  安装完成", "g")

    if problems:
        log("")
        for p in problems:
            log(f"   {C['r']}× {p}{C['x']}")
        log("")
        log("环境检查未通过，已停止。", "r")
        sys.exit(2)

    # 读取 setup.iss 中的定义，供版本信息使用
    defines = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', ISS.read_text(
        encoding="utf-8-sig", errors="replace"), re.M))
    for k in ("MyAppName", "MyAppVersion", "MyAppPublisher", "MyAppExeName"):
        defines.setdefault(k, {"MyAppName": "定向井设计工具箱", "MyAppVersion": "1.0",
                               "MyAppPublisher": "", "MyAppExeName": "定向井设计工具箱.exe"}[k])
    log(f"   版本号       {defines['MyAppVersion']}")
    return defines


# ----------------------------------------------------------------------
# 版本信息资源（让 exe 属性里显示名称/版本/公司）
# ----------------------------------------------------------------------
def step_version_info(defines: dict) -> None:
    rule("2/6  生成版本信息")
    ver = defines["MyAppVersion"]
    parts = [int(x) for x in re.findall(r"\d+", ver)][:4]
    while len(parts) < 4:
        parts.append(0)
    tup = tuple(parts)
    year = datetime.date.today().year
    text = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={tup},
    prodvers={tup},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '080404b0',
          [StringStruct('CompanyName', '{defines["MyAppPublisher"]}'),
           StringStruct('FileDescription', '{defines["MyAppName"]}'),
           StringStruct('FileVersion', '{ver}'),
           StringStruct('InternalName', '{defines["MyAppName"]}'),
           StringStruct('LegalCopyright', 'Copyright (C) {year} {defines["MyAppPublisher"]}'),
           StringStruct('OriginalFilename', '{defines["MyAppExeName"]}'),
           StringStruct('ProductName', '{defines["MyAppName"]}'),
           StringStruct('ProductVersion', '{ver}')])
      ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    VERSION_FILE.write_text(text, encoding="utf-8")
    log(f"   已写入 {VERSION_FILE.name}（{defines['MyAppName']} {ver}）")


# ----------------------------------------------------------------------
# PyInstaller
# ----------------------------------------------------------------------
def step_pyinstaller(defines: dict) -> Path:
    rule("3/6  PyInstaller 打包")
    log(f"   {C['d']}首次打包约 2~5 分钟，请耐心等待 ...{C['x']}")
    t0 = time.time()
    rc = run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
              "--log-level", "WARN", SPEC])
    dt = time.time() - t0
    if rc != 0:
        log("")
        log(f"PyInstaller 打包失败（退出码 {rc}）。", "r")
        log("常见原因：源码有语法错误 / 依赖缺失 / 文件被占用。", "y")
        log(f"完整日志：{LOG_FILE}")
        sys.exit(3)
    log(f"   打包完成，用时 {dt:.0f} 秒", "g")

    exe = DIST_DIR / defines["MyAppName"] / defines["MyAppExeName"]
    return exe


def step_verify(exe: Path, defines: dict) -> None:
    rule("4/6  校验打包结果")
    if not exe.exists():
        log(f"   {C['r']}未找到 {exe}{C['x']}")
        sys.exit(4)
    log(f"   {C['g']}OK{C['x']}  {exe.name}  ({human(exe.stat().st_size)})")

    internal = exe.parent / "_internal"
    must = [
        (internal / "wj.ico", "窗口图标"),
        (internal / "15-寻找最优点" / "寻找最优点参数.py", "最优点模块"),
        (internal / "matplotlib" / "mpl-data", "matplotlib 数据"),
    ]
    for path, label in must:
        if path.exists():
            log(f"   {C['g']}OK{C['x']}  {label}")
        else:
            log(f"   {C['y']}!{C['x']}   缺少 {label}：{path.relative_to(exe.parent)}", "y")

    total = sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file())
    nfiles = sum(1 for f in exe.parent.rglob("*") if f.is_file())
    log(f"   绿色版总大小 {human(total)}（{nfiles} 个文件）")


# ----------------------------------------------------------------------
# Inno Setup
# ----------------------------------------------------------------------
def find_iscc() -> Path | None:
    p = shutil.which("iscc") or shutil.which("ISCC")
    if p:
        return Path(p)
    cands = [
        Path(os.environ.get("INNO_SETUP_PATH", "")) / "ISCC.exe" if os.environ.get("INNO_SETUP_PATH") else None,
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
    ]
    for c in cands:
        if c and c.exists():
            return c

    try:
        import winreg
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for root, sub in keys:
            try:
                with winreg.OpenKey(root, sub) as k:
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        try:
                            name = winreg.EnumKey(k, i)
                            with winreg.OpenKey(k, name) as sk:
                                disp = str(winreg.QueryValueEx(sk, "DisplayName")[0])
                                if "inno setup" in disp.lower():
                                    loc = str(winreg.QueryValueEx(sk, "InstallLocation")[0]).strip()
                                    if loc:
                                        exe = Path(loc) / "ISCC.exe"
                                        if exe.exists():
                                            return exe
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception:
        pass
    return None


def install_iscc() -> Path | None:
    log("")
    log(f"{C['y']}未检测到 Inno Setup（生成安装包需要它）。{C['x']}")
    log("   官方下载：https://jrsoftware.org/isdl.php")
    log("   安装时一路默认即可，装完重新双击本脚本。")
    winget = shutil.which("winget")
    if winget:
        log("")
        try:
            ans = input("   检测到 winget，是否现在自动安装 Inno Setup？[Y/n] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans in ("", "y", "yes"):
            run([winget, "install", "-e", "--id", "JRSoftware.InnoSetup",
                 "--accept-source-agreements", "--accept-package-agreements"])
            return find_iscc()
    try:
        os.startfile("https://jrsoftware.org/isdl.php")
    except Exception:
        pass
    return None


def step_inno(defines: dict) -> Path:
    rule("5/6  生成安装包（Inno Setup）")
    iscc = find_iscc()
    if not iscc:
        iscc = install_iscc()
    if not iscc:
        log("")
        log("安装 Inno Setup 后重新运行本脚本即可。", "r")
        sys.exit(5)
    log(f"   ISCC  {iscc}")

    t0 = time.time()
    rc = run([iscc, "/Qp", f"/DMyAppVersion={defines['MyAppVersion']}", ISS])
    dt = time.time() - t0
    if rc != 0:
        log("")
        log(f"Inno Setup 编译失败（退出码 {rc}），详见上方输出。", "r")
        log(f"完整日志：{LOG_FILE}")
        sys.exit(6)
    log(f"   编译完成，用时 {dt:.0f} 秒", "g")

    out = PROJECT / "安装包输出"
    found = sorted(out.glob("*.exe"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not found:
        log(f"   {C['r']}未找到输出安装包：{out}{C['x']}")
        sys.exit(7)
    return found[0]


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def main() -> int:
    t_all = time.time()
    rule()
    log(f"{C['w']}定向井设计工具箱 · 一键打包{C['x']}")
    log(f"{C['d']}{datetime.datetime.now():%Y-%m-%d %H:%M:%S}   {PROJECT}{C['x']}")
    rule()

    defines = step_env()
    if DO_CLEAN:
        step_clean()
    else:
        log("")
        log("   已指定 --no-clean，保留 build/ 与 dist/（增量打包更快）", "y")

    step_version_info(defines)
    exe = step_pyinstaller(defines)
    step_verify(exe, defines)
    installer = step_inno(defines)

    # ---------------- 汇总 ----------------
    rule("6/6  完成")
    log(f"{C['g']}✔ 打包成功{C['x']}")
    log("")
    log(f"   绿色版  {exe}")
    log(f"           {human(exe.stat().st_size)}（exe 本体），"
        f"整个文件夹 {human(sum(f.stat().st_size for f in exe.parent.rglob('*') if f.is_file()))}")
    log(f"   安装包  {C['g']}{installer}{C['x']}")
    log(f"           {human(installer.stat().st_size)}")
    log("")
    log(f"   安装包双击即可安装（默认装到 当前用户\\AppData\\Local\\Programs，无需管理员）。")
    log(f"   日志：{LOG_FILE.name}")
    log(f"   总用时 {time.time() - t_all:.0f} 秒")

    if DO_OPEN:
        try:
            subprocess.Popen(["explorer", "/select,", str(installer)])
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n已取消。", "y")
        sys.exit(130)
    finally:
        _logf.close()
