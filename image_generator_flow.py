"""
图片生成模块 (Flow2API)
基于用户提供的 requests 流式调用逻辑
"""

import os
import re
import io
import json
import base64
import requests
from PIL import Image

class ImageGeneratorFlow:
    """图片生成器 (Flow2API 版本)"""
    
    def __init__(self, api_key: str = "", base_url: str = "", 
                 model: str = "gemini-3.0-pro-image-landscape"):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.max_retries = 3
        self._output_dir = os.path.join(os.path.dirname(__file__), "output")
        
        # 确保 output/images 存在
        os.makedirs(os.path.join(self._output_dir, "images"), exist_ok=True)

    def update_config(self, api_key: str, base_url: str, model: str = None):
        """更新配置"""
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        if model:
            self.model = model

    @property
    def output_dir(self):
        return self._output_dir
    
    @output_dir.setter
    def output_dir(self, value):
        self._output_dir = value
        os.makedirs(os.path.join(value, "images"), exist_ok=True)

    def _encode_image(self, image_path: str) -> str | None:
        """本地图片 -> Base64 (兼容 jpg/png)"""
        if not os.path.exists(image_path):
            print(f"❌ [Flow] 找不到图片: {image_path}")
            return None
            
        try:
            # 简单压缩以防过大 (保持原逻辑，这里复用 V2 的 PIL 逻辑稍微处理一下，或者直接读取)
            # 用户示例直接 read，我们这里做个简单的 RGB 转换防止 RGBA 报错，并限制大小
            with Image.open(image_path) as img:
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                    
                # 限制最大边长 1024 (可选，根据实际需求)
                if max(img.size) > 1024:
                    img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                buf.seek(0)
                return base64.b64encode(buf.read()).decode("utf-8")
        except Exception as e:
            print(f"❌ [Flow] 图片处理失败: {e}")
            return None

    def generate_text_to_image(self, prompt: str, filename: str) -> dict:
        return self.generate_with_reference(prompt, [], filename)

    def generate_with_reference(self, prompt: str, ref_images: list, filename: str) -> dict:
        """
        核心生成逻辑 (Flow 模式)
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                print(f"🔄 [Flow] 重试 {attempt}/{self.max_retries}...")
            
            result = self._do_generate(prompt, ref_images, filename)
            
            if result["success"]:
                return result
            
            last_error = result.get("error", "Unknown error")
            print(f"⚠️ [Flow] 第 {attempt + 1} 次尝试失败: {last_error}")
        
        return {"success": False, "error": f"重试 {self.max_retries} 次后仍失败: {last_error}"}

    def _do_generate(self, prompt: str, ref_images: list, filename: str) -> dict:
        """
        基于 requests + stream=True 实现 Manual Parsing
        """
        # 构造 URL
        # 确保 base_url 包含 /v1
        base = self.base_url
        if not base.endswith('/v1'):
            base += '/v1'
        url = f"{base}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # 构造多 image_url 内容
        content_list = []
        content_list.append({"type": "text", "text": prompt})

        valid_refs = 0
        for p in ref_images:
            b64 = self._encode_image(p)
            if b64:
                content_list.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}"
                    }
                })
                valid_refs += 1
        
        print(f"🚀 [Flow] 发送生成请求... (Ref: {valid_refs}) Prompt长度: {len(prompt)}")

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": content_list
                }
            ],
            "stream": True
        }

        image_url = None
        
        try:
            with requests.post(url, headers=headers, json=payload, stream=True, timeout=120) as resp:
                if resp.status_code != 200:
                    return {"success": False, "error": f"API 状态码 {resp.status_code}: {resp.text[:200]}"}

                print("⏳ [Flow] 接收流式响应...", end="", flush=True)
                
                for raw_line in resp.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    
                    if raw_line.startswith("data:"):
                        raw_line = raw_line[5:].strip()
                    
                    if raw_line == "[DONE]":
                        break
                    
                    try:
                        chunk = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    
                    if content:
                        # 简单的进度反馈
                        print(".", end="", flush=True)
                        
                        # 提取 Markdown 图片 URL: ![...](http...)
                        match = re.search(r"!\[.*?\]\((https?://[^\s)]+)\)", content)
                        if match:
                            image_url = match.group(1)
                            # 找到 URL 后是否可以 break？
                            # 通常是一次返回完整 Markdown 链接，但也可能分片
                            # 安全起见，继续读完或直到找到完整 URL
                            break
                            
            print(" 完成")

            if not image_url:
                return {"success": False, "error": "响应中未解析到图片 URL"}
            
            # 下载生成图片
            print(f"⬇️ [Flow] 下载图片: {image_url[:60]}...")
            img_resp = requests.get(image_url, timeout=60)
            if img_resp.status_code == 200:
                # 确定保存路径
                if "images" in filename or filename.startswith("page_"):
                    save_path = os.path.join(self.output_dir, "images", f"{filename}.png")
                else:
                    save_path = os.path.join(self.output_dir, f"{filename}.png")
                
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(img_resp.content)
                
                print(f"✅ [Flow] 图片已保存: {save_path}")
                return {
                    "success": True, 
                    "path": save_path, 
                    "url": image_url, 
                    "error": None
                }
            else:
                return {"success": False, "error": f"下载图片失败: {img_resp.status_code}"}

        except Exception as e:
            print(f"\n❌ [Flow] 请求异常: {e}")
            return {"success": False, "error": str(e)}

    # 兼容性方法
    def get_character_sheet_path(self) -> str:
        return os.path.join(self.output_dir, "character_sheet.png")
    
    def get_scene_sheet_path(self) -> str:
        return os.path.join(self.output_dir, "scene_sheet.png")
    
    def get_page_image_path(self, page_index: int) -> str:
        return os.path.join(self.output_dir, "images", f"page_{page_index:03d}.png")
