# -*- coding: utf-8 -*-
"""
定向井设计工具箱 —— 多标签集成
==============================

标签页:
  1. 靶点提取      (源: 靶点提取工具.py)
  2. 综合数据表    (源: 综合数据表.py / SLB轨迹汇总.py)
  3. 防碰统计      (源: 防碰统计.py)
  4. 槽口图绘制    (源: VBA_004_槽口图绘制, 平台槽口图 + 反旋转坐标表)
  5. 寻找最优点    (源: 15-寻找最优点/寻找最优点参数.py)

每个标签页独立封装为 ttk.Frame 子类, MainWindow 通过 ttk.Notebook 承载.
统一 import / 统一主题 (clam) / 统一顶层 Banner, 各 tab 内部保持原有逻辑不变.
"""

import html
import json
import math
import os
import re
import sys
import glob
import queue
import datetime
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Circle, Rectangle
import matplotlib.pyplot as plt

# 全局中文字体 (matplotlib 默认 DejaVu Sans 不含中文)
plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "SimSun", "KaiTi",
    "Arial Unicode MS", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False  # 负号正常显示

from openpyxl import Workbook, load_workbook
from openpyxl.styles import (
    Alignment, Font, PatternFill, Border, Side,
)
from openpyxl.utils import get_column_letter

# xlrd 可选 (仅 .xls 格式需要)
try:
    import xlrd
except ImportError:
    xlrd = None

# 授权模块（机器绑定 + 网关校验）
from license_client import require_license, show_license_info


# ================================================================
# 公共: 主题 & 工具
# ================================================================
HEADER_BG = "#1F3864"     # 深蓝
THEME = "clam"            # 让 Treeview heading 背景色在 Windows 生效


def configure_global_style(root):
    style = ttk.Style(root)
    try:
        style.theme_use(THEME)
    except tk.TclError:
        pass
    style.configure(".", font=("Microsoft YaHei UI", 10))
    style.configure("Treeview", rowheight=26, font=("Microsoft YaHei UI", 10),
                    background="white", fieldbackground="white")
    style.map("Treeview", background=[("selected", "#D6E4F0")],
              foreground=[("selected", "black")])
    style.configure(
        "Treeview.Heading",
        background=HEADER_BG, foreground="white",
        font=("Microsoft YaHei UI", 10, "bold"),
        relief="solid", borderwidth=1,
        lightcolor="white", darkcolor="white",
        bordercolor="white", padding=(6, 4),
    )
    style.map("Treeview.Heading", background=[("active", HEADER_BG)])


