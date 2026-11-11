import os
import re
import difflib
import datetime
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.filedialog import askopenfilename
#适用于平面外挂很多搬设计前的操作，处理xml删除非实钻数据的井
#1.删除非实钻数据的井
#2.删除新edm中带的井槽(若槽口ID不一致，如HAOPATH生成)
#3.更改导入XML中节点为CD_WELL即可
# 配置
VALID_ACRULE_IDS = {'clUsh', 'kXivj', 'M24PK'}
# 测斜头表名：不同 EDM 版本导出为 CD_SURVEY_HEADER 或 CD_DEFINITIVE_SURVEY_HEADER
SURVEY_HEADER_PREFIXES = ('<CD_SURVEY_HEADER', '<CD_DEFINITIVE_SURVEY_HEADER')
# 整行删除规则：以这些标签开头的行一律删除
REMOVE_LINE_PREFIXES = (
    '<DP_TOOL_TERM',
    '<CD_SURVEY_TOOL',
    '<CD_BHA_COMP',
    '<CD_PROJECT_TARGET_SITE_LINK',
    '<CD_PROJ_TARG_WELL_LINK',
    '<CD_PROJ_TARG_SCENARIO_LINK',
)
# 整行删除规则：包含这些片段的行一律删除
REMOVE_LINE_CONTAINS = ('<CD_CHANGE_HISTORY_JOURNAL',)


def is_survey_header(line):
    """判断是否为测斜头行（兼容两种表名）"""
    return line.strip().startswith(SURVEY_HEADER_PREFIXES)


def read_first_content_line(path):
    """读取XML文件的第一条内容行（跳过 <?xml 声明），失败返回空串"""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith('<?xml'):
                    return s
    except OSError:
        pass
    return ''


def parse_sheet_name_date(name):
    """从工作表名解析日期（如 2026.10.22 / 2026-10-22 / 2026年10月22日）"""
    m = re.search(r'(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})', str(name))
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def read_first_sheet_date(excel_path):
    """读取Excel第一个表格的日期：优先前10行中的日期单元格，其次工作表名"""
    try:
        if excel_path.lower().endswith('.xls'):
            import xlrd
            book = xlrd.open_workbook(excel_path, on_demand=True)
            sh = book.sheet_by_index(0)
            for r in range(min(10, sh.nrows)):
                for c in range(sh.ncols):
                    if sh.cell_type(r, c) == xlrd.XL_CELL_DATE:
                        return xlrd.xldate.xldate_as_datetime(sh.cell_value(r, c), book.datemode).date()
            return parse_sheet_name_date(sh.name)
        else:
            from openpyxl import load_workbook
            wb = load_workbook(excel_path, read_only=True)
            try:
                ws = wb.worksheets[0]
                for row in ws.iter_rows(min_row=1, max_row=10):
                    for cell in row:
                        if isinstance(cell.value, datetime.datetime):
                            return cell.value.date()
                        if isinstance(cell.value, datetime.date):
                            return cell.value
                return parse_sheet_name_date(ws.title)
            finally:
                wb.close()
    except Exception:
        return None


def find_daily_report_date(xml_path):
    """在XML同目录查找定向井日报Excel（文件名与XML名相似度>=80%），返回其第一个表格的日期"""
    base, _ext = _split_edm_name(xml_path)
    xml_name = os.path.basename(base)
    folder = os.path.dirname(xml_path)
    try:
        candidates = [f for f in os.listdir(folder)
                      if '日报' in f and f.lower().endswith(('.xls', '.xlsx'))]
    except OSError:
        return None
    for f in candidates:
        full = os.path.splitext(f)[0]
        key = re.split(r'定向井日报|日报', full)[0].strip() or full
        ratio = max(
            difflib.SequenceMatcher(None, xml_name.lower(), key.lower()).ratio(),
            difflib.SequenceMatcher(None, xml_name.lower(), full.lower()).ratio(),
        )
        if ratio >= 0.8:
            date = read_first_sheet_date(os.path.join(folder, f))
            if date:
                return date
    return None


