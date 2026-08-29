from flask import Flask, request, send_file
from PIL import Image
import requests
import io
import tempfile
import os
import cv2
import numpy as np
from flask_cors import CORS

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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
}

def extract_frame_from_video(video_content):
    """Saves video to a temp file and extracts the first frame."""
    # Use delete=False because Windows often prevents opening a file that is already open
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_video:
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
            os.remove(temp_video_path)
    
    return None

def download_and_resize_image(url):
    """Download an image or video frame and resize it."""
    try:
        # Use headers and allow redirects to handle 'any' website
        response = requests.get(url, headers=HEADERS, stream=True, timeout=10, allow_redirects=True)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '').lower()
        content = response.content

        # Robust check for video
        video_extensions = ('.webm', '.mp4', '.mov', '.avi', '.m4v', '.gif')
        is_video = 'video' in content_type or url.lower().split('?')[0].endswith(video_extensions)

        img = None
        if is_video:
            img = extract_frame_from_video(content)
        
        # If not a video or video frame extraction failed, try opening as image
        if img is None:
            img = Image.open(io.BytesIO(content))
            # Convert to RGB (handles PNG transparency and WebP)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            else:
                img = img.convert("RGB")

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