def resource_path(rel):
    """PyInstaller 兼容"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# ================================================================
# 公共: MainWindow + Notebook
# ================================================================
class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("定向井设计工具箱")
        # 居中 + 主屏幕2/3大小
        # 用 ctypes 取主显示器真实分辨率（多显示器下 winfo_screenwidth 会返回虚拟桌面总宽度）
        try:
            import ctypes
            user32 = ctypes.windll.user32
            sw = user32.GetSystemMetrics(0)   # SM_CXSCREEN — 主显示器宽
            sh = user32.GetSystemMetrics(1)   # SM_CYSCREEN — 主显示器高
        except Exception:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
        w = max(int(sw / 1.5), 1280)
        h = max(int(sh / 1.5), 800)
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(1280, 800)
        # 下一帧再居中一次（闭包捕获本次 sw/sh，不再调 winfo_screen* 防重犯）
        self.after(100, lambda _sw=sw, _sh=sh, _w=w, _h=h: self.geometry(
            f"{_w}x{_h}+{(_sw-_w)//2}+{(_sh-_h)//2}"))
        try:                                    # 窗口图标 (打包后从 _MEIPASS 取)
            self.iconbitmap(resource_path("wj.ico"))
        except Exception:
            pass

        configure_global_style(self)

        # 顶层 Banner
        banner = tk.Frame(self, bg=HEADER_BG, height=46)
        banner.pack(fill="x", side="top")
        banner.pack_propagate(False)
        tk.Label(
            banner, text="定向井设计工具箱", bg=HEADER_BG, fg="white",
            font=("Microsoft YaHei UI", 15, "bold"),
        ).pack(side="left", padx=(14, 10), pady=8)
        tk.Label(
            banner, text="靶点提取 · 综合数据表 · 防碰统计 · 槽口图绘制 · 寻找最优点 免费使用不得作为商业用途",
            bg=HEADER_BG, fg="#BFD0EA",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", pady=8)
        tk.Label(
            banner, text="油技塘沽作业公司定向随钻业务线设计室开发 v1.0  ·  © 2026 王健",
            bg=HEADER_BG, fg="#8FA6C8",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right", padx=14, pady=8)
        tk.Button(
            banner, text="授权", relief="flat", bd=0,
            bg=HEADER_BG, fg="#E74C3C", activebackground=HEADER_BG,
            activeforeground="#FF6B6B", cursor="hand2",
            font=("Microsoft YaHei UI", 11, "bold"),
            command=lambda: show_license_info(self),
        ).pack(side="right", pady=8)

        # Notebook
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=(6, 8))

        # Tab 1: 靶点提取
        tab1 = TargetExtractTab(nb, self)
        nb.add(tab1, text="  ①  靶点提取  ")

        # Tab 2: 综合数据表
        self.tab_traj = TrajectorySummaryTab(nb, self)
        nb.add(self.tab_traj, text="  ②  综合数据表  ")

        # Tab 3: 防碰统计
        tab3 = AntiCollisionTab(nb, self)
        nb.add(tab3, text="  ③  防碰统计  ")

        # Tab 4: 槽口图绘制
        self.tab_slot = SlotMapTab(nb, self)
        nb.add(self.tab_slot, text="  ④  槽口图绘制  ")

        # Tab 5: 寻找最优点
        self.tab_mark = MarkPointTab(nb, self)
        nb.add(self.tab_mark, text="  ⑤  寻找最优点  ")

        # Tab 6: 槽口重命名
        self.tab_rename = SlotRenameTab(nb, self)
        nb.add(self.tab_rename, text="  ⑥  槽口重命名  ")

        # Tab 7: XML 处理
        self.tab_xml = XmlProcessTab(nb, self)
        nb.add(self.tab_xml, text="  ⑦  XML 处理  ")


# ================================================================
# ================================================================
# TAB 1. 靶点提取 (源: 靶点提取工具.py)
# ================================================================
# ================================================================
SUPPORTED_EXT = (".xlsx", ".xlsm", ".xltx", ".xltm", ".xls", ".txt")
HEADER_SCAN_ROWS = 10

TARGET_TAGS = (
    ("第一", "T1"), ("控制", "T1"), ("第二", "T2"), ("第三", "T3"),
    ("第四", "T4"), ("第五", "T5"), ("第六", "T6"),
)

# 英文表头（norm 后小写、无空格）：井名列 / 靶点深度列
EN_NAME_HEADERS = ("wellname", "well", "wellno", "well#")
EN_DEPTH_HEADERS = ("targetdepth", "tvdss", "tvd")


def norm(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u3000", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = re.sub(r"\s+", "", text)
    return text.replace("（", "(").replace("）", ")")


def clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u3000", " ")
    return re.sub(r"\s+", "", text)


def to_float(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = norm(value).replace(",", "").replace("，", "")
    if not text or text in ("-", "—", "/", "无"):
        return None
    try:
        return float(text)
    except ValueError:
        match = re.match(r"^-?\d+(?:\.\d+)?", text)
        return float(match.group()) if match else None


def fmt_num(value: float, digits: int = 3) -> str:
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def round_int(value: float) -> int:
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def cell(row, index: int):
    if 0 <= index < len(row):
        return row[index]
    return None


def read_xlsx(path):
    workbook = load_workbook(path, data_only=True)
    sheets = OrderedDict()
    try:
        for ws in workbook.worksheets:
            if ws.sheet_state != "visible":
                continue  # 跳过隐藏工作表（旧版/草稿，不列入下拉也不解析）
            data = [list(r) for r in ws.iter_rows(values_only=True)]
            # 合并单元格：非锚点格填充锚点值。read_only 模式会读出 XML 中
            # 残留的旧值（如井名旧命名），必须按 Excel 显示语义统一为锚点值
            for rng in ws.merged_cells.ranges:
                anchor = cell(data[rng.min_row - 1], rng.min_col - 1) if rng.min_row - 1 < len(data) else None
                for r in range(rng.min_row - 1, min(rng.max_row, len(data))):
                    for c in range(rng.min_col - 1, min(rng.max_col, len(data[r]))):
                        if r != rng.min_row - 1 or c != rng.min_col - 1:
                            data[r][c] = anchor
            sheets[ws.title] = data
    finally:
        workbook.close()
    return sheets


def read_xls(path):
    if xlrd is None:
        raise RuntimeError("未安装 xlrd, 请先 pip install xlrd==1.2.0")
    workbook = xlrd.open_workbook(path, on_demand=True)
    sheets = OrderedDict()
    try:
        for name in workbook.sheet_names():
            sheet = workbook.sheet_by_name(name)
            if getattr(sheet, "visibility", 0) != 0:
                continue  # 跳过隐藏工作表（0=可见, 1=隐藏, 2=深度隐藏）
            sheets[name] = [
                [sheet.cell_value(r, c) for c in range(sheet.ncols)]
                for r in range(sheet.nrows)
            ]
    finally:
        workbook.release_resources()
    return sheets


def read_workbook(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xls":
        return read_xls(path)
    return read_xlsx(path)


TXT_LINE_RE = re.compile(
    r"^(?P<name>[^:：]+?)\s*[:：]\s*"
    r"(?P<c1>[-+]?\d+(?:\.\d+)?)\s*[/／]\s*"
    r"(?P<c2>[-+]?\d+(?:\.\d+)?)\s*[/／]\s*"
    r"(?P<depth>[-+]*-?\d+(?:\.\d+)?)"
)


def read_text_file(path):
    with open(path, "rb") as handle:
        head = handle.read(4)
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16",)
    elif head.startswith(b"\xef\xbb\xbf"):
        encodings = ("utf-8-sig",)
    else:
        encodings = ("utf-8", "gb18030")
    for encoding in encodings:
        try:
            with open(path, "r", encoding=encoding) as handle:
                return handle.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def split_well_target(name):
    for separator in ("-", "－"):
        pos = name.rfind(separator)
        if 0 < pos < len(name) - 1:
            return name[:pos], name[pos + 1:]
    return name, ""


def _looks_like_northing(value):
    return 2_000_000 <= abs(value) <= 6_000_000


def orient_coords(c1, c2):
    if _looks_like_northing(c2) and not _looks_like_northing(c1):
        return c2, c1
    return c1, c2


def parse_text_content(text):
    records = []
    warnings = {"order": 0, "skipped": 0}
    for line in text.splitlines():
        raw = line.strip().lstrip("\ufeff")
        if not raw or raw.startswith("#") or raw.startswith("//"):
            continue
        match = TXT_LINE_RE.match(raw)
        if not match:
            warnings["skipped"] += 1
            continue
        name = re.sub(r"\s+", "", match.group("name"))
        depth_text = match.group("depth").replace("−", "-")
        depth_match = re.search(r"\d+(?:\.\d+)?", depth_text)
        if not name or not depth_match:
            warnings["skipped"] += 1
            continue
        depth = abs(float(depth_match.group()))  # 深度统一取正, 无论源文件正负
        c1 = float(match.group("c1"))
        c2 = float(match.group("c2"))
        north, east = orient_coords(c1, c2)
        if (north, east) != (c1, c2):
            warnings["order"] += 1
        well, target = split_well_target(name)
        records.append({"name": name, "well": well, "tag": target, "n": north, "e": east, "d": depth})
    return records, warnings


def parse_txt(path):
    return parse_text_content(read_text_file(path))


@dataclass
class Layout:
    name_cols: List[Tuple[int, str]]
    target_col: Optional[int]
    x_col: int
    y_col: int
    depth_col: int
    data_start: int
    seq_cols: List[int]
    # 无「靶点」标签列时按坐标列组解析: (x列, y列, 深度列, 组标题)
    groups: Optional[List[Tuple[int, int, int, str]]] = None


def _name_priority(header):
    if header.startswith("最终井名"):
        return 0
    if "按照平台命名" in header:
        return 1
    if "最终确定" in header:
        return 2
    if header == "井名":
        return 3
    if "原井名" in header or "原来井名" in header:
        return 4
    return 5


def _header_scan_limit(rows):
    limit = min(HEADER_SCAN_ROWS, len(rows))
    for r in range(limit):
        for value in rows[r]:
            # 只把「整格都是数字」的单元格视为数据行起点证据，
            # 避免 "20260311之前的井名" 这类以数字开头的表头被误判为坐标
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                number = float(value)
            elif isinstance(value, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", norm(value)):
                number = float(norm(value))
            else:
                continue
            if abs(number) >= 100_000:
                return r
    return limit


def detect_layout(rows):
    if not rows:
        return None
    name_cands = {}
    target_cands = []
    x_cols, y_cols, depth_cols = set(), set(), set()
    seq_cols = set()
    header_rows = set()
    group_hints = {}  # x 列 -> 其上方最近的分组标题（如 Point A）
    for r in range(_header_scan_limit(rows)):
        row = rows[r]
        for c, value in enumerate(row):
            text = norm(value)
            if not text:
                continue
            lower = text.lower()
            if text == "靶点":
                target_cands.append((0, c, r))
                header_rows.add(r)
            elif "靶点" in text and not any(k in text for k in ("深度", "数据", "名称", "层位", "坐标")):
                target_cands.append((1, c, r))
                header_rows.add(r)
            if ("井名" in text and "靶点" not in text) or lower in EN_NAME_HEADERS:
                priority = 3 if lower in EN_NAME_HEADERS else _name_priority(text)
                header = str(value).replace("\n", "").replace("\r", "").strip()
                if c not in name_cands or priority < name_cands[c][0]:
                    name_cands[c] = (priority, header)
                header_rows.add(r)
            if text.startswith("X") or "北坐标" in text:
                x_cols.add(c); header_rows.add(r)
                for up in range(r - 1, -1, -1):
                    hint = norm(cell(rows[up], c))
                    if hint:
                        group_hints[c] = hint
                        break
            if text.startswith("Y") or "东坐标" in text:
                y_cols.add(c); header_rows.add(r)
            if "靶点深度" in text or lower in EN_DEPTH_HEADERS:
                depth_cols.add(c); header_rows.add(r)
            if "序号" in text or text == "井号":
                seq_cols.add(c)
    if not target_cands and not (x_cols and y_cols and depth_cols and name_cands):
        return None
    name_cols = sorted(name_cands.items(), key=lambda item: (item[1][0], item[0]))
    name_cols = [(c, text or f"{get_column_letter(c + 1)}列") for c, (_, text) in name_cols]
    data_start = max(header_rows) + 1 if header_rows else min(4, len(rows))
    if target_cands:
        # 长表：存在「靶点」标签列，每行一个靶点
        target_col = min(target_cands, key=lambda item: (item[0], item[1]))[1]
        xs = sorted(x_cols)
        x_right = [c for c in xs if c > target_col]
        x_col = x_right[0] if x_right else (xs[0] if xs else target_col + 1)
        ys = sorted(c for c in y_cols if c > x_col)
        y_col = ys[0] if ys else x_col + 1
        depths = sorted(c for c in depth_cols if c > target_col)
        depth_col = depths[0] if depths else y_col + 1
        return Layout(name_cols=name_cols, target_col=target_col,
                      x_col=x_col, y_col=y_col, depth_col=depth_col,
                      data_start=data_start, seq_cols=sorted(seq_cols))
    # 无标签列：按 X/Y/深度 列组解析 —— 多组=靶点在同一行(宽表)，单组=同井多行
    xs = sorted(x_cols)
    ys_all = sorted(y_cols)
    ds_all = sorted(depth_cols)
    groups = []
    for i, xc in enumerate(xs):
        next_x = xs[i + 1] if i + 1 < len(xs) else None
        yc = next((y for y in ys_all if y > xc and (next_x is None or y < next_x)), None)
        if yc is None:
            continue
        dc = next((d for d in ds_all if d > yc and (next_x is None or d < next_x)), None)
        if dc is None:
            dc = next((d for d in ds_all if d > yc), None)
        if dc is None:
            continue
        groups.append((xc, yc, dc, group_hints.get(xc, "")))
    if not groups:
        return None
    return Layout(name_cols=name_cols, target_col=None,
                  x_col=groups[0][0], y_col=groups[0][1], depth_col=groups[0][2],
                  data_start=data_start, seq_cols=sorted(seq_cols), groups=groups)


def _group_tag(hint, index):
    """统一按列组序输出 T1、T2、T3…，忽略源表的 Point A/B 等命名"""
    return f"T{index + 1}"


def parse_sheet_groups(rows, layout, name_col):
    """无「靶点」标签列：一行多组 X/Y/深度（宽表）或同井多行（单组）"""
    records = []
    warnings = {"swapped": 0, "no_depth": 0, "no_coord": 0}
    current_name = ""
    seq = 0
    multi = len(layout.groups) > 1
    for r in range(layout.data_start, len(rows)):
        row = rows[r]
        name_text = clean_text(cell(row, name_col))
        if name_text:
            current_name = name_text
            seq = 0
        if not current_name:
            continue
        for index, (x_col, y_col, depth_col, hint) in enumerate(layout.groups):
            north = to_float(cell(row, x_col))
            east = to_float(cell(row, y_col))
            depth = to_float(cell(row, depth_col))
            if north is None or east is None:
                continue  # 该组无坐标（如只有 Point A），跳过
            if depth is None:
                warnings["no_depth"] += 1
                continue
            depth = abs(depth)  # 深度统一取正, 无论源文件正负
            if 100_000 <= north <= 1_000_000 and 3_000_000 <= east <= 5_500_000:
                north, east = east, north; warnings["swapped"] += 1
            if multi:
                tag = _group_tag(hint, index)
            else:
                seq += 1
                tag = f"T{seq}"
            records.append({"well": current_name, "tag": tag,
                            "n": north, "e": east, "d": depth})
    return records, warnings


def parse_sheet(rows, layout, name_col):
    if layout.groups:
        return parse_sheet_groups(rows, layout, name_col)
    records = []
    warnings = {"swapped": 0, "no_depth": 0, "no_coord": 0}
    current_name = ""
    seq = 0
    for r in range(layout.data_start, len(rows)):
        row = rows[r]
        name_text = clean_text(cell(row, name_col))
        target_text = clean_text(cell(row, layout.target_col))
        has_label = ("靶点" in target_text) or re.match(r"(?i)^T\d+$", target_text) is not None
        if not name_text and not has_label:
            continue
        is_new_well = (
            bool(name_text)
            or any(clean_text(cell(row, c)) for c in layout.seq_cols)
            or ("第一" in target_text) or ("控制" in target_text)
        )
        if name_text:
            current_name = name_text; seq = 0
        elif is_new_well:
            fallback = ""
            for c, _text in layout.name_cols:
                if c == name_col: continue
                fallback = clean_text(cell(row, c))
                if fallback: break
            if not fallback: continue
            current_name = fallback; seq = 0
        if not current_name:
            continue
        north = to_float(cell(row, layout.x_col))
        east = to_float(cell(row, layout.y_col))
        depth = to_float(cell(row, layout.depth_col))
        if north is None or east is None:
            if target_text: warnings["no_coord"] += 1
            continue
        if depth is None:
            warnings["no_depth"] += 1
            continue
        depth = abs(depth)  # 深度统一取正, 无论源文件正负
        if 100_000 <= north <= 1_000_000 and 3_000_000 <= east <= 5_500_000:
            north, east = east, north; warnings["swapped"] += 1
        tag = None
        for key, value in TARGET_TAGS:
            if key in target_text:
                tag = value; break
        if tag is None:
            match = re.search(r"(\d+)", target_text)
            tag = f"T{match.group(1)}" if match else f"T{seq + 1}"
        if tag.startswith("T") and tag[1:].isdigit():
            seq = int(tag[1:])
        else:
            seq += 1
        records.append({"well": current_name, "tag": tag, "n": north, "e": east, "d": depth})
    return records, warnings


class TargetExtractTab(ttk.Frame):
    """靶点提取 —— 由原 App(tk.Tk) 重构为 ttk.Frame"""

    def __init__(self, master, controller=None):
        super().__init__(master)
        self.today = datetime.datetime.now().strftime("%Y%m%d")
        self.var_path = tk.StringVar()
        self.var_suffix = tk.BooleanVar(value=False)
        self.var_round = tk.BooleanVar(value=False)
        self.var_status = tk.StringVar(value="请选择 Excel 或 TXT 文件，或在下方粘贴靶点内容")
        self.var_count = tk.StringVar(value="未生成")
        self.sheets = OrderedDict()
        self.current_sheet = ""
        self.label_to_col = {}
        self.records = []
        self._build_ui()
        self._update_buttons()

    # ---------- 布局 ----------
    def _build_ui(self):
        outer = ttk.Frame(self, padding=(12, 10, 12, 10))
        outer.pack(fill="both", expand=True)

        sec1 = ttk.LabelFrame(outer, text=" ① 选择文件（Excel / TXT）或粘贴文本 ", padding=(10, 8))
        sec1.pack(fill="x")

        line1 = ttk.Frame(sec1); line1.pack(fill="x")
        ttk.Label(line1, text="文件：").pack(side="left")
        ttk.Entry(line1, textvariable=self.var_path, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(line1, text="选择文件…", command=self.choose_file).pack(side="left")

        line2 = ttk.Frame(sec1); line2.pack(fill="x", pady=(8, 0))
        self.lbl_sheet = ttk.Label(line2, text="工作表：")
        self.cbo_sheet = ttk.Combobox(line2, state="readonly", width=34)
        self.cbo_sheet.bind("<<ComboboxSelected>>", self.on_sheet_change)
        self.lbl_namecol = ttk.Label(line2, text="井名列：")
        self.cbo_name = ttk.Combobox(line2, state="readonly", width=26)
        self.cbo_name.bind("<<ComboboxSelected>>", self.on_namecol_change)
        self.lbl_txt_hint = ttk.Label(
            line2,
            text="TXT / 粘贴内容直接解析「井名:坐标/坐标/深度」，无需选择工作表和井名列",
            foreground="#666666",
        )

        line3 = ttk.Frame(sec1); line3.pack(fill="x", pady=(8, 0))
        ttk.Label(line3, text="粘贴：").pack(side="left", anchor="n")
        self.txt_paste = tk.Text(
            line3, height=3, wrap="none", font=("Consolas", 9),
            relief="solid", borderwidth=1,
        )
        self.txt_paste.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(line3, text="识别并生成表格", command=self.parse_paste).pack(side="left", anchor="n")

        ttk.Label(sec1, textvariable=self.var_status, foreground="#666666",
                  wraplength=1100).pack(anchor="w", pady=(7, 0))

        sec2 = ttk.LabelFrame(outer, text=" ② 生成靶点区域表格 ", padding=(10, 8))
        sec2.pack(fill="both", expand=True, pady=(10, 0))

        head = tk.Frame(sec2, bg="#e8eef5"); head.pack(fill="x")
        tk.Checkbutton(
            head, text="是否后缀添加日期", variable=self.var_suffix,
            command=self.refresh_table, bg="#e8eef5", activebackground="#e8eef5",
            selectcolor="#e8eef5", font=("Microsoft YaHei UI", 10), anchor="w",
        ).pack(side="left", padx=(8, 4), pady=6)
        tk.Label(head, text=f"（{self.today}）", bg="#e8eef5", fg="#777777",
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Label(head, text="例：A64H-T1", bg="#e8eef5", fg="#888888",
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(18, 0))
        tk.Checkbutton(
            head, text="是否取整", variable=self.var_round,
            command=self.refresh_table, bg="#e8eef5", activebackground="#e8eef5",
            selectcolor="#e8eef5", font=("Microsoft YaHei UI", 10), anchor="w",
        ).pack(side="left", padx=(22, 4), pady=6)
        tk.Label(head, text="（坐标、深度四舍五入为整数）", bg="#e8eef5", fg="#777777",
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Label(head, textvariable=self.var_count, bg="#e8eef5", fg="#1f4e79",
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="right", padx=10)

        tree_wrap = ttk.Frame(sec2); tree_wrap.pack(fill="both", expand=True, pady=(0, 8))
        self.tree = ttk.Treeview(
            tree_wrap, columns=("name", "north", "east", "depth"),
            show="headings", selectmode="extended",
        )
        self.tree.heading("name", text="井名-T1")
        self.tree.heading("north", text="北坐标 X(N)")
        self.tree.heading("east", text="东坐标 Y(E)")
        self.tree.heading("depth", text="深度 (m)")
        self.tree.column("name", width=260, minwidth=170, anchor="w")
        self.tree.column("north", width=190, minwidth=140, anchor="center")
        self.tree.column("east", width=190, minwidth=140, anchor="center")
        self.tree.column("depth", width=130, minwidth=100, anchor="center")
        self.tree.tag_configure("odd", background="#f5f8fc")
        self.tree.tag_configure("even", background="#ffffff")
        vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_wrap.rowconfigure(0, weight=1); tree_wrap.columnconfigure(0, weight=1)

        bar = ttk.Frame(sec2); bar.pack(fill="x")
        self.btn_copy = ttk.Button(bar, text="复制表格", command=self.copy_table)
        self.btn_copy.pack(side="left")
        self.btn_export = ttk.Button(bar, text="导出 Excel", command=self.export_excel)
        self.btn_export.pack(side="left", padx=(8, 0))

    # ---------- 状态 ----------
    def _update_buttons(self):
        state = "normal" if self.records else "disabled"
        self.btn_copy.configure(state=state)
        self.btn_export.configure(state=state)

    # ---------- 文件 ----------
    def choose_file(self):
        path = filedialog.askopenfilename(
            title="选择靶点文件",
            filetypes=[
                ("支持的文件", "*.xlsx *.xlsm *.xls *.txt"),
                ("Excel 文件", "*.xlsx *.xlsm *.xls"),
                ("文本文件", "*.txt"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.load_file(path)

    def load_file(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext not in SUPPORTED_EXT:
            messagebox.showwarning("不支持的文件", "请选择 .xlsx / .xlsm / .xls / .txt 文件。")
            return
        self.var_status.set("正在读取文件…")
        self.update_idletasks()
        if ext == ".txt":
            self._load_txt(path); return
        try:
            raw_sheets = read_workbook(path)
        except Exception as exc:
            messagebox.showerror("读取失败", f"无法读取文件：\n{path}\n\n{exc}")
            return
        sheets = OrderedDict()
        for name, rows in raw_sheets.items():
            layout = detect_layout(rows)
            if layout and layout.name_cols:
                sheets[name] = {"rows": rows, "layout": layout}
        if not sheets:
            self.var_path.set(path)
            self.var_status.set("未找到含「井名 / 靶点」表头的工作表")
            messagebox.showwarning("未找到靶点", "未在任何工作表中找到「井名 / Well Name」及靶点坐标表头。")
            return
        self.sheets = sheets
        self.var_path.set(path)
        self.cbo_sheet["values"] = list(sheets.keys())
        self.cbo_sheet.current(0)
        self.on_sheet_change()

    def _load_txt(self, path):
        try:
            records, warnings = parse_txt(path)
        except Exception as exc:
            messagebox.showerror("读取失败", f"无法读取文件：\n{path}\n\n{exc}")
            return
        if not records:
            self.var_path.set(path)
            self.var_status.set("未识别到靶点")
            messagebox.showwarning("未识别到靶点", "示例格式：\nDd302h-A:21386628.2/4512562.2/-1500")
            return
        self.sheets = OrderedDict([(os.path.basename(path), {
            "txt": True, "records": records, "warnings": warnings,
        })])
        self.var_path.set(path)
        self.cbo_sheet["values"] = [os.path.basename(path)]
        self.cbo_sheet.current(0)
        self.on_sheet_change()

    def parse_paste(self):
        text = self.txt_paste.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showwarning("没有内容", "请先粘贴靶点内容。")
            return
        records, warnings = parse_text_content(text)
        if not records:
            messagebox.showwarning("未识别到靶点", "示例格式：\nDd302h-A:21386628.2/4512562.2/-1500")
            return
        self.sheets = OrderedDict([("粘贴内容", {
            "txt": True, "records": records, "warnings": warnings,
        })])
        self.var_path.set("（来自粘贴内容）")
        self.cbo_sheet["values"] = ["粘贴内容"]
        self.cbo_sheet.current(0)
        self.on_sheet_change()

    # ---------- 工作表 ----------
    def on_sheet_change(self, event=None):
        sheet = self.cbo_sheet.get()
        info = self.sheets.get(sheet)
        if not info: return
        self.current_sheet = sheet
        if info.get("txt"):
            self.label_to_col = {}; self.records = info["records"]
            for w in (self.lbl_sheet, self.cbo_sheet, self.lbl_namecol, self.cbo_name):
                w.pack_forget()
            self.lbl_txt_hint.pack(side="left")
            self.refresh_table()
            self._set_status(f"文件「{sheet}」", info.get("warnings", {}))
            return
        self.lbl_txt_hint.pack_forget()
        for w, kw in ((self.lbl_sheet, {}), (self.cbo_sheet, {"padx": (0, 18)}),
                     (self.lbl_namecol, {}), (self.cbo_name, {})):
            w.pack(side="left", **kw)
        layout = info["layout"]
        self.label_to_col = {}
        labels = []
        for col, text in layout.name_cols:
            label = text
            if label in self.label_to_col:
                label = f"{label}（{get_column_letter(col + 1)}列）"
            self.label_to_col[label] = col
            labels.append(label)
        self.cbo_name["values"] = labels
        if labels: self.cbo_name.current(0)
        self.parse_current()

    def on_namecol_change(self, event=None):
        self.parse_current()

    def parse_current(self):
        info = self.sheets.get(self.current_sheet)
        label = self.cbo_name.get()
        if not info or label not in self.label_to_col: return
        name_col = self.label_to_col[label]
        self.records, warnings = parse_sheet(info["rows"], info["layout"], name_col)
        self.refresh_table()
        self._set_status(f"工作表「{self.current_sheet}」", warnings)

    def _set_status(self, prefix, warnings):
        well_count = len({rec["well"] for rec in self.records})
        status = f"{prefix}：{len(self.records)} 个靶点，{well_count} 口井"
        extra = []
        if warnings.get("swapped"): extra.append(f"已纠正 X/Y 互换 {warnings['swapped']} 行")
        if warnings.get("order"):   extra.append(f"坐标按北/东自动归位 {warnings['order']} 行")
        if warnings.get("no_depth"):extra.append(f"缺深度跳过 {warnings['no_depth']} 行")
        if warnings.get("no_coord"): extra.append(f"缺坐标跳过 {warnings['no_coord']} 行")
        if warnings.get("skipped"): extra.append(f"跳过无法识别 {warnings['skipped']} 行")
        if extra: status += " ｜ " + "；".join(extra)
        self.var_status.set(status)

    # ---------- 表格 ----------
    def _display_name(self, record):
        name = record.get("name") or f'{record["well"]}-{record["tag"]}'
        if self.var_suffix.get():
            name += f"({self.today})"
        return name

    def _target_header(self):
        return "井名-靶点" if self.sheets.get(self.current_sheet, {}).get("txt") else "井名-T1"

    def _num_text(self, value):
        return str(round_int(value)) if self.var_round.get() else fmt_num(value)

    def _num_value(self, value):
        return round_int(value) if self.var_round.get() else round(value, 3)

    def refresh_table(self):
        self.tree.heading("name", text=self._target_header())
        self.tree.delete(*self.tree.get_children())
        for index, record in enumerate(self.records):
            self.tree.insert(
                "", "end",
                values=(self._display_name(record),
                        self._num_text(record["n"]),
                        self._num_text(record["e"]),
                        self._num_text(record["d"])),
                tags=("odd",) if index % 2 else ("even",),
            )
        self.var_count.set(f"{len(self.records)} 条靶点" if self.records else "未生成")
        self._update_buttons()

    def _table_rows(self):
        header = (self._target_header(), "北坐标", "东坐标", "深度")
        rows = [header]
        for record in self.records:
            rows.append((self._display_name(record),
                         self._num_text(record["n"]),
                         self._num_text(record["e"]),
                         self._num_text(record["d"])))
        return rows

    def copy_table(self):
        if not self.records: return
        text = "\n".join("\t".join(row) for row in self._table_rows())
        self.clipboard_clear(); self.clipboard_append(text); self.update()
        self.var_status.set(f"已复制 {len(self.records)} 条靶点到剪贴板")

    def export_excel(self):
        if not self.records: return
        base_name = self.current_sheet
        if self.sheets.get(base_name, {}).get("txt"):
            base_name = os.path.splitext(base_name)[0]
        safe_sheet = re.sub(r'[\\/:*?"<>|]', "_", base_name)
        default_name = f"靶点区域表格_{safe_sheet}_{self.today}.xlsx"
        path = filedialog.asksaveasfilename(
            title="导出靶点区域表格", defaultextension=".xlsx",
            initialfile=default_name, filetypes=[("Excel 文件", "*.xlsx")],
        )
        if not path: return
        if not path.lower().endswith(".xlsx"): path += ".xlsx"
        wb = Workbook(); ws = wb.active; ws.title = "靶点区域表格"
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="4472C4")
        center = Alignment(horizontal="center", vertical="center")
        for col, title in enumerate((self._target_header(), "北坐标", "东坐标", "深度"), start=1):
            cell = ws.cell(row=1, column=col, value=title)
            cell.font = header_font; cell.fill = header_fill; cell.alignment = center
        for row_index, record in enumerate(self.records, start=2):
            ws.cell(row=row_index, column=1, value=self._display_name(record))
            ws.cell(row=row_index, column=2, value=self._num_value(record["n"]))
            ws.cell(row=row_index, column=3, value=self._num_value(record["e"]))
            ws.cell(row=row_index, column=4, value=self._num_value(record["d"]))
        for col, width in zip("ABCD", (28, 18, 18, 12)):
            ws.column_dimensions[col].width = width
        ws.freeze_panes = "A2"
        try:
            wb.save(path)
        except Exception as exc:
            messagebox.showerror("导出失败", f"无法保存文件：\n{path}\n\n{exc}"); return
        self.var_status.set(f"已导出：{path}")
        messagebox.showinfo("导出完成", f"共导出 {len(self.records)} 条靶点：\n{path}")


# ================================================================
# ================================================================
# TAB 2. 综合数据表 (SLB 轨迹汇总)
# ================================================================
# ================================================================
MIN_INC_GAIN = 2.0
MIN_SEC_LEN  = 20.0
_COL_MD, _COL_INC, _COL_AZI, _COL_TVD = 0, 1, 2, 3
_COL_CLOSED, _COL_DLS = 8, 10
_COL_EAST, _COL_NORTH = 11, 12


def slb_parse_txt(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [l.rstrip("\n") for l in f.readlines()]
    slot = ""
    m = re.search(r"SlotName:\s*(.+)", lines[0])
    if m: slot = m.group(1).strip()
    rows = []
    for line in lines[7:]:
        parts = line.split()
        if len(parts) < 11: continue
        try:
            row = [float(x) for x in parts[:13]]
            row.append(parts[13] if len(parts) > 13 else "")
            rows.append(row)
        except ValueError:
            continue
    return slot, rows


def slb_detect_build_segments(rows):
    n = len(rows)
    sMD, eMD = [], []
    sInc, eInc = [], []
    eAzi, eDls = [], []
    mark_azi = 0.0
    closed = [False] * 300
    for i in range(1, n):
        dls_prev = rows[i - 1][_COL_DLS]
        dls_cur  = rows[i][_COL_DLS]
        if dls_cur != 0 and dls_prev == 0:
            idx = len(sMD)
            sMD.append(rows[i - 1][_COL_MD])
            sInc.append(rows[i - 1][_COL_INC])
            closed.append(False)
            if idx == 0 and i + 1 < n:
                mark_azi = rows[i + 1][_COL_AZI]
        if dls_cur == 0 and dls_prev != 0:
            if sMD and not closed[len(sMD) - 1]:
                k = len(sMD) - 1
                eMD.append(rows[i - 1][_COL_MD])
                eInc.append(rows[i - 1][_COL_INC])
                eAzi.append(rows[i - 1][_COL_AZI])
                eDls.append(rows[i - 1][_COL_DLS])
                closed[k] = True
    nSeg = len(sMD)
    if nSeg > 0 and not closed[nSeg - 1]:
        eMD.append(rows[-1][_COL_MD])
        eInc.append(rows[-1][_COL_INC])
        eAzi.append(rows[-1][_COL_AZI])
        eDls.append(rows[-1][_COL_DLS])
    return dict(nSeg=nSeg, sMD=sMD, eMD=eMD, sInc=sInc, eInc=eInc,
                eAzi=eAzi, eDls=eDls, markAzi=mark_azi)


def slb_summarize_well(well_name, slot, rows):
    if len(rows) < 3: return None
    segs = slb_detect_build_segments(rows)
    nSeg = segs["nSeg"]
    last = rows[-1]
    well_md = last[_COL_MD]
    well_tvd = last[_COL_TVD]
    clos_dist = last[_COL_CLOSED]
    water_tvd = round(clos_dist / well_tvd, 2) if well_tvd != 0 else None
    # 井口坐标: 取井深 0 (即 TXT 里 "0 0 0" 那一行) 的 Easting / Northing, 保留两位小数
    head = next((r for r in rows if r[_COL_MD] == 0), rows[0])
    rec = dict(
        井名=well_name, 井深=well_md, 垂深=well_tvd,
        水平段长=None, 水垂比=water_tvd, 槽口=slot,
        井口Easting=round(head[_COL_EAST], 2),
        井口Northing=round(head[_COL_NORTH], 2),
    )
    if nSeg >= 1:
        FirstSeg = 0
        LastSeg  = nSeg - 1
        for i in range(nSeg - 1, -1, -1):
            if ((segs["eInc"][i] - segs["sInc"][i]) >= MIN_INC_GAIN
                    and (segs["eMD"][i] - segs["sMD"][i]) >= MIN_SEC_LEN):
                LastSeg = i; break
        rec["第一造斜段_造斜点"]     = segs["sMD"][FirstSeg]
        rec["第一造斜段_结束点"]     = round(segs["eMD"][FirstSeg], 2)
        rec["第一造斜段_全角变化率"] = segs["eDls"][FirstSeg]
        rec["最后造斜段_造斜点"]     = round(segs["sMD"][LastSeg], 2)
        rec["最后造斜段_结束点"]     = round(segs["eMD"][LastSeg], 2)
        rec["最后造斜段_全角变化率"] = segs["eDls"][LastSeg]
        rec["井斜"] = f"{segs['eInc'][FirstSeg]:g}→{segs['eInc'][LastSeg]:g}"
        rec["扭方位"] = f"{segs['eAzi'][FirstSeg]:g}→{segs['eAzi'][LastSeg]:g}"
        if segs["eInc"][LastSeg] > 85:
            rec["水平段长"] = round(well_md - segs["eMD"][LastSeg], 2)
        rec["备注"] = f"{nSeg}段造斜,初始定向方位:{segs['markAzi']:g}°"
    return rec


SLB_COL_ORDER = [
    "井名", "井深",
    "第一造斜段_造斜点", "第一造斜段_结束点", "第一造斜段_全角变化率",
    "最后造斜段_造斜点", "最后造斜段_结束点", "最后造斜段_全角变化率",
    "井斜", "扭方位", "垂深", "水平段长", "水垂比",
    "槽口", "备注", "井口Easting", "井口Northing",
]
SLB_COL_WIDTHS = [220, 90, 90, 100, 120, 100, 100, 120, 90, 100, 80, 90, 80, 70, 180, 140, 140]


def slb_build_summary(folder):
    txts = sorted(glob.glob(os.path.join(folder, "*.txt")))
    records, skipped = [], []
    for txt in txts:
        base = os.path.basename(txt)
        well_name = base.replace("-", "_").rsplit(".", 1)[0][:31]
        try:
            slot, rows = slb_parse_txt(txt)
        except Exception as exc:
            skipped.append((well_name, f"解析异常: {exc}")); continue
        rec = slb_summarize_well(well_name, slot, rows)
        if rec is None:
            skipped.append((well_name, "数据行不足 3 行"))
        else:
            records.append(rec)
    return records, skipped


def slb_cell_text(rec, key):
    v = rec.get(key)
    if v is None: return ""
    if isinstance(v, float):
        if key in ("井深", "垂深", "水平段长", "水垂比",
                   "井口Easting", "井口Northing"):
            return f"{v:.2f}"
        return f"{v:g}"
    return str(v)


def slb_export_excel(records, path):
    wb = Workbook(); ws = wb.active; ws.title = "统计结果"
    header_fill = PatternFill("solid", fgColor="1F3864")
    header_font = Font(bold=True, color="FFFFFF", name="Microsoft YaHei UI", size=10)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    body_font = Font(name="Microsoft YaHei UI", size=10)
    thin = Side(border_style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for c, title in enumerate(SLB_COL_ORDER, start=1):
        cell = ws.cell(row=1, column=c, value=title)
        cell.fill = header_fill; cell.font = header_font
        cell.alignment = center; cell.border = border
    for r, rec in enumerate(records, start=2):
        for c, key in enumerate(SLB_COL_ORDER, start=1):
            cell = ws.cell(row=r, column=c, value=slb_cell_text(rec, key))
            cell.font = body_font; cell.alignment = center; cell.border = border
    widths = [26, 10, 12, 12, 14, 12, 12, 14, 10, 12, 10, 12, 10, 8, 22, 16, 16]
    for c, w in enumerate(widths):
        ws.column_dimensions[get_column_letter(c + 1)].width = w
    ws.row_dimensions[1].height = 26
    ws.freeze_panes = "A2"
    wb.save(path)


class TrajectorySummaryTab(ttk.Frame):
    """综合数据表 —— SLB 轨迹汇总"""

    def __init__(self, master, controller=None):
        super().__init__(master)
        self.today = datetime.datetime.now().strftime("%Y%m%d")
        self.var_folder = tk.StringVar()
        self.var_status = tk.StringVar(value="请选择轨迹 txt 所在文件夹")
        self.var_count  = tk.StringVar(value="未分析")
        self.records = []; self.folder = ""
        self._build_ui()

    def _build_ui(self):
        outer = ttk.Frame(self, padding=(12, 10, 12, 10))
        outer.pack(fill="both", expand=True)

        sec1 = ttk.LabelFrame(outer, text=" ① 选择轨迹文件夹 ", padding=(10, 8))
        sec1.pack(fill="x")
        line = ttk.Frame(sec1); line.pack(fill="x")
        ttk.Label(line, text="文件夹：").pack(side="left")
        ttk.Entry(line, textvariable=self.var_folder, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(line, text="选择文件夹…", command=self.choose_folder).pack(side="left")
        ttk.Button(line, text="开始分析", command=self.analyze).pack(side="left", padx=(8, 0))
        ttk.Label(sec1, textvariable=self.var_status, foreground="#666666").pack(anchor="w", pady=(7, 0))

        sec2 = ttk.LabelFrame(outer, text=" ② 统计结果预览 ", padding=(10, 8))
        sec2.pack(fill="both", expand=True, pady=(10, 0))
        head = tk.Frame(sec2, bg="#e8eef5"); head.pack(fill="x")
        tk.Label(
            head,
            text="说明：造斜段依据 DLS 0→非0 起、非0→0 止；末段 DLS 未回落用井底闭合；最后造斜段倒序取 Δinc≥2° 且 ΔMD≥20m 的首段。",
            bg="#e8eef5", fg="#777777", font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=10, pady=6)
        tk.Label(head, textvariable=self.var_count, bg="#e8eef5", fg="#1f4e79",
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="right", padx=10)

        tree_wrap = ttk.Frame(sec2); tree_wrap.pack(fill="both", expand=True, pady=(0, 8))
        ids = [f"c{i}" for i in range(len(SLB_COL_ORDER))]
        self.tree = ttk.Treeview(tree_wrap, columns=ids, show="headings", selectmode="extended")
        for tid, title, width in zip(ids, SLB_COL_ORDER, SLB_COL_WIDTHS):
            self.tree.heading(tid, text=title)
            self.tree.column(tid, width=width, minwidth=60, anchor="center")
        self.tree.tag_configure("odd", background="#f5f8fc")
        self.tree.tag_configure("even", background="#ffffff")
        vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_wrap.rowconfigure(0, weight=1); tree_wrap.columnconfigure(0, weight=1)

        bar = ttk.Frame(sec2); bar.pack(fill="x")
        self.btn_copy = ttk.Button(bar, text="复制表格", command=self.copy_table)
        self.btn_copy.pack(side="left")
        self.btn_export = ttk.Button(bar, text="导出 Excel", command=self.do_export)
        self.btn_export.pack(side="left", padx=(8, 0))
        self._update_buttons()

    def _update_buttons(self):
        state = "normal" if self.records else "disabled"
        self.btn_copy.configure(state=state)
        self.btn_export.configure(state=state)

    def choose_folder(self):
        path = filedialog.askdirectory(title="请选取轨迹txt 所在文件夹")
        if path:
            self.var_folder.set(path)
            self.var_status.set(f"已选文件夹：{path}  ——  点击「开始分析」生成汇总表")

    def analyze(self):
        folder = self.var_folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("请先选择文件夹", "请先选中存放 .txt 轨迹文件的文件夹。"); return
        self.var_status.set("正在扫描 .txt 文件并识别造斜段…"); self.update_idletasks()
        records, skipped = slb_build_summary(folder)
        self.folder = folder; self.records = records
        self.tree.delete(*self.tree.get_children())
        for i, rec in enumerate(records):
            values = [slb_cell_text(rec, k) for k in SLB_COL_ORDER]
            self.tree.insert("", "end", values=values, tags=("odd",) if i % 2 else ("even",))
        extra = f" ｜ 跳过 {len(skipped)} 口" if skipped else ""
        self.var_status.set(
            f"共扫描 {len(glob.glob(os.path.join(folder, '*.txt')))} 个 txt，"
            f"汇总 {len(records)} 口井{extra}")
        self.var_count.set(f"共 {len(records)} 口井" if records else "未生成")
        if skipped:
            messagebox.showwarning(
                "部分井被跳过",
                "以下文件未参与汇总：\n\n"
                + "\n".join(f"  · {n} —— {msg}" for n, msg in skipped[:15]))
        self._update_buttons()

    def copy_table(self):
        if not self.records: return
        rows = [SLB_COL_ORDER]
        for rec in self.records:
            rows.append([slb_cell_text(rec, k) for k in SLB_COL_ORDER])
        text = "\n".join("\t".join(r) for r in rows)
        self.clipboard_clear(); self.clipboard_append(text); self.update()
        self.var_status.set(f"已复制 {len(self.records)} 行数据到剪贴板")

    def do_export(self):
        if not self.records: return
        default = f"钻井轨迹汇总_带坐标_{self.today}.xlsx"
        path = filedialog.asksaveasfilename(
            title="导出统计结果 Excel", defaultextension=".xlsx",
            initialdir=self.folder or "", initialfile=default,
            filetypes=[("Excel 文件", "*.xlsx")])
        if not path: return
        if not path.lower().endswith(".xlsx"): path += ".xlsx"
        try:
            slb_export_excel(self.records, path)
        except Exception as exc:
            messagebox.showerror("导出失败", f"{exc}"); return
        self.var_status.set(f"已导出：{path}")
        messagebox.showinfo("导出完成", f"共 {len(self.records)} 口井：\n{path}")


# ================================================================
# ================================================================
# TAB 3. 防碰统计
# ================================================================
# ================================================================
_F_LIMIT = 2.0
_F_ZERO  = 1.2
_SHALLOW = 300.0
_DIST_BANDS = [(300.0, 1.50), (500.0, 5.00), (1000.0, 10.00)]
_DIST_DEFAULT = 20.00

COL_MD, COL_TVD, COL_OMD, COL_OTVD = 0, 1, 2, 3
COL_HIGHSIDE, COL_CENTRES, COL_SF = 6, 11, 14


def dist_limit(md, cfg):
    for lim, dist in cfg["dist_bands"]:
        if md < lim: return dist
    return cfg["dist_default"]


def num(v):
    if isinstance(v, float) or isinstance(v, int): return float(v)
    s = str(v).strip().replace(",", "")
    if not s: return None
    try: return float(s)
    except ValueError: return None


def parse_well_name(txt):
    parts = [p.strip() for p in txt.split(" - ")]
    parts = [p for p in parts if p][1:]
    out = []
    for p in parts:
        if not out or out[-1] != p: out.append(p)
    name = " ".join(out)
    sub = name.split(" ")
    if len(sub) == 2 and sub[0].startswith(sub[1]): name = sub[1]
    return name


def open_sheet(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xls":
        if xlrd is None:
            raise RuntimeError("未安装 xlrd, 请先 pip install xlrd==1.2.0")
        sh = xlrd.open_workbook(path).sheet_by_index(0)
        return lambda r, c: sh.cell_value(r, c), sh.nrows
    ws = load_workbook(path, data_only=True).worksheets[0]
    return lambda r, c: ws.cell(row=r + 1, column=c + 1).value, ws.max_row


def read_report(path):
    cell, nrows = open_sheet(path)
    ref_well = ""
    for r in range(min(nrows, 80)):
        if "Reference Wellbore" in str(cell(r, 0)):
            ref_well = str(cell(r, 3)).strip(); break
    if not ref_well:
        ref_well = os.path.splitext(os.path.basename(path))[0]
    sections = {}
    cur = None
    for r in range(nrows):
        head_txt = " ".join(str(cell(r, c)) for c in range(3))
        if "Offset Design" in head_txt:
            desc = ""
            for c in range(3):
                v = str(cell(r, c)).strip()
                if v and "Offset Design" not in v: desc = v; break
            name = parse_well_name(desc) if desc else "未知名"
            cur = name; sections.setdefault(name, []); continue
        if cur is None: continue
        md, tvd, omd = num(cell(r, COL_MD)), num(cell(r, COL_TVD)), num(cell(r, COL_OMD))
        if md is None or tvd is None or omd is None: continue
        sections[cur].append(dict(
            md=md, tvd=tvd, omd=omd, otvd=num(cell(r, COL_OTVD)),
            hs=num(cell(r, COL_HIGHSIDE)),
            centres=num(cell(r, COL_CENTRES)), sf=num(cell(r, COL_SF)),
        ))
    return ref_well, sections


def ac_analyze(sections, cfg):
    shallow_md = cfg["shallow_md"]
    sf_limit = cfg["sf_limit"]
    sf_zero_limit = cfg["sf_zero_limit"]
    glitch_md = cfg.get("glitch_md", 0.0)
    results, excluded = [], []
    for name, rows in sections.items():
        if not rows: continue
        # 毛刺过滤：井深 > 200m 且最近距离 < glitch_md 的扫点（深层 CC→0 尖刺）不参与统计
        if glitch_md > 0:
            rows = [x for x in rows
                    if x["md"] is not None and x["md"] <= 200
                       or x["centres"] is None
                       or abs(x["centres"]) >= glitch_md]
            if not rows:
                excluded.append((name, f"所有扫点最近距离均小于毛刺 {glitch_md}m")); continue
        zero_shallow = any(
            x["md"] < shallow_md and x["centres"] is not None and abs(x["centres"]) < 0.005
            for x in rows)
        if zero_shallow:
            cand = [x for x in rows if x["md"] > shallow_md
                    and x["sf"] is not None and x["sf"] < sf_zero_limit]
            skip_reason = f"{shallow_md:.0f}m前中心距为0, 但{shallow_md:.0f}m后无SF<{sf_zero_limit}的点"
        else:
            cand = [x for x in rows
                    if (x["sf"] is not None and x["sf"] < sf_limit)
                    or (x["centres"] is not None and x["centres"] < dist_limit(x["md"], cfg))]
            skip_reason = f"无SF<{sf_limit}或中心距小于阈值的点"
        if not cand:
            excluded.append((name, skip_reason)); continue
        best = min(cand, key=lambda x: x["sf"] if x["sf"] is not None else float("inf"))
        dvd = (best["otvd"] - best["tvd"]) if best["otvd"] is not None else None
        remark = ""
        if zero_shallow: remark = "同槽口设计分析深层防碰"
        elif best["sf"] is None or best["sf"] >= sf_limit:
            remark = f"按中心距阈值({dist_limit(best['md'], cfg)}m)统计"
        if best["sf"] is not None and best["sf"] < 1.0 and dvd is not None:
            abs_dvd = abs(dvd)
            if abs_dvd < 20: sf_remark = "SF<1，垂差小于20"
            elif abs_dvd < 30: sf_remark = "SF<1,垂差大于20，注意井斜"
            else: sf_remark = "垂差大于30m"
            remark = f"{remark}; {sf_remark}" if remark else sf_remark
        results.append(dict(
            name=name, md=best["md"], tvd=best["tvd"],
            omd=best["omd"], otvd=best["otvd"], dvd=dvd,
            hs=best["hs"], centres=best["centres"], sf=best["sf"],
            remark=remark,
        ))
    results.sort(key=lambda x: x["sf"] if x["sf"] is not None else float("inf"))
    return results, excluded


def ac_write_excel(all_results, out_path):
    wb = Workbook(); ws = wb.active; ws.title = "防碰分析汇总"
    headers = ["本井", "邻井井名", "本井井深", "本井垂深", "邻井井深", "邻井垂深",
               "垂深差", "HighSide", "最近距离", "分离系数", "备注"]
    thin = Side(style="thin"); border = Border(left=thin, right=thin, top=thin, bottom=thin)
    fills = [(1.0, PatternFill("solid", fgColor="FFC7CE")),
             (1.25, PatternFill("solid", fgColor="FFEB9C")),
             (1.5, PatternFill("solid", fgColor="BDD7EE"))]
    center = Alignment(horizontal="center", vertical="center")
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True); cell.alignment = center; cell.border = border
    for ref_well, items in all_results:
        start = ws.max_row + 1
        for it in items:
            ws.append([ref_well, it["name"], it["md"], it["tvd"], it["omd"], it["otvd"],
                       it["dvd"], it["hs"], it["centres"], it["sf"], it["remark"]])
            r = ws.max_row
            for c in range(1, len(headers) + 1):
                cell = ws.cell(row=r, column=c); cell.border = border
                if 3 <= c <= 10:
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    cell.number_format = "0.000" if c == 10 else "#,##0.00"
            sf_cell = ws.cell(row=r, column=10)
            if it["sf"] is not None:
                for lim, fill in fills:
                    if it["sf"] < lim:
                        sf_cell.fill = fill; break
            if it["sf"] is not None and it["sf"] < 1.0 \
                    and it["dvd"] is not None and abs(it["dvd"]) < 20:
                ws.cell(row=r, column=11).fill = PatternFill("solid", fgColor="FFC7CE")
        end = ws.max_row
        ws.cell(row=start, column=1).alignment = center
        if end > start:
            ws.merge_cells(start_row=start, start_column=1, end_row=end, end_column=1)
    widths = [10, 30, 11, 11, 11, 11, 10, 10, 11, 10, 30]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    try:
        wb.save(out_path)
    except PermissionError:
        alt = out_path.replace(".xlsx", datetime.datetime.now().strftime("_%Y%m%d_%H%M%S.xlsx"))
        wb.save(alt); out_path = alt
    return out_path


_AC_DEFAULT_CFG = dict(
    sf_limit=_F_LIMIT, sf_zero_limit=_F_ZERO, shallow_md=_SHALLOW,
    dist_bands=[list(x) for x in _DIST_BANDS], dist_default=_DIST_DEFAULT,
    glitch_md=0.1,
)


class AntiCollisionTab(ttk.Frame):
    """防碰统计 —— Compass 防碰报告分析"""

    COLUMNS = [
        ("本井", 70), ("邻井井名", 150), ("本井井深", 70), ("本井垂深", 70),
        ("邻井井深", 70), ("邻井垂深", 70), ("垂深差", 64),
        ("HighSide", 70), ("最近距离", 70), ("分离系数", 70), ("备注", 220),
    ]

    def __init__(self, master, controller=None):
        super().__init__(master)
        self.files = []
        self.all_results = []
        self.cfg = dict(_AC_DEFAULT_CFG)
        self.cfg["dist_bands"] = [list(x) for x in _DIST_BANDS]
        self.band_vars = []
        self.default_var = None
        self._build_ui()

    def _build_ui(self):
        outer = ttk.Frame(self, padding=(12, 10, 12, 10))
        outer.pack(fill="both", expand=True)

        # 工具栏
        tool = ttk.Frame(outer); tool.pack(fill="x")
        ttk.Button(tool, text="添加文件", command=self.add_files).pack(side="left", padx=4)
        ttk.Button(tool, text="移除选中", command=self.remove_selected).pack(side="left", padx=2)
        ttk.Button(tool, text="清空", command=self.clear_files).pack(side="left", padx=2)
        ttk.Button(tool, text="开始分析", command=self.analyze_all).pack(side="right", padx=2)
        ttk.Button(tool, text="生成汇总报告", command=self.generate_report).pack(side="right", padx=4)

        tk.Label(outer, text="防碰报告文件", anchor="w",
                 font=("Microsoft YaHei UI", 9, "bold")).pack(fill="x", pady=(6, 2))
        file_frame = tk.Frame(outer, bg="#808080", bd=1, relief="solid")
        file_frame.pack(fill="x", pady=(0, 8))
        self.file_listbox = tk.Listbox(
            file_frame, height=4, selectmode=tk.EXTENDED,
            relief="flat", font=("Consolas", 9))
        self.file_listbox.pack(fill="both", expand=True, padx=1, pady=1)

        # 主体: 左参数 + 右结果
        body = ttk.Frame(outer); body.pack(fill="both", expand=True)
        self._build_params(body)
        self._build_results(body)

        # 日志
        tk.Label(outer, text="日志", anchor="w",
                 font=("Microsoft YaHei UI", 9, "bold")).pack(fill="x", pady=(8, 2))
        log_frame = tk.Frame(outer, bg="#808080", bd=1, relief="solid")
        log_frame.pack(fill="both", expand=True, pady=(0, 4))
        self.log_text = tk.Text(
            log_frame, height=8, relief="flat", font=("Consolas", 9),
            bg="white", wrap="none")
        log_scroll = tk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True, padx=1, pady=1)

    def _build_params(self, parent):
        left = tk.Frame(parent, bg="#F0F0F0", width=320)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        tk.Label(left, text="统计参数", bg="#F0F0F0", anchor="w",
                 font=("Microsoft YaHei UI", 9, "bold")).pack(fill="x", pady=(0, 6))
        self.sf_limit_var = self._row(left, "分离系数阈值 SF <", _AC_DEFAULT_CFG["sf_limit"])
        self.sf_zero_var  = self._row(left, "同槽口深层 SF <",   _AC_DEFAULT_CFG["sf_zero_limit"])
        self.shallow_var  = self._row(left, "浅层界限 (m)",      _AC_DEFAULT_CFG["shallow_md"])

        tk.Frame(left, bg="#A0A0A0", height=1).pack(fill="x", padx=4, pady=10)
        tk.Label(left, text="中心距阈值表 (井深<上限)", bg="#F0F0F0", anchor="w",
                 font=("Microsoft YaHei UI", 9)).pack(fill="x")
        for lim, dist in _DIST_BANDS:
            self._band_row(left, lim, dist)
        self.default_var = self._row(left, "其余井深阈值 (m)", _DIST_DEFAULT)
        self.glitch_var  = self._row(left, "毛刺 (m)",        _AC_DEFAULT_CFG["glitch_md"])

        ttk.Button(left, text="恢复默认", command=self.restore_default).pack(fill="x", padx=2, pady=10)

    def _row(self, parent, label, value):
        frame = tk.Frame(parent, bg="#F0F0F0"); frame.pack(fill="x", padx=2, pady=3)
        tk.Label(frame, text=label, bg="#F0F0F0", font=("Microsoft YaHei UI", 9),
                 width=16, anchor="w").pack(side="left")
        var = tk.StringVar(value=str(value))
        tk.Entry(frame, textvariable=var, width=8, relief="solid", bd=1,
                 font=("Consolas", 9)).pack(side="left", padx=(4, 0))
        return var

    def _band_row(self, parent, lim, dist):
        frame = tk.Frame(parent, bg="#F0F0F0"); frame.pack(fill="x", padx=2, pady=3)
        tk.Label(frame, text="井深 <", bg="#F0F0F0", font=("Microsoft YaHei UI", 9)).pack(side="left")
        lim_var = tk.StringVar(value=str(lim))
        tk.Entry(frame, textvariable=lim_var, width=6, relief="solid", bd=1,
                 font=("Consolas", 9)).pack(side="left", padx=2)
        tk.Label(frame, text="m 阈值", bg="#F0F0F0",
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(4, 0))
        dist_var = tk.StringVar(value=str(dist))
        tk.Entry(frame, textvariable=dist_var, width=6, relief="solid", bd=1,
                 font=("Consolas", 9)).pack(side="left", padx=2)
        self.band_vars.append((lim_var, dist_var))

    def _build_results(self, parent):
        right = tk.Frame(parent, bg="#808080", bd=1, relief="solid")
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        cols = [c[0] for c in self.COLUMNS]
        widths = [c[1] for c in self.COLUMNS]
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=15)
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center", minwidth=50)
        self.tree.tag_configure("sf_red", background="#FFC7CE")
        self.tree.tag_configure("sf1_mark", background="#FF9999")
        self.tree.tag_configure("sf_yellow", background="#FFEB9C")
        self.tree.tag_configure("sf_blue", background="#BDD7EE")
        self.tree.tag_configure("sf_none", background="white")
        vsb = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(right, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        right.rowconfigure(0, weight=1); right.columnconfigure(0, weight=1)

    def read_cfg(self):
        try:
            bands = [(float(lim.get()), float(dist.get())) for lim, dist in self.band_vars]
            return dict(
                sf_limit=float(self.sf_limit_var.get()),
                sf_zero_limit=float(self.sf_zero_var.get()),
                shallow_md=float(self.shallow_var.get()),
                dist_bands=bands,
                dist_default=float(self.default_var.get()),
                glitch_md=float(self.glitch_var.get()),
            )
        except ValueError as e:
            raise ValueError(f"参数填写有误: {e}")

    def restore_default(self):
        self.sf_limit_var.set(str(_AC_DEFAULT_CFG["sf_limit"]))
        self.sf_zero_var.set(str(_AC_DEFAULT_CFG["sf_zero_limit"]))
        self.shallow_var.set(str(_AC_DEFAULT_CFG["shallow_md"]))
        for (lim_var, dist_var), (lim, dist) in zip(self.band_vars, _DIST_BANDS):
            lim_var.set(str(lim)); dist_var.set(str(dist))
        self.default_var.set(str(_DIST_DEFAULT))
        self.glitch_var.set(str(_AC_DEFAULT_CFG["glitch_md"]))
        self.log("已恢复默认参数")

    def log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.update_idletasks()

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择防碰报告文件(可多选)",
            filetypes=[("Excel 文件", "*.xls *.xlsx"), ("所有文件", "*.*")])
        added = 0
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.file_listbox.insert("end", p); added += 1
        if added:
            self.log(f"已添加 {added} 个文件, 共 {len(self.files)} 个")

    def remove_selected(self):
        idxs = list(self.file_listbox.curselection())
        for i in sorted(idxs, reverse=True):
            self.files.pop(i); self.file_listbox.delete(i)
        if idxs: self.log(f"已移除 {len(idxs)} 个文件")

    def clear_files(self):
        self.files.clear(); self.file_listbox.delete(0, "end")
        self.tree.delete(*self.tree.get_children())
        self.all_results.clear(); self.log("已清空文件列表")

    @staticmethod
    def _fmt(v):
        return f"{v:.2f}" if v is not None else ""

    def analyze_all(self):
        if not self.files:
            self.log("请先添加防碰报告文件"); return
        try:
            cfg = self.read_cfg()
        except ValueError as e:
            self.log(str(e)); return
        self.tree.delete(*self.tree.get_children())
        self.all_results.clear()
        total_wells = 0
        for path in self.files:
            try:
                ref_well, sections = read_report(path)
            except Exception as e:
                self.log(f"[失败] {os.path.basename(path)}: {e}"); continue
            results, excluded = ac_analyze(sections, cfg)
            if results:
                self.all_results.append((ref_well, results))
                total_wells += len(results)
                for it in results:
                    sf = it["sf"]
                    if sf is None: tag = "sf_none"
                    elif sf < 1.0:
                        if it["dvd"] is not None and abs(it["dvd"]) < 20: tag = "sf1_mark"
                        else: tag = "sf_red"
                    elif sf < 1.25: tag = "sf_yellow"
                    elif sf < 1.5: tag = "sf_blue"
                    else: tag = "sf_none"
                    self.tree.insert("", "end", values=(
                        ref_well, it["name"],
                        self._fmt(it["md"]), self._fmt(it["tvd"]),
                        self._fmt(it["omd"]), self._fmt(it["otvd"]),
                        self._fmt(it["dvd"]), self._fmt(it["hs"]),
                        self._fmt(it["centres"]),
                        f"{it['sf']:.3f}" if it["sf"] is not None else "",
                        it.get("remark", ""),
                    ), tags=(tag,))
            for name, reason in excluded:
                self.log(f"[未统计] {ref_well} - {name}: {reason}")
            self.log(f"[完成] {os.path.basename(path)}: 本井 {ref_well}, 统计 {len(results)} 口邻井")
        self.log(f"分析完成, 共统计 {total_wells} 口邻井")

    def generate_report(self):
        if not self.all_results:
            self.log("没有可生成报告的数据, 请先执行分析"); return
        out_dir = os.path.dirname(self.files[0]) if self.files else os.getcwd()
        date_suffix = datetime.date.today().strftime("(%Y%m%d)")
        out_path = os.path.join(out_dir, f"防碰分析汇总报告{date_suffix}.xlsx")
        try:
            out_path = ac_write_excel(self.all_results, out_path)
            self.log(f"报告已生成: {out_path}")
        except Exception as e:
            self.log(f"生成报告失败: {e}")


# ================================================================
# ================================================================
# TAB 4. 槽口图绘制
# ================================================================
# 逆旋转数学 (与数据库 CD_SITE_SOURCE 槽口换算口径一致):
#   正向(平台局部 → 大地): α = 平台北角 - 收敛角
#     dN = rel_N*cosα - rel_E*sinα ,  dE = rel_N*sinα + rel_E*cosα
#   逆旋(大地 → 平台局部): θ = 收敛角 - 平台北角 = -α
#     dN = well_N - 平台中心N ,  dE = well_E - 平台中心E
#     rel_E =  dE * cos θ + dN * sin θ   # 平台局部东 (图面 →)
#     rel_N = -dE * sin θ + dN * cos θ   # 平台局部北 (图面 ↑)
#
#   平台北角 / 软件旋转角: 软件绘制平台时平台北相对网格北的旋转角 (°, 顺时针为正)
#   收敛角: 由平台中心坐标按 Gauss-Krüger 反算 (正 = 网格北在真北以东, +E/-W)
#
# 绘图规则 (与 VBA「槽口图表」一致):
#   · 井槽按 行/列 吸附成等间距网格, 与真实间距无关 → 圆圈一样大、互不遮挡
#   · 版面 = 一张 A4 (自动横/竖), 槽口区域铺满纸面
#   · 每个槽口: 圆 + 圆内标签带 (井名 / KOP / INC / AZI / MD)
#   · 同槽双井: 标签带在圆内上下各一条, 数据互不遮挡
#   · 绿色箭头 = 首段定向方位; 左上角 PN/TN 方位指示
# ================================================================


# ---- Gauss-Krüger 子午线收敛角 (由平台中心平面坐标反算) ----
_GK_A  = 6378137.0                 # 长半轴 (椭球差异对收敛角影响 < 0.0002°)
_GK_F  = 1 / 298.257223563
_GK_E2 = _GK_F * (2 - _GK_F)

# 井口坐标 − 平台中心 (网格位移) 与粘贴网格位移的匹配容差 (m)
# 槽口名义格距 2.50m(北) × 3.10m(东), 取半个格距
SLOT_MATCH_TOL = 1.25

# 图面顶部标题带高度 (pt): 容纳「平台槽口图」标题 + 平台参数 + 右上角罗盘
SLOT_TITLE_H = 66.0

# 行距(列距)绘制的折叠规则: 相邻行北向间距 > 1.5×行距 时只画 1.2×行距, 另标实际距离
SLOT_GAP_LIMIT = 1.5
SLOT_GAP_FOLD = 1.2

# 罗盘 (PN/TN) 箭头长度 (pt)
SLOT_COMPASS_LEN = 46.0


def gk_grid_convergence(easting, northing):
    """由高斯-克吕格平面坐标 (m) 反算子午线收敛角 γ (°)，正 = 网格北在真北以东。

    东坐标 < 1e6  → 不含带号，按 500 km 假东移处理 (如 491613.05)
    东坐标 ≥ 1e6  → 前两位为带号 (如 43491613.05 → 43 带)
    北坐标按北半球赤道起算，负值自动叠加 10,000 km 假北移。
    """
    e, n = float(easting), float(northing)
    if abs(e) >= 1e6:                                   # 去掉带号
        zone = int(abs(e) / 1e6)
        e -= math.copysign(zone * 1e6, e)
    y = e - 500000.0                                    # 距中央子午线的自然东坐标
    M = n + 10000000.0 if n < 0 else n                  # 赤道起算子午线弧长

    # 底点纬度 φ1 (UTM/GK 反算级数, 精度 < 0.001″)
    e2 = _GK_E2
    mu = M / (_GK_A * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu
            + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))

    # γ = arctan(tanφ1 · y / N1),  N1 为卯酉圈曲率半径
    sin_p = math.sin(phi1)
    N1 = _GK_A / math.sqrt(1 - e2 * sin_p ** 2)
    return math.degrees(math.atan2(math.tan(phi1) * y, N1))


def slot_split_arrow(text):
    """'5→85' → (5.0, 85.0)；解析失败返回 (None, None)"""
    if not text or "→" not in str(text):
        return None, None
    a, b = str(text).split("→", 1)
    try:
        return float(a), float(b)
    except ValueError:
        return None, None


A4_LANDSCAPE = (841.89, 595.28)   # A4 横向 (pt)
A4_PORTRAIT  = (595.28, 841.89)   # A4 纵向 (pt)


def parse_slot_coords(text):
    """解析粘贴的槽口坐标: 每行 '槽口号 北位移 东位移' (空格/Tab/逗号分隔)"""
    out = OrderedDict()
    for line in (text or "").splitlines():
        raw = line.replace("\u3000", " ").strip()
        if not raw:
            continue
        parts = [p for p in re.split(r"[\s,，;；\t]+", raw) if p]
        if len(parts) < 3:
            continue
        try:
            n, e = float(parts[1]), float(parts[2])
        except ValueError:
            continue
        out[parts[0]] = (n, e)
    return out


def _slot_pitch(gap, base, fold=SLOT_GAP_FOLD, limit=SLOT_GAP_LIMIT):
    """相邻行/列的北向(或东向)间距在高倍绘制时的取值。

    间距超过 limit × 行距(列距) 视为"过远", 只画 fold × 行距并标注实际距离,
    返回 (绘制间距 m, 是否压缩)。
    """
    if gap <= limit * base:
        return gap, False
    return fold * base, True


def slot_layout(result, margin=22.0, title_h=SLOT_TITLE_H):
    """按真实北/东坐标布槽: 行 = 北向(自上而下), 列 = 东向(自左向右)。

    · 行距 / 列距 按相邻行(列)的真实间距取比例, 版面铺满一张 A4 (自动选横/竖);
    · 相邻两行北向间距过远 (> 1.5×行距) 时, 该段只画 1.2×行距, 实际距离另行标注,
      避免个别远行把版面撑爆;
    · 圆圈直径统一, 互不遮挡。返回坐标单位全部为磅 (pt)。
    """
    top_h = title_h
    groups = {}
    for rec in result:
        key = (round(rec["rel_n"], 1), round(rec["rel_e"], 1))
        groups.setdefault(key, []).append(rec)

    rows_m = sorted({k[0] for k in groups}, reverse=True)     # 北 → 南
    cols_m = sorted({k[1] for k in groups})                   # 西 → 东
    nr, nc = len(rows_m), len(cols_m)

    def _gaps(levels):
        return [abs(a - b) for a, b in zip(levels, levels[1:])]

    def _base(gaps):
        """名义行距/列距: 取出现次数最多的间距 (并列取较小者)"""
        pos = [round(g, 2) for g in gaps if g > 1e-6]
        if not pos:
            return 1.0
        cnt = {}
        for g in pos:
            cnt[g] = cnt.get(g, 0) + 1
        return max(cnt.items(), key=lambda kv: (kv[1], -kv[0]))[0]

    row_gaps, col_gaps = _gaps(rows_m), _gaps(cols_m)
    row_base, col_base = _base(row_gaps), _base(col_gaps)

    drawn_rows = [_slot_pitch(g, row_base) for g in row_gaps]
    drawn_cols = [_slot_pitch(g, col_base) for g in col_gaps]
    row_units = [d for d, _ in drawn_rows] or [1.0]
    col_units = [d for d, _ in drawn_cols] or [1.0]
    # 每个行列一个格子: 间距数比行(列)数少 1, 末尾补一段保持格数一致
    if len(row_units) < nr:
        row_units.append(row_units[-1])
    if len(col_units) < nc:
        col_units.append(col_units[-1])

    # 顶部/左侧留出 列距/行距 标注带
    pad_top = 20.0 if nc > 1 else 4.0
    pad_left = 26.0 if nr > 1 else 4.0

    # 横/竖两种 A4 排布, 取圆圈更大者
    best = None
    for pw, ph, orient in ((A4_LANDSCAPE[0], A4_LANDSCAPE[1], 2),
                           (A4_PORTRAIT[0], A4_PORTRAIT[1], 1)):
        sw = (pw - 2 * margin - pad_left) / sum(col_units)
        sh = (ph - 2 * margin - top_h - pad_top) / sum(row_units)
        if best is None or min(sw, sh) > best[0]:
            best = (min(sw, sh), pw, ph, orient, sw, sh)
    _, page_w, page_h, orient, sx, sy = best
    sx, sy = min(sx, 130.0), min(sy, 130.0)      # 槽口很少时不让圆圈过分放大

    grid_w, grid_h = sum(col_units) * sx, sum(row_units) * sy
    x0 = margin + pad_left + (page_w - 2 * margin - pad_left - grid_w) / 2.0
    y0 = margin + top_h + pad_top + (page_h - 2 * margin - top_h - pad_top - grid_h) / 2.0

    col_x, acc = [], 0.0
    for u in col_units:
        col_x.append(x0 + (acc + u / 2.0) * sx)
        acc += u
    row_y, acc = [], 0.0
    for u in row_units:
        row_y.append(y0 + (acc + u / 2.0) * sy)
        acc += u

    # 圆圈直径: 以最小格距为准; 个别异常贴近的行列 (如 0.2m 重复列) 不让圆圈被压扁
    u_row = max(min(row_units), 0.85 * row_base) if nr > 1 else sum(row_units)
    u_col = max(min(col_units), 0.85 * col_base) if nc > 1 else sum(col_units)
    slot_d = 0.97 * min(u_col * sx, u_row * sy)

    cells = []
    for i, n_val in enumerate(rows_m):
        for j, e_val in enumerate(cols_m):
            key = (n_val, e_val)
            if key in groups:
                cells.append(dict(key=key, row=i, col=j,
                                  x=col_x[j], y=row_y[i], wells=groups[key]))

    return dict(page_w=page_w, page_h=page_h, orient=orient, margin=margin,
                title_h=title_h, top_h=top_h, pad_top=pad_top, pad_left=pad_left,
                cell=min(min(col_units) * sx, min(row_units) * sy),
                cell_w=sx, cell_h=sy, slot_d=slot_d, cells=cells,
                x0=x0, y0=y0, n_cols=nc, n_rows=nr,
                cols=cols_m, rows=rows_m, col_x=col_x, row_y=row_y,
                row_gaps=row_gaps, col_gaps=col_gaps, row_base=row_base,
                col_base=col_base,
                row_compressed=[c for _, c in drawn_rows],
                col_compressed=[c for _, c in drawn_cols],
                n_wells=sum(1 for r in result if not r.get("_empty")))


def slot_center_xy(layout):
    """平台中心 (0,0) 在版面中的插值位置 (pt)"""
    cols, rows = layout["cols"], layout["rows"]       # cols 升序 / rows 降序(北→南)
    xs, ys = layout["col_x"], layout["row_y"]
    px = float(np.interp(0.0, cols, xs)) if len(cols) > 1 else xs[0]
    ry, fy = rows[::-1], ys[::-1]                     # 反转成升序, np.interp 要求 xp 递增
    py = float(np.interp(0.0, ry, fy)) if len(ry) > 1 else fy[0]
    return px, py


def slot_compass_geom(lay, plat_rot_deg, ln=SLOT_COMPASS_LEN):
    """罗盘几何: PN(平台北) 永远竖直朝上; TN(真北) 按平台北角偏转。

    · 平台北为正 → TN 在 PN 左侧; 平台北为负 → TN 在右侧;
    · PN / TN 标签各放在对方一侧, 角度标在两条北向箭头之外的正中,
      三者上下错开, 互不遮挡。返回的坐标单位 pt, Y 向下。
    """
    ox = lay["page_w"] - lay["margin"] - 50.0
    oy = lay["margin"] + lay["top_h"]
    rad = math.radians(-plat_rot_deg)
    tx, ty = ox + math.sin(rad) * ln, oy - math.cos(rad) * ln
    left = plat_rot_deg >= 0                       # TN 是否在左侧
    R = ln * 0.62
    mid = math.radians(-plat_rot_deg / 2.0)
    lr = ln + 14.0                                 # 角度字放在两箭头之外, 避免与 PN 打架
    ax_ = ox + math.sin(mid) * lr
    ax_ = min(max(ax_, lay["margin"] + 22.0), lay["page_w"] - lay["margin"] - 22.0)
    ay_ = oy - math.cos(mid) * lr
    return dict(ox=ox, oy=oy, tip=(tx, ty), left=left,
                pn_x=ox - 5.0 if left else ox + 5.0,
                tn_x=tx - 5.0 if left else tx + 5.0,
                R=R, mid_deg=-plat_rot_deg / 2.0, angle=(ax_, ay_))


class SlotMapTab(ttk.Frame):
    """槽口图绘制 —— 逆旋转 + 北向上俯视 + 距离标注"""

    def __init__(self, master, controller=None):
        super().__init__(master)
        self.controller = controller  # MainWindow
        self.today = datetime.datetime.now().strftime("%Y%m%d")
        self.slot_coords = {}         # 粘贴的槽口坐标 {槽口号: (北位移, 东位移)}
        self._last_result = None
        self._last_params = None

        # ---- UI1 输入 ----
        ui1 = ttk.LabelFrame(self, text=" ① 平台参数 ", padding=(10, 8))
        ui1.pack(fill="x", padx=10, pady=(10, 4))

        self.var_plat_n  = tk.StringVar()
        self.var_plat_e  = tk.StringVar()
        self.var_plat_rot = tk.StringVar(value="0")   # 平台北角 (软件旋转角, °, 顺时针为正)
        self.var_tn_text = tk.StringVar(value="—")    # 收敛角显示 (自动计算, 只读)
        self.tn_deg = None                            # 当前收敛角数值

        row = ttk.Frame(ui1); row.pack(fill="x")
        ttk.Label(row, text="平台中心北坐标 (Northing)：", width=22).pack(side="left")
        ttk.Entry(row, textvariable=self.var_plat_n, width=18).pack(side="left", padx=(0, 18))
        ttk.Label(row, text="平台中心东坐标 (Easting)：", width=22).pack(side="left")
        ttk.Entry(row, textvariable=self.var_plat_e, width=18).pack(side="left", padx=(0, 18))

        row2 = ttk.Frame(ui1); row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text="平台北角/软件旋转角 (°)：").pack(side="left")
        ttk.Entry(row2, textvariable=self.var_plat_rot, width=8).pack(side="left", padx=(0, 18))
        ttk.Label(row2, text="收敛角 (°，由平台中心坐标自动计算)：").pack(side="left")
        ttk.Label(row2, textvariable=self.var_tn_text, width=12, anchor="center",
                  relief="sunken", foreground="#C00000",
                  font=("Microsoft YaHei", 9, "bold")).pack(side="left", padx=(0, 18))
        self.btn_calc = ttk.Button(row2, text="计算槽口坐标并绘图", command=self.compute_and_draw)
        self.btn_calc.pack(side="left", padx=(8, 0))
        self.btn_excel = ttk.Button(row2, text="导出 Excel 槽口图",
                                    command=self.export_excel_chart)
        self.btn_excel.pack(side="left", padx=(6, 0))

        # 平台中心坐标变化 → 实时刷新收敛角
        self.var_plat_n.trace_add("write", lambda *_: self.update_convergence())
        self.var_plat_e.trace_add("write", lambda *_: self.update_convergence())

        # 数据源提示
        row2 = ttk.Frame(ui1); row2.pack(fill="x", pady=(6, 0))
        ttk.Label(
            row2,
            text="数据源：自动读取「② 综合数据表」的井口Northing/Easting。"
                 "若为空请先在 Tab ② 执行「开始分析」。",
            foreground="#666666",
        ).pack(side="left")
        self.btn_load = ttk.Button(row2, text="重新读取 Tab ② 数据", command=self.reload_from_tab2)
        self.btn_load.pack(side="right")

        # ---- UI1.5 槽口坐标 DIY (粘贴区) ----
        uip = ttk.LabelFrame(
            self,
            text=" ② 槽口坐标 DIY (每行「槽口号 北位移 东位移」，按网格位移粘贴，程序自动反旋转并按位移匹配井) ",
            padding=(6, 4))
        uip.pack(fill="x", padx=10, pady=(6, 4))
        self.txt_slots = tk.Text(uip, height=3, font=("Consolas", 9), wrap="none",
                                 undo=True)
        self.txt_slots.pack(side="left", fill="both", expand=True)
        sb_txt = ttk.Scrollbar(uip, orient="vertical", command=self.txt_slots.yview)
        self.txt_slots.configure(yscrollcommand=sb_txt.set)
        sb_txt.pack(side="left", fill="y")
        boxbtn = ttk.Frame(uip)
        boxbtn.pack(side="left", fill="y", padx=(6, 0))
        ttk.Button(boxbtn, text="应用槽口坐标",
                   command=self.apply_slot_coords).pack(fill="x")
        ttk.Button(boxbtn, text="清空", command=self.clear_slot_coords).pack(
            fill="x", pady=(4, 0))

        # ---- UI2 槽口坐标表 ----
        ui2 = ttk.LabelFrame(self, text=" ③ 槽口坐标表 (槽口号 / 反旋转后北·东位移 / 井名) ",
                             padding=(6, 4))
        ui2.pack(fill="x", padx=10, pady=(0, 4))

        col_ids = ("slot", "rel_n", "rel_e", "name")
        col_hdrs = ("槽口号", "反旋转后北位移 (m)", "反旋转后东位移 (m)", "井名")
        col_ws = (100, 150, 150, 620)
        self.tree2 = ttk.Treeview(ui2, columns=col_ids, show="headings", height=4)
        for tid, hdr, w in zip(col_ids, col_hdrs, col_ws):
            self.tree2.heading(tid, text=hdr)
            anchor = "center" if tid != "name" else "w"
            self.tree2.column(tid, width=w, anchor=anchor, minwidth=60)
        vsb2 = ttk.Scrollbar(ui2, orient="vertical", command=self.tree2.yview)
        self.tree2.configure(yscrollcommand=vsb2.set)
        self.tree2.pack(side="left", fill="both", expand=True)
        vsb2.pack(side="right", fill="y")

        # ---- UI3 绘图 (滚轮缩放 / 拖动平移 / 双击复原) ----
        ui3 = ttk.LabelFrame(self, text=" ④ 槽口图 (A4 版面, 平台北↑ | 滚轮缩放 · 拖动平移 · 双击复原) ",
                             padding=(6, 4))
        ui3.pack(fill="both", expand=True, padx=10, pady=(6, 10))

        self.fig = Figure(figsize=(8, 6), dpi=100, facecolor="white")
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=ui3)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.ax.set_aspect("equal")
        self._view0 = None                       # 初始视图 (双击复原用)
        self._pan_start = None                   # 平移起点
        self._blank_figure("请在上方填写平台中心坐标，然后点击「计算槽口坐标并绘图」")

        cid = self.canvas.mpl_connect
        cid("scroll_event", self._on_scroll)
        cid("button_press_event", self._on_press)
        cid("motion_notify_event", self._on_motion)
        cid("button_release_event", self._on_release)

    # ============================================================
    # 数学: 逆旋转
    # ============================================================
    def update_convergence(self):
        """平台中心坐标变化时自动重算收敛角并在界面上显示。"""
        try:
            n = float(self.var_plat_n.get().strip())
            e = float(self.var_plat_e.get().strip())
        except ValueError:
            self.tn_deg = None
            self.var_tn_text.set("—")
            return None
        self.tn_deg = gk_grid_convergence(e, n)
        self.var_tn_text.set(f"{self.tn_deg:+.4f}°")
        return self.tn_deg

    def inverse_rotate(self, plat_n, plat_e, plat_rot_deg, conv_deg, wells):
        """
        wells: [dict(井名, 槽口, 北, 东, ...), ...]
        plat_rot_deg: 软件绘制平台的旋转角 (平台北角), 顺时针为正
        conv_deg:     收敛角 (由平台中心坐标反算), 正 = 网格北在真北以东
        返回: 每口井 dict 追加 rel_n / rel_e (平台局部北/东)
        """
        # 与数据库口径一致: α = 平台北角 - 收敛角, 逆旋 θ = -α
        theta = math.radians(conv_deg - plat_rot_deg)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        out = []
        for w in wells:
            dN = w["北"] - plat_n
            dE = w["东"] - plat_e
            rec = dict(w)
            rec["rel_e"] = dE * cos_t + dN * sin_t
            rec["rel_n"] = -dE * sin_t + dN * cos_t
            out.append(rec)
        return out

    # ============================================================
    # 数据源: Tab ② 的 records
    # ============================================================
    def _get_wells_from_tab2(self):
        """从 综合数据表 Tab 读取井口坐标 + 造斜参数 (KOP/INC/AZI/MD)"""
        tab = getattr(self.controller, "tab_traj", None) if self.controller else None
        if tab is None or not getattr(tab, "records", None):
            return []
        out = []
        for rec in tab.records:
            n, e = rec.get("井口Northing"), rec.get("井口Easting")
            if n is None or e is None:
                continue
            inc1, inc2 = slot_split_arrow(rec.get("井斜"))
            azi1, azi2 = slot_split_arrow(rec.get("扭方位"))
            out.append(dict(
                井名=rec.get("井名", ""), 槽口=rec.get("槽口", ""),
                北=float(n), 东=float(e),
                k1=rec.get("第一造斜段_造斜点"), k2=rec.get("最后造斜段_造斜点"),
                inc1=inc1, inc2=inc2, azi1=azi1, azi2=azi2,
                md=rec.get("井深"),
            ))
        return out

    def reload_from_tab2(self):
        wells = self._get_wells_from_tab2()
        messagebox.showinfo(
            "读取完成",
            f"已从 Tab ② 读取 {len(wells)} 口井的井口坐标。\n"
            f"现在填写平台中心参数后点击「计算槽口坐标并绘图」。")

    # ============================================================
    # 槽口坐标 DIY: 粘贴 → 覆盖逆旋转结果
    # ============================================================
    def apply_slot_coords(self):
        text = self.txt_slots.get("1.0", "end")
        coords = parse_slot_coords(text)
        if not coords:
            messagebox.showwarning(
                "格式有误",
                "未解析到槽口坐标。\n每行格式：槽口号  北位移  东位移\n例如：1401  4.76  -11.45")
            return
        self.slot_coords = coords
        messagebox.showinfo("已应用",
                            f"已采用粘贴的 {len(coords)} 个槽口坐标。")
        if getattr(self, "_last_result", None):
            self.compute_and_draw()

    def clear_slot_coords(self):
        self.txt_slots.delete("1.0", "end")
        self.slot_coords = {}
        if getattr(self, "_last_result", None):
            self.compute_and_draw()

    @staticmethod
    def _to_platform(n, e, plat_rot_deg, conv_deg):
        """网格位移 (北, 东) → 平台局部坐标 (反旋转), 与 inverse_rotate 同一公式"""
        theta = math.radians(conv_deg - plat_rot_deg)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        return (-e * sin_t + n * cos_t, e * cos_t + n * sin_t)

    def _merge_slot_coords(self, result, plat_n, plat_e, plat_rot_deg, conv_deg):
        """按「井口坐标 − 平台中心」的网格位移与粘贴的网格位移匹配井槽。

        · 每口井取井口 (北, 东) 减平台中心, 与粘贴表的 (北位移, 东位移) 比距离,
          最近的槽口且距离 ≤ SLOT_MATCH_TOL 即判定该井布在这个井口中;
        · 命中后用粘贴槽口号覆盖井的槽口号, 并把网格位移反旋转成平台局部坐标;
        · 粘贴表里有、没有井的槽口按空槽补上; 离所有槽口都超过容差的井原样保留。
        """
        coords = getattr(self, "slot_coords", None) or {}
        if not coords:
            return result

        assigned = OrderedDict((s, []) for s in coords)
        unmatched = []
        for rec in result:
            n, e = rec.get("北"), rec.get("东")
            if n is None or e is None:
                unmatched.append(rec)
                continue
            d_n, d_e = float(n) - plat_n, float(e) - plat_e
            best_s, best_d = None, SLOT_MATCH_TOL
            for s, (cn, ce) in coords.items():
                d = math.hypot(d_n - cn, d_e - ce)
                if d < best_d:
                    best_s, best_d = s, d
            if best_s is None:
                unmatched.append(rec)
                continue
            rec["槽口"] = best_s
            assigned[best_s].append(rec)

        merged = []
        for s, ws in assigned.items():
            n, e = coords[s]
            rel_n, rel_e = self._to_platform(n, e, plat_rot_deg, conv_deg)
            if ws:
                for rec in ws:
                    rec["rel_n"], rec["rel_e"] = rel_n, rel_e
                    merged.append(rec)
            else:
                merged.append(dict(井名="", 槽口=s, rel_n=rel_n, rel_e=rel_e,
                                   k1=None, k2=None, inc1=None, inc2=None,
                                   azi1=None, azi2=None, md=None, _empty=True))
        merged.extend(unmatched)
        return merged


    # ============================================================
    # 计算 + 填 UI2 + 画 UI3
    # ============================================================
    def compute_and_draw(self):
        try:
            plat_n = float(self.var_plat_n.get().strip())
            plat_e = float(self.var_plat_e.get().strip())
            plat_rot = float(self.var_plat_rot.get().strip())
        except ValueError:
            messagebox.showwarning(
                "参数有误",
                "请正确填写平台中心北/东坐标、平台北角（均为数值）。"); return

        tn = self.update_convergence()
        if tn is None:
            messagebox.showwarning("参数有误", "平台中心北/东坐标无法解析，收敛角计算失败。"); return

        wells = self._get_wells_from_tab2()
        if not wells:
            messagebox.showwarning(
                "暂无井数据",
                "请先到 Tab ②「综合数据表」执行「开始分析」，\n"
                "再回到本页面点击「重新读取 Tab ② 数据」。"); return

        result = self.inverse_rotate(plat_n, plat_e, plat_rot, tn, wells)
        result = self._merge_slot_coords(result, plat_n, plat_e, plat_rot, tn)
        self._last_result = result
        self._last_params = (plat_n, plat_e, plat_rot, tn)
        self._fill_tree2(result)
        self._draw_slot_map(result, plat_n, plat_e, plat_rot, tn)

    # ------------------------------------------------------------
    # 导出 Excel 版槽口图 (原生圆/文本框/箭头, 可在 Excel 里编辑)
    # ------------------------------------------------------------
    def export_excel_chart(self):
        if not getattr(self, "_last_result", None):
            messagebox.showinfo("提示", "请先点击「计算槽口坐标并绘图」生成槽口图。")
            return
        path = filedialog.asksaveasfilename(
            title="导出 Excel 槽口图", defaultextension=".xlsx",
            initialfile=f"槽口图_{datetime.datetime.now():%Y%m%d_%H%M}.xlsx",
            filetypes=[("Excel 工作簿", "*.xlsx")])
        if not path:
            return
        try:
            import win32com.client as win32
        except ImportError:
            messagebox.showerror(
                "缺少组件", "导出 Excel 槽口图需要 pywin32:\n  pip install pywin32")
            return
        try:
            self._build_excel_workbook(win32, path)
        except Exception as e:
            messagebox.showerror("导出失败", f"{type(e).__name__}: {e}")
            return
        messagebox.showinfo("导出成功", f"Excel 槽口图已保存:\n{path}")

    @staticmethod
    def _bgr(r, g, b):
        return r | (g << 8) | (b << 16)

    def _excel_label_box(self, sh, cx, cy, side):
        """井名标签的浅蓝正方形边框 (以 (cx, cy) 为中心, 无填充)"""
        sq = sh.AddShape(1, cx - side / 2.0, cy - side / 2.0, side, side)  # 1 = 矩形
        sq.Fill.Visible = False
        sq.Line.ForeColor.RGB = self._bgr(157, 195, 230)                  # 浅蓝 #9DC3E6
        sq.Line.Weight = 0.75
        return sq

    def _fit_font_size(self, sh, text, box_w, box_h, ref=8.0, margin=0.94):
        """用临时文本框 AutoSize 量出 text 在 ref 字号下的实际尺寸, 反算能放进
        box_w × box_h 的最大字号 (字号与文字尺寸成正比, 一次换算即可)"""
        probe = sh.AddTextbox(1, 0.0, 0.0, box_w, box_h)
        tf = probe.TextFrame2
        tf.WordWrap = False
        tf.MarginLeft = 0
        tf.MarginRight = 0
        tf.MarginTop = 0
        tf.MarginBottom = 0
        tf.TextRange.Text = text.replace("\n", "\r")
        tf.TextRange.Font.Name = "Microsoft YaHei"
        tf.TextRange.Font.Size = ref
        tf.AutoSize = 1                     # 1 = 形状随文字大小变化
        w, h = probe.Width, probe.Height
        probe.Delete()
        fs = ref * min(margin * box_w / max(w, 1e-6),
                       margin * box_h / max(h, 1e-6), 1.0)
        return max(2.0, fs)

    def _build_excel_workbook(self, win32, path):
        """用 Excel 形状重建槽口图：圆 + 标签文本框 + 方位箭头 + PN/TN"""
        result = self._last_result
        plat_n, plat_e, plat_rot, conv = self._last_params

        lay = slot_layout(result)
        D = lay["slot_d"]
        left0 = lay["margin"]
        area_w = lay["page_w"] - 2 * lay["margin"]

        app = win32.DispatchEx("Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Add()
        try:
            ws = wb.Worksheets(1)
            ws.Name = "槽口图"
            sh = ws.Shapes

            # ---- 标题 ----
            tb = sh.AddTextbox(1, left0, lay["margin"] - 10, area_w, 20.0)
            tf = tb.TextFrame2.TextRange
            tf.Text = "平台槽口图"
            tf.Font.Size = 16
            tf.Font.Bold = True
            tf.Font.Name = "Microsoft YaHei"
            tf.ParagraphFormat.Alignment = 2
            tb.TextFrame2.WordWrap = False
            tb.Line.Visible = False

            tb2 = sh.AddTextbox(1, left0, lay["margin"] + 17.0, area_w, 15.0)
            tf2 = tb2.TextFrame2.TextRange
            tf2.Text = (f"平台中心 N={plat_n:.2f} E={plat_e:.2f}    "
                        f"平台北角 {plat_rot:+.2f}°")
            tf2.Font.Size = 8.5
            tf2.Font.Bold = False
            tf2.Font.Name = "Microsoft YaHei"
            tf2.ParagraphFormat.Alignment = 2
            tb2.TextFrame2.WordWrap = False
            tb2.Line.Visible = False

            rot_deg = plat_rot - conv
            for c in lay["cells"]:
                x, y = c["x"], c["y"]
                oval = sh.AddShape(9, x - D / 2, y - D / 2, D, D)      # 9 = 椭圆
                oval.Fill.Solid()
                oval.Fill.ForeColor.RGB = self._bgr(255, 255, 255)
                oval.Line.ForeColor.RGB = self._bgr(31, 56, 100)
                oval.Line.Weight = 0.75
                oval.TextFrame2.TextRange.Text = ""

                wells = c["wells"]
                n = len(wells)
                # 标签正方形边长: 单井/空槽可放大, 双井上下两框相贴不能超半圆
                side = (0.56 if n == 1 else 0.52) * D
                if n == 1 and wells[0].get("_empty"):        # 粘贴表里的空槽
                    self._excel_label_box(sh, x, y, side)
                    tf0 = oval.TextFrame2
                    tf0.VerticalAnchor = 3                   # 3 = 居中
                    tf0.MarginLeft = 0
                    tf0.MarginRight = 0
                    tf0.MarginTop = 0
                    tf0.MarginBottom = 0
                    tr0 = tf0.TextRange
                    tr0.Text = str(wells[0].get("槽口", ""))
                    tr0.Font.Size = max(5.0, D * 0.16)
                    tr0.Font.Name = "Microsoft YaHei"
                    tr0.Font.Fill.ForeColor.RGB = self._bgr(128, 128, 128)
                    tr0.ParagraphFormat.Alignment = 2
                    continue
                for idx, rec in enumerate(wells):
                    # 单井/空槽: 方框居中于圆心; 双井: 上下各一个方框
                    if n == 1:
                        by = y
                    else:
                        by = (y - side / 2.0) if idx % 2 == 0 else (y + side / 2.0)
                    w_, h_ = side, side
                    tx, ty = x - side / 2.0, by - side / 2.0
                    y_arrow = by
                    self._excel_label_box(sh, x, by, side)

                    box = sh.AddTextbox(1, tx, ty, w_, h_)
                    box.TextFrame2.WordWrap = False
                    box.TextFrame2.VerticalAnchor = 3
                    box.TextFrame2.MarginLeft = 0
                    box.TextFrame2.MarginRight = 0
                    box.TextFrame2.MarginTop = -1
                    box.TextFrame2.MarginBottom = 0
                    box.Line.Visible = False
                    box.Fill.Visible = False
                    tr = box.TextFrame2.TextRange
                    text = self._well_text(rec)
                    tr.Text = text.replace("\n", "\r")
                    tr.Font.Name = "Microsoft YaHei"
                    tr.Font.Size = self._fit_font_size(sh, text, w_, h_)
                    tr.Font.Fill.ForeColor.RGB = self._bgr(31, 56, 100)
                    tr.ParagraphFormat.Alignment = 2

                    # ---- 绿色方位箭头 ----
                    if rec.get("azi1") is not None:
                        rad = math.radians(rec["azi1"] - rot_deg)
                        L = D * 0.50                              # 箭头不超出本格
                        ex = x + math.sin(rad) * L
                        ey = y_arrow - math.cos(rad) * L
                        ln = sh.AddLine(x, y_arrow, ex, ey)
                        ln.Line.ForeColor.RGB = self._bgr(32, 128, 64)
                        ln.Line.Weight = 1.25
                        ln.Line.EndArrowheadStyle = 2                  # 三角箭头

            # ---- 行距 / 列距 标注 (过远的行距只画 1.2×行距, 标实际距离) ----
            def _dim(x1, y1, x2, y2, rgb):
                dl = sh.AddLine(x1, y1, x2, y2)
                dl.Line.ForeColor.RGB = self._bgr(*rgb)
                dl.Line.Weight = 0.75
                dl.Line.BeginArrowheadStyle = 2
                dl.Line.EndArrowheadStyle = 2
                return dl

            def _dim_text(cx, cy, w, h, text, rgb, vertical=False):
                tb = sh.AddTextbox(1, cx - w / 2.0, cy - h / 2.0, w, h)
                tb.TextFrame2.WordWrap = False
                tb.TextFrame2.TextRange.Text = text
                tb.TextFrame2.TextRange.Font.Size = 7.0
                tb.TextFrame2.TextRange.Font.Name = "Microsoft YaHei"
                tb.TextFrame2.TextRange.Font.Fill.ForeColor.RGB = self._bgr(*rgb)
                tb.TextFrame2.TextRange.ParagraphFormat.Alignment = 2
                tb.Line.Visible = False
                tb.Fill.Visible = False
                if vertical:
                    tb.Rotation = 270
                return tb

            occ = {(c["row"], c["col"]) for c in lay["cells"]}
            pair = None
            for i in range(lay["n_rows"]):
                cand = [j for j in range(lay["n_cols"] - 1)
                        if not lay["col_compressed"][j]
                        and (i, j) in occ and (i, j + 1) in occ]
                if cand:
                    pair = (i, min(cand, key=lambda t:
                                   abs(lay["col_gaps"][t] - lay["col_base"])))
                    break
            if pair is None:
                normal_c = [j for j, cp in enumerate(lay["col_compressed"]) if not cp]
                if normal_c:
                    pair = (0, min(normal_c, key=lambda t:
                                   abs(lay["col_gaps"][t] - lay["col_base"])))
            if lay["n_cols"] > 1 and pair:
                i, j = pair
                x1, x2 = lay["col_x"][j], lay["col_x"][j + 1]
                yd = lay["row_y"][i] - D / 2.0 - 5.0
                _dim(x1, yd, x2, yd, (31, 56, 100))
                _dim_text((x1 + x2) / 2.0, yd - 7.0, x2 - x1, 11.0,
                          f'列距 {lay["col_base"]:.2f}m', (31, 56, 100))

            if lay["n_rows"] > 1:
                dx = lay["x0"] - 11.0
                normal_r = [i for i, cp in enumerate(lay["row_compressed"]) if not cp]
                if normal_r:
                    i = min(normal_r, key=lambda t: abs(lay["row_gaps"][t] - lay["row_base"]))
                    y1, y2 = lay["row_y"][i], lay["row_y"][i + 1]
                    _dim(dx, y1, dx, y2, (31, 56, 100))
                    _dim_text(dx - 5.0, (y1 + y2) / 2.0, 44.0, 11.0,
                              f'行距 {lay["row_base"]:.2f}m', (31, 56, 100), True)
                for i, cp in enumerate(lay["row_compressed"]):
                    if not cp:
                        continue
                    y1, y2 = lay["row_y"][i], lay["row_y"][i + 1]
                    _dim(dx, y1, dx, y2, (192, 0, 0))
                    _dim_text(dx - 5.0, (y1 + y2) / 2.0, 54.0, 11.0,
                              f'实际 {lay["row_gaps"][i]:.2f}m', (192, 0, 0), True)

            # ---- 平台中心 ----
            px, py = slot_center_xy(lay)
            for dx, dy in ((5.0, 0.0), (0.0, 5.0)):
                ln = sh.AddLine(px - dx, py - dy, px + dx, py + dy)
                ln.Line.ForeColor.RGB = self._bgr(192, 0, 0)
                ln.Line.Weight = 1.5
            tbp = sh.AddTextbox(1, px - 40.0, py + 6.0, 80.0, 16.0)
            tbp.TextFrame2.TextRange.Text = "平台中心"
            tbp.TextFrame2.TextRange.Font.Size = 9
            tbp.TextFrame2.TextRange.Font.Bold = True
            tbp.TextFrame2.TextRange.Font.Name = "Microsoft YaHei"
            tbp.TextFrame2.TextRange.Font.Fill.ForeColor.RGB = self._bgr(192, 0, 0)
            tbp.TextFrame2.TextRange.ParagraphFormat.Alignment = 2
            tbp.Line.Visible = False

            # ---- 罗盘: PN 永远朝正上方; 平台北为正 → TN 在左, 为负 → TN 在右 ----
            cp = slot_compass_geom(lay, plat_rot)
            ox, oy = cp["ox"], cp["oy"]
            ln_ = SLOT_COMPASS_LEN
            pn = sh.AddLine(ox, oy, ox, oy - ln_)
            pn.Line.ForeColor.RGB = self._bgr(0, 0, 0)
            pn.Line.Weight = 1.25
            pn.Line.EndArrowheadStyle = 2
            tx_, ty_ = cp["tip"]
            tn = sh.AddLine(ox, oy, tx_, ty_)
            tn.Line.ForeColor.RGB = self._bgr(89, 89, 89)
            tn.Line.Weight = 1.0
            tn.Line.DashStyle = 3
            tn.Line.EndArrowheadStyle = 2
            if abs(plat_rot) > 0.01:                 # 弧线用小线段拟合
                R = cp["R"]
                prev = (ox, oy - R)
                for a in np.linspace(0.0, -plat_rot, 9)[1:]:
                    cur = (ox + math.sin(math.radians(a)) * R,
                           oy - math.cos(math.radians(a)) * R)
                    seg = sh.AddLine(prev[0], prev[1], cur[0], cur[1])
                    seg.Line.ForeColor.RGB = self._bgr(89, 89, 89)
                    seg.Line.Weight = 0.75
                    prev = cur
                axx, ayy = cp["angle"]
                adeg = sh.AddTextbox(1, axx - 20.0, ayy - 7.0, 40.0, 14.0)
                adeg.TextFrame2.WordWrap = False
                adeg.TextFrame2.MarginLeft = 0
                adeg.TextFrame2.MarginRight = 0
                adeg.TextFrame2.MarginTop = 0
                adeg.TextFrame2.MarginBottom = 0
                adeg.TextFrame2.TextRange.Text = f"{abs(plat_rot):.2f}°"
                adeg.TextFrame2.TextRange.Font.Size = 8
                adeg.TextFrame2.TextRange.Font.Name = "Microsoft YaHei"
                adeg.TextFrame2.TextRange.ParagraphFormat.Alignment = 2
                adeg.Line.Visible = False
            al = 3 if cp["left"] else 1              # 1=左对齐 3=右对齐 (mso)
            for label, lx, ly in (("PN", cp["pn_x"], oy - ln_),
                                  ("TN", cp["tn_x"], ty_)):
                tbc = sh.AddTextbox(1, lx - 30.0 if cp["left"] else lx, ly - 7.0, 30.0, 14.0)
                tbc.TextFrame2.WordWrap = False
                tbc.TextFrame2.MarginLeft = 0
                tbc.TextFrame2.MarginRight = 0
                tbc.TextFrame2.MarginTop = 0
                tbc.TextFrame2.MarginBottom = 0
                tbc.TextFrame2.TextRange.Text = label
                tbc.TextFrame2.TextRange.Font.Size = 9
                tbc.TextFrame2.TextRange.Font.Name = "Microsoft YaHei"
                tbc.TextFrame2.TextRange.ParagraphFormat.Alignment = al
                tbc.Line.Visible = False

            # ---- 页面设置: A4 铺满一页 ----
            m = lay["margin"]
            ps = ws.PageSetup
            ps.PaperSize = 9                     # xlPaperA4
            ps.Orientation = lay["orient"]       # 1 纵向 / 2 横向
            ps.LeftMargin = m
            ps.RightMargin = m
            ps.TopMargin = m
            ps.BottomMargin = m
            ps.CenterHorizontally = False
            ps.CenterVertically = False
            ps.Zoom = False                      # 关闭百分比, 改为"调整为 1 页"
            ps.FitToPagesWide = 1
            ps.FitToPagesTall = 1
            ps.PrintGridlines = False
            ps.PrintHeadings = False

            wb.SaveAs(path, FileFormat=51)      # 51 = xlsx
            wb.Close(SaveChanges=False)
        finally:
            try:
                app.Quit()
            except Exception:
                pass

    def _fill_tree2(self, result):
        """表格: 槽口号 / 反旋转后北位移 / 反旋转后东位移 / 井名 (双井列出全部井名)"""
        self.tree2.delete(*self.tree2.get_children())
        for row in self._slot_rows(result):
            self.tree2.insert("", "end", values=(
                row["slot"],
                "—" if row["n"] is None else f'{row["n"]:+.2f}',
                "—" if row["e"] is None else f'{row["e"]:+.2f}',
                row["names"],
            ))

    @staticmethod
    def _nat_key(text):
        """槽口号自然排序键 (数字按数值比较)"""
        return [f"{int(t):09d}" if t.isdigit() else t
                for t in re.split(r"(\d+)", str(text))]

    def _slot_rows(self, result):
        """按槽口号归并 → [{slot, n, e, names}]
        names: 该槽口的全部真实井名 (双井用 " / " 连接, 空槽 "—"), 供 ③ 坐标表使用
        """
        cells = OrderedDict()
        for rec in result:
            key = str(rec.get("槽口") or "")
            cells.setdefault(key, []).append(rec)
        rows = []
        for key, ws in cells.items():
            well_names = [str(w.get("井名") or "").strip() for w in ws
                          if not w.get("_empty")]
            well_names = [x for x in well_names if x]
            names = " / ".join(well_names) if well_names else "—"
            rows.append(dict(slot=key or "—",
                             n=ws[0].get("rel_n"), e=ws[0].get("rel_e"),
                             names=names))
        rows.sort(key=lambda r: self._nat_key(r["slot"]))
        return rows

    def _blank_figure(self, msg):
        self.ax.clear()
        self.ax.text(0.5, 0.5, msg, ha="center", va="center",
                     fontsize=12, color="#888888",
                     transform=self.ax.transAxes)
        self.ax.set_axis_off()
        self.fig.tight_layout()
        self._view0 = None
        self.canvas.draw()

    # ------------------------------------------------------------
    # 交互: 滚轮缩放 / 拖动平移 / 双击复原
    # ------------------------------------------------------------
    def _on_scroll(self, event):
        if event.inaxes is not self.ax or not self._view0:
            return
        up = (event.button == "up" or getattr(event, "step", 0) > 0)
        factor = 0.85 if up else 1.18
        ax = self.ax
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        fw, fh = self._view0
        span_x, span_y = abs(x1 - x0), abs(y1 - y0)
        if not up and span_x * factor >= fw and span_y * factor >= fh:
            self._reset_view()
            return
        if up and max(span_x, span_y) * factor < 30.0:
            return                          # 放大到 30pt 宽就不再放大
        xm, ym = event.xdata, event.ydata
        ax.set_xlim(xm + (x0 - xm) * factor, xm + (x1 - xm) * factor)
        ax.set_ylim(ym + (y0 - ym) * factor, ym + (y1 - ym) * factor)
        self.canvas.draw_idle()

    def _on_press(self, event):
        if event.inaxes is not self.ax or not self._view0:
            return
        if getattr(event, "dblclick", False):
            self._reset_view()
            return
        if event.button == 1 and event.xdata is not None:
            x0, x1 = self.ax.get_xlim()
            y0, y1 = self.ax.get_ylim()
            self._pan_start = (event.xdata, event.ydata, x0, x1, y0, y1)

    def _on_motion(self, event):
        if not self._pan_start or event.inaxes is not self.ax:
            return
        sx, sy, x0, x1, y0, y1 = self._pan_start
        if event.xdata is None:
            return
        dx, dy = event.xdata - sx, event.ydata - sy
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return
        self.ax.set_xlim(x0 - dx, x1 - dx)
        self.ax.set_ylim(y0 - dy, y1 - dy)
        self.canvas.draw_idle()

    def _on_release(self, event):
        self._pan_start = None

    def _reset_view(self):
        if self._view0:
            pw, ph = self._view0
            self.ax.set_xlim(0, pw)
            self.ax.set_ylim(ph, 0)
            self.canvas.draw_idle()

    # ------------------------------------------------------------
    # 标签文字: 与 VBA「填数据」一致 (井名 / KOP / INC / AZI / MD)
    # ------------------------------------------------------------
    @staticmethod
    def _g(v):
        return "—" if v is None else f"{v:g}"

    def _well_text(self, rec):
        return "\n".join((
            rec.get("井名", ""),
            f'KOP:{self._g(rec.get("k1"))}/{self._g(rec.get("k2"))}',
            f'INC:{self._g(rec.get("inc1"))}/{self._g(rec.get("inc2"))}',
            f'AZI:{self._g(rec.get("azi1"))}/{self._g(rec.get("azi2"))}',
            f'MD:{self._g(rec.get("md"))}',
        ))

    # ------------------------------------------------------------
    # 井名标签的浅蓝正方形边框 (以 (cx, cy) 为中心)
    # ------------------------------------------------------------
    def _slot_label_box(self, ax, cx, cy, side, k=1.0):
        ax.add_patch(Rectangle((cx - side / 2.0, cy - side / 2.0), side, side,
                               facecolor="none", edgecolor="#9DC3E6",
                               linewidth=0.8 * k, zorder=4))

    # ------------------------------------------------------------
    # 行距 / 列距 标注: 双箭头 + 数值; 过远的行距只画 1.2×行距并标实际距离
    # ------------------------------------------------------------
    def _draw_slot_dims(self, ax, lay, k=1.0):
        D = lay["slot_d"]
        nr, nc = lay["n_rows"], lay["n_cols"]
        fs = max(2.6, 7.0 * k)
        col = "#1F3864"
        arrow = dict(arrowstyle="<|-|>", color=col, linewidth=0.8,
                     shrinkA=0, shrinkB=0, mutation_scale=7 * k)

        # 列距: 放在最上面一行「相邻两列都有槽」的上方, 取最接近名义列距的一段
        occ = {(c["row"], c["col"]) for c in lay["cells"]}
        pair = None
        for i in range(nr):
            cand = [j for j in range(nc - 1)
                    if not lay["col_compressed"][j]
                    and (i, j) in occ and (i, j + 1) in occ]
            if cand:
                pair = (i, min(cand, key=lambda t: abs(lay["col_gaps"][t] - lay["col_base"])))
                break
        if pair is None:
            normal_c = [j for j, c in enumerate(lay["col_compressed"]) if not c]
            if normal_c:
                pair = (0, min(normal_c,
                               key=lambda t: abs(lay["col_gaps"][t] - lay["col_base"])))
        if nc > 1 and pair:
            i, j = pair
            x1, x2 = lay["col_x"][j], lay["col_x"][j + 1]
            y = lay["row_y"][i] - D / 2.0 - 5.0
            ax.annotate("", xy=(x1, y), xytext=(x2, y),
                        arrowprops=arrow, zorder=8)
            ax.text((x1 + x2) / 2.0, y - 2.0, f'列距 {lay["col_base"]:.2f}m',
                    ha="center", va="bottom", fontsize=fs, color=col,
                    fontfamily="Microsoft YaHei", zorder=9)

        # 行距: 最左侧, 取最接近名义行距的一段
        if nr > 1:
            dx = lay["x0"] - 11.0
            normal_r = [i for i, c in enumerate(lay["row_compressed"]) if not c]
            if normal_r:
                i = min(normal_r, key=lambda t: abs(lay["row_gaps"][t] - lay["row_base"]))
                y1, y2 = lay["row_y"][i], lay["row_y"][i + 1]
                ax.annotate("", xy=(dx, y1), xytext=(dx, y2),
                            arrowprops=arrow, zorder=8)
                ax.text(dx - 3.0, (y1 + y2) / 2.0, f'行距 {lay["row_base"]:.2f}m',
                        ha="center", va="center", rotation=90, fontsize=fs,
                        color=col, fontfamily="Microsoft YaHei", zorder=9)

            # 过远的行距: 该段只画 1.2×行距, 标实际北向距离
            for i, comp in enumerate(lay["row_compressed"]):
                if not comp:
                    continue
                y1, y2 = lay["row_y"][i], lay["row_y"][i + 1]
                ax.annotate("", xy=(dx, y1), xytext=(dx, y2),
                            arrowprops=dict(arrowstyle="<|-|>", color="#C00000",
                                            linewidth=0.8, shrinkA=0, shrinkB=0,
                                            mutation_scale=7 * k), zorder=8)
                ax.text(dx - 3.0, (y1 + y2) / 2.0,
                        f'实际 {lay["row_gaps"][i]:.2f}m',
                        ha="center", va="center", rotation=90, fontsize=fs,
                        color="#C00000", fontfamily="Microsoft YaHei", zorder=9)

    # ------------------------------------------------------------
    # 主绘图: 槽口圆圈 + 白底标签 + 方位箭头 + PN/TN 指示
    # ------------------------------------------------------------
    def _draw_slot_map(self, result, plat_n, plat_e, plat_rot_deg, conv_deg):
        """按 A4 版面 (与 Excel 导出版一致) 渲染槽口图"""
        ax = self.ax
        ax.clear()
        if not result:
            self._blank_figure("无井数据"); return

        lay = slot_layout(result)
        page_w, page_h = lay["page_w"], lay["page_h"]
        D = lay["slot_d"]

        # 画布按 A4 实际尺寸 (1pt = 1pt), 导出 PDF 即 1:1 A4
        self.fig.set_size_inches(page_w / 72.0, page_h / 72.0)
        k = 1.0                             # 版面 pt → 图面 pt 的缩放
        ax.set_aspect("equal")
        ax.set_xlim(0, page_w)
        ax.set_ylim(page_h, 0)              # Y 向下, 与 Excel 版面一致
        ax.set_axis_off()
        self._view0 = (page_w, page_h)      # 初始视图, 供缩放/复原

        try:                                # 用于量取文字实际尺寸
            renderer = self.fig.canvas.get_renderer()
        except Exception:
            try:                            # 先画一次再从画布取渲染器
                self.fig.canvas.draw()
                renderer = self.fig.canvas.get_renderer()
            except Exception:
                renderer = None

        rot_deg = plat_rot_deg - conv_deg
        for c in lay["cells"]:
            x, y = c["x"], c["y"]
            ax.add_patch(Circle((x, y), D / 2.0, facecolor="white",
                                edgecolor="#1F3864", linewidth=0.9 * k * 1.2,
                                zorder=3))
            wells = c["wells"]
            n = len(wells)
            # 标签正方形边长: 单井/空槽可放大, 双井上下两框相贴不能超半圆
            side = (0.56 if n == 1 else 0.52) * D
            if n == 1 and wells[0].get("_empty"):
                self._slot_label_box(ax, x, y, side, k)
                ax.text(x, y, str(wells[0].get("槽口", "")), ha="center", va="center",
                        fontsize=max(4.0, 0.18 * D), color="#808080",
                        fontfamily="Microsoft YaHei", zorder=6)
                continue
            for idx, rec in enumerate(wells):
                # 单井/空槽: 方框居中于圆心; 双井: 上下各一个方框
                if n == 1:
                    by = y
                else:
                    by = (y - side / 2.0) if idx % 2 == 0 else (y + side / 2.0)
                self._slot_label_box(ax, x, by, side, k)
                text = self._well_text(rec)
                # 字号自适应: 以 8pt 实测文字外框, 按比例缩到正方形内 (四周留 3% 空隙)
                fs = 8.0
                if renderer is not None:
                    probe = ax.text(x, by, text, ha="center", va="center",
                                    fontsize=fs, linespacing=0.95,
                                    fontfamily="Microsoft YaHei", alpha=0.0)
                    bb = probe.get_window_extent(renderer)
                    probe.remove()
                    wp = bb.width / self.fig.dpi * 72.0
                    hp = bb.height / self.fig.dpi * 72.0
                    fs = min(8.0, 0.94 * side * 8.0 / max(wp, 1e-6),
                             0.94 * side * 8.0 / max(hp, 1e-6))
                else:                       # 量不到渲染器时按字符宽度估算
                    widest = max(len(s) for s in text.split("\n"))
                    fs = min(8.0, 0.94 * side / max(widest * 0.58, 1e-6),
                             0.94 * side / (5 * 1.30))
                ax.text(x, by, text, ha="center", va="center",
                        fontsize=max(2.0, fs), color="#1F3864", linespacing=0.95,
                        fontfamily="Microsoft YaHei", zorder=6)

                if rec.get("azi1") is not None:
                    az = math.radians(rec["azi1"] - rot_deg)
                    L = 0.5 * D
                    ax.annotate("", xy=(x + math.sin(az) * L, by - math.cos(az) * L),
                                xytext=(x, by),
                                arrowprops=dict(arrowstyle="-|>", color="#208040",
                                                linewidth=0.9,
                                                shrinkA=0, shrinkB=0),
                                zorder=5)

        # ---- 行距 / 列距 标注 ----
        self._draw_slot_dims(ax, lay, k)

        # ---- 平台中心 ----
        px, py = slot_center_xy(lay)
        ax.plot(px, py, "x", markersize=9 * k * 1.2, markeredgecolor="#C00000",
                markeredgewidth=1.6, zorder=7)
        ax.text(px - 5 * k * 1.2, py + 9 * k * 1.2, "平台中心", ha="right", va="top",
                fontsize=max(2.0, 7 * k), color="#C00000", fontweight="bold",
                fontfamily="Microsoft YaHei", zorder=7)

        # ---- 罗盘: PN 永远朝正上方; 平台北为正 → TN 在左, 为负 → TN 在右 ----
        cp = slot_compass_geom(lay, plat_rot_deg)
        ox, oy = cp["ox"], cp["oy"]
        ln = SLOT_COMPASS_LEN
        ax.annotate("", xy=(ox, oy - ln), xytext=(ox, oy),
                    arrowprops=dict(arrowstyle="-|>", color="k", lw=1.4), zorder=8)
        ax.text(cp["pn_x"], oy - ln, "PN", ha="right" if cp["left"] else "left",
                va="center", fontsize=max(2.0, 8 * k), fontweight="bold",
                fontfamily="Microsoft YaHei", zorder=9)
        tx, ty = cp["tip"]
        ax.annotate("", xy=(tx, ty), xytext=(ox, oy),
                    arrowprops=dict(arrowstyle="-|>", color="#7F7F7F", lw=1.0,
                                    linestyle="--"), zorder=8)
        ax.text(cp["tn_x"], ty, "TN", ha="right" if cp["left"] else "left",
                va="center", color="#595959",
                fontsize=max(2.0, 8 * k), fontfamily="Microsoft YaHei", zorder=9)

        if abs(plat_rot_deg) > 0.01:
            R = cp["R"]
            angs = np.linspace(0.0, -plat_rot_deg, 25)
            ax.plot([ox + math.sin(math.radians(a)) * R for a in angs],
                    [oy - math.cos(math.radians(a)) * R for a in angs],
                    color="#595959", lw=0.9, zorder=8)
            axx, ayy = cp["angle"]
            ax.text(axx, ayy, f"{abs(plat_rot_deg):.2f}°", ha="center", va="center",
                    color="#404040", fontsize=max(2.0, 7.5 * k),
                    fontfamily="Microsoft YaHei", zorder=9)

        # ---- 标题 ----
        ax.text(page_w / 2.0, lay["margin"] + 6, "平台槽口图", ha="center", va="top",
                fontsize=max(3.0, 15 * k), fontweight="bold", color="#1F3864",
                fontfamily="Microsoft YaHei", zorder=9)
        ax.text(page_w / 2.0, lay["margin"] + 24,
                f"平台中心 N={plat_n:.2f} E={plat_e:.2f}    "
                f"平台北角 {plat_rot_deg:+.2f}°",
                ha="center", va="top", fontsize=max(2.0, 7 * k), color="#404040",
                fontfamily="Microsoft YaHei", zorder=9)

        self.fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
        self.canvas.draw()


# ================================================================
# ================================================================
# TAB 5. 寻找最优点 (Mark 点五参数优化对齐, 源: 15-寻找最优点/寻找最优点参数.py)
# ================================================================
# ================================================================
class MarkPointTab(ttk.Frame):
    """Mark 点五参数寻优: 左右两块粘贴 A/B 井靶点, 第三块输出最优结果"""

    def __init__(self, master, controller=None):
        super().__init__(master)
        self.controller = controller
        self._q = queue.Queue()
        self._running = False
        self._module = None
        self._build_ui()
        self._poll()

    # ---------------- UI ----------------
    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        head = tk.Frame(self)
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
        tk.Label(head, text="Mark 点五参数寻优", font=("Microsoft YaHei UI", 14, "bold"),
                 foreground=HEADER_BG).pack(side="left")
        tk.Label(head, text="优化对齐 CLC 轨迹，使 Mark→A_T1 与 Mark→B_T1 总井深最小",
                 foreground="#606060").pack(side="left", padx=(12, 0))

        # ①② 两个粘贴面板左右并排
        pan = tk.PanedWindow(self, orient="horizontal", sashwidth=4,
                             sashrelief="groove")
        pan.grid(row=1, column=0, sticky="nsew", padx=8)
        self._t1_a = self._paste_panel(pan, "A 井靶点", "①")
        self._t1_b = self._paste_panel(pan, "B 井靶点", "②")

        # ③ 垂深约束 + 计算按钮
        ctrl = ttk.LabelFrame(self, text="③ 寻优参数", padding=(10, 6, 10, 6))
        ctrl.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 0))
        self._var_fixed_mtvd = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctrl, text="指定 Mark 点垂深（不勾选=垂深无限制）",
                        variable=self._var_fixed_mtvd,
                        command=self._toggle_mtvd).pack(side="left")
        self._e_mtvd = ttk.Entry(ctrl, width=10, state="disabled")
        self._e_mtvd.pack(side="left", padx=(6, 14))
        ttk.Label(ctrl, text="DLS1 / DLS2 (°/30m)").pack(side="left")
        self._e_dls1 = ttk.Entry(ctrl, width=5)
        self._e_dls1.insert(0, "3.0")
        self._e_dls1.pack(side="left", padx=(4, 6))
        self._e_dls2 = ttk.Entry(ctrl, width=5)
        self._e_dls2.insert(0, "3.0")
        self._e_dls2.pack(side="left", padx=(0, 14))
        self._btn_go = ttk.Button(ctrl, text="计算最优点", command=self._go)
        self._btn_go.pack(side="left")

        # 结果输出
        out = ttk.LabelFrame(self, text="最优 Mark 点五参数", padding=(10, 6, 10, 6))
        out.grid(row=3, column=0, sticky="nsew", padx=12, pady=(8, 12))
        self._res_text = tk.Text(out, height=10, font=("Microsoft YaHei", 10),
                                 state="disabled", wrap="word")
        sv = ttk.Scrollbar(out, orient="vertical", command=self._res_text.yview)
        self._res_text.configure(yscrollcommand=sv.set)
        self._res_text.pack(side="left", fill="both", expand=True)
        sv.pack(side="right", fill="y")
        self._res("粘贴 A/B 井靶点后点击「计算最优点」。")
        self._res("  双靶点：两行，每行 X Y Z（T1、T2）")
        self._res("  单靶点：一行 X Y Z 井斜 方位")

    def _paste_panel(self, pan, title, idx):
        box = ttk.Frame(pan, padding=10)
        tk.Label(box, text=f"{idx}  {title}", font=("Microsoft YaHei UI", 11, "bold"),
                 foreground=HEADER_BG).pack(anchor="w")
        tk.Label(box, text="双靶点：两行 X Y Z（T1、T2）\n单靶点：一行 X Y Z 井斜 方位",
                 foreground="#707070", justify="left").pack(anchor="w", pady=(4, 6))
        txt = tk.Text(box, height=7, font=("Consolas", 10), wrap="none", undo=True)
        txt.pack(fill="both", expand=True)
        pan.add(box, minsize=240)
        return txt

    def _toggle_mtvd(self):
        self._e_mtvd.config(state="normal" if self._var_fixed_mtvd.get() else "disabled")

    def _res(self, text, clear=False):
        self._res_text.configure(state="normal")
        if clear:
            self._res_text.delete("1.0", "end")
        self._res_text.insert("end", text + "\n")
        self._res_text.see("end")
        self._res_text.configure(state="disabled")

    # ---------------- 计算 ----------------
    @staticmethod
    def _parse_line(raw):
        """一行 → 3 或 5 个浮点数（忽略 T1/T2、A/T 等标签）"""
        nums = []
        for tok in raw.replace("，", " ").replace(",", " ").replace(";", " ").split():
            if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", tok):
                nums.append(float(tok))
        if len(nums) == 3:
            return tuple(nums)
        if len(nums) == 5:
            return tuple(nums)
        if not nums:
            return None
        raise ValueError(f"每行需要 3 个数（X Y Z）或 5 个数（X Y Z 井斜 方位），"
                         f"这一行有 {len(nums)} 个：{raw.strip()}")

    def _parse_targets(self, text, well):
        rows = []
        for raw in text.splitlines():
            if not raw.strip():
                continue
            row = self._parse_line(raw)
            if row is not None:
                rows.append(row)
        if not rows:
            raise ValueError(f"{well} 井：请粘贴靶点数据")
        if len(rows) > 2:
            raise ValueError(f"{well} 井：最多两行（T1、T2）")
        if len(rows) == 1 and len(rows[0]) != 5:
            raise ValueError(f"{well} 井：单靶点需要 5 个数（X Y Z 井斜 方位）；"
                             f"若只给 X Y Z，请再加一行 T2")
        if len(rows) == 2 and len(rows[1]) != 3:
            raise ValueError(f"{well} 井：第二行 T2 必须是 3 个数（X Y Z）")
        t2 = rows[1] if len(rows) == 2 else None
        return rows[0], t2

    def _load_optimizer(self):
        if self._module is None:
            import importlib.util
            base = (getattr(sys, "_MEIPASS", None)
                    or os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base, "15-寻找最优点", "寻找最优点参数.py")
            spec = importlib.util.spec_from_file_location("mark_point_opt", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._module = module
        return self._module

    def _go(self):
        if self._running:
            messagebox.showinfo("提示", "计算正在后台进行，请稍候。")
            return
        try:
            a_t1, a_t2 = self._parse_targets(self._t1_a.get("1.0", "end"), "A")
            b_t1, b_t2 = self._parse_targets(self._t1_b.get("1.0", "end"), "B")
            dls1 = float(self._e_dls1.get())
            dls2 = float(self._e_dls2.get())
            if self._var_fixed_mtvd.get():
                if not self._e_mtvd.get().strip():
                    raise ValueError("已勾选「指定 Mark 点垂深」，请填写垂深数值")
                mtvd = float(self._e_mtvd.get())
            else:
                mtvd = None
        except ValueError as e:
            messagebox.showerror("输入有误", str(e)); return

        self._res("--- 计算中（差分进化 + Nelder-Mead 精修，可能需要十几秒）---", clear=True)
        self._running = True
        self._btn_go.config(state="disabled")

        def worker():
            try:
                mod = self._load_optimizer()
                res = mod.optimize_mark_point(dls1, dls2, a_t1, b_t1,
                                              a_t2=a_t2, b_t2=b_t2, mtvd=mtvd)
                self._q.put(("done", res))
            except Exception as e:
                self._q.put(("err", f"{type(e).__name__}: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self._q.get_nowait()
                self._running = False
                self._btn_go.config(state="normal")
                if kind == "err":
                    self._res(f"运行异常：{payload}")
                else:
                    self._show_result(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _show_result(self, res):
        if not res.ok:
            self._res(f"未找到可行解：{res.message}")
            return
        m = res.mark
        lines = [
            f"总井深（Mark→A_T1 + Mark→B_T1）= {res.total_md:.4f} m",
            f"狗腿度 DLS1/DLS2 = {res.dls1:g}/{res.dls2:g} °/30m",
            ("Mark 垂深约束 = " + f"{res.mtvd:.2f} m") if res.mtvd is not None
            else "Mark 垂深 = 自由优化（无限制）",
            "",
            "Mark 点五参数：",
            f"    INCm = {m[0]:.4f} °",
            f"    AZIm = {m[1]:.4f} °",
            f"    MN   = {m[2]:.4f}",
            f"    ME   = {m[3]:.4f}",
            f"    MT   = {m[4]:.4f}",
            "",
            (f"A 井 T1 五参数: INC={res.a_t1[3]:.4f}° AZI={res.a_t1[4]:.4f}° "
             f"N={res.a_t1[0]:.2f} E={res.a_t1[1]:.2f} TVD={res.a_t1[2]:.2f}"),
            (f"B 井 T1 五参数: INC={res.b_t1[3]:.4f}° AZI={res.b_t1[4]:.4f}° "
             f"N={res.b_t1[0]:.2f} E={res.b_t1[1]:.2f} TVD={res.b_t1[2]:.2f}"),
            "",
            "─" * 50,
            "CLC 轨迹详情（圆弧-稳斜-圆弧，精修后残差应 < 1e-6 m）：",
        ]
        for name, seg in (("Mark → A_T1", res.seg_a), ("Mark → B_T1", res.seg_b)):
            if seg is None or not seg.get("ok", True):
                lines.append(f"\n  {name}: 无解或残差超限")
                continue
            md_tot = seg["md1"] + seg["md2"] + seg["md3"]
            err = seg["error"]
            ok = err < 1e-6
            tag = "✅" if ok else ("⚠" if err < 0.01 else "❌")
            lines.append(f"\n  {name}  合计 MD = {md_tot:.3f} m  "
                         f"CLC 还原残差 = {err:.2e} m  {tag}")
            lines.append(f"    弧1: 转角 {seg['alpha1_deg']:.3f}°  MD = {seg['md1']:.2f} m")
            if seg["md2"] > 1e-6:
                lines.append(f"    稳斜: INC = {seg['inc2']:.4f}°  AZI = {seg['azi2']:.4f}°"
                             f"  MD = {seg['md2']:.2f} m")
            else:
                lines.append(f"    稳斜段长 ≈ 0（无 C 段，纯圆弧组合）")
            lines.append(f"    弧2: 转角 {seg['alpha2_deg']:.3f}°  MD = {seg['md3']:.2f} m")
        self._res("\n".join(lines))


# ================================================================
# ================================================================
# TAB 6. 槽口重命名 (旋转平台槽口按 从下往上→从左往右 编 #01、#02…)
# ================================================================
# ================================================================
class SlotRenameTab(ttk.Frame):
    """槽口重命名：对旋转过的槽口坐标按平台系重编 #01…

    输入坐标为旋转 θ° 后的画布坐标，内部按 -θ 逆旋转回平台系。
    标题生成方式（下拉可选）。语义：「由A再由B」= 组内按 A 方向排，跨组按 B 方向排：
      · 由左往右再由下往上：按 pn 聚行，行从下往上，行内 pe 升序（左→右）
      · 由下往上再由左往右：按 pe 聚列，列从左往右，列内 pn 升序（下→上）
      · 由左往右再由上往下：按 pn 聚行，行从上往下，行内 pe 升序（左→右）
    聚行/聚列容差由「行距容差」控制。
    """

    def __init__(self, master, controller=None):
        super().__init__(master)
        self.records = []  # [{new, old, n, e, pn, pe}]
        self._build_ui()

    # ---------- 布局 ----------
    def _build_ui(self):
        outer = ttk.Frame(self, padding=(12, 10, 12, 10))
        outer.pack(fill="both", expand=True)

        sec1 = ttk.LabelFrame(outer, text=" ① 槽口坐标（粘贴或选择 TXT，格式：槽口号 北位移 东位移） ", padding=(10, 8))
        sec1.pack(fill="x")

        line1 = ttk.Frame(sec1); line1.pack(fill="x")
        self.var_path = tk.StringVar()
        ttk.Label(line1, text="文件：").pack(side="left")
        ttk.Entry(line1, textvariable=self.var_path, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(line1, text="选择文件…", command=self.pick_file).pack(side="left")

        line2 = ttk.Frame(sec1); line2.pack(fill="x", pady=(6, 0))
        ttk.Label(line2, text="粘贴：").pack(side="left", anchor="n")
        self.txt_paste = tk.Text(line2, height=5, wrap="none")
        self.txt_paste.pack(side="left", fill="x", expand=True, padx=(0, 8))

        line3 = ttk.Frame(sec1); line3.pack(fill="x", pady=(6, 0))
        ttk.Label(line3, text="旋转角θ(°)：").pack(side="left")
        self.var_angle = tk.StringVar(value="67.5")
        ttk.Entry(line3, textvariable=self.var_angle, width=8).pack(side="left")
        ttk.Label(line3, text="（坐标相对平台北顺时针旋转的角度，按 -θ 还原）").pack(side="left", padx=(4, 16))
        ttk.Label(line3, text="行距容差(m)：").pack(side="left")
        self.var_tol = tk.StringVar(value="1.0")
        ttk.Entry(line3, textvariable=self.var_tol, width=6).pack(side="left")
        ttk.Label(line3, text="标题生成方式：").pack(side="left", padx=(16, 0))
        self.var_mode = tk.StringVar(value="由下往上再由左往右")
        self.cbo_mode = ttk.Combobox(line3, textvariable=self.var_mode, state="readonly", width=22)
        self.cbo_mode["values"] = (
            "由左往右再由下往上",
            "由下往上再由左往右",
            "由左往右再由上往下",
        )
        self.cbo_mode.pack(side="left")
        ttk.Button(line3, text="重新命名", command=self.rename).pack(side="right")

        self.var_status = tk.StringVar(value="请粘贴槽口坐标或选择 TXT 文件")
        ttk.Label(sec1, textvariable=self.var_status, foreground="#666666").pack(anchor="w", pady=(6, 0))

        # 按钮行先以 side="bottom" 占位，窗口高度不足时也不会被结果表格挤出屏幕
        line4 = ttk.Frame(outer); line4.pack(fill="x", side="bottom", pady=(8, 0))
        ttk.Button(line4, text="复制表格", command=self.copy_table).pack(side="left")
        ttk.Button(line4, text="仅复制新槽号+位移", command=self.copy_new_only).pack(side="left", padx=(8, 0))
        ttk.Button(line4, text="导出 Excel", command=self.export_excel).pack(side="left", padx=(8, 0))

        sec2 = ttk.LabelFrame(outer, text=" ② 重命名结果 ", padding=(10, 8))
        sec2.pack(fill="both", expand=True, pady=(8, 0))
        cols = ("new", "old", "n", "e")
        self.tree = ttk.Treeview(sec2, columns=cols, show="headings", height=14)
        for cid, title, w in zip(cols, ("新槽号", "原槽号", "北位移(m)", "东位移(m)"), (90, 120, 130, 130)):
            self.tree.heading(cid, text=title)
            self.tree.column(cid, width=w, anchor="center")
        vsb = ttk.Scrollbar(sec2, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ---------- 输入 ----------
    def pick_file(self):
        path = filedialog.askopenfilename(
            title="选择槽口 TXT 文件", filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        self.var_path.set(path)
        self.txt_paste.delete("1.0", "end")
        self.txt_paste.insert("1.0", read_text_file(path))
        self.var_status.set(f"已读取：{path}")

    # ---------- 核心算法 ----------
    def rename(self):
        slots = parse_slot_coords(self.txt_paste.get("1.0", "end"))
        if not slots:
            messagebox.showwarning("无数据", "未识别到槽口坐标，格式：槽口号 北位移 东位移")
            return
        try:
            theta = float(self.var_angle.get())
            tol = float(self.var_tol.get())
        except ValueError:
            messagebox.showwarning("参数错误", "旋转角 / 行距容差必须是数字")
            return
        if tol <= 0:
            messagebox.showwarning("参数错误", "行距容差必须大于 0")
            return
        phi = math.radians(-theta)  # 逆旋转回平台系
        c, s = math.cos(phi), math.sin(phi)
        items = []
        for name, (n, e) in slots.items():
            pn = n * c - e * s
            pe = n * s + e * c
            items.append({"old": name, "n": n, "e": e, "pn": pn, "pe": pe})
        mode = self.var_mode.get()
        digits = max(2, len(str(len(items))))
        self.records = []
        # 语义：「由A再由B」= 组内按 A 方向排，跨组按 B 方向排
        if mode == "由下往上再由左往右":
            # 列优先：按东向(pe)聚列，列从左往右(pe升序)，列内从下往上(pn升序)
            items.sort(key=lambda r: r["pe"])
            groups = []
            for it in items:
                if groups and abs(it["pe"] - groups[-1][-1]["pe"]) <= tol:
                    groups[-1].append(it)
                else:
                    groups.append([it])
            for g in groups:
                g.sort(key=lambda r: r["pn"])  # 列内从下往上
            unit = "列"
        else:
            # 行优先：按北向(pn)聚行，行内从左往右(pe升序)
            items.sort(key=lambda r: r["pn"])
            groups = []
            for it in items:
                if groups and abs(it["pn"] - groups[-1][-1]["pn"]) <= tol:
                    groups[-1].append(it)
                else:
                    groups.append([it])
            if mode == "由左往右再由上往下":
                # 行从上往下：groups 原为 pn 升序(从下往上)，反转后从上往下
                groups.reverse()
            # else 由左往右再由下往上：行从下往上，保持原序
            for g in groups:
                g.sort(key=lambda r: r["pe"])  # 行内从左往右
            unit = "行"
        # 统一编号
        seq = 0
        for g in groups:
            for it in g:
                seq += 1
                it["new"] = f"#{seq:0{digits}d}"
                self.records.append(it)
        self._refresh()
        self.var_status.set(
            f"共 {len(self.records)} 个槽口，{len(groups)} {unit}"
            f"（θ={theta}°，行距容差 {tol} m，{mode}）")

    # ---------- 输出 ----------
    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        for index, rec in enumerate(self.records):
            self.tree.insert(
                "", "end",
                values=(rec["new"], rec["old"],
                        fmt_num(rec["n"], 2), fmt_num(rec["e"], 2)),
                tags=("odd",) if index % 2 else ("even",),
            )

    def _table_rows(self):
        rows = [("新槽号", "原槽号", "北位移", "东位移")]
        for rec in self.records:
            rows.append((rec["new"], rec["old"],
                         fmt_num(rec["n"], 2), fmt_num(rec["e"], 2)))
        return rows

    def copy_table(self):
        if not self.records:
            return
        text = "\n".join("\t".join(row) for row in self._table_rows())
        self.clipboard_clear(); self.clipboard_append(text); self.update()
        self.var_status.set(f"已复制 {len(self.records)} 条槽口到剪贴板")

    def copy_new_only(self):
        """只复制 新槽号 北位移 东位移（无表头，可直接粘贴到槽口图 DIY 区）"""
        if not self.records:
            return
        text = "\n".join(
            f'{rec["new"]}\t{fmt_num(rec["n"], 2)}\t{fmt_num(rec["e"], 2)}'
            for rec in self.records)
        self.clipboard_clear(); self.clipboard_append(text); self.update()
        self.var_status.set(f"已复制 {len(self.records)} 条「新槽号+北/东位移」到剪贴板")

    def export_excel(self):
        if not self.records:
            return
        default_name = f"槽口重命名_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx"
        path = filedialog.asksaveasfilename(
            title="导出槽口重命名表", defaultextension=".xlsx",
            initialfile=default_name, filetypes=[("Excel 文件", "*.xlsx")])
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        wb = Workbook(); ws = wb.active; ws.title = "槽口重命名"
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="4472C4")
        center = Alignment(horizontal="center", vertical="center")
        for col, title in enumerate(("新槽号", "原槽号", "北位移", "东位移"), start=1):
            c0 = ws.cell(row=1, column=col, value=title)
            c0.font = header_font; c0.fill = header_fill; c0.alignment = center
        for row_index, rec in enumerate(self.records, start=2):
            ws.cell(row=row_index, column=1, value=rec["new"])
            ws.cell(row=row_index, column=2, value=rec["old"])
            ws.cell(row=row_index, column=3, value=round(rec["n"], 3))
            ws.cell(row=row_index, column=4, value=round(rec["e"], 3))
        for col, width in zip("ABCD", (12, 16, 14, 14)):
            ws.column_dimensions[col].width = width
        ws.freeze_panes = "A2"
        try:
            wb.save(path)
        except Exception as exc:
            messagebox.showerror("导出失败", f"无法保存文件：\n{path}\n\n{exc}")
            return
        self.var_status.set(f"已导出：{path}")
        messagebox.showinfo("导出完成", f"共导出 {len(self.records)} 条槽口：\n{path}")


# ================================================================
# ================================================================
# TAB 7. XML 处理 (源: 设计提取(已完工).py / 提取实钻数据新(现场实钻).py /
#                    删xml格式中非实钻数据(应用场景外挂设计).py)
# ================================================================
# ================================================================

# ---------- 7 公共: XML 行级工具 ----------
XML_TAG_RE = re.compile(r'<([A-Z0-9_]+)')


def xml_get_tag(line):
    """取行首标签名，非标签行返回None"""
    match = XML_TAG_RE.match(line.strip())
    return match.group(1) if match else None


def xml_get_attr(line, name):
    """从XML行中提取属性值（要求属性名前是空白，支持单/双引号，且值内部可含另一种引号）"""
    match = re.search(rf'\s{name}=(["\'])(.*?)\1', line)
    return match.group(2) if match else None


def xml_get_attr_loose(line, name):
    """与源脚本 extract_attribute 行为一致：属性名前不加空白约束，
    因此 well_id 也能命中 drill_well_id= 中的子串（保留源脚本既有行为）"""
    match = re.search(rf'{name}=(["\'])(.*?)\1', line)
    return match.group(2) if match else None


# ---------- 7.1 设计提取（合并全设计 / 已完工实钻） ----------
# 必须保留：轨迹相关标签
XML_TRAJECTORY_TAGS = (
    'CD_POLICY', 'CD_PROJECT', 'CD_SITE', 'DP_TEMPLATE', 'CD_WELL', 'CD_DATUM', 'CD_WELLBORE',
    'CD_DEFINITIVE_SURVEY_HEADER', 'CD_DEFINITIVE_SURVEY_STATION', 'CD_SURVEY_PROGRAM',
    'CD_VERTICAL_SECTION', 'CD_SCENARIO', 'CD_SURVEY_HEADER', 'CD_SURVEY_STATION','CD_CASE'
)
# 选择保留：水力相关标签
XML_HYDRAULIC_TAGS = (
    'CD_ASSEMBLY', 'CD_ASSEMBLY_COMP', 'CD_BHA_COMP', 'CD_CASE',
    'CD_NBK_LEAK_OFF', 'CD_FLUID', 'CD_HOLE_SECT',
)
XML_KEEP_TAGS = set(XML_TRAJECTORY_TAGS + XML_HYDRAULIC_TAGS)
XML_TARGET_TAG = 'DP_PROJECT_TARGET'
# 引用靶点的表：测站，以及 LINKTABLE 中的靶点关联表
XML_TARGET_REF_TAGS = (
    'CD_SURVEY_STATION', 'CD_PROJ_TARG_WELL_LINK', 'CD_PROJECT_TARGET_WB_LINK',
    'CD_PROJECT_TARGET_SITE_LINK', 'CD_PROJ_TARG_SCENARIO_LINK',
)

# 改ID：提取前先统一替换这些ID
XML_REPLACE_GROUPS = [
    {'old_ids': ['PRDPL00000', 'rNJS0Mx2vV', 'gSyBMQKdDt'], 'new_id': '12345Mx2vV'}
]
# 测量工具ID：survey_tool_id 属性内精确替换（不全局替换，避免误伤）
XML_SURVEY_TOOL_REPLACE_GROUPS = [
    {'old_ids': ['8b4PS', 'HdWb7', 'CU5bO'], 'new_id': 'mDBG5'},
    {'old_ids': ['vLU3w', 'Av6LZ', 'eUZtM'], 'new_id': 'TKHg1'}
]

# 表头（固定，不随源文件）
XML_HEADER = (
    '<?xml version="1.0" standalone="no"?>',
    '<?DataServices DB_Major_Version=17;DB_Minor_Version=01;DB_Build_Version=000;'
    'DB_Version=EDM 5000.17.1 (17.01.00.000);expandPoint=CD_SCENARIO;?>',
    '',
    '<export>',
    '<TOPLEVEL>',
    '<CD_GEO_SYSTEM geo_system_id="BOHAI" measure_id="121" geo_system_name="Bohai Gauss Projection" />',
    '<CD_GEO_ZONE geo_system_id="BOHAI" geo_zone_id="Zone20, North 117E to 123E" '
    'zone_name="Zone20, North 117E to 123E" lat_origin="0.0" lon_origin="120.0" '
    'scale_factor="0.9996" false_easting="500000.0" false_northing="0.0" proj_type="0" />',
    '<CD_GEO_DATUM geo_datum_id="WGS84" datum_name="WGS 1984" geo_ellipsoid_id="WGS84" '
    'pmshift="0.0" x_shift="0.0" y_shift="0.0" z_shift="0.0" x_rotate="0.0" y_rotate="0.0" '
    'z_rotate="0.0" scale_factor="0.0" />',
    '<CD_GEO_ELLIPSOID geo_ellipsoid_id="WGS84" name="WGS 1984" semi_major="6378137.0" '
    'first_eccentricity="0.0818191908426215" />',
    '</TOPLEVEL>',
)

# 生成文件的统一结尾：清除 <LINKTABLE> 之后的全部内容，替换为下面四行
XML_DEFAULT_ENDING = (
    '</LINKTABLE>',
    '<BINARY_DATA data_encoding="base64">',
    '</BINARY_DATA>',
    '</export>',
)


def xml_align_default_ending(lines):
    """统一收尾：清除 <LINKTABLE> 之后的全部内容，补回标准结尾"""
    idx = next((i for i, l in enumerate(lines) if l.strip().startswith('<LINKTABLE>')), None)
    if idx is None:
        return list(lines)
    return list(lines[:idx + 1]) + list(XML_DEFAULT_ENDING)


def xml_replace_ids(content, groups=XML_REPLACE_GROUPS):
    """改ID：全局替换"""
    for group in groups:
        for old_id in group['old_ids']:
            content = content.replace(old_id, group['new_id'])
    return content


def xml_replace_survey_tool_ids(content, groups=XML_SURVEY_TOOL_REPLACE_GROUPS):
    """survey_tool_id 属性值精确替换（仅改属性值，避免误伤正文中的其他片段）"""
    for group in groups:
        old_ids_pattern = '|'.join(group['old_ids'])
        content = re.sub(rf'survey_tool_id=(["\'])({old_ids_pattern})\1',
                         rf'survey_tool_id=\1{group["new_id"]}\1', content)
    return content


def xml_read_lines(path):
    """读取文件并先做改ID（全局ID + survey_tool_id属性值），返回行列表（兼容BOM）"""
    with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
        content = f.read()
    content = xml_replace_ids(content)
    content = xml_replace_survey_tool_ids(content)
    return content.splitlines()


def xml_collect_kept_lines(lines, seen):
    """按标签白名单收集行；CD_POLICY 按 policy_id 去重，其余按整行内容去重"""
    kept = []
    for line in lines:
        tag = xml_get_tag(line)
        if tag in XML_KEEP_TAGS:
            key = (tag, xml_get_attr(line, 'policy_id')) if tag == 'CD_POLICY' else line.strip()
            if key not in seen:
                seen.add(key)
                kept.append(line)
    return kept


def xml_collect_targets(lines):
    """靶点：只保留被测站或 LINKTABLE 关联表引用过的靶点，以及源文件 ALWAYS-UPDATE 里的靶点"""
    ref_ids = set()
    always_ids = set()
    body_targets = {}
    in_always = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('<ALWAYS-UPDATE>'):
            in_always = True
            continue
        if stripped.startswith('</ALWAYS-UPDATE>'):
            in_always = False
            continue
        tag = xml_get_tag(line)
        if tag in XML_TARGET_REF_TAGS:
            target_id = xml_get_attr(line, 'project_target_id')
            if target_id:
                ref_ids.add(target_id)
        elif tag == XML_TARGET_TAG:
            target_id = xml_get_attr(line, 'project_target_id')
            if not target_id:
                continue
            key = (xml_get_attr(line, 'project_id'), target_id)
            if in_always:
                always_ids.add(target_id)
            body_targets.setdefault(key, line)

    valid_ids = ref_ids | always_ids
    return [line for (_pid, tid), line in body_targets.items() if tid in valid_ids]


def _xml_attr(value):
    """XML 属性值转义：SQL 里出现的 & < > 必须转成实体，否则整份 EDM XML 解析失败
    （例如井槽名 'B53&B54H(12#' 中的 & 会被当成实体起始符）。"""
    return (
        str(value)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def xml_add_dp_template_updates(lines, fix_coords=True):
    """为每个被 CD_WELL.slot_name 匹配到的 DP_TEMPLATE 行，在其下方追加 update execsql：
      1. 把 DB 里 short_name 已经是该井槽名的行改名为 '<井槽名>_old'（腾出槽位名，
         但排除当前这条模板自身的 template_id）——无论是否勾选都执行；
      2. 把 (site_id, template_id) 行的 short_name / template_name 写成井槽名；
         勾选校正槽口坐标（fix_coords=True）时再追加该 DP_TEMPLATE 行自带的
         template_north / template_east（原样使用，不做旋转）。
    匹配口径：同 site_id 下 DP_TEMPLATE.short_name（缺省回退 slot_name）== CD_WELL.slot_name。"""
    well_slots = set()
    for line in lines:
        if line.strip().startswith('<CD_WELL'):
            sid = xml_get_attr_loose(line, 'site_id')
            slot = html.unescape(xml_get_attr_loose(line, 'slot_name') or '').strip()
            if sid and slot:
                well_slots.add((sid, slot))
    if not well_slots:
        return list(lines)
    renamed = set()
    out = []
    for line in lines:
        out.append(line)
        if not line.strip().startswith('<DP_TEMPLATE'):
            continue
        sid = xml_get_attr_loose(line, 'site_id')
        tid = xml_get_attr_loose(line, 'template_id')
        short_nm = html.unescape(
            xml_get_attr_loose(line, 'short_name') or xml_get_attr_loose(line, 'slot_name') or ''
        ).strip()
        if sid and tid and (sid, short_nm) in well_slots:
            # 先做 SQL 字面量转义（' -> ''），再做 XML 属性转义（& < > "）
            slot_sql = _xml_attr(short_nm.replace("'", "''"))
            sid_sql = _xml_attr(sid.replace("'", "''"))
            tid_sql = _xml_attr(tid.replace("'", "''"))
            if short_nm not in renamed:
                renamed.add(short_nm)
                out.append(
                    '<execsql command="update dp_template set '
                    f"short_name='{slot_sql}_old', template_name='{slot_sql}_old' "
                    f"from dp_template where short_name='{slot_sql}' "
                    f"and template_id!='{tid_sql}'\"/>"
                )
            # 第二条：写井槽名；勾选校正槽口坐标时再用本行自带的 template_north / template_east
            sets = [f"short_name='{slot_sql}'", f"template_name='{slot_sql}'"]
            if fix_coords:
                for col in ('template_north', 'template_east'):
                    val = xml_get_attr_loose(line, col)
                    if val:
                        sets.append(f"{col}='{val}'")
            out.append(
                '<execsql command="update dp_template set '
                + ', '.join(sets)
                + f" from dp_template dp where dp.site_id='{sid_sql}' and dp.template_id='{tid_sql}'\"/>"
            )
    return out


def xml_list_source_files(folder, exclude_prefix='全设计'):
    """列出文件夹内的 .edm.xml（排除生成的结果文件），按名称自然排序"""
    names = [
        name for name in os.listdir(folder)
        if name.lower().endswith('.edm.xml') and not name.startswith(exclude_prefix)
    ]
    names.sort(key=lambda n: [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', n)])
    return [os.path.join(folder, name) for name in names]


def xml_merge_folder(folder, out_prefix='全设计'):
    """把文件夹内所有 .edm.xml 按轨道/水力/靶点组合成一个文件"""
    files = xml_list_source_files(folder, exclude_prefix=out_prefix)
    if not files:
        raise ValueError('所选文件夹内没有 .edm.xml 文件')

    header = list(XML_HEADER)
    kept, seen = [], set()
    target_lines, target_keys = [], set()

    for path in files:
        lines = xml_read_lines(path)

        kept.extend(xml_collect_kept_lines(lines, seen))

        for line in xml_collect_targets(lines):
            project_id = xml_get_attr(line, 'project_id')
            target_id = xml_get_attr(line, 'project_target_id')
            key = (project_id, target_id)
            if key not in target_keys:
                target_keys.add(key)
                target_lines.append(line)

    kept = xml_add_dp_template_updates(kept)
    output = list(header) + kept
    output.append('<ALWAYS-UPDATE>')
    output.extend(target_lines)
    output.append('</ALWAYS-UPDATE>')
    output.append('<LINKTABLE>')
    output.extend(XML_DEFAULT_ENDING)

    out_name = f'{out_prefix}{datetime.date.today():%Y%m%d}.edm.xml'
    out_path = os.path.join(folder, out_name)
    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(output))

    return out_path, len(files), len(kept), len(target_lines)


# ---------- 7.2 提取实钻数据（现场实钻） ----------
XML_SURVEY_HEADER_PREFIXES = ('<CD_SURVEY_HEADER', '<CD_DEFINITIVE_SURVEY_HEADER')
# 整行删除规则：以这些标签开头的行一律删除
XML_REMOVE_LINE_PREFIXES = (
    '<DP_TOOL_TERM',
    '<CD_SURVEY_TOOL',
    '<CD_BHA_COMP',
    '<CD_PROJECT_TARGET_SITE_LINK',
    '<CD_PROJ_TARG_WELL_LINK',
    '<CD_PROJ_TARG_SCENARIO_LINK',
)
# 整行删除规则：包含这些片段的行一律删除
XML_REMOVE_LINE_CONTAINS = ('<CD_CHANGE_HISTORY_JOURNAL',)


def xml_is_survey_header(line):
    """判断是否为测斜头行（兼容两种表名）"""
    return line.strip().startswith(XML_SURVEY_HEADER_PREFIXES)


def xml_parse_create_date(value):
    """解析 create_date 为 date 对象，失败返回 None。兼容 EDM 的 {ts '2007-10-15 20:28:36'} 写法"""
    if not value:
        return None
    s = value.strip()
    m = re.match(r"\{ts\s*'([^']*)'\}", s) or re.match(r'\{ts\s*"([^"]*)"\}', s)
    if m:
        s = m.group(1).strip()
    try:
        return datetime.date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ('%m/%d/%Y %H:%M:%S', '%m/%d/%Y', '%Y/%m/%d'):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def xml_extract_actual_survey_create_dates(content, cutoff):
    """提取测斜头中 phase="ACTUAL" 且 create_date 晚于 cutoff 的 well_id -> 最新日期"""
    dates = {}
    for line in content.split('\n'):
        if xml_is_survey_header(line):
            if xml_get_attr_loose(line, 'phase') != 'ACTUAL':
                continue
            create_date = xml_parse_create_date(xml_get_attr_loose(line, 'create_date'))
            if create_date is None or create_date <= cutoff:
                continue
            well_id = xml_get_attr_loose(line, 'well_id')
            if well_id and (well_id not in dates or create_date > dates[well_id]):
                dates[well_id] = create_date
    return dates


def xml_remove_lines_not_in_well_ids(content, well_ids):
    """删除所有 well_id= 值不在 well_ids 集合中的行（与源脚本一致的宽松匹配），
    返回(新内容, 删除数)"""
    lines = content.split('\n')
    kept, removed = [], []
    for line in lines:
        well_id = xml_get_attr_loose(line, 'well_id')
        if well_id is not None and well_id not in well_ids:
            removed.append(line)
        else:
            kept.append(line)
    return '\n'.join(kept), len(removed), removed


def xml_remove_unwanted_lines(content):
    """删除配置中的整行：前缀匹配或片段包含，返回(新内容, 删除数)"""
    def keep(line):
        if line.strip().startswith(XML_REMOVE_LINE_PREFIXES):
            return False
        return not any(k in line for k in XML_REMOVE_LINE_CONTAINS)
    lines = content.split('\n')
    kept = [l for l in lines if keep(l)]
    return '\n'.join(kept), len(lines) - len(kept)


def xml_set_expand_point(content, name):
    """把 <?DataServices ... expandPoint=XXX;?> 改成 name，返回(新内容, 替换次数)"""
    return re.subn(r'expandPoint=[^;?]*', f'expandPoint={name}', content)


def xml_extract_project_target_ids(content):
    """提取 CD_SURVEY_STATION 行中实际引用过的 project_target_id 集合
    （这些才是有效靶点，DP_PROJECT_TARGET 和 LINKTABLE 只保留被引用的）"""
    return set(re.findall(r'<CD_SURVEY_STATION[^>]*project_target_id=(["\'])([^"\']+)\1', content))


def xml_remove_invalid_dp_project_target(content, valid_ids):
    """删除 DP_PROJECT_TARGET 中 project_target_id 不在 valid_ids 里的行（含 CD_PROJECT_TARGET 别名），
    返回(新内容, 删除数)"""
    def keep(line):
        stripped = line.strip()
        if stripped.startswith('<DP_PROJECT_TARGET') or stripped.startswith('<CD_PROJECT_TARGET'):
            tid = xml_get_attr_loose(line, 'project_target_id')
            return tid is None or tid in valid_ids
        return True
    lines = content.split('\n')
    kept = [l for l in lines if keep(l)]
    return '\n'.join(kept), len(lines) - len(kept)


def xml_remove_invalid_links_after_linktable(content, valid_ids):
    """删除 <LINKTABLE> 之后 project_target_id 不在 valid_ids 的所有行（含 ALWAY-UPDATE 里的靶点行、
    以及 LINKTABLE 内部被引用的其他表行），返回(新内容, 删除数)"""
    lines = content.split('\n')
    idx = next((i for i, l in enumerate(lines) if '<LINKTABLE>' in l.strip()), -1)
    if idx == -1:
        return content, 0
    kept = []
    deleted = 0
    for i, line in enumerate(lines):
        if i > idx and 'project_target_id' in line:
            tid = xml_get_attr_loose(line, 'project_target_id')
            if tid and tid not in valid_ids:
                deleted += 1
                continue
        kept.append(line)
    return '\n'.join(kept), deleted


def xml_extract_well_common_names(content):
    """提取<CD_WELL行中 well_id -> well_common_name"""
    names = {}
    for line in content.split('\n'):
        if line.strip().startswith('<CD_WELL'):
            well_id = xml_get_attr_loose(line, 'well_id')
            name = xml_get_attr_loose(line, 'well_common_name')
            if well_id and name:
                names[well_id] = name
    return names


def xml_split_edm_name(filepath):
    """拆分文件名，把 .edm.xml 视为后缀：返回(去后缀的主名, 完整后缀)"""
    base, ext = os.path.splitext(filepath)
    if base.lower().endswith('.edm'):
        base = base[:-4]
        ext = '.edm' + ext
    return base, ext


def xml_kept_wells_info(content, well_ids, cutoff):
    """生成保留的实钻井信息文本（不写文件，供界面显示）"""
    names = xml_extract_well_common_names(content)
    dates = xml_extract_actual_survey_create_dates(content, cutoff)

    lines = ['序号\twell_common_name\tcreate_date']
    for i, well_id in enumerate(sorted(well_ids), 1):
        name = names.get(well_id, '(未找到CD_WELL)')
        date = dates.get(well_id)
        lines.append(f'{i}\t{name}\t{date.isoformat() if date else "(无)"}')
    lines.append(f'\n共记录实钻井 {len(well_ids)} 口（筛选日期 {cutoff}）')
    return '\n'.join(lines)


def xml_sanitize_filename(name):
    """替换Windows文件名非法字符（/ 替换为 &）。
    井名来自 XML 属性值，可能含 &#xFF0C; &quot; 等实体，先反转义再处理"""
    unescaped = html.unescape(name)
    cleaned = re.sub(r'[\\/:*?"<>|]', lambda m: '&' if m.group(0) == '/' else '_', unescaped).strip()
    return cleaned or 'unnamed'


