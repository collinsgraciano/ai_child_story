import base64
import os
import requests
import time
from openai import OpenAI

# ================= 配置区域 =================
# API 配置
API_KEY = "sk-5ab3f263562e466baa7001ff2a90d659"
BASE_URL = "http://127.0.0.1:8045/v1"
MODEL = "gemini-3-pro-image"

# 图像生成参数
# 支持: "1024x1024" (1:1), "1280x720" (16:9), "720x1280" (9:16), "1216x896" (4:3)
IMAGE_SIZE = "1024x1024"

# 输入参考图片路径列表
# 请将这里替换为你本地实际存在的图片路径
REFERENCE_IMAGES = [
    r"D:\gemini\anti_gemini_images_pro\character_sheet.png",
    r"D:\gemini\anti_gemini_images_pro\scene_sheet.png"
]

# 提示词
PROMPT = '''Reference the character and scene from the image generated above, maintain consistency, A cozy bedroom inside a hollow tree trunk, the small hedgehog in a red sleeping cap is peeking out from under a patchwork quilt, looking wide-eyed, while the large hedgehog sits in a rocking chair reading a book, warm ambient lighting, title text "一个吵闹的夜晚" in the center with stylized font, masterpiece, 8k resolution --ar 16:9'''

# 输出目录
OUTPUT_DIR = "generated_images"
# ===========================================

from PIL import Image
import io

def encode_image(image_path):
    """将本地图片转换为 Base64 字符串，并进行预处理（缩放、压缩）"""
    if not os.path.exists(image_path):
        print(f"❌ 警告: 找不到文件 {image_path}，已跳过。")
        return None
    
    try:
        # 使用 Pillow 打开图片
        with Image.open(image_path) as img:
            # 转换为 RGB (兼容 PNG 透明通道)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
                
            # 缩放图片 (最大边长 1024)
            max_size = 1024
            if max(img.size) > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                
            # 保存为 JPEG 格式到内存
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            buffer.seek(0)
            
            # 返回 Base64
            encoded = base64.b64encode(buffer.read()).decode("utf-8")
            print(f"🖼️ 已处理图片: {os.path.basename(image_path)} | 大小: {len(encoded)/1024:.1f}KB")
            return encoded
            
    except Exception as e:
        print(f"❌ 处理图片时出错 {image_path}: {e}")
        return None

def save_image_from_url(url, output_dir):
    """从 URL 下载并保存图片"""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    timestamp = int(time.time())
    filename = f"gen_{timestamp}.png"
    filepath = os.path.join(output_dir, filename)
    
    try:
        print(f"⬇️ 正在下载图片: {url}")
        response = requests.get(url)
        if response.status_code == 200:
            with open(filepath, "wb") as f:
                f.write(response.content)
            print(f"✅ 图片已保存至: {filepath}")
        else:
            print(f"❌ 下载失败，状态码: {response.status_code}")
    except Exception as e:
        print(f"❌ 保存图片时出错: {e}")

def main():
    client = OpenAI(
        base_url=BASE_URL,
        api_key=API_KEY
    )

    # 1. 构建消息体
    messages_content = []
    
    # 添加文本提示词
    messages_content.append({
        "type": "text",
        "text": PROMPT
    })

    # 添加参考图片
    if not REFERENCE_IMAGES:
        print("⚠️ 提示: 未配置参考图片 (REFERENCE_IMAGES 列表为空)，将仅使用文本生成。")
    
    for img_path in REFERENCE_IMAGES:
        base64_img = encode_image(img_path)
        if base64_img:
            # 由于 encode_image 统一转换为 JPEG，这里固定使用 image/jpeg
            mime_type = "image/jpeg"
            
            messages_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{base64_img}"
                }
            })

    # 2. 发送请求
    print("🚀 正在发送生成请求...")
    try:
        # 增加 timeout 设置 (秒)
        # 尝试开启 stream=True，以防服务器只支持流式输出或为了避免超时
        stream = client.chat.completions.create(
            model=MODEL,
            extra_body={"size": IMAGE_SIZE},
            messages=[{
                "role": "user",
                "content": messages_content
            }],
            timeout=120.0,
            stream=True
        )

        print("\n⏳ 正在接收流式响应...")
        content = ""
        for chunk in stream:
            if chunk.choices[0].delta.content:
                print(".", end="", flush=True)
                content += chunk.choices[0].delta.content
        print("\n")

        # 3. 处理响应
        print("\n📄 API 响应内容:")
        print(content)
        
        # 4. 尝试提取和保存图片
        import re
        urls = re.findall(r'(https?://[^\s\)]+)', content)
        data_urls = re.findall(r'\((data:image/[^;]+;base64,[^\)]+)\)', content)
        
        clean_urls = [u.rstrip(')') for u in urls]
        
        found_any = False
        if clean_urls:
            found_any = True
            for url in clean_urls:
                save_image_from_url(url, OUTPUT_DIR)
        
        if data_urls:
            found_any = True
            for i, data_url in enumerate(data_urls):
                try:
                    header, encoded = data_url.split(',', 1)
                    ext = header.split(';')[0].split('/')[-1]
                    img_data = base64.b64decode(encoded)
                    
                    if not os.path.exists(OUTPUT_DIR):
                        os.makedirs(OUTPUT_DIR)
                    
                    filename = f"gen_data_{int(time.time())}_{i}.{ext}"
                    filepath = os.path.join(OUTPUT_DIR, filename)
                    
                    with open(filepath, "wb") as f:
                        f.write(img_data)
                    print(f"✅ Data 图片已保存至: {filepath}")
                except Exception as e:
                    print(f"❌ 保存Data图片出错: {e}")

        if not found_any:
            print("⚠️ 未在响应中找到有效的图片 URL。")

    except Exception as e:
        print(f"\n❌ 请求发生错误: {e}")
        if hasattr(e, 'response') and e.response:
             print(f"Server response logic: {e.response.text}")


if __name__ == "__main__":
    main()
