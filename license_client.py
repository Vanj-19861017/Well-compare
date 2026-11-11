# -*- coding: utf-8 -*-
"""
定向井设计工具箱 —— 授权模块
============================

机制
----
1. 首次运行弹出「激活」对话框，用户填写网关地址 + 授权码。
2. 软件向网关 POST /api/license/verify，网关校验后返回一个 HMAC 签名令牌。
3. 令牌（含 machine_id / expires）存到 %APPDATA%\\定向井设计工具箱\\license.dat。
4. 之后启动：本地校验令牌（机器匹配 + 未过期）即放行；同时后台尝试联网续期。
5. 令牌被篡改（HMAC 校验失败）或机器不匹配或已过期 → 重新弹出激活框。

网关接口约定（服务端需自行实现）
--------------------------------
请求：
    POST {gateway}/api/license/verify
    Content-Type: application/json
    {"license_code": "用户输入的授权码", "machine_id": "本机机器码"}

响应（成功）：
    {"valid": true,
     "expires": "2027-12-31",
     "token": "<payload_b64>.<sig_b64>"}

  其中 payload_b64 = base64url(json({
        "license_code": "...",
        "machine_id": "...",
        "expires": "YYYY-MM-DD"
     }))
  sig_b64 = base64url(HMAC-SHA256(LICENSE_SECRET, payload_b64))

响应（失败）：
    {"valid": false, "message": "授权码无效"}

注意：LICENSE_SECRET 必须与网关保持一致，且不要随安装包外发真实值。
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

# ── 与网关共享的 HMAC 密钥（网关端必须用同一密钥签发令牌） ────────────────
# 上线前请改成你们自己的值，并在网关服务端配置一致。
LICENSE_SECRET = "wj-toolbox-2026-secret"

# 默认网关地址（用户可在激活框里改）
DEFAULT_GATEWAY = "http://127.0.0.1:8000"

# 本地缓存目录与文件
APP_NAME = "定向井设计工具箱"
LICENSE_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
LICENSE_FILE = LICENSE_DIR / "license.dat"


# ================================================================
# 机器指纹
# ================================================================
def get_machine_id() -> str:
    """稳定的机器码：主机名 + 首个 MAC + 系统盘卷序列号，SHA-256 取前 16 位。"""
    parts = []
    parts.append(socket.gethostname())
    try:
        parts.append(f"{uuid_getnode():012X}")
    except Exception:
        parts.append("0")
    # Windows 系统盘卷序列号
    if sys.platform == "win32":
        try:
            import ctypes
            serial = ctypes.c_ulong(0)
            ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p("C:\\"), None, 0,
                ctypes.byref(serial), None, None, None, 0,
            )
            parts.append(f"{serial.value:08X}")
        except Exception:
            pass
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16].upper()


def uuid_getnode() -> int:
    import uuid
    return uuid.getnode()


# ================================================================
# 令牌（HMAC 签名）
# ================================================================
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def verify_token(token: str, secret: str = LICENSE_SECRET) -> dict | None:
    """校验令牌签名并返回 payload；失败返回 None。"""
    try:
        payload_b64, sig_b64 = token.rsplit(".", 1)
        sig = _b64url_decode(sig_b64)
        expected = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        return payload
    except Exception:
        return None


def make_token(license_code: str, machine_id: str, expires: str,
               secret: str = LICENSE_SECRET) -> str:
    """本地生成令牌（仅用于自测 / 离线签发；正式应由网关签发）。"""
    payload = json.dumps(
        {"license_code": license_code, "machine_id": machine_id, "expires": expires},
        separators=(",", ":"),
    ).encode("utf-8")
    payload_b64 = _b64url_encode(payload)
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


# ================================================================
# 本地缓存读写
# ================================================================
def _ensure_dir() -> None:
    LICENSE_DIR.mkdir(parents=True, exist_ok=True)


def load_license() -> dict | None:
    """读取本地授权信息；无文件/损坏返回 None。"""
    if not LICENSE_FILE.exists():
        return None
    try:
        raw = LICENSE_FILE.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        return data
    except Exception:
        return None


def save_license(gateway: str, license_code: str, token: str, expires: str) -> None:
    _ensure_dir()
    data = {
        "gateway": gateway,
        "license_code": license_code,
        "machine_id": get_machine_id(),
        "expires": expires,
        "token": token,
        "activated_at": datetime.date.today().isoformat(),
    }
    LICENSE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def is_license_valid(lic: dict | None) -> tuple[bool, str]:
    """本地校验：令牌签名 + 机器匹配 + 未过期。"""
    if not lic:
        return False, "未找到本地授权"
    payload = verify_token(lic.get("token", ""))
    if payload is None:
        return False, "授权信息已被篡改，请重新激活"
    if payload.get("machine_id") != get_machine_id():
        return False, "授权与本机不匹配，请重新激活"
    expires = payload.get("expires") or lic.get("expires")
    try:
        exp = datetime.date.fromisoformat(str(expires))
    except Exception:
        return False, "授权有效期格式无效"
    if exp < datetime.date.today():
        return False, f"授权已于 {exp.isoformat()} 过期，请重新激活"
    return True, f"授权有效，到期 {exp.isoformat()}"


# ================================================================
# 网关在线校验
# ================================================================
def verify_online(gateway: str, license_code: str, machine_id: str,
                  timeout: float = 8.0) -> dict:
    """POST 到网关校验授权码。返回 {ok, expires, token, message}。"""
    url = gateway.rstrip("/") + "/api/license/verify"
    body = json.dumps({"license_code": license_code, "machine_id": machine_id}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "WJ-Toolbox"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "ok": bool(data.get("valid")),
                "expires": data.get("expires"),
                "token": data.get("token"),
                "message": data.get("message", ""),
            }
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode("utf-8"))
            msg = data.get("message", f"网关返回 HTTP {e.code}")
        except Exception:
            msg = f"网关返回 HTTP {e.code}"
        return {"ok": False, "message": msg}
    except Exception as e:
        return {"ok": False, "message": f"无法连接网关：{e}"}


# ================================================================
# 激活对话框
# ================================================================
class ActivationDialog(tk.Toplevel):
    def __init__(self, master=None, gateway: str = DEFAULT_GATEWAY):
        super().__init__(master)
        self.title("软件激活")
        self.geometry("480x420")
        self.resizable(False, False)
        # 注意：Windows 上 transient 到「已 withdraw 的隐藏根窗口」会把本对话框
        # 一并隐藏（表现为双击 exe 后毫无反应），所以只在父窗口可见时才设置。
        try:
            if master is not None and master.winfo_viewable():
                self.transient(master)
        except Exception:
            pass
        self.grab_set()

        self.result: dict | None = None
        self.var_gateway = tk.StringVar(value=gateway)
        self.var_code = tk.StringVar()
        self.machine_id = get_machine_id()

        pad = {"padx": 12, "pady": 4}
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=16, pady=14)

        ttk.Label(body, text="欢迎使用「定向井设计工具箱」",
                  font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Label(body, text="请选择激活方式：联网输入授权码，或导入离线授权文件。",
                  foreground="#666").pack(anchor="w", pady=(0, 10))

        # 机器码（客户发给开发者，用于生成绑定机器的授权文件）
        mid_frame = ttk.Frame(body)
        mid_frame.pack(fill="x", **pad)
        ttk.Label(mid_frame, text="本机机器码：").pack(side="left")
        ttk.Entry(mid_frame, width=24, state="readonly",
                  font=("Consolas", 10)).pack(side="left", padx=(6, 6))
        # 回填机器码
        mid_entry = mid_frame.winfo_children()[-1]
        mid_entry.configure(state="normal")
        mid_entry.insert(0, self.machine_id)
        mid_entry.configure(state="readonly")
        ttk.Button(mid_frame, text="复制", width=6,
                   command=lambda: self._copy(self.machine_id)).pack(side="left")
        ttk.Label(body, text="↑ 将此机器码发给软件提供者，获取授权文件后点「导入授权文件」",
                  foreground="#888", font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=12)

        ttk.Separator(body).pack(fill="x", pady=8)

        # 方式一：联网激活
        ttk.Label(body, text="方式一 · 联网激活").pack(anchor="w", **pad)
        ttk.Label(body, text="网关地址：").pack(anchor="w", **pad)
        ttk.Entry(body, textvariable=self.var_gateway, width=48).pack(fill="x", **pad)
        ttk.Label(body, text="授权码：").pack(anchor="w", **pad)
        ttk.Entry(body, textvariable=self.var_code, width=48, show="*").pack(fill="x", **pad)

        self.lbl_status = ttk.Label(body, text="", foreground="#C0392B")
        self.lbl_status.pack(anchor="w", padx=12, pady=(6, 0))

        btns = ttk.Frame(body)
        btns.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(btns, text="导入授权文件", command=self._on_import).pack(side="left")
        self.btn_ok = ttk.Button(btns, text="联网激活", command=self._on_activate)
        self.btn_ok.pack(side="right")
        ttk.Button(btns, text="取消", command=self._on_cancel).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        if master:
            self.update_idletasks()
            x = master.winfo_rootx() + (master.winfo_width() - 480) // 2
            y = master.winfo_rooty() + (master.winfo_height() - 420) // 2
            self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.lbl_status.config(text="机器码已复制到剪贴板", foreground="#2E7D32")

    def _on_import(self):
        """方式二：导入开发者生成的 .lic 授权文件（离线，绑定本机机器码）"""
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择授权文件",
            filetypes=[("授权文件", "*.lic"), ("所有文件", "*.*")],
            parent=self,
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8").strip()
        except Exception as e:
            self.lbl_status.config(text=f"读取授权文件失败：{e}", foreground="#C0392B")
            return
        token = text
        # 兼容 .lic 里包了一层 JSON {"token": "..."}
        if text.startswith("{"):
            try:
                token = json.loads(text).get("token", "")
            except Exception:
                token = ""
        payload = verify_token(token)
        if payload is None:
            self.lbl_status.config(text="授权文件无效或已被篡改", foreground="#C0392B")
            return
        if payload.get("machine_id") != self.machine_id:
            self.lbl_status.config(
                text="授权文件与本机机器码不匹配", foreground="#C0392B")
            return
        expires = payload.get("expires", "")
        save_license("offline", payload.get("license_code", ""), token, expires)
        self.result = {"ok": True, "expires": expires, "token": token,
                       "message": "离线激活成功"}
        self.destroy()

    def _on_activate(self):
        gateway = self.var_gateway.get().strip()
        code = self.var_code.get().strip()
        if not gateway:
            self.lbl_status.config(text="请填写网关地址")
            return
        if not code:
            self.lbl_status.config(text="请填写授权码")
            return
        self.btn_ok.config(state="disabled")
        self.lbl_status.config(text="正在连接网关校验...", foreground="#333")
        self.update_idletasks()

        result = verify_online(gateway, code, get_machine_id())
        if result.get("ok") and result.get("token"):
            save_license(gateway, code, result["token"],
                         result.get("expires") or "")
            self.result = result
            self.destroy()
        else:
            self.btn_ok.config(state="normal")
            self.lbl_status.config(text=result.get("message") or "激活失败",
                                   foreground="#C0392B")

    def _on_cancel(self):
        self.result = None
        self.destroy()


# ================================================================
# 对外入口
# ================================================================
def require_license(master=None) -> bool:
    """启动时调用：有有效授权返回 True；否则弹激活框，激活成功返回 True，
    用户取消返回 False（调用方应退出程序）。"""
    lic = load_license()
    ok, _ = is_license_valid(lic)
    if ok:
        # 后台静默续期（失败不影响本次使用）
        try:
            _try_renew(lic)
        except Exception:
            pass
        return True

    # 用一个隐藏根窗口承载激活框（主窗口尚未创建时）
    own_root = master is None
    if own_root:
        master = tk.Tk()
        master.withdraw()
    try:
        dlg = ActivationDialog(master, gateway=(lic or {}).get("gateway", DEFAULT_GATEWAY))
        master.wait_window(dlg)
        return dlg.result is not None
    finally:
        if own_root:
            try:
                master.destroy()
            except Exception:
                pass


def _try_renew(lic: dict) -> None:
    gateway = lic.get("gateway")
    code = lic.get("license_code")
    if not gateway or not code:
        return
    result = verify_online(gateway, code, get_machine_id(), timeout=5.0)
    if result.get("ok") and result.get("token"):
        save_license(gateway, code, result["token"], result.get("expires") or "")


def show_license_info(master) -> None:
    """在主界面里查看/重新激活授权。"""
    lic = load_license()
    ok, msg = is_license_valid(lic)
    info = [
        f"机器码：{get_machine_id()}",
        f"状态：{msg}",
    ]
    if lic:
        info.append(f"授权码：{lic.get('license_code', '')}")
        info.append(f"网关：{lic.get('gateway', '')}")
        info.append(f"激活日期：{lic.get('activated_at', '')}")
    choice = messagebox.askyesnocancel(
        "授权信息", "\n".join(info) + "\n\n是否重新激活？",
        parent=master,
    )
    if choice is True:
        dlg = ActivationDialog(master, gateway=(lic or {}).get("gateway", DEFAULT_GATEWAY))
        master.wait_window(dlg)
        if dlg.result:
            messagebox.showinfo("授权信息", "激活成功", parent=master)


# 本地自测：生成一个本机永久（到 2099 年）令牌，便于没有网关时调试
if __name__ == "__main__":
    mid = get_machine_id()
    token = make_token("LOCAL-TEST", mid, "2099-12-31")
    save_license(DEFAULT_GATEWAY, "LOCAL-TEST", token, "2099-12-31")
    print(f"machine_id = {mid}")
    print(f"已写入本地测试授权 -> {LICENSE_FILE}")