# ---------- 实钻井开钻记录（按年累计，井名去重） ----------
def xml_extract_scope_names(content):
    """提取 油田名、site_id->平台名、well_id->site_id、well_id->井槽名(slot_name)、
    site_id->平台id(site_id本体)、site_id->槽口id(template_id，来自DP_TEMPLATE)"""
    project_name = ''
    site_names = {}
    well_sites = {}
    well_slots = {}
    site_sites = {}             # site_name -> site_id
    site_tmpl_by_sid = {}       # site_id -> template_id (临时，循环后归并)
    for line in content.split('\n'):
        s = line.strip()
        if not project_name and s.startswith('<CD_PROJECT'):
            project_name = xml_get_attr_loose(line, 'project_name') or ''
        elif s.startswith('<CD_SITE'):
            sid = xml_get_attr_loose(line, 'site_id')
            nm = xml_get_attr_loose(line, 'site_name')
            if sid and nm:
                site_names[sid] = nm
                site_sites[nm] = sid
        elif s.startswith('<CD_WELL'):
            wid = xml_get_attr_loose(line, 'well_id')
            sid = xml_get_attr_loose(line, 'site_id')
            slot = xml_get_attr_loose(line, 'slot_name') or ''
            slot = html.unescape(slot)
            if wid and sid:
                well_sites[wid] = sid
            if wid and slot:
                well_slots[wid] = slot
        elif s.startswith('<DP_TEMPLATE'):
            tmpl = xml_get_attr_loose(line, 'template_id')
            sid = xml_get_attr_loose(line, 'site_id')
            if tmpl and sid:
                site_tmpl_by_sid[sid] = tmpl
    # site_name -> template_id（site_id 可能在 DP_TEMPLATE 之后才出现，循环后归并）
    site_template_ids = {
        site_names[sid]: tmpl
        for sid, tmpl in site_tmpl_by_sid.items()
        if sid in site_names
    }
    site_ids = {nm: sid for sid, nm in site_names.items()}
    return project_name, site_names, well_sites, well_slots, site_ids, site_template_ids


