"""
视频生成模块
封装 Sora2 API 调用，支持基于图片生成视频
使用流式响应和重试机制
"""

import os
import re
import time
import base64
import requests
from pathlib import Path
from openai import OpenAI


class VideoGenerator:
    """视频生成器类"""
    
    def __init__(self, api_key: str = "sk-dummy", base_url: str = "http://127.0.0.1:8003/v1", 
                 model_name: str = "sora"):
        """
        初始化视频生成器
        
        Args:
            api_key: API 密钥
            base_url: Sora2 API 基础地址
            model_name: 模型名称
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self._output_dir = os.path.join(os.path.dirname(__file__), "output", "videos")
        
        # 确保输出目录存在
        os.makedirs(self._output_dir, exist_ok=True)
    
    @property
    def output_dir(self):
        """获取输出目录"""
        return self._output_dir
    
    @output_dir.setter
    def output_dir(self, value):
        """设置输出目录并确保目录存在"""
        self._output_dir = value
        os.makedirs(value, exist_ok=True)
    
    def update_config(self, api_key: str, base_url: str, model_name: str):
        """更新 API 配置"""
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.client = OpenAI(api_key=api_key, base_url=base_url)
    
    def _encode_image(self, image_path: str) -> str:
        """将图片编码为 base64"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    
    def generate_video(self, prompt: str, reference_image: str, filename: str,
                       force_regenerate: bool = False) -> dict:
        """
        生成视频
        
        Args:
            prompt: 视频生成提示词
            reference_image: 参考图片路径
            filename: 保存的文件名（不含扩展名）
            force_regenerate: 是否强制重新生成
            
        Returns:
            dict: {"success": bool, "path": str, "url": str, "error": str, "status": str}
        """
        output_folder = Path(self.output_dir)
        output_folder.mkdir(parents=True, exist_ok=True)
        
        save_path = output_folder / f"{filename}.mp4"
        
        # 检查是否已存在
        if save_path.exists() and not force_regenerate:
            return {
                "success": True,
                "path": str(save_path),
                "url": None,
                "error": None,
                "status": "exists"
            }
        
        max_retries = 10
        
        for attempt in range(max_retries + 1):
            try:
                # 编码参考图片
                if reference_image and os.path.exists(reference_image):
                    image_data_url = f"data:image/png;base64,{self._encode_image(reference_image)}"
                else:
                    return {
                        "success": False,
                        "path": None,
                        "url": None,
                        "error": "参考图片不存在",
                        "status": "failed"
                    }
                
                # 调用 API（流式响应）
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": image_data_url}},
                            ],
                        }
                    ],
                    stream=True
                )
                
                full_content = ""
                
                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_content += content
                
                # 提取视频 URL
                match = re.search(r"<video src='([^']+)'", full_content) or \
                        re.search(r'https://[^\s"]+\.mp4', full_content)
                
                if not match:
                    if not full_content:
                        raise Exception("Empty response from API")
                    
                    # 检查是否触发风控
                    if any(x in full_content for x in [
                        "content policies", "violate our guardrails", "similarity to third-party"
                    ]):
                        if attempt < max_retries:
                            time.sleep(5)
                            continue
                        else:
                            return {
                                "success": False,
                                "path": None,
                                "url": None,
                                "error": "触发内容风控，重试次数耗尽",
                                "status": "blocked"
                            }
                    
                    return {
                        "success": False,
                        "path": None,
                        "url": None,
                        "error": f"API 未返回视频 URL: {full_content[:100]}",
                        "status": "failed"
                    }
                
                video_url = match.group(1) if match.group(1).startswith('http') else match.group(0)
                
                # 下载视频
                download_success = self._download_video(video_url, str(save_path))
                if download_success:
                    return {
                        "success": True,
                        "path": str(save_path),
                        "url": video_url,
                        "error": None,
                        "status": "completed"
                    }
                else:
                    raise Exception("Video download failed after retries")
                
            except Exception as e:
                error_str = str(e)
                is_rate_limit = "429" in error_str and "rate_limit" in error_str
                is_heavy_load = "400" in error_str and "heavy_load" in error_str
                is_server_error = "500" in error_str
                is_download_failed = "Video download failed" in error_str
                
                should_retry = is_rate_limit or is_heavy_load or is_server_error or is_download_failed
                
                if should_retry and attempt < max_retries:
                    time.sleep(5)
                    continue
                else:
                    return {
                        "success": False,
                        "path": None,
                        "url": None,
                        "error": str(e),
                        "status": "failed"
                    }
        
        return {
            "success": False,
            "path": None,
            "url": None,
            "error": "超过最大重试次数",
            "status": "failed"
        }
    
    def _download_video(self, url: str, save_path: str) -> bool:
        """
        带重试机制的视频下载函数
        """
        max_download_retries = 10
        retry_delay = 2
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        for attempt in range(max_download_retries):
            try:
                r = requests.get(url, stream=True, timeout=120, headers=headers)
                r.raise_for_status()
                
                with open(save_path, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                
                return True
                
            except Exception as e:
                if attempt < max_download_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 10)
                else:
                    return False
        
        return False
    
    def get_video_path(self, page_index: int) -> str:
        """获取视频路径"""
        return os.path.join(self.output_dir, f"page_{page_index:03d}.mp4")


# 测试代码
if __name__ == "__main__":
    generator = VideoGenerator()
    print(f"视频输出目录: {generator.output_dir}")
