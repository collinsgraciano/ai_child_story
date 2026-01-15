"""
图片生成模块
封装 OpenAI 兼容 API 调用，支持文生图和多图参考生成
完全重构：使用 requests 直接调用，移除 openai 库依赖
"""

import os
import re
import base64
import requests
import json

class ImageGenerator:
    """图片生成器类"""
    
    def __init__(self, api_key: str = "", base_url: str = ""):
        """
        初始化图片生成器
        
        Args:
            api_key: API 密钥
            base_url: API 基础地址 (例如: http://domain.com/v1)
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = "gemini-3-pro-preview-image"
        # self.image_size 已移除，不再使用
        self._output_dir = os.path.join(os.path.dirname(__file__), "output")
        
        # 确保输出目录存在
        os.makedirs(os.path.join(self._output_dir, "images"), exist_ok=True)
    
    @property
    def output_dir(self):
        """获取输出目录"""
        return self._output_dir
    
    @output_dir.setter
    def output_dir(self, value):
        """设置输出目录并确保目录存在"""
        self._output_dir = value
        os.makedirs(os.path.join(value, "images"), exist_ok=True)
    
    def _encode_image(self, image_path: str) -> str:
        """
        读取图片并转为 Base64 字符串
        """
        if not os.path.exists(image_path):
            print(f"❌ 警告: 找不到文件 {image_path}")
            return None
        
        try:
            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            print(f"❌ 读取图片失败 {image_path}: {e}")
            return None

    def _save_base64_image(self, base64_data: str, save_path: str) -> bool:
        """保存 Base64 图片"""
        try:
            # 清理
            base64_data = base64_data.strip().replace('\n', '')
            img_bytes = base64.b64decode(base64_data)
            with open(save_path, "wb") as f:
                f.write(img_bytes)
            print(f"✅ 图片已保存: {save_path} ({len(img_bytes)/1024:.1f}KB)")
            return True
        except Exception as e:
            print(f"❌ 保存图片出错: {e}")
            return False

    def _save_url_image(self, url: str, save_path: str) -> bool:
        """下载并保存 URL 图片"""
        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code == 200:
                with open(save_path, "wb") as f:
                    f.write(resp.content)
                print(f"✅ 图片已下载: {save_path}")
                return True
            return False
        except Exception as e:
            print(f"❌ 下载图片出错: {e}")
            return False
            
    def generate_text_to_image(self, prompt: str, filename: str) -> dict:
        """文生图包装器"""
        return self.generate_with_reference(prompt, [], filename)

    def generate_with_reference(self, prompt: str, ref_images: list, filename: str) -> dict:
        """
        核心生成方法：使用 requests 发送请求
        """
        # 构造 URL
        # 确保 base_url 包含 /v1
        base = self.base_url.rstrip('/')
        if not base.endswith('/v1'):
            base += '/v1'
        
        url = f"{base}/chat/completions"
        
        # 构造消息内容
        content_list = []
        
        # 1. 添加文本 Prompt
        content_list.append({
            "type": "text",
            "text": prompt
        })
        
        # 2. 添加参考图片 (如果有)
        valid_refs = 0
        if ref_images:
            for img_path in ref_images:
                b64_str = self._encode_image(img_path)
                if b64_str:
                    content_list.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_str}"
                        }
                    })
                    valid_refs += 1

        print(f"🚀 发送生成请求... (Ref: {valid_refs}) Prompt长度: {len(prompt)}")

        # 构造 Payload
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": content_list
                }
            ],
            "stream": False # 暂时关闭流式以简化解析，用户示例也不是流式
        }

        # 构造 Headers
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=120)
            
            # 检查状态码
            if response.status_code != 200:
                print(f"❌ API 错误: {response.status_code} - {response.text}")
                return {
                    "success": False, 
                    "error": f"API Error {response.status_code}: {response.text[:200]}"
                }
            
            # 解析响应
            result = response.json()
            # print(f"API 响应: {result}") # 调试用

            choices = result.get('choices', [])
            if not choices:
                return {"success": False, "error": "No choices in response"}
            
            content = choices[0]['message']['content']
            
            # 提取图片
            # 格式通常是: ![image](data:image/png;base64,...)
            # 或者直接是 URL
            
            # 1. 尝试匹配 Base64 Markdown
            b64_match = re.search(r'\(data:image/[^;]+;base64,([^\)]+)\)', content)
            
            # 确定保存路径
            if "images" in filename or filename.startswith("page_"):
                save_path = os.path.join(self.output_dir, "images", f"{filename}.png")
            else:
                save_path = os.path.join(self.output_dir, f"{filename}.png")

            if b64_match:
                base64_data = b64_match.group(1)
                if self._save_base64_image(base64_data, save_path):
                    return {"success": True, "path": save_path, "url": None, "error": None}
            
            # 2. 尝试匹配 URL Markdown ![image](http...)
            url_match = re.search(r'\((https?://[^\)]+)\)', content)
            if url_match:
                img_url = url_match.group(1)
                if self._save_url_image(img_url, save_path):
                    return {"success": True, "path": save_path, "url": img_url, "error": None}
            
            # 3. 都没有
            print(f"⚠️ 未能从响应中提取图片: {content[:100]}...")
            return {"success": False, "error": "No image found in response"}

        except Exception as e:
            print(f"❌ 请求异常: {e}")
            return {"success": False, "error": str(e)}

    # 兼容性方法 (供 app.py 调用)
    def get_character_sheet_path(self) -> str:
        return os.path.join(self.output_dir, "character_sheet.png")
    
    def get_scene_sheet_path(self) -> str:
        return os.path.join(self.output_dir, "scene_sheet.png")
    
    def get_page_image_path(self, page_index: int) -> str:
        return os.path.join(self.output_dir, "images", f"page_{page_index:03d}.png")

# 测试代码
if __name__ == "__main__":
    gen = ImageGenerator(
        api_key="ghk_89222a8da6c6e4bfcd8a67571e7db0eb",
        base_url="https://business2api.openel.top"
    )
    res = gen.generate_text_to_image("A test image of a cat", "test_cat")
    print(res)