SPUD_RECORD_HEADER = '序列号\t油田名\t平台名\t井名\t井id\twellborename\t开钻日期'


def xml_extract_actual_wellbores(content, cutoff):
    """well_id -> (最新ACTUAL测斜日期, 该测斜的wellbore_id)"""
    info = {}
    for line in content.split('\n'):
        s = line.strip()
        if s.startswith(('<CD_SURVEY_HEADER', '<CD_DEFINITIVE_SURVEY_HEADER')):
            if xml_get_attr_loose(line, 'phase') != 'ACTUAL':
                continue
            d = xml_parse_create_date(xml_get_attr_loose(line, 'create_date'))
            if d is None or d <= cutoff:
                continue
            wid = xml_get_attr_loose(line, 'well_id')
            if wid and (wid not in info or d > info[wid][0]):
                info[wid] = (d, xml_get_attr(line, 'wellbore_id') or '')
    return info


def xml_extract_wellbore_names(content):
    """wellbore_id -> wellbore_name（CD_WELLBORE）"""
    names = {}
    for line in content.split('\n'):
        if line.strip().startswith('<CD_WELLBORE'):
            wbid = xml_get_attr(line, 'wellbore_id')
            nm = xml_get_attr(line, 'wellbore_name')
            if wbid and nm:
                names[wbid] = nm
    return names


