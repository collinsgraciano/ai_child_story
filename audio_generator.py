
import os
import shutil
import re
import wave
import contextlib
import struct
import math
from gradio_client import Client, handle_file

class AudioGenerator:
    def __init__(self, api_url: str, default_ref_audio: str = None):
        """
        初始化音频生成器
        :param api_url: Gradio Live URL
        :param default_ref_audio: 默认参考音频路径
        """
        self.api_url = api_url.rstrip('/')
        self.default_ref_audio = default_ref_audio
        self.client = None
        
    def _get_client(self):
        if not self.client:
            print(f"Connecting to TTS API: {self.api_url}")
            self.client = Client(self.api_url)
        return self.client

    def update_config(self, api_url: str, default_ref_audio: str):
        """更新配置"""
        if api_url and api_url != self.api_url:
            self.api_url = api_url
            self.client = None # Reset client
        self.default_ref_audio = default_ref_audio

    # ================= 文本处理工具 =================

    def arabic_to_chinese(self, number):
        """将整数转换为中文数字字符串"""
        number = int(number)
        if number == 0: return "零"
        if number == 2: return "两"
        digits = {0: "零", 1: "一", 2: "二", 3: "三", 4: "四",
                  5: "五", 6: "六", 7: "七", 8: "八", 9: "九"}
        units = ["", "十", "百", "千", "万"]
        s_num = str(number)
        length = len(s_num)
        result = ""
        for i, d in enumerate(s_num):
            digit = int(d)
            if digit != 0:
                result += digits[digit] + units[length - i - 1]
            else:
                if not result.endswith("零"):
                    result += "零"
        result = result.rstrip("零")
        if 10 <= number < 20 and result.startswith("一十"):
            result = result[1:]
        return result

    def text_convert_numbers(self, text):
        return re.sub(r'\d+', lambda x: self.arabic_to_chinese(x.group()), text)

    def split_text_by_punctuation(self, text):
        """
        将文本按标点符号分割成列表，保留标点，合并到上一句中。
        """
        pattern = r'([。！？?!；;，,、\n]+)'
        parts = re.split(pattern, text)
        sentences = []
        current_sent = ""

        for part in parts:
            if not part: continue
            if re.match(pattern, part):
                current_sent += part
                sentences.append(current_sent.strip())
                current_sent = ""
            else:
                if current_sent:
                    sentences.append(current_sent.strip())
                    current_sent = ""
                current_sent += part

        if current_sent.strip():
            sentences.append(current_sent.strip())
        return sentences

    # ================= 音频处理工具 =================

    def get_wav_duration(self, file_path):
        """获取 WAV 文件的时长（秒）"""
        with contextlib.closing(wave.open(str(file_path), 'r')) as f:
            frames = f.getnframes()
            rate = f.getframerate()
            return frames / float(rate)

    def seconds_to_srt_time(self, seconds):
        """将秒数转换为 SRT 时间戳格式 00:00:00,000"""
        millis = int((seconds - int(seconds)) * 1000)
        seconds = int(seconds)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"

    def apply_fadeout(self, file_path, duration_ms=200):
        """使用纯 Python 对 WAV 文件末尾进行淡出处理"""
        try:
            file_path = str(file_path)
            with wave.open(file_path, 'rb') as f:
                params = f.getparams()
                data = f.readframes(params.nframes)

            if params.sampwidth != 2:
                print(f"Skipping fadeout: unsupported sampwidth {params.sampwidth}")
                return

            fade_frames = int(params.framerate * duration_ms / 1000)
            if fade_frames > params.nframes:
                fade_frames = params.nframes

            mutable_data = bytearray(data)
            start_frame = params.nframes - fade_frames

            for i in range(fade_frames):
                factor = 1.0 - (i / fade_frames)
                frame_offset = (start_frame + i) * params.nchannels * params.sampwidth
                for ch in range(params.nchannels):
                    idx = frame_offset + ch * 2
                    try:
                        sample = struct.unpack_from('<h', mutable_data, idx)[0]
                        new_sample = int(sample * factor)
                        struct.pack_into('<h', mutable_data, idx, new_sample)
                    except:
                        pass

            with wave.open(file_path, 'wb') as f:
                f.setparams(params)
                f.writeframes(mutable_data)
                
        except Exception as e:
            print(f"Fadeout failed: {e}")

    # ================= 核心生成逻辑 =================

    def generate_audio(self, text: str, output_path: str, ref_audio_path: str = None, lang: str = "cn") -> dict:
        """
        生成单个音频文件
        :param text: 朗读文本
        :param output_path: 保存路径 (.wav) (绝对路径或相对路径)
        :param ref_audio_path: 参考音频路径 (可选)
        :param lang: 语言 'cn' 或 'en'
        :return: {success: bool, error: str, path: str}
        """
        ref_path = ref_audio_path or self.default_ref_audio
        if not ref_path or not os.path.exists(ref_path):
             return {"success": False, "error": f"Reference audio not found: {ref_path}"}

        try:
            client = self._get_client()
            
            # 预处理文本: 数字转中文 (仅 CN) + 句号停顿
            if lang == "cn":
                processed_text = self.text_convert_numbers(text) + "。"
            else:
                processed_text = text + "." # English punctuation
            
            print(f"TTS Generating: {processed_text[:20]}...")
            
            # 调用 API
            result = client.predict(
                emo_control_method="Same as the voice reference",
                prompt=handle_file(ref_path),
                text=processed_text,
                emo_ref_path=None,
                emo_weight=0.8,
                vec1=0, vec2=0, vec3=0, vec4=0, vec5=0, vec6=0, vec7=0, vec8=0,
                emo_text="",
                emo_random=False,
                max_text_tokens_per_segment=120,
                param_16=True, param_17=0.8, param_18=30, param_19=0.8,
                param_20=0, param_21=3, param_22=10, param_23=1500,
                api_name="/gen_single"
            )
            
            # result 应该是临时文件路径
            temp_path = result[1] if isinstance(result, tuple) else result
            if isinstance(temp_path, dict) and 'value' in temp_path:
                temp_path = temp_path['value']
                
            # 确保目录存在
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # 移动/复制文件
            shutil.copy(temp_path, output_path)
            
            # 应用淡出
            self.apply_fadeout(output_path, duration_ms=150)
            
            return {"success": True, "path": output_path}
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    def generate_project_srt(self, pages: list, audio_dir: str, output_srt_path: str, lang: str = "cn") -> dict:
        """
        生成项目 SRT 字幕文件
        :param pages: 页面列表 [{"page_index": 1, "narration": "..."}]
        :param audio_dir: 音频文件所在目录
        :param output_srt_path: SRT 输出路径
        :param lang: 语言 'cn' 或 'en'
        """
        srt_content_list = []
        current_time_cursor = 0.0
        srt_index = 1
        
        try:
            sorted_pages = sorted(pages, key=lambda x: x['page_index'])
            text_key = "eng_narration" if lang == "en" else "narration"

            for page in sorted_pages:
                idx = page['page_index']
                # 文件名区分语言
                filename_suffix = "en" if lang == "en" else "cn"
                audio_path = os.path.join(audio_dir, f"page_{idx:03d}_{filename_suffix}.wav")
                
                # 兼容旧文件名 (cn)
                if lang == "cn" and not os.path.exists(audio_path):
                     legacy_path = os.path.join(audio_dir, f"page_{idx:03d}.wav")
                     if os.path.exists(legacy_path):
                         audio_path = legacy_path

                text = page.get(text_key, '')
                
                if not os.path.exists(audio_path):
                    print(f"Skip SRT for page {idx} ({lang}): Audio missing")
                    continue
                    
                # 获取音频时长
                duration = self.get_wav_duration(audio_path)
                
                # 分割文本
                sub_sentences = self.split_text_by_punctuation(text)
                
                # 计算权重
                weights = []
                for s in sub_sentences:
                    if lang == "cn":
                        spoken_s = self.text_convert_numbers(s)
                    else:
                        spoken_s = s
                    weights.append(len(spoken_s))
                
                total_weight = sum(weights)
                if total_weight == 0: total_weight = 1
                
                # 生成字幕块
                segment_start = current_time_cursor
                for i, sub_text in enumerate(sub_sentences):
                    seg_duration = duration * (weights[i] / total_weight)
                    segment_end = segment_start + seg_duration
                    
                    start_str = self.seconds_to_srt_time(segment_start)
                    end_str = self.seconds_to_srt_time(segment_end)
                    
                    srt_content_list.append(f"{srt_index}\n{start_str} --> {end_str}\n{sub_text}\n")
                    
                    srt_index += 1
                    segment_start = segment_end
                
                current_time_cursor += duration
                
            # 保存 SRT
            with open(output_srt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(srt_content_list))
                
            return {"success": True, "path": output_srt_path}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