def ask_params():
    """参数对话框：上方选择XML文件，下方选择日期（默认当前日期前60天）"""
    root = tk.Tk()
    root.title('提取实钻数据 · 参数')
    root.resizable(False, False)

    var_file = tk.StringVar()
    var_date = tk.StringVar(
        value=(datetime.date.today() - datetime.timedelta(days=60)).isoformat()
    )
    state = {}

    body = ttk.Frame(root, padding=16)
    body.pack(fill='both', expand=True)

    ttk.Label(body, text='XML 文件：').grid(row=0, column=0, sticky='w', pady=6)
    ttk.Entry(body, textvariable=var_file, width=46).grid(
        row=0, column=1, columnspan=2, sticky='w', pady=6)

    def browse():
        path = askopenfilename(
            title='请选择XML文件',
            filetypes=[('XML文件', '*.xml')],
            parent=root,
        )
        if path:
            var_file.set(path)

    ttk.Button(body, text='浏览...', width=8, command=browse).grid(
        row=0, column=3, padx=(6, 0))

    ttk.Label(body, text='日期：').grid(row=1, column=0, sticky='w', pady=6)
    ttk.Entry(body, textvariable=var_date, width=18).grid(
        row=1, column=1, sticky='w', pady=6)
    date_hint = ttk.Label(
        body, text='create_date 晚于此日期才保留（格式 YYYY-MM-DD，默认当前日期前 60 天）',
        foreground='#666',
    )
    date_hint.grid(row=2, column=0, columnspan=4, sticky='w')

    var_split = tk.BooleanVar(value=False)

    def update_file_defaults(*_args):
        """选中文件后：按首行自动勾选拆分；匹配到定向井日报时日期取第一个表格日期-3天"""
        path = var_file.get().strip()
        if not os.path.isfile(path):
            return
        var_split.set('CD_WELL' not in read_first_content_line(path))
        report_date = find_daily_report_date(path)
        if report_date:
            var_date.set((report_date - datetime.timedelta(days=3)).isoformat())
            date_hint.config(
                text=f'已匹配定向井日报，日期 = 第一个表格 {report_date} - 3天（可手动修改）'
            )

    var_file.trace_add('write', update_file_defaults)

    ttk.Checkbutton(
        body,
        text='生成单井 EDM 文件（按 well_id 拆分，文件首行不含 CD_WELL 时自动勾选）',
        variable=var_split,
    ).grid(row=3, column=0, columnspan=4, sticky='w', pady=(10, 0))

    tip = ttk.Label(body, text='', foreground='#C0392B')
    tip.grid(row=4, column=0, columnspan=4, sticky='w', pady=(6, 0))

    def on_ok():
        path = var_file.get().strip()
        if not path or not os.path.isfile(path):
            tip.config(text='请先选择有效的 XML 文件')
            return
        try:
            cutoff = datetime.date.fromisoformat(var_date.get().strip())
        except ValueError:
            tip.config(text='日期格式应为 YYYY-MM-DD')
            return
        state['file'] = path
        state['date'] = cutoff
        state['split'] = var_split.get()
        root.destroy()

    btns = ttk.Frame(body)
    btns.grid(row=5, column=0, columnspan=4, sticky='e', pady=(14, 0))
    ttk.Button(btns, text='开始处理', command=on_ok).pack(side='right')
    ttk.Button(btns, text='取消', command=root.destroy).pack(side='right', padx=(0, 8))

    root.bind('<Return>', lambda _e: on_ok())
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 3
    root.geometry(f'+{x}+{y}')
    root.mainloop()
    return state.get('file'), state.get('date'), state.get('split', False)


def filter_lines(content, keep_condition):
    """通用行过滤函数"""
    lines = content.split('\n')
    kept = [line for line in lines if keep_condition(line)]
    deleted = len(lines) - len(kept)
    return '\n'.join(kept), deleted


def extract_attribute(line, attr_name):
    """从XML行中提取属性值（支持单/双引号，且值内部可含另一种引号）"""
    match = re.search(rf'{attr_name}=(["\'])(.*?)\1', line)
    return match.group(2) if match else None


def extract_project_target_ids(content):
    """提取CD_SURVEY_STATION中的project_target_id"""
    return set(re.findall(r'<CD_SURVEY_STATION[^>]*project_target_id="([^"]*)"', content))


def remove_unwanted_lines(content):
    """删除配置中的整行：前缀匹配(REMOVE_LINE_PREFIXES)或片段包含(REMOVE_LINE_CONTAINS)"""
    def keep(line):
        if line.strip().startswith(REMOVE_LINE_PREFIXES):
            return False
        return not any(k in line for k in REMOVE_LINE_CONTAINS)
    return filter_lines(content, keep)


def replace_project_geo_info(content):
    """CD_PROJECT中geo_zone_id为指定值时，替换geo_system_id/geo_zone_id/geo_datum_id"""
    target_zone = 'Zone20, North 117E to 123E'
    replacements = {
        'geo_system_id': 'CGCS2000_UTM120',
        'geo_zone_id': 'BoHai',
        'geo_datum_id': 'CGCS2000',
    }
    count = 0
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.strip().startswith('<CD_PROJECT project_id='):
            if extract_attribute(line, 'geo_zone_id') == target_zone:
                for attr, new_val in replacements.items():
                    lines[i] = re.sub(
                        rf'({attr}=["\'])[^"\']*(["\'])',
                        rf'\g<1>{new_val}\g<2>',
                        lines[i]
                    )
                count += 1
    return '\n'.join(lines), count


