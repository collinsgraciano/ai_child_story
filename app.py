
"""
儿童故事图片视频生成工具 - Flask 服务器
支持：图片生成、参考图生成、视频生成、重新生成、配置管理
"""

import json
import os
import re
import shutil
import glob
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from image_generator import ImageGenerator
from video_generator import VideoGenerator
from audio_generator import AudioGenerator
from config_manager import config

app = Flask(__name__, static_folder='static')
CORS(app)

# 初始化生成器（使用配置）
image_gen = ImageGenerator(
    api_key=config.get("image_api", "api_key"),
    base_url=config.get("image_api", "base_url")
)
image_gen.model = config.get("image_api", "model")
image_gen.max_retries = config.get("generation", "image_max_retries") or 3

video_gen = VideoGenerator(
    api_key=config.get("video_api", "api_key"),
    base_url=config.get("video_api", "base_url"),
    model_name=config.get("video_api", "model")
)

audio_gen = AudioGenerator(
    api_url=config.get("audio_api", "base_url") or "",
    default_ref_audio=config.get("audio_api", "reference_audio")
)

# 全局状态
story_data = None
current_project_dir = None  # 当前项目输出目录
current_project_name = None  # 当前项目名称（清理后的 title）
current_style = None  # 当前选中的风格名称

# 风格图片目录
STYLES_DIR = os.path.join(os.path.dirname(__file__), "styles")
os.makedirs(STYLES_DIR, exist_ok=True)

generation_status = {
    "character_sheet": None,
    "scene_sheet": None,
    "current_project": None,
    "pages": {},  # {page_index: {"image": status, "video": status, "audio": status, "selected": bool}}
    "srt": None   # None, "generating", "completed", "failed"
}

# 全局任务计数 (Debug)
active_video_tasks = 0
active_audio_tasks = 0

def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-', '（', '）')).strip()


def fix_json_content(content: str) -> str:
    """
    自动修复常见的 JSON 格式问题
    - 三引号多行字符串 -> 标准双引号
    - 尾随逗号
    """
    import re
    
    # 修复三引号多行字符串
    def replace_triple_quotes(match):
        inner = match.group(1)
        # 将实际换行符替换为 \\n 转义序列
        inner = inner.replace('\r\n', '\\n').replace('\n', '\\n')
        # 将内部的双引号转义
        inner = inner.replace('"', '\\"')
        return '"' + inner + '"'
    
    # 匹配 """...""" 模式（非贪婪）
    pattern = r'"""(.*?)"""'
    content = re.sub(pattern, replace_triple_quotes, content, flags=re.DOTALL)
    
    # 移除尾随逗号（对象和数组末尾的逗号）
    content = re.sub(r',\s*}', '}', content)
    content = re.sub(r',\s*]', ']', content)
    
    return content


def reset_generation_status():
    """重置生成状态"""
    global generation_status
    generation_status = {
        "character_sheet": None,
        "scene_sheet": None,
        "current_project": None,
        "pages": {},
        "srt": None
    }


