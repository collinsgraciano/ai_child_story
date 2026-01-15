"""
配置管理模块
存储和管理所有 API 配置
"""

import os
import json
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
        "generation": {
            "image_size": "1024x1024",
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
        self.config = self.load_config()
    
    def load_config(self) -> dict:
        """加载配置文件，如果不存在则使用默认配置"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # 合并默认配置（确保新增的配置项有默认值）
                return self._merge_config(self.DEFAULT_CONFIG, loaded)
            except Exception as e:
                print(f"加载配置失败: {e}，使用默认配置")
                return self.DEFAULT_CONFIG.copy()
        else:
            # 保存默认配置
            self.save_config(self.DEFAULT_CONFIG)
            return self.DEFAULT_CONFIG.copy()
    
    def _merge_config(self, default: dict, loaded: dict) -> dict:
        """递归合并配置"""
        result = default.copy()
        for key, value in loaded.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        return result
    
    def save_config(self, config: dict = None):
        """保存配置到文件"""
        if config is not None:
            self.config = config
        
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
    
    def get(self, *keys, default=None):
        """
        获取配置值
        
        Args:
            keys: 配置路径，如 get("image_api", "base_url")
            default: 默认值
        """
        result = self.config
        for key in keys:
            if isinstance(result, dict) and key in result:
                result = result[key]
            else:
                return default
        return result
    
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
        return self.config.copy()


# 全局配置实例
config = Config()


if __name__ == "__main__":
    # 测试配置
    print(f"图片 API: {config.get('image_api', 'base_url')}")
    print(f"视频 API: {config.get('video_api', 'base_url')}")
