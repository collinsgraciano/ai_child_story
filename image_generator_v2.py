"""
图片生成模块 V2（流式响应版）
- 文生图（Text → Image）
- 图生图 / 多参考图（Image → Image）
- 使用 OpenAI 兼容 API
- chat.completions + 流式响应
"""

import os
import re
import io
import base64
import requests
from PIL import Image
from openai import OpenAI


class ImageGeneratorV2:
    """图片生成器 V2 - 流式响应版本"""
    
    def __init__(self, api_key: str = "", base_url: str = "", 
                 model: str = "g3-img-pro", image_size: str = ""):
        """
        初始化图片生成器
        
        Args:
            api_key: API 密钥
            base_url: API 基础地址
            model: 模型名称
            image_size: 图片尺寸 (如 "1024x1024", "4096x4096")
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.image_size = image_size
        self.max_retries = 3
        self._output_dir = os.path.join(os.path.dirname(__file__), "output")
        self.client = None
        self._init_client()
        
        # 确保输出目录存在
        os.makedirs(os.path.join(self._output_dir, "images"), exist_ok=True)
    
    def _init_client(self):
        """初始化 OpenAI 客户端"""
        if self.api_key and self.base_url:
            # 确保 base_url 包含 /v1
            base = self.base_url
            if not base.endswith('/v1'):
                base += '/v1'
            self.client = OpenAI(api_key=self.api_key, base_url=base)
    
    def update_config(self, api_key: str, base_url: str, model: str = None, image_size: str = None):
        """更新配置"""
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        if model:
            self.model = model
        if image_size is not None:
            self.image_size = image_size
        self._init_client()
    
    @property
    def output_dir(self):
        """获取输出目录"""
        return self._output_dir
    
    @output_dir.setter
    def output_dir(self, value):
        """设置输出目录并确保目录存在"""
        self._output_dir = value
        os.makedirs(os.path.join(value, "images"), exist_ok=True)
    
    def _encode_image(self, image_path: str, max_size: int = 1024) -> str | None:
        """本地图片 → Base64（自动缩放 / 压缩）"""
        if not os.path.exists(image_path):
            print(f"❌ 找不到图片: {image_path}")
            return None

        try:
            with Image.open(image_path) as img:
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")

                if max(img.size) > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                buf.seek(0)

                return base64.b64encode(buf.read()).decode("utf-8")

        except Exception as e:
            print(f"❌ 图片处理失败: {e}")
            return None

    def _extract_image_from_content(self, content: str):
        """
        从模型返回文本中提取图片
        返回:
            ("base64", data, format) | ("url", url, None) | (None, None, None)
        """
        # Base64
        base64_pattern = r'data:image/([^;]+);base64,([A-Za-z0-9+/=]+)'
        m = re.search(base64_pattern, content)
        if m:
            return "base64", m.group(2), m.group(1)

        # URL
        urls = re.findall(r'(https?://[^\s\)\]\"]+)', content)
        for url in urls:
            if any(ext in url.lower() for ext in (".png", ".jpg", ".jpeg", ".webp")):
                return "url", url, None

        return None, None, None

    def _save_base64_image(self, base64_data: str, save_path: str) -> bool:
        """保存 Base64 图片"""
        try:
            img_bytes = base64.b64decode(base64_data)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(img_bytes)
            print(f"✅ 已保存图片: {save_path} ({len(img_bytes)/1024:.1f}KB)")
            return True
        except Exception as e:
            print(f"❌ Base64 保存失败: {e}")
            return False

    def _download_image(self, url: str, save_path: str) -> bool:
        """下载图片"""
        try:
            print(f"⬇️ 下载图片: {url[:80]}...")
            r = requests.get(url, timeout=120)
            if r.status_code == 200:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(r.content)
                print(f"✅ 已保存图片: {save_path}")
                return True
            print(f"❌ 下载失败，状态码: {r.status_code}")
            return False
        except Exception as e:
            print(f"❌ 下载异常: {e}")
            return False

    def generate_text_to_image(self, prompt: str, filename: str) -> dict:
        """文生图包装器"""
        return self.generate_with_reference(prompt, [], filename)

    def generate_with_reference(self, prompt: str, ref_images: list, filename: str) -> dict:
        """
        核心生成方法：支持重试
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                print(f"🔄 重试 {attempt}/{self.max_retries}...")
            
            result = self._do_generate(prompt, ref_images, filename)
            
            if result["success"]:
                return result
            
            last_error = result.get("error", "Unknown error")
            print(f"⚠️ 第 {attempt + 1} 次尝试失败: {last_error}")
        
        return {"success": False, "error": f"重试 {self.max_retries} 次后仍失败: {last_error}"}

    def _do_generate(self, prompt: str, ref_images: list, filename: str) -> dict:
        """实际执行生成的内部方法 - 流式响应"""
        if not self.client:
            return {"success": False, "error": "API 客户端未初始化，请检查配置"}
        
        # 构造消息内容
        content = [{"type": "text", "text": prompt}]
        
        # 添加参考图片
        valid_refs = 0
        for img_path in ref_images:
            b64 = self._encode_image(img_path)
            if b64:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}"
                    }
                })
                valid_refs += 1
        
        print(f"🚀 [V2] 发送生成请求... (Ref: {valid_refs}) Prompt长度: {len(prompt)}")
        
        # 构造请求参数
        params = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": content
            }],
            "stream": True,
            "timeout": 180,
        }
        
        # 添加图片尺寸参数
        if self.image_size:
            params["extra_body"] = {"size": self.image_size}
        
        try:
            stream = self.client.chat.completions.create(**params)
            
            full_content = ""
            print("⏳ 生成中...", end="", flush=True)
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    print(".", end="", flush=True)
                    full_content += chunk.choices[0].delta.content
            print(" 完成")
            
            # 确定保存路径
            if "images" in filename or filename.startswith("page_"):
                save_path = os.path.join(self.output_dir, "images", f"{filename}.png")
            else:
                save_path = os.path.join(self.output_dir, f"{filename}.png")
            
            # 提取图片
            result_type, data, _ = self._extract_image_from_content(full_content)
            
            if result_type == "base64":
                success = self._save_base64_image(data, save_path)
                return {
                    "success": success,
                    "path": save_path if success else None,
                    "url": None,
                    "error": None if success else "保存失败"
                }
            elif result_type == "url":
                success = self._download_image(data, save_path)
                return {
                    "success": success,
                    "path": save_path if success else None,
                    "url": data,
                    "error": None if success else "下载失败"
                }
            else:
                return {
                    "success": False,
                    "path": None,
                    "url": None,
                    "error": f"未找到生成图片: {full_content[:100]}"
                }
                
        except Exception as e:
            print(f"\n❌ 请求异常: {e}")
            return {"success": False, "error": str(e)}

    # 兼容性方法
    def get_character_sheet_path(self) -> str:
        return os.path.join(self.output_dir, "character_sheet.png")
    
    def get_scene_sheet_path(self) -> str:
        return os.path.join(self.output_dir, "scene_sheet.png")
    
    def get_page_image_path(self, page_index: int) -> str:
        return os.path.join(self.output_dir, "images", f"page_{page_index:03d}.png")


# 测试代码
if __name__ == "__main__":
    gen = ImageGeneratorV2(
        api_key="sk-5ab3f263562e466baa7001ff2a90d659",
        base_url="http://127.0.0.1:8045/v1",
        model="gemini-3-pro-image-9-16",
        image_size="4096x4096"
    )
    
    # 文生图
    result = gen.generate_text_to_image(
        "A cute cartoon mouse wearing blue pajamas, simple style",
        "test_v2"
    )
    print("文生图结果:", result)
