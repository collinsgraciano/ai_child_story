"""
测试视频拼接卡顿问题 - 包含场景分割步骤
"""

import subprocess
import os
import shutil
from pathlib import Path

# 第三方库
try:
    from scenedetect import open_video, SceneManager, ContentDetector
except ImportError:
    subprocess.run(["pip", "install", "scenedetect[opencv]"], check=True)
    from scenedetect import open_video, SceneManager, ContentDetector

# 测试配置
VIDEO_DIR = r"D:\gemini\child_story\output\完美的礼物\videos"
OUTPUT_DIR = r"D:\gemini\child_story\output\完美的礼物"
THRESHOLD = 27.0

def get_duration(file_path):
    """获取视频时长"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
        return float(output)
    except:
        return None

def find_scenes(video_path, threshold=27.0):
    """检测视频中的场景分割点"""
    try:
        video = open_video(str(video_path))
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=15))
        scene_manager.detect_scenes(video, show_progress=False)
        return scene_manager.get_scene_list()
    except Exception as e:
        print(f"场景检测失败: {e}")
        return []

def trim_first_scene(input_path, output_path, threshold=27.0):
    """删除视频的第一个场景 - 使用 -c copy (原始方式)"""
    scenes = find_scenes(input_path, threshold)
    
    if not scenes:
        print(f"  未检测到场景，复制原视频")
        shutil.copy2(input_path, output_path)
        return True
    
    first_scene_end = scenes[0][1].get_seconds()
    video_duration = get_duration(input_path)
    
    print(f"  首个镜头结束于: {first_scene_end:.2f}s / 总时长: {video_duration:.2f}s")
    
    if first_scene_end >= video_duration:
        print(f"  第一个镜头贯穿全片，复制原视频")
        shutil.copy2(input_path, output_path)
        return True
    
    # 使用 -c copy 剪辑 (这可能是问题所在)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-ss", str(first_scene_end),
        "-c", "copy",
        str(output_path)
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0

def trim_first_scene_reencode(input_path, output_path, threshold=27.0):
    """删除视频的第一个场景 - 使用重新编码 (修复方式)"""
    scenes = find_scenes(input_path, threshold)
    
    if not scenes:
        print(f"  未检测到场景，复制原视频")
        shutil.copy2(input_path, output_path)
        return True
    
    first_scene_end = scenes[0][1].get_seconds()
    video_duration = get_duration(input_path)
    
    print(f"  首个镜头结束于: {first_scene_end:.2f}s / 总时长: {video_duration:.2f}s")
    
    if first_scene_end >= video_duration:
        print(f"  第一个镜头贯穿全片，复制原视频")
        shutil.copy2(input_path, output_path)
        return True
    
    # 使用重新编码剪辑 (确保关键帧对齐)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(first_scene_end),  # 放在 -i 前面，更快
        "-i", str(input_path),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path)
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0

def test_with_scene_trim():
    """测试包含场景分割的完整流程"""
    video1 = os.path.join(VIDEO_DIR, "page_001.mp4")
    video2 = os.path.join(VIDEO_DIR, "page_002.mp4")
    
    # 临时目录
    temp_dir = os.path.join(OUTPUT_DIR, "test_temp")
    os.makedirs(temp_dir, exist_ok=True)
    
    print("\n=== 方法 A: 场景分割用 -c copy (原始方式，可能卡顿) ===")
    trimmed1_a = os.path.join(temp_dir, "trimmed1_copy.mp4")
    trimmed2_a = os.path.join(temp_dir, "trimmed2_copy.mp4")
    
    print(f"处理 page_001.mp4:")
    trim_first_scene(video1, trimmed1_a, THRESHOLD)
    print(f"处理 page_002.mp4:")
    trim_first_scene(video2, trimmed2_a, THRESHOLD)
    
    # 拼接
    list_file_a = os.path.join(temp_dir, "list_a.txt")
    with open(list_file_a, "w", encoding="utf-8") as f:
        f.write(f"file '{trimmed1_a}'\n")
        f.write(f"file '{trimmed2_a}'\n")
    
    output_a = os.path.join(OUTPUT_DIR, "test_trim_copy.mp4")
    cmd_a = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file_a,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_a
    ]
    subprocess.run(cmd_a, capture_output=True)
    print(f"输出: {output_a}")
    
    print("\n=== 方法 B: 场景分割用重新编码 (修复方式) ===")
    trimmed1_b = os.path.join(temp_dir, "trimmed1_reencode.mp4")
    trimmed2_b = os.path.join(temp_dir, "trimmed2_reencode.mp4")
    
    print(f"处理 page_001.mp4:")
    trim_first_scene_reencode(video1, trimmed1_b, THRESHOLD)
    print(f"处理 page_002.mp4:")
    trim_first_scene_reencode(video2, trimmed2_b, THRESHOLD)
    
    # 拼接
    list_file_b = os.path.join(temp_dir, "list_b.txt")
    with open(list_file_b, "w", encoding="utf-8") as f:
        f.write(f"file '{trimmed1_b}'\n")
        f.write(f"file '{trimmed2_b}'\n")
    
    output_b = os.path.join(OUTPUT_DIR, "test_trim_reencode.mp4")
    cmd_b = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file_b,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_b
    ]
    subprocess.run(cmd_b, capture_output=True)
    print(f"输出: {output_b}")
    
    print("\n=== 完成 ===")
    print("请分别播放以下文件检查是否有卡顿:")
    print(f"  A. {output_a} (场景分割用 -c copy)")
    print(f"  B. {output_b} (场景分割用重新编码)")

if __name__ == "__main__":
    test_with_scene_trim()