def remove_invalid_dp_project_target(content, valid_ids):
    """删除DP_PROJECT_TARGET中不在valid_ids列表中的行"""
    def keep(line):
        if line.strip().startswith('<DP_PROJECT_TARGET'):
            target_id = extract_attribute(line, 'project_target_id')
            return target_id is None or target_id in valid_ids
        return True
    return filter_lines(content, keep)


def remove_invalid_dp_acrule(content):
    """删除DP_ACRULE中acrule_id不是有效值的行"""
    def keep(line):
        if line.strip().startswith('<DP_ACRULE'):
            acrule_id = extract_attribute(line, 'acrule_id')
            return acrule_id is None or acrule_id in VALID_ACRULE_IDS
        return True
    return filter_lines(content, keep)


def remove_invalid_links_after_linktable(content):
    """删除<LINKTABLE>之后project_target_id无效的行"""
    lines = content.split('\n')
    valid_ids = extract_project_target_ids(content)
    
    # 找到<LINKTABLE>位置
    linktable_idx = next((i for i, line in enumerate(lines) if '<LINKTABLE>' in line.strip()), -1)
    if linktable_idx == -1:
        return content, 0
    



def parse_create_date(value):
    """解析 create_date 为 date 对象，失败返回 None。
    兼容 EDM 的 {ts '2007-10-15 20:28:36'} 写法。"""
    if not value:
        return None
    s = value.strip()
    # 去掉 {ts '...'} 包裹，取里面的时间字符串
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


def extract_actual_survey_create_dates(content, cutoff):
    """提取测斜头(CD_SURVEY_HEADER/CD_DEFINITIVE_SURVEY_HEADER)中 phase="ACTUAL"
    且 create_date 晚于 cutoff 的 well_id -> 最新日期"""
    dates = {}
    for line in content.split('\n'):
        if is_survey_header(line):
            if extract_attribute(line, 'phase') != 'ACTUAL':
                continue
            create_date = parse_create_date(extract_attribute(line, 'create_date'))
            if create_date is None or create_date <= cutoff:
                continue
            well_id = extract_attribute(line, 'well_id')
            if well_id and (well_id not in dates or create_date > dates[well_id]):
                dates[well_id] = create_date
    return dates


def extract_recent_actual_well_ids(content, cutoff):
    """提取测斜头行中 phase="ACTUAL" 且 create_date 晚于 cutoff 的 well_id集合"""
    return set(extract_actual_survey_create_dates(content, cutoff))


def remove_lines_not_in_well_ids(content, well_ids):
    """删除所有 well_id= 值不在 well_ids 集合中的行，返回(新内容, 删除数, 被删行列表)"""
    lines = content.split('\n')
    kept, removed = [], []
    for line in lines:
        well_id = extract_attribute(line, 'well_id')
        if well_id is not None and well_id not in well_ids:
            removed.append(line)
        else:
            kept.append(line)
    return '\n'.join(kept), len(removed), removed


def replace_expand_point(content):
    """把 expandPoint=CD_SITE 改成 expandPoint=CD_WELL，返回(新内容, 替换次数)"""
    count = content.count('expandPoint=CD_SITE')
    return content.replace('expandPoint=CD_SITE', 'expandPoint=CD_WELL'), count


def extract_well_common_names(content):
    """提取<CD_WELL行中 well_id -> well_common_name"""
    names = {}
    for line in content.split('\n'):
        if line.strip().startswith('<CD_WELL'):
            well_id = extract_attribute(line, 'well_id')
            name = extract_attribute(line, 'well_common_name')
            if well_id and name:
                names[well_id] = name
    return names


def write_kept_wells_log(filepath, content, well_ids, cutoff):
    """把保留的实钻井信息记录到与XML同目录的txt文件中"""
    base, _ext = _split_edm_name(filepath)
    log_path = base + '_保留井信息.txt'
    names = extract_well_common_names(content)
    dates = extract_actual_survey_create_dates(content, cutoff)

    with open(log_path, 'w', encoding='utf-8') as f:
        f.write('序号\twell_common_name\tcreate_date\n')
        for i, well_id in enumerate(sorted(well_ids), 1):
            name = names.get(well_id, '(未找到CD_WELL)')
            date = dates.get(well_id)
            f.write(f'{i}\t{name}\t{date.isoformat() if date else "(无)"}\n')
        f.write(f'\n共记录实钻井 {len(well_ids)} 口（筛选日期 {cutoff}）\n')


