"""
视频后处理脚本
功能：
1. 删除每个视频的第一个分割场景
2. 以配音时长为准调整视频速度并混合音频
3. 按自然顺序合并所有片段成一条视频
"""

import os
import subprocess
import glob
import shutil
from pathlib import Path
from datetime import datetime

# 第三方库导入
try:
    import natsort
except ImportError:
    subprocess.run(["pip", "install", "natsort"], check=True)
    import natsort

try:
    from scenedetect import open_video, SceneManager, ContentDetector
except ImportError:
    subprocess.run(["pip", "install", "scenedetect[opencv]"], check=True)
    from scenedetect import open_video, SceneManager, ContentDetector


class VideoPostProcessor:
    """视频后处理器：删除第一个镜头 + 配音对齐 + 合并"""
    
    def __init__(
        self,
        video_folder: str,
        audio_folder: str,
        output_folder: str,
        final_output_path: str = None,
        threshold: float = 27.0,
        video_volume: float = 0.05,
        audio_volume: float = 4.0
    ):
        """
        初始化视频后处理器
        
        Args:
            video_folder: 原始视频文件夹路径
            audio_folder: 配音音频文件夹路径
            output_folder: 临时输出文件夹路径
            final_output_path: 最终输出视频路径
            threshold: 场景检测阈值 (值越大，检测越宽松)
            video_volume: 原视频音量倍率 (0-5, 1为原始音量)
            audio_volume: 配音音量倍率 (0-5, 1为原始音量)
        """
        self.video_folder = Path(video_folder)
        self.audio_folder = Path(audio_folder)
        self.output_folder = Path(output_folder)
        self.final_output_path = Path(final_output_path) if final_output_path else None
        self.threshold = threshold
        self.video_volume = video_volume
        self.audio_volume = audio_volume
        
        # 临时文件夹
        self.trimmed_folder = self.output_folder / "trimmed"
        self.merged_folder = self.output_folder / "merged"
        
        # 创建目录
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.trimmed_folder.mkdir(parents=True, exist_ok=True)
        self.merged_folder.mkdir(parents=True, exist_ok=True)
        
        # 有效文件扩展名
        self.valid_video_ext = ['.mp4', '.mov', '.avi', '.mkv', '.webm']
        self.valid_audio_ext = ['.wav', '.mp3', '.m4a', '.aac']
    
    # ==========================================
    # 工具函数
    # ==========================================
    
    def get_duration(self, file_path: str) -> float:
        """获取媒体文件时长(秒)"""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path)
        ]
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
            return float(output)
        except Exception as e:
            print(f"⚠️ 无法获取文件时长: {file_path}, 错误: {e}")
            return None
    
    def has_audio_stream(self, file_path: str) -> bool:
        """检查视频文件是否包含音频流"""
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(file_path)
        ]
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
            return len(output) > 0
        except:
            return False
    
    def get_atempo_filter(self, speed: float) -> str:
        """
        生成 atempo 滤镜链
        ffmpeg atempo 滤镜限制在 0.5 到 2.0 之间，超出需要级联多个滤镜
        """
        if abs(speed - 1.0) < 0.001:
            return "atempo=1.0"
        
        filters = []
        
        # 处理加速情况 (speed > 1)
        while speed > 2.0:
            filters.append("atempo=2.0")
            speed /= 2.0
        
        # 处理减速情况 (speed < 1)
        while speed < 0.5:
            filters.append("atempo=0.5")
            speed /= 0.5
        
        filters.append(f"atempo={speed:.6f}")
        return ",".join(filters)
    
    def find_scenes(self, video_path: str) -> list:
        """检测视频中的场景分割点"""
        if not os.path.exists(video_path):
            return []
        try:
            video = open_video(str(video_path))
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector(threshold=self.threshold, min_scene_len=15))
            scene_manager.detect_scenes(video, show_progress=False)
            return scene_manager.get_scene_list()
        except Exception as e:
            print(f"⚠️ 场景检测失败 {os.path.basename(video_path)}: {e}")
            return []
    
    # ==========================================
    # 步骤1: 删除第一个镜头
    # ==========================================
    
    def trim_first_scene(self, input_path: Path, output_path: Path, force: bool = False) -> bool:
        """
        删除视频的第一个场景
        
        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            force: 是否强制重新处理
            
        Returns:
            是否成功
        """
        if output_path.exists() and not force:
            print(f"⏩ 已存在剪辑版，跳过: {input_path.name}")
            return True
        
        print(f"✂️ 正在检测场景: {input_path.name}")
        scenes = self.find_scenes(str(input_path))
        
        if not scenes:
            print(f"   ⚠️ 未检测到场景，复制原视频")
            shutil.copy2(input_path, output_path)
            return True
        
        try:
            # 获取第一个场景结束时间
            first_scene_end_time = scenes[0][1].get_seconds()
            video_duration = self.get_duration(str(input_path))
            
            print(f"   ⏱️ 首个镜头结束于: {first_scene_end_time:.2f}s / 总时长: {video_duration:.2f}s")
            
            if first_scene_end_time >= video_duration:
                print(f"   ⚠️ 第一个镜头贯穿全片，复制原视频")
                shutil.copy2(input_path, output_path)
                return True
            
            # 使用 ffmpeg 剪辑 (比 MoviePy 更快更稳定)
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-ss", str(first_scene_end_time),
                "-c", "copy",  # 无损复制，速度快
                str(output_path)
            ]
            
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            
            if result.returncode == 0:
                print(f"   ✅ 剪辑完成: {output_path.name}")
                return True
            else:
                print(f"   ❌ 剪辑失败: {result.stderr.decode('utf-8')[:200]}")
                return False
                
        except Exception as e:
            print(f"   ❌ 剪辑出错: {e}")
            return False
    
    def trim_all_videos(self, force: bool = False) -> list:
        """
        批量删除所有视频的第一个场景
        
        Returns:
            剪辑后的视频路径列表
        """
        print("\n" + "="*50)
        print("步骤 1: 删除每个视频的第一个镜头")
        print("="*50)
        
        video_files = []
        for ext in self.valid_video_ext:
            video_files.extend(self.video_folder.glob(f"*{ext}"))
        
        video_files = natsort.natsorted(video_files)
        
        if not video_files:
            print(f"⚠️ 未找到视频文件: {self.video_folder}")
            return []
        
        print(f"📁 找到 {len(video_files)} 个视频文件")
        
        trimmed_videos = []
        for video_path in video_files:
            output_path = self.trimmed_folder / video_path.name
            if self.trim_first_scene(video_path, output_path, force):
                trimmed_videos.append(output_path)
        
        return trimmed_videos
    
    # ==========================================
    # 步骤2: 以配音时长为准合并
    # ==========================================
    
    def merge_with_audio(self, video_path: Path, audio_path: Path, output_path: Path) -> bool:
        """
        将视频与配音合并，以配音时长为准调整视频速度
        
        Args:
            video_path: 视频路径
            audio_path: 配音路径
            output_path: 输出路径
            
        Returns:
            是否成功
        """
        # 获取时长
        dur_audio = self.get_duration(str(audio_path))
        dur_video = self.get_duration(str(video_path))
        
        if not dur_audio or not dur_video:
            print(f"   ⚠️ 无法读取时长，跳过")
            return False
        
        # 计算缩放比例
        # pts_factor: setpts滤镜参数。 >1 视频变慢(时长变长), <1 视频变快(时长变短)
        pts_factor = dur_audio / dur_video
        
        # audio_speed: 视频原声需要的播放速度
        audio_speed_factor = 1.0 / pts_factor
        
        print(f"   📊 音频: {dur_audio:.2f}s | 视频: {dur_video:.2f}s | 视频倍速: {1/pts_factor:.2f}x")
        
        # 构建 FFmpeg 命令
        has_orig_audio = self.has_audio_stream(str(video_path))
        
        # 视频滤镜: 调整PTS以改变时长
        video_filter = f"[0:v]setpts=PTS*{pts_factor}[v_out]"
        
        # 音频滤镜
        atempo_chain = self.get_atempo_filter(audio_speed_factor)
        
        if has_orig_audio:
            # 复杂滤镜：处理原声 + 外部音频混合
            filter_complex = (
                f"{video_filter};"
                f"[0:a]{atempo_chain},volume={self.video_volume}[a_orig];"
                f"[1:a]volume={self.audio_volume}[a_ext];"
                f"[a_orig][a_ext]amix=inputs=2:duration=longest[a_out]"
            )
            map_cmd = ["-map", "[v_out]", "-map", "[a_out]"]
        else:
            # 视频没声音，直接使用外部音频
            filter_complex = (
                f"{video_filter};"
                f"[1:a]volume={self.audio_volume}[a_out]"
            )
            map_cmd = ["-map", "[v_out]", "-map", "[a_out]"]
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex", filter_complex,
            *map_cmd,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_path)
        ]
        
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        
        if result.returncode == 0:
            return True
        else:
            print(f"   ❌ 合并失败: {result.stderr.decode('utf-8')[:200]}")
            return False
    
    def merge_all_with_audio(self) -> list:
        """
        批量合并视频与配音
        
        Returns:
            合并后的视频片段路径列表
        """
        print("\n" + "="*50)
        print("步骤 2: 以配音时长为准合并视频与音频")
        print("="*50)
        
        # 获取所有音频文件
        audio_files = []
        for ext in self.valid_audio_ext:
            audio_files.extend(self.audio_folder.glob(f"*{ext}"))
        
        audio_files = natsort.natsorted(audio_files)
        
        if not audio_files:
            print(f"⚠️ 未找到音频文件: {self.audio_folder}")
            return []
        
        # 创建视频文件名到路径的映射 (使用剪辑后的视频)
        video_files = list(self.trimmed_folder.glob("*"))
        video_map = {f.stem: f for f in video_files if f.suffix.lower() in self.valid_video_ext}
        
        print(f"📁 找到 {len(audio_files)} 个音频文件，{len(video_map)} 个剪辑后视频")
        
        merged_segments = []
        
        for i, audio_path in enumerate(audio_files):
            base_name = audio_path.stem
            
            if base_name not in video_map:
                print(f"⚠️ 跳过: 找不到对应视频 -> {base_name}")
                continue
            
            video_path = video_map[base_name]
            output_path = self.merged_folder / f"{i:03d}_{base_name}.mp4"
            
            print(f"🎬 处理: {base_name}")
            
            if self.merge_with_audio(video_path, audio_path, output_path):
                merged_segments.append(output_path)
                print(f"   ✅ 合并完成")
            else:
                print(f"   ❌ 合并失败")
        
        return merged_segments
    
    # ==========================================
    # 步骤3: 拼接所有片段
    # ==========================================
    
    def concatenate_videos(self, segments: list) -> Path:
        """
        将所有视频片段拼接成一条视频
        
        Args:
            segments: 视频片段路径列表
            
        Returns:
            最终视频路径
        """
        print("\n" + "="*50)
        print("步骤 3: 拼接所有视频片段")
        print("="*50)
        
        if not segments:
            print("⚠️ 没有可拼接的视频片段")
            return None
        
        print(f"📁 准备拼接 {len(segments)} 个视频片段...")
        
        # 创建文件列表
        list_file_path = self.output_folder / "file_list.txt"
        
        with open(list_file_path, "w", encoding="utf-8") as f:
            for segment in segments:
                # concat demuxer 使用绝对路径
                f.write(f"file '{segment.absolute()}'\n")
        
        # 先输出到临时路径 (避免中文路径问题)
        tmp_output_path = self.output_folder / "final_merged.mp4"
        
        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file_path),
            "-c", "copy",
            str(tmp_output_path)
        ]
        
        result = subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        
        if result.returncode != 0:
            print(f"❌ 拼接失败: {result.stderr.decode('utf-8')[:200]}")
            return None
        
        # 如果指定了最终路径，复制过去
        if self.final_output_path:
            self.final_output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tmp_output_path, self.final_output_path)
            print(f"✅ 最终视频已生成: {self.final_output_path}")
            return self.final_output_path
        else:
            print(f"✅ 最终视频已生成: {tmp_output_path}")
            return tmp_output_path
    
    # ==========================================
    # 主流程
    # ==========================================
    
    def process(self, force_trim: bool = False, cleanup: bool = True) -> Path:
        """
        执行完整的后处理流程
        
        Args:
            force_trim: 是否强制重新剪辑
            cleanup: 是否清理临时文件
            
        Returns:
            最终视频路径
        """
        print("\n" + "="*60)
        print("🎬 视频后处理开始")
        print("="*60)
        print(f"📂 视频文件夹: {self.video_folder}")
        print(f"📂 音频文件夹: {self.audio_folder}")
        print(f"📂 输出文件夹: {self.output_folder}")
        print(f"🎚️ 原视频音量: {self.video_volume} | 配音音量: {self.audio_volume}")
        
        # 步骤1: 删除第一个镜头
        trimmed_videos = self.trim_all_videos(force=force_trim)
        if not trimmed_videos:
            print("⚠️ 没有成功剪辑的视频")
            return None
        
        # 步骤2: 以配音时长为准合并
        merged_segments = self.merge_all_with_audio()
        if not merged_segments:
            print("⚠️ 没有成功合并的视频片段")
            return None
        
        # 步骤3: 拼接成一条视频
        final_video = self.concatenate_videos(merged_segments)
        
        # 清理临时文件
        if cleanup and final_video:
            print("\n🧹 清理临时文件...")
            shutil.rmtree(self.trimmed_folder, ignore_errors=True)
            shutil.rmtree(self.merged_folder, ignore_errors=True)
            (self.output_folder / "file_list.txt").unlink(missing_ok=True)
            # 如果输出到了最终路径，删除临时输出
            if self.final_output_path:
                (self.output_folder / "final_merged.mp4").unlink(missing_ok=True)
        
        print("\n" + "="*60)
        print("🎉 视频后处理完成!")
        print("="*60)
        
        return final_video