def init_project_from_story():
    """根据 story_data 初始化项目目录和状态"""
    global current_project_dir, current_project_name, generation_status
    
    if not story_data:
        return False
    
    # 创建以 title 命名的项目目录
    title = story_data.get("title", "untitled")
    current_project_name = sanitize_filename(title)
    if not current_project_name:
        current_project_name = "untitled"
    
    current_project_dir = os.path.join(os.path.dirname(__file__), "output", current_project_name)
    os.makedirs(os.path.join(current_project_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(current_project_dir, "videos"), exist_ok=True)
    os.makedirs(os.path.join(current_project_dir, "audio"), exist_ok=True)
    
    # 更新生成器输出目录
    image_gen.output_dir = current_project_dir
    video_gen.output_dir = os.path.join(current_project_dir, "videos")
    
    # 初始化每一页的状态
    for page in story_data.get("script", []):
        idx = page["page_index"]
        if idx not in generation_status["pages"]:
            generation_status["pages"][idx] = {
                "image": None,
                "video": None,
                "audio": {"cn": None, "en": None},
                "selected": False
            }
        
        # 检查文件是否存在
        if generation_status["pages"][idx]["image"] is None:
            if os.path.exists(f"{current_project_dir}/images/page_{idx:03d}.png"):
                generation_status["pages"][idx]["image"] = "completed"
                
        if generation_status["pages"][idx]["video"] is None:
            if os.path.exists(f"{current_project_dir}/videos/page_{idx:03d}.mp4"):
                generation_status["pages"][idx]["video"] = "completed"

        # 检查音频状态 (双语)
        if generation_status["pages"][idx]["audio"] is None: # fix dirty data if needed
             generation_status["pages"][idx]["audio"] = {"cn": None, "en": None}
             
        if generation_status["pages"][idx]["audio"]["cn"] is None:
            if os.path.exists(f"{current_project_dir}/audio/page_{idx:03d}_cn.wav") or \
               os.path.exists(f"{current_project_dir}/audio/page_{idx:03d}.wav"):
                generation_status["pages"][idx]["audio"]["cn"] = "completed"
                
        if generation_status["pages"][idx]["audio"]["en"] is None:
            if os.path.exists(f"{current_project_dir}/audio/page_{idx:03d}_en.wav"):
                generation_status["pages"][idx]["audio"]["en"] = "completed"

    return True


def load_story_data():
    """加载故事数据"""
    global story_data
    json_path = os.path.join(os.path.dirname(__file__), "child_story_fixed.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 使用 fix_json_content 预处理
        content = fix_json_content(content)
        
        story_data = json.loads(content)
        init_project_from_story()
        return True
    return False


# 启动时加载数据
load_story_data()


# ===== 配置相关 API =====

@app.route('/api/config', methods=['GET'])
def get_config():
    """获取当前配置"""
    # 强制重载以获取最新状态和错误
    current_config = config.to_dict()
    
    return jsonify({
        "success": True,
        "config": current_config,
        "config_error": config.last_error # [NEW] 暴露配置加载错误
    })


@app.route('/api/config', methods=['POST'])
def update_config():
    """更新配置"""
    try:
        data = request.get_json()
        
        # 更新图片 API 配置
        if "image_api" in data:
            img_cfg = data["image_api"]
            config.update_image_api(
                base_url=img_cfg.get("base_url", config.get("image_api", "base_url")),
                api_key=img_cfg.get("api_key", config.get("image_api", "api_key")),
                model=img_cfg.get("model", config.get("image_api", "model"))
            )
            # 更新生成器
            image_gen.client = None  # 重新初始化
            image_gen.__init__(
                api_key=config.get("image_api", "api_key"),
                base_url=config.get("image_api", "base_url")
            )
            image_gen.model = config.get("image_api", "model")
        
        # 更新视频 API 配置
        if "video_api" in data:
            vid_cfg = data["video_api"]
            config.update_video_api(
                base_url=vid_cfg.get("base_url", config.get("video_api", "base_url")),
                api_key=vid_cfg.get("api_key", config.get("video_api", "api_key")),
                model=vid_cfg.get("model", config.get("video_api", "model"))
            )
            # 更新生成器
            video_gen.update_config(
                api_key=config.get("video_api", "api_key"),
                base_url=config.get("video_api", "base_url"),
                model_name=config.get("video_api", "model")
            )
        
        # [FIX] 更新音频 API 配置
        if "audio_api" in data:
            audio_cfg = data["audio_api"]
            config.update_audio_api(
                base_url=audio_cfg.get("base_url", config.get("audio_api", "base_url")),
                reference_audio=audio_cfg.get("reference_audio", config.get("audio_api", "reference_audio"))
            )
            # 更新生成器
            audio_gen.update_config(
                api_url=config.get("audio_api", "base_url"),
                default_ref_audio=config.get("audio_api", "reference_audio")
            )
        
        # 更新优化 API 配置
        if "optimize_api" in data:
            opt_cfg = data["optimize_api"]
            # 直接更新整个 optimize_api 部分
            current_opt = config.config.get("optimize_api", {})
            current_opt.update({
                "base_url": opt_cfg.get("base_url", current_opt.get("base_url", "")),
                "api_key": opt_cfg.get("api_key", current_opt.get("api_key", "")),
                "model": opt_cfg.get("model", current_opt.get("model", "")),
                "image_prompt_template": opt_cfg.get("image_prompt_template", current_opt.get("image_prompt_template", "")),
                "video_prompt_template": opt_cfg.get("video_prompt_template", current_opt.get("video_prompt_template", ""))
            })
            config.config["optimize_api"] = current_opt
            config.save_config()
        
        # 更新其他配置
        if "generation" in data:
            for key, value in data["generation"].items():
                config.set("generation", key, value=value)
        
        return jsonify({
            "success": True,
            "message": "配置已更新",
            "config": config.to_dict()
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })


# ===== 风格管理 API =====

@app.route('/api/styles', methods=['GET'])
def list_styles():
    """获取所有已保存的风格"""
    styles = []
    for f in os.listdir(STYLES_DIR):
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            name = os.path.splitext(f)[0]
            styles.append({
                "name": name,
                "path": f"/styles/{f}"
            })
    return jsonify({
        "success": True,
        "styles": styles,
        "current_style": current_style
    })


@app.route('/api/styles', methods=['POST'])
def upload_style():
    """上传新风格图片"""
    global current_style
    
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "未找到上传文件"})
    
    file = request.files['file']
    name = request.form.get('name', '').strip()
    
    if not name:
        return jsonify({"success": False, "error": "请提供风格名称"})
    
    if not file.filename:
        return jsonify({"success": False, "error": "文件名为空"})
    
    # 保存文件
    ext = os.path.splitext(file.filename)[1].lower() or '.png'
    save_path = os.path.join(STYLES_DIR, f"{name}{ext}")
    file.save(save_path)
    
    # 自动设为当前风格
    current_style = name
    
    return jsonify({
        "success": True,
        "message": f"风格 '{name}' 上传成功",
        "path": f"/styles/{name}{ext}"
    })


