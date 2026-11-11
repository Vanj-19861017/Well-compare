import os
import re
from tkinter import Tk, messagebox
from tkinter.filedialog import askdirectory

# 配置
VALID_ACRULE_IDS = {'clUsh', 'kXivj', 'M24PK'}
processed_files = []
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


def select_folder():
    """选择XML文件夹"""
    root = Tk()
    root.withdraw()
    folder_path = askdirectory(title='请选择XML文件夹')
    root.destroy()
    return folder_path


def filter_lines(content, keep_condition):
    """通用行过滤函数"""
    lines = content.split('\n')
    kept = [line for line in lines if keep_condition(line)]
    deleted = len(lines) - len(kept)
    return '\n'.join(kept), deleted


def extract_attribute(line, attr_name):
    """从XML行中提取属性值（支持双引号和单引号）"""
    match = re.search(rf'{attr_name}=["\']([^"\']*)["\']', line)
    return match.group(1) if match else None


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
    
    # 过滤
    kept = []
    deleted = 0
    for i, line in enumerate(lines):
        if i > linktable_idx and 'project_target_id' in line:
            target_id = extract_attribute(line, 'project_target_id')
            if target_id and target_id not in valid_ids:
                deleted += 1
                continue
        kept.append(line)
    
    return '\n'.join(kept), deleted


def replace_ids(content, replace_groups):
    """替换ID"""
    for group in replace_groups:
        for old_id in group['old_ids']:
            content = content.replace(old_id, group['new_id'])
    return content


def replace_survey_tool_ids(content):
    """替换survey_tool_id属性中的特定值（仅替换属性值，避免全局替换）"""
    for group in SURVEY_TOOL_REPLACE_GROUPS:
        old_ids_pattern = '|'.join(group['old_ids'])
        content = re.sub(rf'survey_tool_id="({old_ids_pattern})"', f'survey_tool_id="{group["new_id"]}"', content)
    return content


REPLACE_GROUPS = [
    {'old_ids': ['PRDPL00000', 'rNJS0Mx2vV', 'gSyBMQKdDt'], 'new_id': '12345Mx2vV'}
]

SURVEY_TOOL_REPLACE_GROUPS = [
    {'old_ids': ['8b4PS', 'HdWb7','CU5bO'], 'new_id': 'mDBG5'},
    {'old_ids': ['vLU3w', 'Av6LZ','eUZtM'], 'new_id': 'TKHg1'}
]


def extract_site_name(content):
    """从内容中提取site_name的值"""
    match = re.search(r'site_name="([^"]*)"', content)
    return match.group(1) if match else None


_SAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')


def _sanitize_filename(name):
    """去掉 Windows 文件名非法字符，保留可读"""
    return _SAFE_FILENAME_RE.sub('-', name).strip()


def process_file(filepath):
    """处理单个XML文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    filename = os.path.basename(filepath)
    # 如果文件名不包含-，则查找site_name并重命名文件
    if '-' not in filename:
        site_name = extract_site_name(content)
        if site_name:
            safe = _sanitize_filename(site_name)
            if safe:
                dir_path = os.path.dirname(filepath)
                new_filename = f"{safe}-{filename}"
                new_filepath = os.path.join(dir_path, new_filename)
                try:
                    os.rename(filepath, new_filepath)
                    filepath = new_filepath
                    print(f"已重命名: {filename} -> {new_filename}")
                except OSError as e:
                    print(f"重命名跳过（{e}），继续处理原文件")
    
    total_deleted = 0
    operations = [
        remove_unwanted_lines,
        lambda c: remove_invalid_dp_project_target(c, extract_project_target_ids(c)),
        remove_invalid_dp_acrule,
        remove_invalid_links_after_linktable,
        replace_project_geo_info
    ]
    
    for op in operations:
        content, deleted = op(content)
        total_deleted += deleted
    
    content = replace_ids(content, REPLACE_GROUPS)
    
    # 替换survey_tool_id属性中的特定值
    content = replace_survey_tool_ids(content)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return total_deleted


def main():
    """主函数"""
    folder_path = select_folder()
    if not folder_path:
        print('未选择文件夹，程序退出')
        return
    
    print(f'已选择文件夹: {folder_path}')
    
    for filename in os.listdir(folder_path):
        if filename.endswith('.xml'):
            filepath = os.path.join(folder_path, filename)
            try:
                deleted = process_file(filepath)
                processed_files.append(f"{filename} (删除{deleted}行)")
                print(f"已处理: {filename} (删除{deleted}行)")
            except Exception as e:
                print(f"处理 {filename} 时出错: {e}")
    
    root = Tk()
    root.withdraw()
    if processed_files:
        messagebox.showinfo('完成', f'成功处理 {len(processed_files)} 个文件！\n\n已处理的文件：\n' + '\n'.join(processed_files))
    else:
        messagebox.showinfo('完成', '未找到需要处理的XML文件')


if __name__ == '__main__':
    main()