# ==========================================
# 命令行入口
# ==========================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="视频后处理工具")
    parser.add_argument("--video", "-v", required=True, help="原始视频文件夹路径")
    parser.add_argument("--audio", "-a", required=True, help="配音音频文件夹路径")
    parser.add_argument("--output", "-o", required=True, help="临时输出文件夹路径")
    parser.add_argument("--final", "-f", default=None, help="最终输出视频路径 (可选)")
    parser.add_argument("--threshold", "-t", type=float, default=27.0, help="场景检测阈值 (默认: 27.0)")
    parser.add_argument("--video-volume", type=float, default=0.05, help="原视频音量 (默认: 0.05)")
    parser.add_argument("--audio-volume", type=float, default=4.0, help="配音音量 (默认: 4.0)")
    parser.add_argument("--force", action="store_true", help="强制重新剪辑")
    parser.add_argument("--no-cleanup", action="store_true", help="不清理临时文件")
    
    args = parser.parse_args()
    
    processor = VideoPostProcessor(
        video_folder=args.video,
        audio_folder=args.audio,
        output_folder=args.output,
        final_output_path=args.final,
        threshold=args.threshold,
        video_volume=args.video_volume,
        audio_volume=args.audio_volume
    )
    
    processor.process(force_trim=args.force, cleanup=not args.no_cleanup)