@app.route('/api/styles/<name>', methods=['DELETE'])
def delete_style(name):
    """删除风格"""
    global current_style
    
    # 查找匹配的文件
    for f in os.listdir(STYLES_DIR):
        if os.path.splitext(f)[0] == name:
            os.remove(os.path.join(STYLES_DIR, f))
            if current_style == name:
                current_style = None
            return jsonify({"success": True, "message": f"风格 '{name}' 已删除"})
    
    return jsonify({"success": False, "error": f"风格 '{name}' 不存在"})


@app.route('/api/styles/current', methods=['GET'])
def get_current_style():
    """获取当前选中的风格"""
    return jsonify({
        "success": True,
        "current_style": current_style
    })


@app.route('/api/styles/current', methods=['POST'])
def set_current_style():
    """设置当前风格"""
    global current_style
    data = request.get_json()
    name = data.get("name")
    
    if name:
        # 验证风格存在
        found = False
        for f in os.listdir(STYLES_DIR):
            if os.path.splitext(f)[0] == name:
                found = True
                break
        if not found:
            return jsonify({"success": False, "error": f"风格 '{name}' 不存在"})
    
    current_style = name
    return jsonify({
        "success": True,
        "current_style": current_style
    })


@app.route('/styles/<path:filename>')
def serve_style(filename):
    """提供风格图片静态文件服务"""
    return send_from_directory(STYLES_DIR, filename)


@app.route('/api/config/test-image-api', methods=['POST'])
def test_image_api():
    """测试图片 API 连接"""
    try:
        # 尝试一个简单的请求
        result = image_gen.generate_text_to_image(
            prompt="A simple test image, minimal, white background",
            filename="__test_connection__"
        )
        
        # 删除测试文件
        test_path = os.path.join(image_gen.output_dir, "__test_connection__.png")
        if os.path.exists(test_path):
            os.remove(test_path)
        
        if result["success"]:
            return jsonify({
                "success": True,
                "message": "图片 API 连接成功"
            })
        else:
            return jsonify({
                "success": False,
                "error": result["error"]
            })
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })


# ===== 视频提示词优化 API =====

@app.route('/api/optimize/video-prompt', methods=['POST'])
def optimize_video_prompt():
    """使用 AI 优化视频提示词"""
    import requests as req
    
    data = request.get_json()
    page_index = data.get("page_index")
    old_prompt = data.get("video_prompt", "")
    eng_narration = data.get("eng_narration", "")
    image_prompt = data.get("image_prompt", "")  # [NEW] 参考图片提示词
    
    if not old_prompt:
        return jsonify({"success": False, "error": "视频提示词为空"})
    
    # 获取优化 API 配置
    opt_config = config.to_dict().get("optimize_api", {})
    base_url = opt_config.get("base_url", "").rstrip('/')
    api_key = opt_config.get("api_key", "")
    model = opt_config.get("model", "gpt-4.1-mini")
    
    if not base_url or not api_key:
        return jsonify({"success": False, "error": "请先配置优化 API (optimize_api)"})
    
    # 使用自定义模板或默认模板
    default_template = "根据下面旁白、图片提示词和视频提示词，在不改变故事大意的情况下，加上更多的细节，更合理的逻辑，优化修改润色生成新视频提示词，直接只输出新视频提示词，不要多余的解释：\n视频提示词：{prompt}\n图片提示词：{image_prompt}\n旁白：{narration}"
    template = opt_config.get("video_prompt_template", "") or default_template
    prompt_text = template.replace("{prompt}", old_prompt).replace("{narration}", eng_narration).replace("{image_prompt}", image_prompt)
    
    try:
        resp = req.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant that optimizes video prompts."},
                    {"role": "user", "content": prompt_text}
                ]
            },
            timeout=60
        )
        
        if resp.status_code != 200:
            return jsonify({"success": False, "error": f"API 错误: {resp.status_code}"})
        
        result = resp.json()
        new_prompt = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        
        if not new_prompt:
            return jsonify({"success": False, "error": "优化结果为空"})
        
        return jsonify({
            "success": True,
            "old_prompt": old_prompt,
            "new_prompt": new_prompt,
            "page_index": page_index
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"优化失败: {str(e)}"})


@app.route('/api/optimize/image-prompt', methods=['POST'])
def optimize_image_prompt():
    """使用 AI 优化图片提示词"""
    import requests as req
    
    data = request.get_json()
    page_index = data.get("page_index")
    old_prompt = data.get("image_prompt", "")
    eng_narration = data.get("eng_narration", "")
    video_prompt = data.get("video_prompt", "")  # [NEW] 参考视频提示词
    
    if not old_prompt:
        return jsonify({"success": False, "error": "图片提示词为空"})
    
    # 获取优化 API 配置
    opt_config = config.to_dict().get("optimize_api", {})
    base_url = opt_config.get("base_url", "").rstrip('/')
    api_key = opt_config.get("api_key", "")
    model = opt_config.get("model", "gpt-4.1-mini")
    
    if not base_url or not api_key:
        return jsonify({"success": False, "error": "请先配置优化 API (optimize_api)"})
    
    # 使用自定义模板或默认模板
    default_template = "根据下面旁白、视频提示词和图片提示词，在不改变故事大意的情况下，加上更多的视觉细节、场景描述和艺术风格，优化修改润色生成新图片提示词，直接只输出新图片提示词，不要多余的解释：\n图片提示词：{prompt}\n视频提示词：{video_prompt}\n旁白：{narration}"
    template = opt_config.get("image_prompt_template", "") or default_template
    prompt_text = template.replace("{prompt}", old_prompt).replace("{narration}", eng_narration).replace("{video_prompt}", video_prompt)
    
    try:
        resp = req.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant that optimizes image generation prompts for better visual quality."},
                    {"role": "user", "content": prompt_text}
                ]
            },
            timeout=60
        )
        
        if resp.status_code != 200:
            return jsonify({"success": False, "error": f"API 错误: {resp.status_code}"})
        
        result = resp.json()
        new_prompt = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        
        if not new_prompt:
            return jsonify({"success": False, "error": "优化结果为空"})
        
        return jsonify({
            "success": True,
            "old_prompt": old_prompt,
            "new_prompt": new_prompt,
            "page_index": page_index
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"优化失败: {str(e)}"})

