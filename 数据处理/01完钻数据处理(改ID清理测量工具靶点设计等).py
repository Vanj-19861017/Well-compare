import os
import re
from tkinter import Tk, messagebox
from tkinter.filedialog import askdirectory

# 配置
VALID_ACRULE_IDS = {'clUsh', 'kXivj', 'M24PK'}
PROTOTYPE_PHASES = {'PROTOTYPE', 'PLAN'}
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


def extract_attribute(line, attr_name):
    """从XML行中提取属性值"""
    match = re.search(rf'{attr_name}=["\']([^"\']*)["\']', line)
    return match.group(1) if match else None


def filter_lines(content, keep_condition):
    """通用行过滤函数"""
    lines = content.split('\n')
    kept = [line for line in lines if keep_condition(line)]
    deleted = len(lines) - len(kept)
    return '\n'.join(kept), deleted


def extract_project_target_ids(content):
    """提取CD_SURVEY_STATION中的project_target_id"""
    pattern = r'<CD_SURVEY_STATION[^>]*project_target_id="([^"]*)"'
    return set(re.findall(pattern, content))

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


def remove_unwanted_lines(content):
    """删除配置中的整行：前缀匹配(REMOVE_LINE_PREFIXES)或片段包含(REMOVE_LINE_CONTAINS)"""
    def keep(line):
        if line.strip().startswith(REMOVE_LINE_PREFIXES):
            return False
        return not any(k in line for k in REMOVE_LINE_CONTAINS)
    return filter_lines(content, keep)


def remove_invalid_links_after_linktable(content):
    """清除 <LINKTABLE> 之后的全部内容，补回标准结尾（空 LINKTABLE + BINARY_DATA + </export>）"""
    lines = content.split('\n')

    # 找到<LINKTABLE>位置
    linktable_idx = next((i for i, line in enumerate(lines) if '<LINKTABLE>' in line.strip()), -1)
    if linktable_idx == -1:
        return content, 0

    kept = lines[:linktable_idx + 1] + [
        '</LINKTABLE>',
        '<BINARY_DATA data_encoding="base64">',
        '</BINARY_DATA>',
        '</export>',
    ]

    return '\n'.join(kept), len(lines) - linktable_idx - 1


def remove_specific_lines(content):
    """删除phase为PROTOTYPE/PLAN的行及其相关行"""
    lines = content.split('\n')

    # 提取待删除的ID（一次扫描完成）
    ids_to_delete = set()
    wellbore_ids_to_delete = set()

    # 提取phase="ACTUAL"的CD_DEFINITIVE_SURVEY_HEADER行中的wellbore_id
    actual_wellbore_ids = set()

    for line in lines:
        if any(phase in line for phase in PROTOTYPE_PHASES):
            if '<CD_DEFINITIVE_SURVEY_HEADER' in line:
                def_id = extract_attribute(line, 'def_survey_header_id')
                if def_id:
                    ids_to_delete.add(def_id)
            elif '<CD_SURVEY_HEADER' in line:
                survey_id = extract_attribute(line, 'survey_header_id')
                if survey_id:
                    ids_to_delete.add(survey_id)
                wellbore_id = extract_attribute(line, 'wellbore_id')
                if wellbore_id:
                    wellbore_ids_to_delete.add(wellbore_id)
        # 记录phase="ACTUAL"的CD_DEFINITIVE_SURVEY_HEADER行中的wellbore_id
        if line.strip().startswith('<CD_DEFINITIVE_SURVEY_HEADER') and 'phase="ACTUAL"' in line:
            wellbore_id = extract_attribute(line, 'wellbore_id')
            if wellbore_id:
                actual_wellbore_ids.add(wellbore_id)

    # 执行删除
    def keep(line):
        # 删除phase=PROTOTYPE/PLAN的CD_DEFINITIVE_SURVEY_HEADER和CD_SURVEY_HEADER行
        if any(phase in line for phase in PROTOTYPE_PHASES):
            if '<CD_DEFINITIVE_SURVEY_HEADER' in line or '<CD_SURVEY_HEADER' in line:
                return False

        # 删除CD_WELLBORE行：只删除与PROTOTYPE/PLAN相关的，保留与ACTUAL相关的
        if line.strip().startswith('<CD_WELLBORE'):
            wellbore_id = extract_attribute(line, 'wellbore_id')
            # 如果wellbore_id在ACTUAL列表中，保留
            if wellbore_id in actual_wellbore_ids:
                return True
            # 如果wellbore_id在PROTOTYPE/PLAN列表中，删除
            if wellbore_id in wellbore_ids_to_delete:
                return False
            # 如果wellbore_id既不在ACTUAL也不在PROTOTYPE/PLAN列表中，保留（可能是其他phase）
            return True

        # 删除包含待删除ID的行
        if '<CD_SURVEY_PROGRAM' in line or '<DP_ANNOTATION' in line:
            def_id = extract_attribute(line, 'def_survey_header_id')
            survey_id = extract_attribute(line, 'survey_header_id')
            if (def_id in ids_to_delete) or (survey_id in ids_to_delete):
                return False

        for id_val in ids_to_delete:
            if id_val in line:
                return False

        return True
    
    return filter_lines(content, keep)


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


def process_file(filepath):
    """处理单个XML文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    filename = os.path.basename(filepath)
    # 如果文件名不包含-，则查找site_name并重命名文件
    if '-' not in filename:
        site_name = extract_site_name(content)
        if site_name:
            dir_path = os.path.dirname(filepath)
            new_filename = f"{site_name}-{filename}"
            new_filepath = os.path.join(dir_path, new_filename)
            os.rename(filepath, new_filepath)
            filepath = new_filepath
            print(f"已重命名: {filename} -> {new_filename}")
    # 如果文件名只有一个-，且-左边的内容被右边的内容包含，也加上site_name
    elif filename.count('-') == 1:
        parts = filename.split('-', 1)
        left = parts[0]
        right = parts[1]
        if left in right:
            site_name = extract_site_name(content)
            if site_name:
                dir_path = os.path.dirname(filepath)
                new_filename = f"{site_name}-{filename}"
                new_filepath = os.path.join(dir_path, new_filename)
                os.rename(filepath, new_filepath)
                filepath = new_filepath
                print(f"已重命名: {filename} -> {new_filename}")
    
    total_deleted = 0
    operations = [
        remove_specific_lines,
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
                status = f"已处理: {filename} (删除{deleted}行)"
                if deleted > 0:
                    processed_files.append(f"{filename} (删除{deleted}行)")
                print(status)
            except Exception as e:
                print(f"处理 {filename} 时出错: {e}")
    
    root = Tk()
    root.withdraw()
    if processed_files:
        messagebox.showinfo('完成', f'成功处理 {len(processed_files)} 个文件！\n\n详细结果：\n' + '\n'.join(processed_files))
    else:
        messagebox.showinfo('完成', '未找到需要处理的XML文件，或没有需要删除的行')


if __name__ == '__main__':
    main()