def xml_update_spud_record(content, well_ids, cutoff, record_dir=None):
    """把本次保留的实钻井写入按年划分的累计记录（实钻井记录_YYYY.json，在脚本目录）。
    JSON 叠加不覆盖：读取已有记录 → 本次新增 → 去重 → 序号续接 → 写回。
    返回 (更新的文件列表, 本次新增井数)。无有效日期的井不记录。"""
    if record_dir is None:
        record_dir = os.path.dirname(os.path.abspath(__file__))
    scope = xml_extract_scope_names(content)
    project_name, site_names, well_sites, well_slots, site_ids, site_template_ids = scope
    names = xml_extract_well_common_names(content)
    dates = xml_extract_actual_survey_create_dates(content, cutoff)
    wb_info = xml_extract_actual_wellbores(content, cutoff)
    wb_names = xml_extract_wellbore_names(content)

    # 新记录：井名+平台名 作唯一键（跨平台同名井分开）
    new_entries = []
    new_count = 0
    for well_id in sorted(well_ids):
        d = dates.get(well_id)
        if not d:
            continue
        wname = names.get(well_id) or well_id
        sid = well_sites.get(well_id, '')
        site_name = site_names.get(sid, '')
        slot_name = well_slots.get(well_id, '')
        wbid = wb_info.get(well_id, (None, ''))[1]
        wbname = wb_names.get(wbid, wbid)
        # 该平台的 site_id / template_id（同一平台所有井共用）
        plat_site_id = site_ids.get(site_name, '')
        plat_template_id = site_template_ids.get(site_name, '')
        new_entries.append({
            '油田名': project_name,
            '平台名': site_name,
            '平台id': plat_site_id,
            '槽口id': plat_template_id,
            '井名': wname,
            '井槽名': slot_name,
            '井id': well_id,
            'wellbore_id': wbid,
            'wellbore_name': wbname,
            '开钻日期': d.isoformat(),
        })
        new_count += 1

    # 按年分桶
    from collections import defaultdict
    by_year_new = defaultdict(list)
    for e in new_entries:
        try:
            y = datetime.date.fromisoformat(e['开钻日期']).year
        except ValueError:
            continue
        by_year_new[y].append(e)

    updated = []
    for year, new_rows in by_year_new.items():
        path = os.path.join(record_dir, f'实钻井记录_{year}.json')
        txt_path = os.path.join(record_dir, f'实钻井记录_{year}.txt')
        # 读取已有记录（优先 json，兼容旧 txt）
        existing = []
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                existing = data.get('records', [])
            except Exception:
                existing = []
        elif os.path.isfile(txt_path):
            # 迁移同名旧 txt
            existing = _migrate_txt_to_json(txt_path)

        # 去重键：(平台名, 井名)
        seen = {(r.get('平台名', ''), r.get('井名', '')) for r in existing}
        for r in new_rows:
            key = (r['平台名'], r['井名'])
            if key in seen:
                continue
            seen.add(key)
            existing.append(r)

        # 排序（先日期后井名） + 序号续接
        def _date_of(r):
            try:
                return datetime.date.fromisoformat(r.get('开钻日期', ''))
            except ValueError:
                return datetime.date.min
        existing.sort(key=lambda r: (_date_of(r), r.get('井名', '')))
        for i, r in enumerate(existing, 1):
            r['序号'] = i

        # 写回 json
        data_out = {'year': year, 'records': existing}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data_out, f, ensure_ascii=False, indent=2)

        # 迁移完 txt 删掉
        if os.path.isfile(txt_path):
            try:
                os.remove(txt_path)
            except OSError:
                pass
        updated.append(path)
    return updated, new_count