# ===== 页面路由 =====

@app.route('/')
def index():
    """主页"""
    return send_file('index.html')


@app.route('/static/<path:filename>')
def serve_static(filename):
    """提供静态文件"""
    return send_from_directory('static', filename)


@app.route('/output/<path:filename>')
def serve_output(filename):
    """提供生成的图片/视频文件"""
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    return send_from_directory(output_dir, filename)


# ===== 故事数据 API =====

@app.route('/api/story', methods=['GET'])
def get_story():
    """获取故事数据"""
    if story_data is None:
        load_story_data()
    
    if story_data is None:
        return jsonify({"success": False, "error": "无法加载故事数据"})
    
    return jsonify({
        "success": True,
        "data": {
            "title": story_data.get("title", ""),
            "eng_title": story_data.get("eng_title", ""),
            "story_insight": story_data.get("story_insight", ""),
            "character_sheet_prompt": story_data.get("character_sheet_prompt", ""),
            "scene_sheet_prompt": story_data.get("scene_sheet_prompt", ""),
            "cover_image_prompt": story_data.get("cover_image_prompt", ""),
            "script": story_data.get("script", [])
        }
    })


@app.route('/api/story/upload', methods=['POST'])
def upload_story():
    """上传并解析故事 JSON"""
    global story_data
    
    try:
        data = request.get_json()
        raw_json = data.get("json_content", "")
        
        if not raw_json.strip():
            return jsonify({"success": False, "error": "JSON 内容为空"})
        
        # 自动修复常见格式问题
        fixed_json = fix_json_content(raw_json)
        
        # 解析 JSON
        parsed_data = json.loads(fixed_json)
        
        # 验证必要字段
        if "title" not in parsed_data:
            return jsonify({"success": False, "error": "缺少必要字段: title"})
        if "script" not in parsed_data or not isinstance(parsed_data["script"], list):
            return jsonify({"success": False, "error": "缺少必要字段: script (必须是数组)"})
        if len(parsed_data["script"]) == 0:
            return jsonify({"success": False, "error": "script 数组为空"})
        
        # 验证 script 中每个页面的必要字段
        for i, page in enumerate(parsed_data["script"]):
            if "page_index" not in page:
                return jsonify({"success": False, "error": f"第 {i+1} 页缺少 page_index 字段"})
            if "image_prompt" not in page:
                return jsonify({"success": False, "error": f"第 {page.get('page_index', i+1)} 页缺少 image_prompt 字段"})
        
        # 保存数据
        story_data = parsed_data
        
        # 重置生成状态并初始化项目
        reset_generation_status()
        init_project_from_story()
        
        # 保存到项目文件夹内
        save_story_to_project()
        
        return jsonify({
            "success": True,
            "title": story_data.get("title", ""),
            "pages": len(story_data.get("script", [])),
            "project_name": current_project_name,
            "message": f"故事「{story_data.get('title')}」加载成功，共 {len(story_data.get('script', []))} 页"
        })
        
    except json.JSONDecodeError as e:
        return jsonify({
            "success": False,
            "error": f"JSON 解析失败: {str(e)}"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"处理失败: {str(e)}"
        })


def save_story_to_project():
    """将故事数据保存到项目文件夹"""
    if story_data and current_project_dir:
        save_path = os.path.join(current_project_dir, "story.json")
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(story_data, f, ensure_ascii=False, indent=2)
        print(f"📁 故事数据已保存至: {save_path}")


