import os
import re
import datetime
from tkinter import Tk, messagebox
from tkinter.filedialog import askdirectory

# 2.必须保留：轨迹相关标签
TRAJECTORY_TAGS = (
    'CD_POLICY', 'CD_PROJECT', 'CD_SITE', 'DP_TEMPLATE', 'CD_WELL', 'CD_DATUM', 'CD_WELLBORE',
    'CD_DEFINITIVE_SURVEY_HEADER', 'CD_DEFINITIVE_SURVEY_STATION', 'CD_SURVEY_PROGRAM', 'CD_VERTICAL_SECTION',
    'CD_SCENARIO', 'CD_SURVEY_HEADER', 'CD_SURVEY_STATION',
)
# 3.选择保留：水力相关标签
HYDRAULIC_TAGS = (
    'CD_ASSEMBLY', 'CD_ASSEMBLY_COMP', 'CD_BHA_COMP', 'CD_CASE',
    'CD_NBK_LEAK_OFF', 'CD_FLUID', 'CD_HOLE_SECT',
)
KEEP_TAGS = set(TRAJECTORY_TAGS + HYDRAULIC_TAGS)
TARGET_TAG = 'DP_PROJECT_TARGET'
# 引用靶点的表：测站，以及 LINKTABLE 中的靶点关联表
TARGET_REF_TAGS = (
    'CD_SURVEY_STATION', 'CD_PROJ_TARG_WELL_LINK', 'CD_PROJECT_TARGET_WB_LINK',
    'CD_PROJECT_TARGET_SITE_LINK', 'CD_PROJ_TARG_SCENARIO_LINK',
)
TAG_RE = re.compile(r'<([A-Z0-9_]+)')

# 改ID：提取前先统一替换这些ID
REPLACE_GROUPS = [
    {'old_ids': ['PRDPL00000', 'rNJS0Mx2vV', 'gSyBMQKdDt'], 'new_id': '12345Mx2vV'}
]

