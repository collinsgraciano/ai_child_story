# 🎨 儿童故事图片视频生成工具

一个基于 Flask 的 Web 应用，用于将儿童故事 JSON 数据自动转换为图片、视频和配音。

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## ✨ 功能特性

### 🖼️ 图片生成
- **角色设计稿** - 基于提示词生成统一风格的角色设计图
- **场景设计稿** - 参考角色设计稿生成场景图
- **分镜图片** - 参考设计稿和前序分镜，保持风格一致性
- **批量生成** - 支持可配置并发数的批量处理

### 🎬 视频生成
- **图转视频** - 基于分镜图片和视频提示词生成动态视频
- **批量生成** - 智能跳过已完成任务
- **并发控制** - 可配置的视频生成并发数

### 🔊 配音生成 (TTS)
- **双语支持** - 中文和英文配音分别生成
- **自动数字转换** - 中文配音自动将阿拉伯数字转为中文读法
- **批量生成** - 智能跳过已完成的配音任务
- **SRT 字幕** - 自动生成双语 SRT 字幕文件

### ⚙️ 配置管理
- **实时配置** - 通过 Web 界面修改 API 配置，无需重启
- **多 API 支持** - 图片、视频、音频 API 独立配置
- **持久化存储** - 配置自动保存到 `config.json`

## 🚀 快速开始

### 安装依赖

```bash
pip install flask requests openai gradio_client
```

### 准备故事数据

创建 `child_story_fixed.json` 文件，格式如下：

```json
{
  "title": "故事标题",
  "character_sheet_prompt": "角色设计稿提示词...",
  "scene_sheet_prompt": "场景设计稿提示词...",
  "script": [
    {
      "page_index": 1,
      "image_prompt": "分镜图片提示词...",
      "video_prompt": "视频动作提示词...",
      "narration": "中文旁白...",
      "eng_narration": "English narration..."
    }
  ]
}
```

### 启动服务

```bash
python app.py
```

访问 `http://localhost:5000` 打开 Web 界面。

## 📁 项目结构

```
child_story/
├── app.py                 # Flask 主应用
├── config_manager.py      # 配置管理模块
├── image_generator.py     # 图片生成模块
├── video_generator.py     # 视频生成模块
├── audio_generator.py     # 音频/TTS 生成模块
├── config.json            # 运行时配置 (自动生成)
├── static/
│   ├── app.js             # 前端逻辑
│   └── style.css          # 样式
├── templates/
│   └── index.html         # 主页面
└── output/                # 生成的文件输出目录
    └── [项目名]/
        ├── images/        # 分镜图片
        ├── videos/        # 分镜视频
        ├── audio/         # 配音文件
        ├── character_sheet.png
        ├── scene_sheet.png
        └── *.srt          # 字幕文件
```

## 🔧 API 配置

在 Web 界面点击右上角 ⚙️ 按钮打开设置面板：

| 配置项 | 说明 |
|--------|------|
| **图片 API** | OpenAI 兼容的图片生成 API |
| **视频 API** | Sora 风格的视频生成 API |
| **音频 API** | Gradio TTS API 地址 |
| **参考音频** | TTS 参考音色文件路径 |
| **批量数量** | 每次生成的变体数量 |
| **并发数** | 批量任务的并发数 |

## 📝 使用流程

1. **加载故事** - 粘贴 JSON 或选择已有项目
2. **生成设计稿** - 先生成角色设计稿，再生成场景设计稿
3. **生成分镜** - 逐页或批量生成分镜图片
4. **生成视频** - 基于图片生成动态视频
5. **生成配音** - 生成中英文配音
6. **导出字幕** - 生成 SRT 字幕文件

## 🛠️ 技术栈

- **后端**: Python, Flask, OpenAI SDK, Gradio Client
- **前端**: Vanilla JavaScript, CSS3
- **API 兼容**: OpenAI Chat Completions (图片), 自定义视频 API, Gradio TTS

## 📄 License

MIT License