@app.route('/api/projects', methods=['GET'])
def list_projects():
    """列出所有已有项目"""
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    projects = []
    
    if os.path.exists(output_dir):
        for name in os.listdir(output_dir):
            project_path = os.path.join(output_dir, name)
            story_path = os.path.join(project_path, "story.json")
            
            if os.path.isdir(project_path) and os.path.exists(story_path):
                # 读取项目标题
                try:
                    with open(story_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    projects.append({
                        "name": name,
                        "title": data.get("title", name),
                        "pages": len(data.get("script", []))
                    })
                except:
                    projects.append({
                        "name": name,
                        "title": name,
                        "pages": 0
                    })
    
    return jsonify({
        "success": True,
        "projects": projects,
        "current": current_project_name
    })


@app.route('/api/project/switch', methods=['POST'])
def switch_project():
    """切换到指定项目"""
    global story_data
    
    data = request.get_json()
    project_name = data.get("project_name", "")
    
    if not project_name:
        return jsonify({"success": False, "error": "项目名称不能为空"})
    
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    story_path = os.path.join(output_dir, project_name, "story.json")
    
    if not os.path.exists(story_path):
        return jsonify({"success": False, "error": f"项目 {project_name} 不存在"})
    
    try:
        with open(story_path, "r", encoding="utf-8") as f:
            story_data = json.load(f)
        
        reset_generation_status()
        init_project_from_story()
        
        return jsonify({
            "success": True,
            "project_name": current_project_name,
            "title": story_data.get("title", ""),
            "pages": len(story_data.get("script", []))
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/project/delete', methods=['POST'])
def delete_project():
    """删除指定项目"""
    global story_data, current_project_name, current_project_dir, generation_status
    import shutil
    
    data = request.get_json()
    project_name = data.get("project_name", "")
    
    if not project_name:
        return jsonify({"success": False, "error": "项目名称不能为空"})
    
    # 安全检查：只允许删除 output 下的一级目录
    if ".." in project_name or "/" in project_name or "\\" in project_name:
         return jsonify({"success": False, "error": "非法的项目名称"})

    output_dir = os.path.join(os.path.dirname(__file__), "output")
    target_dir = os.path.join(output_dir, project_name)
    
    if not os.path.exists(target_dir):
        return jsonify({"success": False, "error": "项目不存在"})
    
    try:
        # 物理删除文件夹
        shutil.rmtree(target_dir)
        print(f"🗑️ 项目已删除: {target_dir}")
        
        # 如果删除的是当前项目，重置状态
        if current_project_name == project_name:
            story_data = None
            current_project_name = None
            current_project_dir = None
            reset_generation_status()
        
        return jsonify({
            "success": True,
            "message": f"项目 {project_name} 已删除",
            "is_current": (current_project_name is None) # 告诉前端是否重置了
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"删除失败: {str(e)}"})


@app.route('/api/story/update-prompt', methods=['POST'])
def update_prompt():
    """更新单页的提示词"""
    global story_data
    
    if story_data is None:
        return jsonify({"success": False, "error": "故事数据未加载"})
    
    data = request.get_json()
    page_index = data.get("page_index")
    prompt_type = data.get("prompt_type")  # "image_prompt" 或 "video_prompt"
    new_value = data.get("value", "")
    
    if page_index is None or not prompt_type:
        return jsonify({"success": False, "error": "缺少必要参数"})
    
    # 更新 story_data
    for page in story_data.get("script", []):
        if page["page_index"] == page_index:
            page[prompt_type] = new_value
            break
    else:
        return jsonify({"success": False, "error": f"未找到第 {page_index} 页"})
    
    # 保存到文件
    save_story_to_project()
    
    return jsonify({
        "success": True,
        "message": f"第 {page_index} 页 {prompt_type} 已更新"
    })


@app.route('/api/status', methods=['GET'])
def get_status():
    """获取生成状态"""
    # 检查文件是否存在，更新状态
    if os.path.exists(image_gen.get_character_sheet_path()):
        if generation_status["character_sheet"] != "generating":
            generation_status["character_sheet"] = "completed"
    
    if os.path.exists(image_gen.get_scene_sheet_path()):
        if generation_status["scene_sheet"] != "generating":
            generation_status["scene_sheet"] = "completed"
    
    # 检查每页图片
    for idx in generation_status["pages"]:
        img_path = image_gen.get_page_image_path(idx)
        if os.path.exists(img_path):
            if generation_status["pages"][idx]["image"] != "generating":
                generation_status["pages"][idx]["image"] = "completed"
        
        vid_path = video_gen.get_video_path(idx)
        if os.path.exists(vid_path):
            if generation_status["pages"][idx]["video"] != "generating":
                generation_status["pages"][idx]["video"] = "completed"
    
    # 构建带项目目录的路径
    char_path = None
    scene_path = None
    
    if current_project_name and os.path.exists(image_gen.get_character_sheet_path()):
        char_path = f"/output/{current_project_name}/character_sheet.png"
    if current_project_name and os.path.exists(image_gen.get_scene_sheet_path()):
        scene_path = f"/output/{current_project_name}/scene_sheet.png"
    
    return jsonify({
        "success": True,
        "status": generation_status,
        "project_name": current_project_name,
        "paths": {
            "character_sheet": char_path,
            "scene_sheet": scene_path
        }
    })


# ===== 生成 API =====

@app.route('/api/generate/character-sheet', methods=['POST'])
def generate_character_sheet():
    """生成角色设计稿 (参考风格图)"""
    if story_data is None:
        return jsonify({"success": False, "error": "故事数据未加载"})
    
    generation_status["character_sheet"] = "generating"
    
    prompt = story_data.get("character_sheet_prompt", "")
    
    # [NEW] 使用风格图作为参考
    ref_images = []
    if current_style:
        for f in os.listdir(STYLES_DIR):
            if os.path.splitext(f)[0] == current_style:
                style_path = os.path.join(STYLES_DIR, f)
                if os.path.exists(style_path):
                    ref_images.append(style_path)
                break
    
    if ref_images:
        result = image_gen.generate_with_reference(prompt, ref_images, "character_sheet")
    else:
        result = image_gen.generate_text_to_image(prompt, "character_sheet")
    
    if result["success"]:
        generation_status["character_sheet"] = "completed"
        return jsonify({
            "success": True,
            "path": f"/output/{current_project_name}/character_sheet.png",
            "message": "角色设计稿生成成功" + (f" (参考风格: {current_style})" if current_style else "")
        })
    else:
        generation_status["character_sheet"] = "failed"
        return jsonify({
            "success": False,
            "error": result["error"]
        })


@app.route('/api/generate/scene-sheet', methods=['POST'])
def generate_scene_sheet():
    """生成场景设计稿（参考风格图 + 角色设计稿）"""
    if story_data is None:
        return jsonify({"success": False, "error": "故事数据未加载"})
    
    generation_status["scene_sheet"] = "generating"
    
    prompt = story_data.get("scene_sheet_prompt", "")
    
    # [UPDATED] 参考图: 风格图 (优先) + 角色设计稿
    ref_images = []
    
    # 1. 风格图
    if current_style:
        for f in os.listdir(STYLES_DIR):
            if os.path.splitext(f)[0] == current_style:
                style_path = os.path.join(STYLES_DIR, f)
                if os.path.exists(style_path):
                    ref_images.append(style_path)
                break
    
    # 2. 角色设计稿
    char_sheet_path = image_gen.get_character_sheet_path()
    if os.path.exists(char_sheet_path):
        ref_images.append(char_sheet_path)
    
    result = image_gen.generate_with_reference(prompt, ref_images, "scene_sheet")
    
    if result["success"]:
        generation_status["scene_sheet"] = "completed"
        return jsonify({
            "success": True,
            "path": f"/output/{current_project_name}/scene_sheet.png",
            "message": "场景设计稿生成成功" + (f" (参考风格: {current_style})" if current_style else "")
        })
    else:
        generation_status["scene_sheet"] = "failed"
        return jsonify({
            "success": False,
            "error": result["error"]
        })


@app.route('/api/generate/page-image/<int:page_index>', methods=['POST'])
def generate_page_image(page_index):
    """生成分镜图片（参考设计稿）"""
    if story_data is None:
        return jsonify({"success": False, "error": "故事数据未加载"})
    
    # 查找对应页面
    page = None
    for p in story_data.get("script", []):
        if p["page_index"] == page_index:
            page = p
            break
    
    if page is None:
        return jsonify({"success": False, "error": f"页面 {page_index} 不存在"})
    
    # 收集参考图片（优先级：设计稿 > 前面的分镜）
    # 限制总数不超过 10 张
    MAX_REF_IMAGES = 10
    ref_images = []
    
    # 1. 必传：角色设计稿和场景设计稿
    char_sheet = image_gen.get_character_sheet_path()
    scene_sheet = image_gen.get_scene_sheet_path()
    
    if os.path.exists(char_sheet):
        ref_images.append(char_sheet)
    if os.path.exists(scene_sheet):
        ref_images.append(scene_sheet)
    
    if not ref_images:
        return jsonify({
            "success": False,
            "error": "请先生成角色设计稿和场景设计稿"
        })
    
    # 2. 添加前面已生成的分镜图片（倒序添加，优先近的）
    remaining_slots = MAX_REF_IMAGES - len(ref_images)
    if remaining_slots > 0:
        prev_pages = []
        for i in range(page_index - 1, 0, -1):  # 从前一页开始倒序
            prev_img_path = image_gen.get_page_image_path(i)
            if os.path.exists(prev_img_path):
                prev_pages.append(prev_img_path)
                if len(prev_pages) >= remaining_slots:
                    break
        # 按正序添加（让较早的图片在前面）
        ref_images.extend(reversed(prev_pages))
    
    print(f"📚 第 {page_index} 页参考图片: {len(ref_images)} 张")    # 参考图收集完毕
    
    # 获取生成配置
    batch_size = config.get("generation", "batch_size") or 1
    
    # 标记状态
    if page_index not in generation_status["pages"]:
         generation_status["pages"][page_index] = {"image": None, "video": None, "selected": False}
    generation_status["pages"][page_index]["image"] = "generating"
    
    try:
        last_result = None
        success_count = 0
        
        success_count = 0
        
        # [NEW] 重新生成前清理旧文件 (强制刷新)
        old_images = glob.glob(f"output/{current_project_name}/images/page_{page_index:03d}*.png")
        if old_images:
            print(f"🧹 清理旧文件: {len(old_images)} 个")
            for f in old_images:
                try:
                    os.remove(f)
                except Exception as e:
                    print(f"⚠️ 删除旧文件失败 {f}: {e}")
        
        # 循环生成
        for i in range(batch_size):
            # 第一张图使用标准文件名 page_001
            # 后续图片使用变体文件名 page_001_var1, page_001_var2
            suffix = "" if i == 0 else f"_var{i}"
            filename = f"page_{page_index:03d}{suffix}"
            
            print(f"🔄 正在生成第 {page_index} 页 ({i+1}/{batch_size})... -> {filename}")
            
            result = image_gen.generate_with_reference(page["image_prompt"], ref_images, filename)
            
            if result["success"]:
                success_count += 1
                last_result = result
            else:
                print(f"❌ 生成失败 ({i+1}/{batch_size}): {result.get('error')}")
        
        if success_count > 0:
            generation_status["pages"][page_index]["image"] = "completed"
            return jsonify({
                "success": True,
                "path": f"/output/{current_project_name}/images/page_{page_index:03d}.png",
                "message": f"第 {page_index} 页生成成功 (共 {success_count} 张)"
            })
        else:
            generation_status["pages"][page_index]["image"] = "failed"
            error_msg = last_result["error"] if last_result else "未知错误"
            return jsonify({
                "success": False,
                "error": error_msg
            })
    except Exception as e:
        print(f"⚠️ 生成页面图片异常: {e}")
        generation_status["pages"][page_index]["image"] = "failed"
        return jsonify({
            "success": False,
            "error": f"服务器内部错误: {str(e)}"
        })


@app.route('/api/generate/page-video/<int:page_index>', methods=['POST'])
def generate_page_video(page_index):
    """生成分镜视频"""
    global active_video_tasks
    active_video_tasks += 1
    print(f"🎬 [Start] Video Task for Page {page_index} | Active Tasks: {active_video_tasks}")
    
    if story_data is None:
        active_video_tasks -= 1
        return jsonify({"success": False, "error": "故事数据未加载"})
    
    page = next((p for p in story_data["script"] if p["page_index"] == page_index), None)
    if not page:
        active_video_tasks -= 1
        return jsonify({"success": False, "error": "页码不存在"})
    
    # 状态更新
    generation_status["pages"][page_index]["video"] = "generating"
    
    try:
        # [NEW] 重新生成前清理旧视频
        video_path = f"output/{current_project_name}/videos/page_{page_index:03d}.mp4"
        if os.path.exists(video_path):
             try:
                os.remove(video_path)
             except Exception:
                pass

        # 生成视频
        prompt = page.get("video_prompt", "")
        result = video_gen.generate_video(
            prompt=prompt,
            reference_image=f"output/{current_project_name}/images/page_{page_index:03d}.png",
            filename=f"page_{page_index:03d}",
            force_regenerate=True
        )
        
        if result["success"]:
            generation_status["pages"][page_index]["video"] = "completed"
            active_video_tasks -= 1
            print(f"✅ [End] Video Task for Page {page_index} | Active Tasks: {active_video_tasks}")
            return jsonify({
                "success": True, 
                "video_path": f"/output/{current_project_name}/videos/page_{page_index:03d}.mp4",
                "message": "视频生成成功"
            })
        else:
            generation_status["pages"][page_index]["video"] = "failed"
            active_video_tasks -= 1
            print(f"❌ [Fail] Video Task for Page {page_index} | Active Tasks: {active_video_tasks}")
            return jsonify({"success": False, "error": result["error"]})

    except Exception as e:
        print(f"视频生成异常: {e}")
        generation_status["pages"][page_index]["video"] = "failed"
        active_video_tasks -= 1
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/generate/page-audio/<int:page_index>', methods=['POST'])
def generate_page_audio(page_index):
    """生成分镜音频"""
    global active_audio_tasks
    active_audio_tasks += 1
    
    # 获取语言参数
    lang = request.args.get('lang', 'cn') # 'cn' or 'en'
    
    print(f"🔊 [Start] Audio Task for Page {page_index} ({lang}) | Active Tasks: {active_audio_tasks}")

    if story_data is None:
        active_audio_tasks -= 1
        return jsonify({"success": False, "error": "故事数据未加载"})
    
    page = next((p for p in story_data["script"] if p["page_index"] == page_index), None)
    if not page:
        active_audio_tasks -= 1
        return jsonify({"success": False, "error": "页码不存在"})
        
    # 状态更新 (字典结构)
    if generation_status["pages"][page_index]["audio"] is None:
         generation_status["pages"][page_index]["audio"] = {"cn": None, "en": None}
    
    # 兼容旧状态如果是字符串的情况 (虽然 init 做了处理，以防万一)
    if isinstance(generation_status["pages"][page_index]["audio"], str):
         generation_status["pages"][page_index]["audio"] = {"cn": None, "en": None}
         
    generation_status["pages"][page_index]["audio"][lang] = "generating"
    
    try:
        # [FIX] 强制同步最新的 Audio 配置 (确保手动修改 config.json 生效)
        current_api_url = config.get("audio_api", "base_url")
        current_ref_audio = config.get("audio_api", "reference_audio")
        
        # 如果配置有变，或者为了保险起见，更新 audio_gen
        if current_api_url != audio_gen.api_url or current_ref_audio != audio_gen.default_ref_audio:
            print(f"🔄 Syncing Audio Config: {current_api_url}")
            audio_gen.update_config(current_api_url, current_ref_audio)

        # 确定文件名和文本键
        filename_suffix = "en" if lang == "en" else "cn"
        text_key = "eng_narration" if lang == "en" else "narration"
        
        audio_path = f"output/{current_project_name}/audio/page_{page_index:03d}_{filename_suffix}.wav"
        
        # 清理旧音频
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except:
                pass
                
        # 朗读文本
        text = page.get(text_key, "")
        if not text:
             active_audio_tasks -= 1
             return jsonify({"success": False, "error": f"{lang} 旁白为空"})

        # 生成
        result = audio_gen.generate_audio(
            text=text,
            output_path=audio_path,
            ref_audio_path=config.get("audio_api", "reference_audio"),
            lang=lang
        )
        
        if result["success"]:
            generation_status["pages"][page_index]["audio"][lang] = "completed"
            active_audio_tasks -= 1
            print(f"✅ [End] Audio Task for Page {page_index} ({lang}) | Active Tasks: {active_audio_tasks}")
            return jsonify({
                "success": True,
                "audio_path": f"/output/{current_project_name}/audio/page_{page_index:03d}_{filename_suffix}.wav",
                "message": f"{lang.upper()} 音频生成成功"
            })
        else:
            generation_status["pages"][page_index]["audio"][lang] = "failed"
            active_audio_tasks -= 1
            print(f"❌ [Fail] Audio Task for Page {page_index} ({lang}) | Active Tasks: {active_audio_tasks}")
            return jsonify({"success": False, "error": result["error"]})
            
    except Exception as e:
        print(f"音频生成异常: {e}")
        if isinstance(generation_status["pages"][page_index]["audio"], dict):
            generation_status["pages"][page_index]["audio"][lang] = "failed"
        active_audio_tasks -= 1
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/generate/project-srt', methods=['POST'])
def generate_project_srt():
    """生成项目 SRT"""
    if story_data is None:
        return jsonify({"success": False, "error": "故事数据未加载"})
        
    generation_status["srt"] = "generating"
    
    try:
        audio_dir = f"output/{current_project_name}/audio"
        
        # 1. 生成中文 SRT
        srt_cn_path = f"output/{current_project_name}/{current_project_name}_cn.srt"
        res_cn = audio_gen.generate_project_srt(
            pages=story_data["script"],
            audio_dir=audio_dir,
            output_srt_path=srt_cn_path,
            lang="cn"
        )
        
        # 2. 生成英文 SRT
        srt_en_path = f"output/{current_project_name}/{current_project_name}_en.srt"
        res_en = audio_gen.generate_project_srt(
            pages=story_data["script"],
            audio_dir=audio_dir,
            output_srt_path=srt_en_path,
            lang="en"
        )
        
        if res_cn["success"] and res_en["success"]:
            generation_status["srt"] = "completed"
            return jsonify({
                "success": True,
                "message": "双语 SRT 字幕生成成功"
            })
        elif res_cn["success"]:
             generation_status["srt"] = "completed"
             return jsonify({"success": True, "message": "中文 SRT 生成成功, 英文失败: " + res_en.get("error", "")})
        elif res_en["success"]:
             generation_status["srt"] = "completed"
             return jsonify({"success": True, "message": "英文 SRT 生成成功, 中文失败: " + res_cn.get("error", "")})
        else:
            generation_status["srt"] = "failed"
            return jsonify({"success": False, "error": "SRT 生成失败"})
            
    except Exception as e:
        generation_status["srt"] = "failed"
        return jsonify({"success": False, "error": str(e)})
def toggle_select(page_index):
    """切换页面选中状态"""
    if page_index not in generation_status["pages"]:
        generation_status["pages"][page_index] = {"image": None, "video": None, "selected": False}
    
    current = generation_status["pages"][page_index]["selected"]
    generation_status["pages"][page_index]["selected"] = not current
    
    return jsonify({
        "success": True,
        "selected": not current
    })


@app.route('/api/generate/all-images', methods=['POST'])
def generate_all_images():
    """批量生成所有分镜图片"""
    if story_data is None:
        return jsonify({"success": False, "error": "故事数据未加载"})
    
    # 检查设计稿
    if not os.path.exists(image_gen.get_character_sheet_path()):
        return jsonify({"success": False, "error": "请先生成角色设计稿"})
    
    results = []
    for page in story_data.get("script", []):
        idx = page["page_index"]
        results.append({
            "page_index": idx,
            "status": generation_status["pages"].get(idx, {}).get("image")
        })
    
    return jsonify({
        "success": True,
        "pages": results,
        "message": "请逐个点击生成，或使用批量生成功能"
    })


if __name__ == '__main__':
    print("=" * 50)
    print("儿童故事图片视频生成工具")
    print("=" * 50)
    print(f"故事标题: {story_data.get('title', '未加载') if story_data else '未加载'}")
    print(f"总页数: {len(story_data.get('script', [])) if story_data else 0}")
    print("=" * 50)
    print(f"图片 API: {config.get('image_api', 'base_url')}")
    print(f"视频 API: {config.get('video_api', 'base_url')}")
    print("=" * 50)
    print("启动服务器: http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
