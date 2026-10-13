from flask import Flask, request, send_file
from PIL import Image, ImageFile
import requests
import io
import tempfile
import os
import cv2
import numpy as np
from flask_cors import CORS
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ImageFile.LOAD_TRUNCATED_IMAGES = True

app = Flask(__name__)
CORS(app)

# Configuration
BACKGROUND_IMAGE_PATH = "./Background_image/ALONGBOTS.jpg"
SPACING_PX = 20
HORIZONTAL_SPACING_PX = 14
VERTICAL_SPACING_PX = SPACING_PX
IMAGE_WIDTH_PX = 576
IMAGE_HEIGHT_PX = 756

# Add a realistic Browser Header to bypass blocks
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
}

def extract_frame_from_video(video_content, ext=".webm"):
    """Saves video to a temp file and extracts the first frame."""
    # Detect true format via magic bytes
    if video_content.startswith(b'\x1a\x45\xdf\xa3'):
        candidates = [".webm", ".mkv", ".mp4"]
    elif len(video_content) > 8 and video_content[4:8] == b'ftyp':
        candidates = [".mp4", ".mov", ".m4v"]
    else:
        candidates = [ext, ".webm", ".mp4", ".avi", ".mov"]

    for suffix in candidates:
        temp_video_path = None
        try:
            # Write and CLOSE the file first so OpenCV can read it freely on Windows
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_video:
                temp_video.write(video_content)
                temp_video.flush()
                temp_video_path = temp_video.name

            vidcap = cv2.VideoCapture(temp_video_path)
            success, image = vidcap.read()
            vidcap.release()
            
            if success and image is not None:
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                return Image.fromarray(image)
        except Exception as e:
            print(f"Error processing video frame ({suffix}): {e}")
        finally:
            if temp_video_path and os.path.exists(temp_video_path):
                try:
                    os.remove(temp_video_path)
                except Exception:
                    pass
    
    return None

def download_and_resize_image(url):
    """Download an image or video frame and resize it."""
    try:
        # Build headers with domain-specific referer to bypass CDN anti-hotlinking
        req_headers = HEADERS.copy()
        if 'mazoku.cc' in url:
            req_headers['Referer'] = 'https://mazoku.cc/'

        response = requests.get(url, headers=req_headers, stream=True, timeout=12, allow_redirects=True, verify=False)
        if response.status_code == 403:
            req_headers['Referer'] = 'https://discord.com/'
            response = requests.get(url, headers=req_headers, stream=True, timeout=12, allow_redirects=True, verify=False)
        response.raise_for_status()

        content = response.content
        img = None

        # 1. Try opening as a standard image / animated GIF via PIL
        try:
            pil_img = Image.open(io.BytesIO(content))
            pil_img.seek(0)
            if pil_img.mode in ("RGBA", "LA") or (pil_img.mode == "P" and "transparency" in pil_img.info):
                pil_img = pil_img.convert("RGBA")
                canvas = Image.new("RGBA", pil_img.size, (255, 255, 255, 255))
                canvas.paste(pil_img, mask=pil_img)
                img = canvas.convert("RGB")
            else:
                img = pil_img.convert("RGB")
        except Exception:
            img = None

        # 2. Try decoding with OpenCV if PIL failed
        if img is None:
            try:
                nparr = np.frombuffer(content, np.uint8)
                cv_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if cv_img is not None:
                    img = Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))
            except Exception:
                img = None

        # 3. Extract as video (handles WebM/MP4 masked as .gif/.png)
        if img is None:
            ext = os.path.splitext(url.lower().split('?')[0])[1] or '.webm'
            img = extract_frame_from_video(content, ext)

        if img:
            resized_img = img.resize((IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX), Image.Resampling.LANCZOS)
            return resized_img
            
    except Exception as e:
        print(f"Error downloading or processing {url}: {e}")
        return None
    return None

def create_image_grid(image_urls, rows, cols, horizontal_spacing, vertical_spacing):
    total_width = cols * IMAGE_WIDTH_PX + (cols - 1) * horizontal_spacing
    total_height = rows * IMAGE_HEIGHT_PX + (rows - 1) * vertical_spacing

    # Try to load background, otherwise create a white one
    try:
        if os.path.exists(BACKGROUND_IMAGE_PATH):
            background = Image.open(BACKGROUND_IMAGE_PATH)
            background = background.resize((total_width, total_height))
        else:
            background = Image.new("RGB", (total_width, total_height), (255, 255, 255))
    except Exception:
        background = Image.new("RGB", (total_width, total_height), (255, 255, 255))

    grid_image = background

    for idx, url in enumerate(image_urls):
        if idx >= rows * cols:
            break
        
        img = download_and_resize_image(url)
        if img:
            row, col = divmod(idx, cols)
            x_offset = col * (IMAGE_WIDTH_PX + horizontal_spacing)
            y_offset = row * (IMAGE_HEIGHT_PX + vertical_spacing)
            grid_image.paste(img, (x_offset, y_offset))

    return grid_image

@app.route('/api/combine-images', methods=['GET'])
def combine_images():
    # Supports up to 12 images via pic1, pic2...
    image_urls = [request.args.get(f'pic{i}') for i in range(1, 13)]
    image_urls = [url for url in image_urls if url]

    if not image_urls:
        return "No images provided", 400

    # Grid logic: you can adjust rows/cols based on len(image_urls)
    rows, cols = 4, 3 
    grid_image = create_image_grid(image_urls, rows, cols, HORIZONTAL_SPACING_PX, VERTICAL_SPACING_PX)

    # Save to memory instead of a physical file for faster response
    img_io = io.BytesIO()
    grid_image.save(img_io, 'PNG')
    img_io.seek(0)

    return send_file(img_io, mimetype='image/png')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
