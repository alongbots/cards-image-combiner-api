from flask import Flask, request, send_file
from PIL import Image
import requests
import io
import tempfile
import os
import cv2
import numpy as np
import re
import urllib.request
import urllib3
from flask_cors import CORS

# Suppress insecure request warnings for URLs with broken SSL certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Optional but highly recommended: Support for AVIF and HEIC formats (Apple/Modern Web)
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

app = Flask(__name__)
CORS(app)

# Configuration
BACKGROUND_IMAGE_PATH = "./Background_image/ALONGBOTS.jpg"
SPACING_PX = 20
HORIZONTAL_SPACING_PX = 14
VERTICAL_SPACING_PX = SPACING_PX
IMAGE_WIDTH_PX = 576
IMAGE_HEIGHT_PX = 756

# Realistic Browser Headers to bypass anti-bot blocks
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://google.com/'
}

def extract_frame_from_video(video_content):
    """Saves video to a temp file and extracts the first frame using OpenCV."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_video:
        temp_video.write(video_content)
        temp_video_path = temp_video.name

    try:
        vidcap = cv2.VideoCapture(temp_video_path)
        success, image = vidcap.read()
        vidcap.release()

        if success:
            # Convert BGR (OpenCV) to RGB (PIL)
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            return Image.fromarray(image)
    except Exception as e:
        print(f"Error processing video frame: {e}")
    finally:
        if os.path.exists(temp_video_path):
            try:
                os.remove(temp_video_path)
            except Exception:
                pass
    return None

def process_image_bytes(content):
    """Safely opens image bytes using PIL, handling GIFs and Transparency."""
    try:
        img = Image.open(io.BytesIO(content))
        
        # If it's a GIF or animated format, make sure we are on the first frame
        if getattr(img, "is_animated", False):
            img.seek(0)

        # Handle Transparency (Alpha Channel) to prevent black backgrounds
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            img = img.convert('RGBA')
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert('RGB')
            
        return img
    except Exception as e:
        print(f"PIL Failed to process image bytes: {e}")
        return None

def download_and_resize_image(url, depth=0):
    """Download an image, HTML meta-image, base64 URI, or video frame and resize it."""
    # Prevent infinite redirects on malicious/circular links
    if depth > 2:
        return None

    try:
        # 1. Handle Base64 Data URIs directly
        if url.startswith('data:'):
            with urllib.request.urlopen(url) as response:
                content = response.read()
            img = process_image_bytes(content)
            if img:
                return img.resize((IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX), Image.Resampling.LANCZOS)
            return None

        # 2. Fetch the URL (verify=False helps bypass SSL blocks)
        response = requests.get(url, headers=HEADERS, stream=True, timeout=15, allow_redirects=True, verify=False)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '').lower()
        content = response.content

        # 3. Handle HTML pages (Extract image from standard links like Imgur or websites)
        if 'text/html' in content_type:
            html_content = content.decode('utf-8', errors='ignore')
            # Look for the OpenGraph image tag (<meta property="og:image" content="...">)
            match = re.search(r'<meta\s+(?:property|name)=[\'"]og:image[\'"]\s+content=[\'"]([^\'"]+)[\'"]', html_content, re.IGNORECASE)
            if match:
                og_url = match.group(1)
                # Recursively download the actual extracted image
                return download_and_resize_image(og_url, depth=depth+1)

        # 4. Determine if it's a video (GIFs are deliberately excluded so PIL handles them)
        video_extensions = ('.webm', '.mp4', '.mov', '.avi', '.m4v', '.mkv', '.wmv')
        is_video = 'video' in content_type or url.lower().split('?')[0].endswith(video_extensions)

        img = None
        
        # Route 1: Try as Video First
        if is_video:
            img = extract_frame_from_video(content)
            
        # Route 2: Try as Standard Image (JPG, PNG, GIF, WEBP)
        if img is None:
            img = process_image_bytes(content)
            
        # Route 3: Deep Fallback - if PIL failed, maybe it's a mislabeled video file
        if img is None and not is_video:
            img = extract_frame_from_video(content)

        # Finalize and Resize
        if img:
            return img.resize((IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX), Image.Resampling.LANCZOS)

    except Exception as e:
        print(f"Error downloading or processing {url}: {e}")
        
    return None

def create_image_grid(image_urls, rows, cols, horizontal_spacing, vertical_spacing):
    total_width = cols * IMAGE_WIDTH_PX + (cols - 1) * horizontal_spacing
    total_height = rows * IMAGE_HEIGHT_PX + (rows - 1) * vertical_spacing

    # Try to load background, otherwise create a white one
    try:
        if os.path.exists(BACKGROUND_IMAGE_PATH):
            background = Image.open(BACKGROUND_IMAGE_PATH).convert('RGB')
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