# 表头：直接使用 表头.txt 的内容（不再从源文件复制）
HEADER = (
    '<?xml version="1.0" standalone="no"?>',
    '<?DataServices DB_Major_Version=17;DB_Minor_Version=01;DB_Build_Version=000;'
    'DB_Version=EDM 5000.17.1 (17.01.00.000);expandPoint=CD_WELL;?>',
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

# 兜底结尾（源文件没有 </ALWAYS-UPDATE> 结尾时使用）
DEFAULT_ENDING = (
    '</ALWAYS-UPDATE>',
    '<LINKTABLE>',
    '</LINKTABLE>',
    '<BINARY_DATA data_encoding="base64">',
    '</BINARY_DATA>',
    '</export>',
)


def select_folder():
    """选择XML文件夹"""
    root = Tk()
    root.withdraw()
    folder_path = askdirectory(title='请选择XML文件夹')
    root.destroy()
    return folder_path


def get_attr(line, name):
    """从XML行中提取属性值（支持单/双引号）"""
    match = re.search(rf'\s{name}=(["\'])(.*?)\1', line)
    return match.group(2) if match else None


def get_tag(line):
    """取行首标签名，非标签行返回None"""
    match = TAG_RE.match(line.strip())
    return match.group(1) if match else None


def replace_ids(content, groups=REPLACE_GROUPS):
    """改ID：全局替换"""
    for group in groups:
        for old_id in group['old_ids']:
            content = content.replace(old_id, group['new_id'])
    return content


def read_lines(path):
    """读取文件并先做改ID，返回行列表（兼容BOM）"""
    with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
        content = f.read()
    return replace_ids(content).splitlines()


def split_ending(lines):
    """5.结尾：</ALWAYS-UPDATE> 到文件末尾，LINKTABLE 内部链接行清空"""
    start = None
    for i, line in enumerate(lines):
        if '</ALWAYS-UPDATE>' in line:
            start = i
            break
    if start is None:
        return None

    ending, in_linktable = [], False
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith('<LINKTABLE>'):
            in_linktable = True
        elif stripped.startswith('</LINKTABLE>'):
            in_linktable = False
        if not in_linktable or stripped.startswith(('<LINKTABLE>', '</LINKTABLE>')):
            ending.append(line)
    return ending


def collect_kept_lines(lines, seen):
    """按标签白名单收集行；CD_POLICY 按 policy_id 去重，其余按整行内容去重"""
    kept = []
    for line in lines:
        tag = get_tag(line)
        if tag in KEEP_TAGS:
            key = (tag, get_attr(line, 'policy_id')) if tag == 'CD_POLICY' else line.strip()
            if key not in seen:
                seen.add(key)
                kept.append(line)
    return kept


def collect_targets(lines):
    """4a.靶点：只保留被测站或 LINKTABLE 关联表引用过的靶点，以及源文件 ALWAYS-UPDATE 里的靶点"""
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
        tag = get_tag(line)
        if tag in TARGET_REF_TAGS:
            target_id = get_attr(line, 'project_target_id')
            if target_id:
                ref_ids.add(target_id)
        elif tag == TARGET_TAG:
            target_id = get_attr(line, 'project_target_id')
            if not target_id:
                continue
            key = (get_attr(line, 'project_id'), target_id)
            if in_always:
                always_ids.add(target_id)
            body_targets.setdefault(key, line)

    valid_ids = ref_ids | always_ids
    return [line for (_pid, tid), line in body_targets.items() if tid in valid_ids]


def build_always_update(target_lines):
    """4b.生成 <ALWAYS-UPDATE> 块：靶点行 + 每个靶点的 delete 语句"""
    block = ['<ALWAYS-UPDATE>']
    for line in target_lines:
        block.append(line)
        project_id = get_attr(line, 'project_id')
        target_id = get_attr(line, 'project_target_id')
        block.append(
            '<execsql command="delete from DP_PROJECT_TARGET_POINT where '
            f"project_id='{project_id}' and project_target_id='{target_id}'\"/>"
        )
    return block


def list_source_files(folder):
    """列出文件夹内的 .edm.xml（排除上一次生成的“全设计”文件），按名称自然排序"""
    names = [
        name for name in os.listdir(folder)
        if name.lower().endswith('.edm.xml') and not name.startswith('全设计')
    ]
    names.sort(key=lambda n: [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', n)])
    return [os.path.join(folder, name) for name in names]


def merge_folder(folder):
    """把文件夹内所有 .edm.xml 按轨道/水力/靶点组合成一个全设计文件"""
    files = list_source_files(folder)
    if not files:
        raise ValueError('所选文件夹内没有 .edm.xml 文件')

    header = list(HEADER)
    ending = None
    kept, seen = [], set()
    target_lines, target_keys = [], set()

    for path in files:
        lines = read_lines(path)
        if ending is None:
            ending = split_ending(lines)

        kept.extend(collect_kept_lines(lines, seen))

        for line in collect_targets(lines):
            project_id = get_attr(line, 'project_id')
            target_id = get_attr(line, 'project_target_id')
            key = (project_id, target_id)
            if key not in target_keys:
                target_keys.add(key)
                target_lines.append(line)

    if ending is None:
        ending = list(DEFAULT_ENDING)

    output = list(header) + kept
    if ending[0].strip().startswith('</ALWAYS-UPDATE>'):
        output.append('<ALWAYS-UPDATE>')
        output.extend(target_lines)
        output.extend(ending)
    else:
        output.extend(build_always_update(target_lines))
        output.extend(ending)

    out_name = f'全设计{datetime.date.today():%Y%m%d}.edm.xml'
    out_path = os.path.join(folder, out_name)
    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(output))

    return out_path, len(files), len(kept), len(target_lines)


def main():
    folder = select_folder()
    if not folder:
        print('未选择文件夹，程序退出')
        return

    try:
        out_path, file_count, kept_count, target_count = merge_folder(folder)
        name = os.path.basename(out_path)
        print(f'已生成: {name}（源文件{file_count}个，保留{kept_count}行，靶点{target_count}个）')
        messagebox.showinfo(
            '完成',
            f'组合完成！\n\n源文件：{file_count} 个\n保留行：{kept_count} 行\n'
            f'靶点：{target_count} 个\n\n输出：{name}'
        )
    except Exception as e:
        print(f'处理出错: {e}')
        messagebox.showerror('错误', f'处理出错：\n{e}')


if __name__ == '__main__':
    main()
