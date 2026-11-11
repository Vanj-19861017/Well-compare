import os
import re
from tkinter import Tk, messagebox
from tkinter.filedialog import askopenfilename
#适用于平面外挂很多搬设计前的操作，处理xml删除非实钻数据的井
#1.删除非实钻数据的井
#2.删除新edm中带的井槽(若槽口ID不一致，如HAOPATH生成)
#3.更改导入XML中节点为CD_WELL即可
# 配置
VALID_ACRULE_IDS = {'clUsh', 'kXivj', 'M24PK'}
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


def select_xml_file():
    """选择单个XML文件"""
    root = Tk()
    root.withdraw()
    file_path = askopenfilename(
        title='请选择XML文件',
        filetypes=[('XML文件', '*.xml')],
    )
    root.destroy()
    return file_path


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
    



def extract_non_actual_survey_well_ids(content):
    """提取<CD_DEFINITIVE_SURVEY_HEADER行中phase不是"ACTUAL"的well_id集合"""
    well_ids = set()
    for line in content.split('\n'):
        if line.strip().startswith('<CD_DEFINITIVE_SURVEY_HEADER'):
            if extract_attribute(line, 'phase') != 'ACTUAL':
                well_id = extract_attribute(line, 'well_id')
                if well_id:
                    well_ids.add(well_id)
    return well_ids


def remove_lines_by_well_ids(content, well_ids):
    """删除所有包含well_id=值在记录集合中的行，返回(新内容, 删除数, 被删行列表)"""
    lines = content.split('\n')
    kept, removed = [], []
    for line in lines:
        well_id = extract_attribute(line, 'well_id')
        if well_id is not None and well_id in well_ids:
            removed.append(line)
        else:
            kept.append(line)
    return '\n'.join(kept), len(removed), removed


def write_deleted_log(filepath, well_ids, removed_lines):
    """把被删除的行记录到与XML同目录的txt文件中"""
    log_path = os.path.splitext(filepath)[0] + '_删除行.txt'
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f'源文件: {os.path.basename(filepath)}\n')
        f.write(f'删除条件: <CD_DEFINITIVE_SURVEY_HEADER> 中 phase != "ACTUAL" 的 well_id\n')
        f.write(f'涉及的well_id: {", ".join(sorted(well_ids)) if well_ids else "(无)"}\n')
        f.write(f'删除行数: {len(removed_lines)}\n')
        f.write('=' * 60 + '\n')
        for i, line in enumerate(removed_lines, 1):
            f.write(f'[{i}] {line.strip()}\n')


def process_file(filepath):
    """处理单个XML文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    well_ids = extract_non_actual_survey_well_ids(content)
    content, deleted, removed_lines = remove_lines_by_well_ids(content, well_ids)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    if removed_lines:
        write_deleted_log(filepath, well_ids, removed_lines)

    return deleted


def main():
    """主函数"""
    file_path = select_xml_file()
    if not file_path:
        print('未选择文件，程序退出')
        return

    print(f'已选择文件: {file_path}')

    filename = os.path.basename(file_path)
    root = Tk()
    root.withdraw()
    try:
        deleted = process_file(file_path)
        print(f"已处理: {filename} (删除{deleted}行)")
        messagebox.showinfo('完成', f'处理完成！\n\n文件：{filename}\n删除行数：{deleted}\n\n删除明细见同目录下的 {os.path.splitext(filename)[0]}_删除行.txt')
    except Exception as e:
        print(f"处理 {filename} 时出错: {e}")
        messagebox.showerror('错误', f'处理 {filename} 时出错：\n{e}')


if __name__ == '__main__':
    main()
