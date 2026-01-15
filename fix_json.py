"""
修复 child_story.json 中的非标准 JSON 格式
将三引号多行字符串转换为标准 JSON 格式
"""

import re

def fix_json_file():
    input_path = "child_story.json"
    output_path = "child_story_fixed.json"
    
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 找到所有 """...""" 模式并替换
    # 步骤1: 将三引号内的换行符替换为 \n 转义序列
    def replace_triple_quotes(match):
        inner = match.group(1)
        # 将实际换行符替换为 \\n 转义序列
        inner = inner.replace('\r\n', '\\n').replace('\n', '\\n')
        # 将内部的双引号转义
        inner = inner.replace('"', '\\"')
        return '"' + inner + '"'
    
    # 匹配 """...""" 模式（非贪婪）
    pattern = r'"""(.*?)"""'
    fixed_content = re.sub(pattern, replace_triple_quotes, content, flags=re.DOTALL)
    
    # 写入修复后的文件
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(fixed_content)
    
    print(f"修复完成！已保存到 {output_path}")
    
    # 验证 JSON 是否有效
    import json
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"✅ JSON 验证通过！共 {len(data.get('script', []))} 个场景")
        
        # 覆盖原文件
        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ 已更新原文件 {input_path}")
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON 仍有错误: {e}")


if __name__ == "__main__":
    fix_json_file()