def _split_edm_name(filepath):
    """拆分文件名，把 .edm.xml 视为后缀：返回(去后缀的主名, 完整后缀)"""
    base, ext = os.path.splitext(filepath)
    if base.lower().endswith('.edm'):
        base = base[:-4]
        ext = '.edm' + ext
    return base, ext


def build_output_path(filepath):
    """生成新文件路径：_提取近期开钻井 加在 .edm 之前（如 xxx.edm.xml -> xxx_提取近期开钻井.edm.xml）"""
    base, ext = _split_edm_name(filepath)
    return f'{base}_提取近期开钻井{ext or ".xml"}'


def sanitize_filename(name):
    """替换Windows文件名非法字符"""
    cleaned = re.sub(r'[\\/:*?"<>|]', '_', name).strip()
    return cleaned or 'unnamed'


def split_single_well_files(output_path, content, well_ids):
    """把多井XML按井拆分为单井文件：
    <DP_TEMPLATE 与 <ALWAYS-UPDATE> 之间仅保留同一 well_id 的行，
    区间之外的内容（含文件首行）原样保留。
    文件名 = well_common_name + .edm.xml，返回生成的文件路径列表。"""
    lines = content.split('\n')
    start = next((i for i, l in enumerate(lines) if l.strip().startswith('<DP_TEMPLATE')), None)
    end = next((i for i, l in enumerate(lines) if '<ALWAYS-UPDATE>' in l), None)
    if start is None or end is None or end <= start:
        return []
    head = lines[:start]    # 区间前：xml声明、DataServices头、CD_PROJECT、CD_SITE 等
    region = lines[start:end]
    tail = lines[end:]      # <ALWAYS-UPDATE> 起至文件尾
    names = extract_well_common_names(content)
    out_dir = os.path.dirname(output_path)
    out_paths = []
    for well_id in sorted(well_ids):
        kept = [l for l in region if extract_attribute(l, 'well_id') == well_id]
        if not kept:
            continue
        name = sanitize_filename(names.get(well_id) or well_id)
        out = os.path.join(out_dir, f'{name}.edm.xml')
        with open(out, 'w', encoding='utf-8') as f:
            f.write('\n'.join(head + kept + tail))
        out_paths.append(out)
    return out_paths


def process_file(filepath, cutoff, split=False):
    """处理单个XML文件，结果另存为新文件。
    返回(删除行数, expandPoint替换次数, 保留井数, 输出文件路径, 单井文件列表)"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    well_ids = extract_recent_actual_well_ids(content, cutoff)
    content, deleted, removed_lines = remove_lines_not_in_well_ids(content, well_ids)
    content, cleaned = remove_unwanted_lines(content)
    content, replaced = replace_expand_point(content)

    output_path = build_output_path(filepath)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    if well_ids:
        write_kept_wells_log(output_path, content, well_ids, cutoff)

    single_files = split_single_well_files(output_path, content, well_ids) if split else []

    return deleted, replaced, len(well_ids), output_path, single_files, cleaned


def main():
    """主函数"""
    file_path, cutoff, split = ask_params()
    if not file_path:
        print('未选择文件，程序退出')
        return

    print(f'已选择文件: {file_path}，筛选日期: {cutoff}，拆分单井: {split}')

    filename = os.path.basename(file_path)
    try:
        deleted, replaced, kept_wells, output_path, single_files, cleaned = process_file(file_path, cutoff, split)
        out_name = os.path.basename(output_path)
        print(f"已处理: {filename} -> {out_name} (删除{deleted}行, 清理历史/链接{cleaned}行, expandPoint替换{replaced}处, 保留{kept_wells}口井)")
        for p in single_files:
            print(f"单井文件: {os.path.basename(p)}")
        if split and kept_wells and not single_files:
            split_msg = '\n单井拆分：未找到 <DP_TEMPLATE/<ALWAYS-UPDATE> 区间，未生成单井文件\n'
        elif split:
            split_msg = f'\n单井文件：{len(single_files)} 个（同目录，按井名命名）\n'
        else:
            split_msg = ''
        messagebox.showinfo(
            '完成',
            f'处理完成！\n\n原文件保留不动\n'
            f'新文件：{out_name}\n'
            f'筛选日期：{cutoff}\n'
            f'保留井数：{kept_wells}\n'
            f'删除行数：{deleted}\n'
            f'历史/链接行清理：{cleaned} 行\n'
            f'expandPoint 替换：{replaced} 处\n'
            f'{split_msg}\n'
            f'保留井清单：{os.path.splitext(out_name)[0]}_保留井信息.txt'
        )
    except Exception as e:
        print(f"处理 {filename} 时出错: {e}")
        messagebox.showerror('错误', f'处理 {filename} 时出错：\n{e}')


if __name__ == '__main__':
    main()