def _migrate_txt_to_json(txt_path):
    """旧 txt 格式迁移到 json（字段对齐 + 缺失字段补空）"""
    existing = []
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.rstrip('\n').split('\t')
                if len(parts) < 6 or parts[0] == '序列号':
                    continue
                _no, proj, site, wname, wid = parts[0], parts[1], parts[2], parts[3], parts[4]
                wbname, dstr = (parts[5], parts[6]) if len(parts) >= 7 else ('', parts[5])
                existing.append({
                    '油田名': proj,
                    '平台名': site,
                    '平台id': '',
                    '槽口id': '',
                    '井名': wname,
                    '井槽名': '',
                    '井id': wid,
                    'wellbore_id': '',
                    'wellbore_name': wbname,
                    '开钻日期': dstr,
                })
    except OSError:
        pass
    return existing





def xml_parameterize_single_well_execsql(lines, well_id):
    """把平台级 <execsql> 删除语句参数化为单井级：
    在所有 locator like pattern 的 site_id 之后插入 `+well_id=(well_id)`，
    让 CD_POLYLINE_HEADER / CD_CHANGE_HISTORY_JOURNAL / CD_EXPLORER_FOLDER 的
    删除范围精确到当前井，避免部署时误删同平台其他井的数据。"""
    out = []
    for line in lines:
        if '<execsql command="delete from CD_' not in line:
            out.append(line)
            continue
        # 在 `site_id=(xxx)` 之后、like pattern 结尾的 `%'` 或 `%"` 之前插入 `+well_id=(well_id)`
        # 若已有 well_id 片段则替换值，保留片段位置
        new_line = re.sub(
            r'(site_id=\([^)]+\))(\+well_id=\([^)]+\))?(%[\'"])',
            lambda m: f'{m.group(1)}+well_id=({well_id}){m.group(3)}',
            line,
        )
        out.append(new_line)
    return out


