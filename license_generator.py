# -*- coding: utf-8 -*-
"""
定向井设计工具箱 —— 授权码生成器（开发者工具，不随安装包分发）
================================================================

用途：根据客户提供的「机器码」生成绑定该机器的 .lic 授权文件，
      客户在激活对话框中「导入授权文件」即可离线激活。

用法：
    python license_generator.py

流程：
    1. 客户运行 exe → 激活对话框里复制「本机机器码」发给你。
    2. 你运行本工具，粘贴机器码，设置授权对象 / 到期日。
    3. 点「生成授权文件」→ 得到 xxx.lic。
    4. 把 .lic 发给客户，客户在激活框点「导入授权文件」即可。

注意：
    - 本工具与客户端共用 license_client.LICENSE_SECRET，签发的令牌
      才能被客户端 verify_token() 校验通过。修改密钥必须两端同步。
    - 本工具仅供开发者使用，不要打包进安装包。
"""

from __future__ import annotations

import datetime
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from license_client import make_token, verify_token, LICENSE_SECRET


class GeneratorWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("授权码生成器（开发者）")
        self.geometry("560x400")
        self.resizable(False, False)

        self.var_mid = tk.StringVar()
        self.var_code = tk.StringVar(value="CUSTOMER-001")
        self.var_expires = tk.StringVar(
            value=(datetime.date.today() + datetime.timedelta(days=365)).isoformat())

        pad = {"padx": 14, "pady": 5}
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=16, pady=14)

        ttk.Label(body, text="定向井设计工具箱 · 授权文件生成器",
                  font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w", pady=(0, 8))

        ttk.Label(body, text="客户机器码（16 位）：").pack(anchor="w", **pad)
        ttk.Entry(body, textvariable=self.var_mid, width=40,
                  font=("Consolas", 11)).pack(fill="x", **pad)

        ttk.Label(body, text="授权对象（授权码标识，如客户名/编号）：").pack(anchor="w", **pad)
        ttk.Entry(body, textvariable=self.var_code, width=40).pack(fill="x", **pad)

        ttk.Label(body, text="到期日期（YYYY-MM-DD）：").pack(anchor="w", **pad)
        ttk.Entry(body, textvariable=self.var_expires, width=20).pack(anchor="w", **pad)

        self.lbl_status = ttk.Label(body, text="", foreground="#2E7D32")
        self.lbl_status.pack(anchor="w", padx=14, pady=(8, 0))

        btns = ttk.Frame(body)
        btns.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Button(btns, text="生成并保存授权文件",
                   command=self._generate).pack(side="right")
        ttk.Button(btns, text="复制令牌到剪贴板",
                   command=self._copy_token).pack(side="right", padx=(0, 8))

    def _collect(self):
        mid = self.var_mid.get().strip().upper()
        code = self.var_code.get().strip()
        expires = self.var_expires.get().strip()
        if len(mid) != 16 or not all(c in "0123456789ABCDEF" for c in mid):
            self.lbl_status.config(text="机器码格式应为 16 位十六进制", foreground="#C0392B")
            return None
        if not code:
            self.lbl_status.config(text="请填写授权对象", foreground="#C0392B")
            return None
        try:
            datetime.date.fromisoformat(expires)
        except Exception:
            self.lbl_status.config(text="到期日期格式应为 YYYY-MM-DD", foreground="#C0392B")
            return None
        return mid, code, expires

    def _make(self):
        data = self._collect()
        if not data:
            return None
        mid, code, expires = data
        token = make_token(code, mid, expires)
        # 自检：客户端能否校验通过
        if verify_token(token) is None:
            self.lbl_status.config(text="生成的令牌自检失败", foreground="#C0392B")
            return None
        return token, mid, code, expires

    def _generate(self):
        result = self._make()
        if not result:
            return
        token, mid, code, expires = result
        path = filedialog.asksaveasfilename(
            title="保存授权文件",
            defaultextension=".lic",
            filetypes=[("授权文件", "*.lic")],
            initialfile=f"{code}_{mid}.lic",
        )
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps({"token": token, "license_code": code,
                            "machine_id": mid, "expires": expires},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            self.lbl_status.config(text=f"保存失败：{e}", foreground="#C0392B")
            return
        self.lbl_status.config(
            text=f"已生成：{path}\n机器码 {mid}，到期 {expires}", foreground="#2E7D32")

    def _copy_token(self):
        result = self._make()
        if not result:
            return
        token, mid, code, expires = result
        self.clipboard_clear()
        self.clipboard_append(token)
        self.lbl_status.config(
            text=f"令牌已复制到剪贴板（机器码 {mid}，到期 {expires}）",
            foreground="#2E7D32")


if __name__ == "__main__":
    # 防止误发：运行时打印密钥长度而非明文
    print(f"[授权生成器] 当前签发密钥长度 = {len(LICENSE_SECRET)} 字符"
          f"（必须与客户端 license_client.LICENSE_SECRET 一致）")
    GeneratorWindow().mainloop()
