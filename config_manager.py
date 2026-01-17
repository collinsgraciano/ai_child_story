"""
配置管理模块
存储和管理所有 API 配置
"""

import os
import json
import copy
from pathlib import Path


class Config:
    """配置管理类"""
    
    # 默认配置
    DEFAULT_CONFIG = {
        "image_api": {
            "base_url": "http://107.174.131.42:8001/v1",
            "api_key": "sk-dummy",
            "model": "g3-img-pro"
        },
        "video_api": {
            "base_url": "http://127.0.0.1:8003/v1",
            "api_key": "sk-dummy",
            "model": "sora"
        },
        "audio_api": {
            "base_url": "https://11111.gradio.live",
            "reference_audio": "d:\\gemini\\child_story\\10s.mp3"
        },
        "optimize_api": {
            "base_url": "https://x666.me/v1",
            "api_key": "sk-NXZmDCUXqz5zAsrC6nHePGrfe62vSiyGEVBw3OwHoHtvd8Mj",
            "model": "gpt-4.1-mini"
        },
        "generation": {
            "image_size": "1024x1024",
            "image_max_retries": 3,
            "video_max_retries": 10,
            "download_timeout": 120,
            "batch_size": 1,
            "concurrency": {
                "image": 2,
                "video": 1
            }
        }
    }
    
    def __init__(self, config_path: str = None):
        """
        初始化配置
        
        Args:
            config_path: 配置文件路径，默认为项目目录下的 config.json
        """
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "config.json")
        
        self.config_path = config_path
        self.last_error = None # [NEW] 记录最近一次加载错误
        self.config = self.load_config()
    
    def load_config(self) -> dict:
        """加载配置文件，如果不存在则使用默认配置"""
        print(f"📂 [Config] Loading from: {self.config_path}")
        self.last_error = None # Reset error
        
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if not content:
                         # Handle empty file explicitly
                         raise json.JSONDecodeError("File is empty", "", 0)
                    loaded = json.loads(content)
                    
                print("✅ [Config] Loaded successfully.")
                return self._merge_config(self.DEFAULT_CONFIG, loaded)
                
            except json.JSONDecodeError as e:
                err_msg = f"JSON format error: {e.msg} at line {e.lineno}"
                print(f"❌ [Config] {err_msg}")
                self.last_error = err_msg
                return copy.deepcopy(self.DEFAULT_CONFIG)
                
            except Exception as e:
                err_msg = f"Load failed: {str(e)}"
                print(f"❌ [Config] {err_msg}")
                self.last_error = err_msg
                return copy.deepcopy(self.DEFAULT_CONFIG)
        else:
            print("⚠️ [Config] File not found. Creating default.")
            # 保存默认配置
            self.save_config(self.DEFAULT_CONFIG)
            return copy.deepcopy(self.DEFAULT_CONFIG)
    
    def _merge_config(self, default: dict, loaded: dict) -> dict:
        """递归合并配置"""
        result = copy.deepcopy(default)
        for key, value in loaded.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        return result
    
    def save_config(self, config: dict = None):
        """保存配置到文件"""
        print(f"💾 [Config] Saving to {self.config_path}...")
        if config is not None:
            self.config = config
        
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            print("✅ [Config] Saved.")
        except Exception as e:
            print(f"❌ [Config] Save failed: {e}")
    
    def get(self, *keys, default=None):
        """
        获取配置值 (每次获取前尝试重新加载，确保文件修改生效)
        
        Args:
            keys: 配置路径，如 get("image_api", "base_url")
            default: 默认值
        """
        # [NEW] 每次获取配置时重新加载，解决用户手动修改 config.json 不生效的问题
        self.reload()
        
        result = self.config
        for key in keys:
            if isinstance(result, dict) and key in result:
                result = result[key]
            else:
                return default
        return result

    def reload(self):
        """强制从磁盘重新加载配置"""
        self.config = self.load_config()
    
    def set(self, *keys, value):
        """
        设置配置值
        
        Args:
            keys: 配置路径
            value: 配置值
        """
        if len(keys) == 0:
            return
        
        result = self.config
        for key in keys[:-1]:
            if key not in result:
                result[key] = {}
            result = result[key]
        
        result[keys[-1]] = value
        self.save_config()
    
    def update_image_api(self, base_url: str, api_key: str, model: str):
        """更新图片 API 配置"""
        self.config["image_api"] = {
            "base_url": base_url,
            "api_key": api_key,
            "model": model
        }
        self.save_config()
    
    def update_audio_api(self, base_url: str, reference_audio: str):
        """更新音频 API 配置"""
        self.config["audio_api"] = {
            "base_url": base_url,
            "reference_audio": reference_audio
        }
        self.save_config()
    
    def update_video_api(self, base_url: str, api_key: str, model: str):
        """更新视频 API 配置"""
        self.config["video_api"] = {
            "base_url": base_url,
            "api_key": api_key,
            "model": model
        }
        self.save_config()
    
    def to_dict(self) -> dict:
        """返回完整配置字典"""
        # [FIX] 确保返回最新配置
        self.reload()
        return copy.deepcopy(self.config)


# 全局配置实例
config = Config()


if __name__ == "__main__":
    # 测试配置
    print(f"图片 API: {config.get('image_api', 'base_url')}")
    print(f"视频 API: {config.get('video_api', 'base_url')}")