def _xml_set_attr(line, name, value):
    """在 XML 行里设置属性值。若属性已存在则替换值，不存在则在 > 前插入。"""
    if re.search(rf'{name}=(["\']).*?\1', line):
        line = re.sub(
            rf'({name}=)(["\']).*?\2',
            lambda m: f'{m.group(1)}"{value}"',
            line, count=1)
    else:
        if line.rstrip().endswith('/>'):
            line = line.rstrip()[:-2] + f' {name}="{value}" />'
        else:
            line = re.sub(r'(<\w+[^>]*?)(\s*/?>)', rf'\1 {name}="{value}"\2', line, count=1)
    return line


def xml_split_single_well_files(output_path, content, well_ids, fix_coords=True):
    """把多井XML按井拆分为单井文件，文件名 = 平台名-well_common_name.edm.xml
    tail 里的 <ALWAYS-UPDATE> 块含平台级 execsql 删除语句，此处对每个井参数化注入 well_id，
    避免部署时误删同平台其他井的 POLYLINE / CHANGE_HISTORY / EXPLORER_FOLDER。"""
    # 必须原样保留的平台/项目级标签（无 well_id，所有井共享）
    SHARED_PREFIXES = (
        '<DP_TEMPLATE', '<CD_PROJECT', '<CD_SITE', '<CD_POLICY',
        '<CD_DATUM', '<CD_COORDINATE_REFERENCE',
    )
    lines = content.split('\n')
    start = next((i for i, l in enumerate(lines) if l.strip().startswith('<DP_TEMPLATE')), None)
    end = next((i for i, l in enumerate(lines) if '<ALWAYS-UPDATE>' in l), None)
    if start is None or end is None or end <= start:
        return []
    head = lines[:start]
    region = lines[start:end]
    tail = lines[end:]
    names = xml_extract_well_common_names(content)
    _project_name, site_names, well_sites, *_ = xml_extract_scope_names(content)
    out_dir = os.path.dirname(output_path)
    out_paths = []
    for well_id in sorted(well_ids):
        site_id = well_sites.get(well_id, '')
        kept = []
        for l in region:
            s = l.strip()
            if 'execsql' in s and 'dp_template' in s.lower():
                # 合并内容里的模板 UPDATE 是平台级的，单井文件按本井井槽名重新生成
                continue
            if s.startswith(SHARED_PREFIXES):
                # DP_TEMPLATE / CD_SITE 等：只保留当前井所属平台的
                if not s.startswith('<DP_TEMPLATE') and not s.startswith('<CD_SITE'):
                    kept.append(l)
                else:
                    # DP_TEMPLATE / CD_SITE 都有 site_id，匹配当前井所在平台才保留
                    sid = xml_get_attr_loose(l, 'site_id')
                    if not site_id or sid == site_id:
                        kept.append(l)
                continue
            # 有 well_id 的行才按井过滤
            l_wid = xml_get_attr_loose(l, 'well_id')
            if l_wid is None or l_wid == well_id:
                kept.append(l)
        if not kept:
            continue
        well_name = names.get(well_id) or well_id
        site_name = site_names.get(site_id, '')
        name = xml_sanitize_filename(f'{site_name}-{well_name}' if site_name else well_name)
        out = os.path.join(out_dir, f'{name}.edm.xml')
        # 本井井槽名命中的 DP_TEMPLATE 行下方追加 update 语句
        well_kept = xml_add_dp_template_updates(kept, fix_coords)
        # tail 里的 execsql 参数化为当前井
        well_tail = xml_parameterize_single_well_execsql(tail, well_id)
        # 单井文件用 expandPoint=CD_WELL
        single, _ = xml_set_expand_point('\n'.join(head + well_kept + well_tail), 'CD_WELL')
        with open(out, 'w', encoding='utf-8') as f:
            f.write(single)
        out_paths.append(out)
    return out_paths


def xml_extract_recent_actual(filepath, cutoff, split=False, fix_coords=True):
    """提取实钻数据（现场实钻）：保留 ACTUAL 且 create_date 晚于 cutoff 的井，另存为新文件。
    返回(删井行, expandPoint替换, 删整行, 删无效靶点, 删LINKTABLE后无效行,
          保留井数, 输出路径, 单井文件列表, 井信息文本, 记录文件列表, 本次记录井数)"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    # 处理前先改ID（全局ID + survey_tool_id属性值）
    content = xml_replace_ids(content)
    content = xml_replace_survey_tool_ids(content)

    well_ids = set(xml_extract_actual_survey_create_dates(content, cutoff))
    content, deleted, _removed = xml_remove_lines_not_in_well_ids(content, well_ids)
    content, cleaned = xml_remove_unwanted_lines(content)
    content, replaced = xml_set_expand_point(content, 'CD_SCENARIO')

    # 靶点处理：只保留被 CD_SURVEY_STATION 实际引用过的 target_id
    valid_targets = xml_extract_project_target_ids(content)
    content, targets_deleted = xml_remove_invalid_dp_project_target(content, valid_targets)
    content, link_deleted = xml_remove_invalid_links_after_linktable(content, valid_targets)

    # DP_TEMPLATE：被 CD_WELL.slot_name 匹配到的模板行下方追加 update 语句（同 7.1 合并口径）
    content = '\n'.join(xml_add_dp_template_updates(content.split('\n'), fix_coords))
    # 统一收尾：清除 <LINKTABLE> 之后的全部内容，补回标准结尾
    content = '\n'.join(xml_align_default_ending(content.split('\n')))

    base, ext = xml_split_edm_name(filepath)
    output_path = f'{base}_提取近期开钻井{ext or ".xml"}'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    wells_info = xml_kept_wells_info(content, well_ids, cutoff) if well_ids else ''
    single_files = xml_split_single_well_files(output_path, content, well_ids, fix_coords) if split else []
    record_files, record_count = xml_update_spud_record(content, well_ids, cutoff) if well_ids else ([], 0)
    return (deleted, replaced, cleaned, targets_deleted, link_deleted,
            len(well_ids), output_path, single_files,
            wells_info, record_files, record_count)


# ---------- 7.3 删除非实钻井（外挂设计） ----------
def xml_remove_non_actual_wells(filepath):
    """删除 CD_DEFINITIVE_SURVEY_HEADER 中 phase != ACTUAL 的井对应的所有行（直接改原文件）。
    返回(删除行数, 涉及井数, 日志路径或None)"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    well_ids = set()
    for line in content.split('\n'):
        if line.strip().startswith('<CD_DEFINITIVE_SURVEY_HEADER'):
            if xml_get_attr_loose(line, 'phase') != 'ACTUAL':
                well_id = xml_get_attr_loose(line, 'well_id')
                if well_id:
                    well_ids.add(well_id)

    lines = content.split('\n')
    kept, removed = [], []
    for line in lines:
        well_id = xml_get_attr_loose(line, 'well_id')
        if well_id is not None and well_id in well_ids:
            removed.append(line)
        else:
            kept.append(line)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(kept))

    log_path = None
    if removed:
        log_path = os.path.splitext(filepath)[0] + '_删除行.txt'
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(f'源文件: {os.path.basename(filepath)}\n')
            f.write('删除条件: <CD_DEFINITIVE_SURVEY_HEADER> 中 phase != "ACTUAL" 的 well_id\n')
            f.write(f'涉及的well_id: {", ".join(sorted(well_ids)) if well_ids else "(无)"}\n')
            f.write(f'删除行数: {len(removed)}\n')
            f.write('=' * 60 + '\n')
            for i, line in enumerate(removed, 1):
                f.write(f'[{i}] {line.strip()}\n')
    return len(removed), len(well_ids), log_path


# ---------- 7.4 删除数据库非实钻设计井（SQL 版，源: 删COMPASS数据库非实钻设计井.sql） ----------
try:
    import pyodbc
    HAS_ODBC = True
except ImportError:
    HAS_ODBC = False

# SQL 模板文件（与本脚本同目录）
DB_CLEANUP_SQL_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '删COMPASS数据库非实钻设计井.sql')


def db_get_driver():
    """获取可用的 SQL Server ODBC 驱动（源: EDM轨迹导出工具）"""
    if not HAS_ODBC:
        return None
    preferred = [
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server",
        "SQL Server Native Client 10.0",
        "SQL Native Client",
    ]
    installed = set(pyodbc.drivers())
    for driver in preferred:
        if driver in installed:
            return driver
    return None


def db_make_conn_str(server, database, user, pwd):
    """按 EDM 轨迹导出工具的方式拼连接串"""
    driver = db_get_driver() or "SQL Server"
    return (f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};"
            f"UID={user};PWD={pwd}")


def _sql_quote(value):
    """把 Python 字符串转义为 T-SQL 字面量（防引号注入）"""
    return "N'" + str(value).replace("'", "''") + "'"


def db_list_databases(conn_str):
    """枚举服务器上的用户数据库（排除系统库），按名称排序"""
    with pyodbc.connect(conn_str, timeout=15) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sys.databases "
                    "WHERE database_id > 4 AND state = 0 ORDER BY name")
        return [r.name for r in cur.fetchall()]


def db_list_projects(conn_str):
    """油田列表（CD_PROJECT_SOURCE）：返回 [(project_id, project_name), ...]"""
    with pyodbc.connect(conn_str, timeout=15) as conn:
        cur = conn.cursor()
        cur.execute("SELECT project_id, project_name "
                    "FROM dbo.CD_PROJECT_SOURCE ORDER BY project_name")
        return [(r.project_id.strip(), (r.project_name or '').strip()) for r in cur.fetchall()]


def db_list_sites(conn_str, project_id):
    """平台列表（CD_SITE_SOURCE，按油田过滤）：返回 [(site_id, site_name), ...]"""
    with pyodbc.connect(conn_str, timeout=15) as conn:
        cur = conn.cursor()
        cur.execute("SELECT site_id, site_name FROM dbo.CD_SITE_SOURCE "
                    "WHERE project_id = ? ORDER BY site_name", project_id)
        return [(r.site_id.strip(), (r.site_name or '').strip()) for r in cur.fetchall()]


def db_build_cleanup_sql(database, project_id, site_id, execute):
    """以 删COMPASS数据库非实钻设计井.sql 为模板生成可执行 SQL：
    用参数声明块替换模板第 1-2 节，并把项目过滤条件替换为 油田/平台 作用域。
    site_id 非空时按平台级处理，否则按油田级处理。"""
    with open(DB_CLEANUP_SQL_FILE, 'r', encoding='utf-8-sig') as f:
        text = f.read()

    marker = "IF OBJECT_ID('tempdb..#del_headers')"
    idx = text.index(marker)
    body = text[idx:]
    # pyodbc 不支持 GO 批分隔符：整段在一个批里执行，去掉所有 GO 行
    body = '\n'.join(line for line in body.splitlines() if line.strip() != 'GO')
    # 临时表约束名在 tempdb 全局唯一，其他会话残留同名约束会冲突：改为匿名主键
    for cname, cols in (('PK_del_headers', '(well_id, wellbore_id, def_survey_header_id)'),
                        ('PK_del_wellbores', '(wellbore_id)'),
                        ('PK_del_wells', '(well_id)')):
        body = body.replace(f'CONSTRAINT {cname} PRIMARY KEY {cols}', f'PRIMARY KEY {cols}')

    # 作用域：替换模板中的 (@all_projects = 1 OR s/t.project_id = @pid)
    if site_id:
        scope_s = f"s.site_id COLLATE DATABASE_DEFAULT = {_sql_quote(site_id)}"
        # DP_PROJECT_TARGET 无 site_id；5.5 已通过 drill_well_id/drill_wellbore_id
        # 限定在被删对象上，这里不再加项目级限制
        scope_t = "1 = 1"
    else:
        scope_s = f"s.project_id COLLATE DATABASE_DEFAULT = {_sql_quote(project_id)}"
        scope_t = f"t.project_id COLLATE DATABASE_DEFAULT = {_sql_quote(project_id)}"
    body = body.replace(
        "(@all_projects = 1 OR s.project_id COLLATE DATABASE_DEFAULT = @pid)",
        f"({scope_s})")
    body = body.replace(
        "(@all_projects = 1 OR t.project_id COLLATE DATABASE_DEFAULT = @pid)",
        f"({scope_t})")

    header = (
        f"USE [{database}];\n"
        "SET NOCOUNT ON;\nSET XACT_ABORT ON;\n"
        f"DECLARE @pid char(10) = {_sql_quote(project_id)};\n"
        f"DECLARE @Execute bit = {1 if execute else 0};\n"
        "DECLARE @DeleteNoSurveyObjects bit = 0;\n"  # 无测斜头的井眼/井不删
        "DECLARE @DeleteTargets bit = 1;\n"
        "DECLARE @DeleteHistory bit = 1;\n"
        "DECLARE @NullDanglingRefs bit = 1;\n"
    )
    return header + body


def db_run_cleanup(conn_str, database, project_id, site_id, execute):
    """执行清理 SQL（预览或删除）。
    返回 (汇总dict, 明细行列表[(level, well_name, well_id, wb_name, wb_id, header_id, phase)], 消息列表)"""
    sql = db_build_cleanup_sql(database, project_id, site_id, execute)
    conn = pyodbc.connect(conn_str, timeout=15, autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        summary = {}
        details = []
        while True:
            if cur.description:
                cols = [c[0] for c in cur.description]
                rows = cur.fetchall()
                if 'headers_to_delete' in cols and rows:
                    r = rows[0]
                    summary = dict(zip(cols, r))
                elif 'delete_level' in cols:
                    for r in rows:
                        d = dict(zip(cols, r))
                        details.append((
                            d.get('delete_level', ''),
                            d.get('well_common_name') or '',
                            (d.get('well_id') or '').strip(),
                            d.get('wellbore_name') or '',
                            (d.get('wellbore_id') or '').strip(),
                            (d.get('def_survey_header_id') or '').strip(),
                            d.get('phase') or '',
                        ))
            if not cur.nextset():
                break
        messages = [m[1] for m in (cur.messages or [])]
        return summary, details, messages
    finally:
        conn.close()


# ================================================================
# TAB 7 界面
# ================================================================
class XmlProcessTab(ttk.Frame):
    """XML 处理：设计提取(合并全设计) / 提取实钻数据(现场实钻) / 删除非实钻井(外挂设计)"""

    def __init__(self, master, controller=None):
        super().__init__(master)
        self.var_mode = tk.StringVar(value='extract')
        self.var_merge_folder = tk.StringVar()
        self.var_merge_prefix = tk.StringVar(value='全设计')
        self.var_extract_file = tk.StringVar()
        self.var_extract_date = tk.StringVar(
            value=(datetime.date.today() - datetime.timedelta(days=60)).isoformat())
        self.var_split = tk.BooleanVar(value=False)
        self.var_fix_coords = tk.BooleanVar(value=False)
        self.var_remove_file = tk.StringVar()
        self.var_status = tk.StringVar(value='请选择上方功能并完成参数设置')
        self._build_ui()
        self._switch_mode()

    # ---------- 布局 ----------
    def _build_ui(self):
        outer = ttk.Frame(self, padding=(12, 10, 12, 10))
        outer.pack(fill="both", expand=True)

        # 功能选择
        top = ttk.LabelFrame(outer, text=" ① 选择功能 ", padding=(10, 8))
        top.pack(fill="x")
        for value, text in (
            ('merge', '设计提取（合并文件夹内 .edm.xml 为全设计）'),
            ('extract', '提取实钻数据（按日期保留近期 ACTUAL 实钻井）'),
            ('remove', '删除非实钻井（外挂设计，直接改原文件）'),
            ('db', '删除数据库非实钻设计井（连接 EDM 数据库，按油田/平台处理）'),
        ):
            ttk.Radiobutton(top, text=text, value=value, variable=self.var_mode,
                            command=self._switch_mode).pack(anchor="w", pady=2)

        # 参数区（三个子框，按模式切换显示）
        self.frm_merge = ttk.LabelFrame(outer, text=" ② 设计提取参数 ", padding=(10, 8))
        line = ttk.Frame(self.frm_merge); line.pack(fill="x")
        ttk.Label(line, text="文件夹：").pack(side="left")
        ttk.Entry(line, textvariable=self.var_merge_folder, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(line, text="选择文件夹…", command=self._pick_merge_folder).pack(side="left")
        line2 = ttk.Frame(self.frm_merge); line2.pack(fill="x", pady=(6, 0))
        ttk.Label(line2, text="输出前缀：").pack(side="left")
        ttk.Entry(line2, textvariable=self.var_merge_prefix, width=14).pack(side="left")
        ttk.Label(line2, text="（输出文件名 = 前缀 + 日期.edm.xml，如 全设计20261101.edm.xml）",
                  foreground="#666666").pack(side="left", padx=(6, 0))
        ttk.Button(self.frm_merge, text="开始合并", command=self._run_merge).pack(anchor="e", pady=(8, 0))

        self.frm_extract = ttk.LabelFrame(outer, text=" ② 提取实钻数据参数 ", padding=(10, 8))
        line = ttk.Frame(self.frm_extract); line.pack(fill="x")
        ttk.Label(line, text="XML 文件：").pack(side="left")
        ttk.Entry(line, textvariable=self.var_extract_file, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(line, text="选择文件…", command=self._pick_extract_file).pack(side="left")
        line2 = ttk.Frame(self.frm_extract); line2.pack(fill="x", pady=(6, 0))
        ttk.Label(line2, text="日期：").pack(side="left")
        ttk.Entry(line2, textvariable=self.var_extract_date, width=14).pack(side="left")
        ttk.Label(line2, text="（YYYY-MM-DD，create_date 晚于此日期的 ACTUAL 井才保留）",
                  foreground="#666666").pack(side="left", padx=(6, 0))
        line3 = ttk.Frame(self.frm_extract); line3.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(line3, text="生成单井 EDM 文件（按 well_id 拆分）",
                        variable=self.var_split).pack(side="left")
        ttk.Checkbutton(line3, text="校正槽口坐标（默认只校正槽口名）",
                        variable=self.var_fix_coords).pack(side="left", padx=(24, 0))
        ttk.Button(self.frm_extract, text="开始提取", command=self._run_extract).pack(anchor="e", pady=(4, 0))

        self.frm_remove = ttk.LabelFrame(outer, text=" ② 删除非实钻井参数 ", padding=(10, 8))
        line = ttk.Frame(self.frm_remove); line.pack(fill="x")
        ttk.Label(line, text="XML 文件：").pack(side="left")
        ttk.Entry(line, textvariable=self.var_remove_file, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(line, text="选择文件…", command=self._pick_remove_file).pack(side="left")
        ttk.Label(self.frm_remove,
                  text="删除 CD_DEFINITIVE_SURVEY_HEADER 中 phase≠ACTUAL 的井对应所有行；直接修改原文件，并生成「_删除行.txt」日志",
                  foreground="#C0392B", wraplength=1000).pack(anchor="w", pady=(6, 0))
        ttk.Button(self.frm_remove, text="开始删除", command=self._run_remove).pack(anchor="e", pady=(4, 0))

        # ---------- 数据库删除非实钻设计井 ----------
        self._db_conn_str = None
        self._db_projects = []   # [(project_id, project_name)]
        self._db_sites = []      # [(site_id, site_name)]，索引0为“全部平台”
        # 后台线程结果队列：worker 只入队，主线程轮询执行（tkinter 跨线程 after 不可靠）
        self._db_queue = queue.Queue()
        self.after(150, self._db_poll)
        self.var_db_server = tk.StringVar(value='.\\EDM5000')
        self.var_db_name = tk.StringVar(value='EDM')
        self.var_db_user = tk.StringVar(value='sa')
        self.var_db_pwd = tk.StringVar(value='w')
        self.var_db_conn = tk.StringVar(value='未连接')
        self.var_db_project = tk.StringVar()
        self.var_db_site = tk.StringVar()
        self.var_db_summary = tk.StringVar(value='')
        self._db_load_creds()

        self.frm_db = ttk.LabelFrame(outer, text=" ② 删除数据库非实钻设计井 ", padding=(10, 8))
        # 连接行（源: EDM轨迹导出工具 的连接界面）
        line = ttk.Frame(self.frm_db); line.pack(fill="x")
        ttk.Label(line, text="服务器：").pack(side="left")
        ttk.Combobox(line, textvariable=self.var_db_server, width=16,
                     values=['.\\EDM5000', '.\\FORESITEEDM', '(local)', '.\\SQLEXPRESS', 'localhost']
                     ).pack(side="left")
        ttk.Label(line, text="数据库：").pack(side="left", padx=(8, 0))
        self.cbo_db_name = ttk.Combobox(line, textvariable=self.var_db_name,
                                        width=10, values=['EDM'])
        self.cbo_db_name.pack(side="left")
        # 已连接状态下切换数据库：自动用新库重连并重新加载油田
        self.cbo_db_name.bind('<<ComboboxSelected>>',
                              lambda _e: self._db_connect() if self._db_conn_str else None)
        # 打开标签页不做任何数据库查询，需用户点「连接数据库」后才访问 SQL
        ttk.Label(line, text="用户：").pack(side="left", padx=(8, 0))
        ttk.Entry(line, textvariable=self.var_db_user, width=6).pack(side="left")
        ttk.Label(line, text="密码：").pack(side="left", padx=(8, 0))
        ttk.Entry(line, textvariable=self.var_db_pwd, width=10, show='*').pack(side="left")
        ttk.Button(line, text="连接数据库", command=self._db_connect).pack(side="left", padx=(10, 0))
        ttk.Label(line, textvariable=self.var_db_conn, foreground="#666666").pack(side="left", padx=(8, 0))
        # 范围行：油田/平台
        line2 = ttk.Frame(self.frm_db); line2.pack(fill="x", pady=(8, 0))
        ttk.Label(line2, text="油田：").pack(side="left")
        self.cbo_db_project = ttk.Combobox(line2, textvariable=self.var_db_project,
                                           state="readonly", width=34)
        self.cbo_db_project.pack(side="left")
        self.cbo_db_project.bind('<<ComboboxSelected>>', self._db_on_project_selected)
        ttk.Label(line2, text="平台：").pack(side="left", padx=(10, 0))
        self.cbo_db_site = ttk.Combobox(line2, textvariable=self.var_db_site,
                                        state="readonly", width=26)
        self.cbo_db_site.pack(side="left")
        self.btn_db_preview = ttk.Button(line2, text="预览", command=self._db_preview, state="disabled")
        self.btn_db_preview.pack(side="left", padx=(12, 0))
        self.btn_db_delete = ttk.Button(line2, text="执行删除", command=self._db_delete, state="disabled")
        self.btn_db_delete.pack(side="left", padx=(6, 0))
        ttk.Label(self.frm_db,
                  text="平台选「全部平台」时按油田级处理；选中具体平台时按平台级处理。先预览核对清单，再执行删除（单事务，失败回滚）。",
                  foreground="#C0392B", wraplength=1000).pack(anchor="w", pady=(6, 0))

        # 数据库结果表格（db 模式下替换文本日志区）
        self.frm_db_result = ttk.LabelFrame(outer, text=" ③ 处理结果 ", padding=(10, 8))
        ttk.Label(self.frm_db_result, textvariable=self.var_db_summary,
                  foreground="#1B4F8A", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        cols = ('level', 'well_name', 'well_id', 'wb_name', 'wb_id', 'header_id', 'phase')
        self.db_tree = ttk.Treeview(self.frm_db_result, columns=cols, show='headings', height=11)
        for cid, text, w in (('level', '层级', 80), ('well_name', '井名', 180), ('well_id', 'well_id', 90),
                             ('wb_name', '井眼名', 200), ('wb_id', 'wellbore_id', 90),
                             ('header_id', '测斜头ID', 70), ('phase', 'phase', 90)):
            self.db_tree.heading(cid, text=text)
            self.db_tree.column(cid, width=w, anchor='w')
        dsb = ttk.Scrollbar(self.frm_db_result, orient="vertical", command=self.db_tree.yview)
        self.db_tree.configure(yscrollcommand=dsb.set)
        self.db_tree.pack(side="left", fill="both", expand=True, pady=(6, 0))
        dsb.pack(side="right", fill="y", pady=(6, 0))
        self.db_tree.tag_configure('HEADER', background='#FFF3CD')
        self.db_tree.tag_configure('WELLBORE', background='#F8D7DA')
        self.db_tree.tag_configure('WELL', background='#F5C6CB')

        # 状态/结果
        self.frm_log_result = ttk.LabelFrame(outer, text=" ③ 处理结果 ", padding=(10, 8))
        self.frm_log_result.pack(fill="both", expand=True, pady=(10, 0))
        self.txt_log = tk.Text(self.frm_log_result, height=12, wrap="word", font=("Consolas", 9),
                               relief="solid", borderwidth=1, state="disabled")
        sb = ttk.Scrollbar(self.frm_log_result, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=sb.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        ttk.Label(outer, textvariable=self.var_status, foreground="#666666").pack(anchor="w", pady=(6, 0))

    # ---------- 模式切换 ----------
    def _switch_mode(self):
        mode = self.var_mode.get()
        for frm in (self.frm_merge, self.frm_extract, self.frm_remove, self.frm_db):
            frm.pack_forget()
        {'merge': self.frm_merge, 'extract': self.frm_extract,
         'remove': self.frm_remove, 'db': self.frm_db}[mode].pack(fill="x", pady=(10, 0))
        # 结果区：db 模式显示表格，其余显示文本日志
        self.frm_log_result.pack_forget()
        self.frm_db_result.pack_forget()
        if mode == 'db':
            self.frm_db_result.pack(fill="both", expand=True, pady=(10, 0))
        else:
            self.frm_log_result.pack(fill="both", expand=True, pady=(10, 0))

    # ---------- 文件选择 ----------
    def _pick_merge_folder(self):
        path = filedialog.askdirectory(title='请选择存放 .edm.xml 的文件夹', parent=self)
        if path:
            self.var_merge_folder.set(path)

    def _pick_extract_file(self):
        path = filedialog.askopenfilename(
            title='请选择XML文件', filetypes=[('XML文件', '*.xml'), ('所有文件', '*.*')], parent=self)
        if path:
            self.var_extract_file.set(path)

    def _pick_remove_file(self):
        path = filedialog.askopenfilename(
            title='请选择XML文件', filetypes=[('XML文件', '*.xml'), ('所有文件', '*.*')], parent=self)
        if path:
            self.var_remove_file.set(path)

    # ---------- 数据库：连接 / 范围 / 执行 ----------
    def _db_poll(self):
        """主线程轮询后台任务结果并执行回调（worker 只负责入队）"""
        try:
            while True:
                fn = self._db_queue.get_nowait()
                try:
                    fn()
                except Exception as e:
                    print('db callback error:', e)
        except queue.Empty:
            pass
        self.after(150, self._db_poll)

    def _db_submit(self, work, on_done, on_error):
        """work() 在线程中执行；完成后把 on_done(result) 入队交给主线程"""
        def run():
            try:
                result = work()
            except Exception as e:
                self._db_queue.put(lambda: on_error(e))
            else:
                self._db_queue.put(lambda: on_done(result))
        threading.Thread(target=run, daemon=True).start()

    def _db_current_scope(self):
        """返回 (project_id, site_id or None)；未选返回 (None, None)"""
        idx = self.cbo_db_project.current()
        if idx < 0 or idx >= len(self._db_projects):
            return None, None
        project_id = self._db_projects[idx][0]
        sidx = self.cbo_db_site.current()
        site_id = self._db_sites[sidx][0] if 0 < sidx < len(self._db_sites) else None
        return project_id, site_id

    def _db_connect(self):
        if not HAS_ODBC:
            messagebox.showerror("缺少依赖", "请先安装 pyodbc：\npip install pyodbc", parent=self)
            return
        conn_str = db_make_conn_str(
            self.var_db_server.get().strip(), self.var_db_name.get().strip(),
            self.var_db_user.get().strip(), self.var_db_pwd.get())
        self.var_db_conn.set('连接中…')
        self.var_status.set('正在连接数据库…')
        self.update_idletasks()

        def work():
            # 先枚举服务器上的数据库，再读当前库的油田列表
            databases = db_list_databases(conn_str)
            projects = db_list_projects(conn_str)
            return databases, projects

        self._db_submit(
            work=work,
            on_done=lambda r: self._db_on_connected(conn_str, r[0], r[1]),
            on_error=self._db_on_connect_error,
        )

    def _db_on_connected(self, conn_str, databases, projects):
        self._db_conn_str = conn_str
        self._db_projects = projects
        current_db = self.var_db_name.get().strip()
        self.cbo_db_name['values'] = databases or [current_db]
        if current_db and current_db not in (databases or []):
            self.cbo_db_name['values'] = list(databases) + [current_db]
        self.cbo_db_project['values'] = [f'{name} ({pid})' for pid, name in projects]
        self.cbo_db_site['values'] = []
        self.var_db_project.set('')
        self.var_db_site.set('')
        self.btn_db_preview.configure(state="disabled")
        self.btn_db_delete.configure(state="disabled")
        self.var_db_conn.set(f'已连接（{len(projects)} 个油田）')
        self.var_status.set('连接成功，请选择油田')
        self._db_save_creds()

    def _db_on_connect_error(self, e):
        self._db_conn_str = None
        self.var_db_conn.set('连接失败')
        self.var_status.set('数据库连接失败')
        messagebox.showerror("连接失败", f"数据库连接失败：\n{e}", parent=self)

    def _db_creds_path(self):
        """DB 参数持久化文件路径：~/.toolbox/db_creds.json"""
        try:
            home = os.path.expanduser('~')
        except Exception:
            home = os.path.dirname(os.path.abspath(__file__))
        d = os.path.join(home, '.toolbox')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, 'db_creds.json')

    def _db_save_creds(self):
        """把当前 DB 连接参数保存到本地（连接成功时调用）"""
        try:
            data = {
                'server': self.var_db_server.get(),
                'database': self.var_db_name.get(),
                'user': self.var_db_user.get(),
                'pwd': self.var_db_pwd.get(),
            }
            with open(self._db_creds_path(), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _db_load_creds(self):
        """启动时从本地恢复 DB 连接参数"""
        try:
            path = self._db_creds_path()
            if not os.path.isfile(path):
                return
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get('server'):
                self.var_db_server.set(data['server'])
            if data.get('database'):
                self.var_db_name.set(data['database'])
            if data.get('user'):
                self.var_db_user.set(data['user'])
            if data.get('pwd'):
                self.var_db_pwd.set(data['pwd'])
        except Exception:
            pass

    def _db_on_project_selected(self, _event=None):
        project_id, _ = self._db_current_scope()
        if not project_id or not self._db_conn_str:
            return
        self.var_db_site.set('加载中…')
        self.btn_db_preview.configure(state="disabled")
        self.btn_db_delete.configure(state="disabled")
        conn_str = self._db_conn_str

        self._db_submit(
            work=lambda: db_list_sites(conn_str, project_id),
            on_done=self._db_on_sites_loaded,
            on_error=lambda e: messagebox.showerror("错误", f"加载平台失败：\n{e}", parent=self),
        )

    def _db_on_sites_loaded(self, sites):
        self._db_sites = [(None, '（全部平台）')] + sites
        self.cbo_db_site['values'] = [name for _sid, name in self._db_sites]
        self.cbo_db_site.current(0)
        self.btn_db_preview.configure(state="normal")
        self.btn_db_delete.configure(state="disabled")
        self.var_status.set(f'已加载 {len(sites)} 个平台，可预览')

    def _db_selected_scope_or_warn(self):
        project_id, site_id = self._db_current_scope()
        if not self._db_conn_str:
            messagebox.showwarning("未连接", "请先连接数据库", parent=self)
            return None, None
        if not project_id:
            messagebox.showwarning("未选油田", "请先选择油田", parent=self)
            return None, None
        return project_id, site_id

    def _db_fill_result(self, summary, details, messages, executed):
        for item in self.db_tree.get_children():
            self.db_tree.delete(item)
        for row in details:
            self.db_tree.insert('', 'end', values=row, tags=(row[0],))
        h = summary.get('headers_to_delete', 0) or 0
        b = summary.get('wellbores_to_delete', 0) or 0
        w = summary.get('wells_to_delete', 0) or 0
        pname = summary.get('project_name') or ''
        mode_txt = '已删除' if executed else '待删除（预览）'
        self.var_db_summary.set(
            f'{mode_txt}：{pname} — 测斜头 {h} 个，井眼 {b} 个，井 {w} 口；明细 {len(details)} 行')
        if messages:
            self.var_status.set(messages[-1][:120])

    def _db_run(self, execute, on_done):
        scope = self._db_selected_scope_or_warn()
        if not scope[0]:
            return
        project_id, site_id = scope
        conn_str = self._db_conn_str
        database = self.var_db_name.get().strip()
        self.btn_db_preview.configure(state="disabled")
        self.btn_db_delete.configure(state="disabled")
        self.var_status.set('正在执行 SQL，请稍候…')

        def fail(e):
            self.btn_db_preview.configure(state="normal")
            self.btn_db_delete.configure(state="normal")
            self.var_status.set('执行失败（已回滚）')
            messagebox.showerror("执行失败", f"SQL 执行失败：\n{e}", parent=self)

        self._db_submit(
            work=lambda: db_run_cleanup(conn_str, database, project_id, site_id, execute),
            on_done=on_done,
            on_error=fail,
        )

    def _db_preview(self):
        def done(result):
            summary, details, messages = result
            self._db_fill_result(summary, details, messages, executed=False)
            self.btn_db_preview.configure(state="normal")
            total = len(details)
            self.btn_db_delete.configure(state="normal" if total else "disabled")
            self.var_status.set(f'预览完成：{total} 行待删除')
        self._db_run(execute=False, on_done=done)

    def _db_export_excel(self, summary, details):
        """把删除明细导出为 Excel（用户选路径；取消返回 None）"""
        from openpyxl import Workbook
        project_label = summary.get('project_name') or ''
        default_name = (f"删除非实钻设计井明细_{project_label}_"
                        f"{datetime.datetime.now():%Y%m%d_%H%M%S}.xlsx")
        path = filedialog.asksaveasfilename(
            title='保存删除明细 Excel', defaultextension='.xlsx',
            initialfile=default_name, filetypes=[('Excel文件', '*.xlsx')], parent=self)
        if not path:
            return None
        wb = Workbook()
        ws = wb.active
        ws.title = '删除明细'
        ws.append(['层级', '井名', 'well_id', '井眼名', 'wellbore_id', '测斜头ID', 'phase'])
        for row in details:
            ws.append(list(row))
        ws2 = wb.create_sheet('概要')
        ws2.append(['项目', '值'])
        ws2.append(['执行时间', f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}"])
        ws2.append(['数据库', self.var_db_name.get().strip()])
        ws2.append(['油田', self.var_db_project.get()])
        ws2.append(['平台', self.var_db_site.get() or '（全部平台）'])
        ws2.append(['删除测斜头', summary.get('headers_to_delete', 0) or 0])
        ws2.append(['删除井眼', summary.get('wellbores_to_delete', 0) or 0])
        ws2.append(['删除井', summary.get('wells_to_delete', 0) or 0])
        for col, width in zip('ABCDEFG', (10, 24, 12, 26, 12, 10, 12)):
            ws.column_dimensions[col].width = width
        ws2.column_dimensions['A'].width = 12
        ws2.column_dimensions['B'].width = 40
        wb.save(path)
        return path

    def _db_delete(self):
        total = len(self.db_tree.get_children())
        if not total:
            messagebox.showwarning("无数据", "请先预览，且预览结果为空时不执行删除", parent=self)
            return
        if not messagebox.askyesno(
                "确认删除",
                f"即将真正删除预览中的 {total} 行数据（非实钻测斜头/井眼/井）！\n\n"
                "执行前请确认已备份 EDM 数据库。\n\n是否继续？",
                icon='warning', parent=self):
            return

        def done(result):
            summary, details, messages = result
            self._db_fill_result(summary, details, messages, executed=True)
            self.btn_db_preview.configure(state="normal")
            self.btn_db_delete.configure(state="normal")
            h = summary.get('headers_to_delete', 0) or 0
            b = summary.get('wellbores_to_delete', 0) or 0
            w = summary.get('wells_to_delete', 0) or 0
            try:
                excel_path = self._db_export_excel(summary, details)
            except Exception as e:
                excel_path = None
                messagebox.showerror("导出失败", f"删除已完成，但导出 Excel 失败：\n{e}", parent=self)
            msg = f"删除完成（单事务提交）！\n\n测斜头：{h} 个\n井眼：{b} 个\n井：{w} 口"
            msg += (f"\n\n明细已导出：\n{excel_path}" if excel_path
                    else "\n\n明细未导出（已取消保存）")
            messagebox.showinfo("完成", msg, parent=self)
        self._db_run(execute=True, on_done=done)

    # ---------- 日志 ----------
    def _log(self, text):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", text + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _clear_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    # ---------- 执行 ----------
    def _run_merge(self):
        folder = self.var_merge_folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("参数错误", "请先选择有效的文件夹", parent=self)
            return
        prefix = self.var_merge_prefix.get().strip() or '全设计'
        self._clear_log()
        self._log(f"合并文件夹：{folder}\n输出前缀：{prefix}\n")
        self.var_status.set("正在合并，请稍候…")
        self.update_idletasks()
        try:
            out_path, file_count, kept_count, target_count = xml_merge_folder(folder, out_prefix=prefix)
        except Exception as e:
            self.var_status.set("合并失败")
            self._log(f"错误：{e}")
            messagebox.showerror("错误", f"合并失败：\n{e}", parent=self)
            return
        self._log(f"已生成：{out_path}")
        self._log(f"源文件：{file_count} 个；保留行：{kept_count} 行；靶点：{target_count} 个")
        self.var_status.set(f"合并完成：{os.path.basename(out_path)}")
        messagebox.showinfo(
            "完成", f"合并完成！\n\n源文件：{file_count} 个\n保留行：{kept_count} 行\n"
            f"靶点：{target_count} 个\n\n输出：{os.path.basename(out_path)}", parent=self)

    def _run_extract(self):
        path = self.var_extract_file.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("参数错误", "请先选择有效的 XML 文件", parent=self)
            return
        try:
            cutoff = datetime.date.fromisoformat(self.var_extract_date.get().strip())
        except ValueError:
            messagebox.showwarning("参数错误", "日期格式应为 YYYY-MM-DD", parent=self)
            return
        split = self.var_split.get()
        fix_coords = self.var_fix_coords.get()
        self._clear_log()
        self._log(f"源文件：{path}\n筛选日期：{cutoff}（保留晚于该日的 ACTUAL 井）\n"
                  f"拆分单井：{split}\n校正槽口坐标：{fix_coords}\n")
        self.var_status.set("正在提取，请稍候…")
        self.update_idletasks()
        try:
            (deleted, replaced, cleaned, targets_deleted, link_deleted,
             kept_wells, output_path, single_files,
             wells_info, record_files, record_count) = xml_extract_recent_actual(
                path, cutoff, split, fix_coords)
        except Exception as e:
            self.var_status.set("提取失败")
            self._log(f"错误：{e}")
            messagebox.showerror("错误", f"提取失败：\n{e}", parent=self)
            return
        self._log(f"新文件：{output_path}")
        self._log(f"删除行：{deleted}；历史/链接清理：{cleaned} 行；expandPoint 替换：{replaced} 处；"
                  f"删无效靶点：{targets_deleted} 行；删 LINKTABLE 后无效行：{link_deleted} 行；"
                  f"保留井：{kept_wells} 口")
        if single_files:
            self._log(f"单井文件：{len(single_files)} 个（同目录，按井名命名）")
        if wells_info:
            self._log("\n保留井信息：\n" + wells_info)
        if record_files:
            names = '、'.join(os.path.basename(p) for p in record_files)
            self._log(f"\n开钻记录已更新：{record_count} 口井写入 {names}（脚本目录，按年累计、井名去重）")

        self.var_status.set(f"提取完成：{os.path.basename(output_path)}")
        messagebox.showinfo(
            "完成", f"提取完成！\n\n新文件：{os.path.basename(output_path)}\n"
            f"保留井数：{kept_wells}\n删除行数：{deleted}\n"
            f"历史/链接清理：{cleaned} 行\nexpandPoint 替换：{replaced} 处",
            parent=self)

    def _run_remove(self):
        path = self.var_remove_file.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("参数错误", "请先选择有效的 XML 文件", parent=self)
            return
        if not messagebox.askyesno(
                "确认", "此功能将直接修改原文件！\n建议先备份。\n\n是否继续？", parent=self):
            return
        self._clear_log()
        self._log(f"源文件：{path}\n")
        self.var_status.set("正在删除，请稍候…")
        self.update_idletasks()
        try:
            deleted, well_count, log_path = xml_remove_non_actual_wells(path)
        except Exception as e:
            self.var_status.set("删除失败")
            self._log(f"错误：{e}")
            messagebox.showerror("错误", f"删除失败：\n{e}", parent=self)
            return
        self._log(f"删除行数：{deleted}（涉及非实钻井 {well_count} 口）")
        if log_path:
            self._log(f"日志：{log_path}")
        self.var_status.set("删除完成")
        messagebox.showinfo(
            "完成", f"删除完成！\n\n删除行数：{deleted}\n涉及井数：{well_count}\n"
            + (f"\n日志：{os.path.basename(log_path)}" if log_path else ""), parent=self)


# ================================================================
# 入口
# ================================================================
def main():
    # 启动前强制授权：未激活/已过期则弹出激活框，用户取消则直接退出
    if not require_license():
        return
    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
