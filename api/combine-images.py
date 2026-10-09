from flask import Flask, request, send_file
from flask_cors import CORS
from PIL import Image
import requests
import io
import tempfile
import os
import cv2
import math
import concurrent.futures

app = Flask(__name__)
CORS(app)

# Configuration
BACKGROUND_IMAGE_PATH = "./Background_image/ALONGBOTS.jpg"
SPACING_PX = 20
HORIZONTAL_SPACING_PX = 14
VERTICAL_SPACING_PX = SPACING_PX
IMAGE_WIDTH_PX = 576
IMAGE_HEIGHT_PX = 756

# High-Security Bypass Headers (Crucial for Mazoku CDN)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    # Tells the CDN that the request is coming from their own website to bypass Hotlink protection
    'Referer': 'https://mazoku.cc/', 
}

def extract_frame_from_video(video_content, ext=".mp4"):
    """Saves video to a temp file, safely closes it, and extracts the first frame."""
    fd, temp_video_path = tempfile.mkstemp(suffix=ext)
    with os.fdopen(fd, 'wb') as f:
        f.write(video_content)

    try:
        vidcap = cv2.VideoCapture(temp_video_path)
        success, image = vidcap.read()
        vidcap.release()
        
        if success:
            # Convert BGR (OpenCV) to RGB (PIL)
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            return Image.fromarray(image).convert("RGBA")
    except Exception as e:
        print(f"Error processing video frame: {e}")
    finally:
        if os.path.exists(temp_video_path):
            try:
                os.remove(temp_video_path)
            except Exception:
                pass
    
    return None

def process_gif_frame(img):
    """Safely extracts the first frame of an animated GIF/WebP and preserves perfect transparency."""
    img.seek(0) # Ensure we are grabbing the first frame of the animation
    
    # If the GIF uses a transparency palette (P mode), convert it safely
    if img.mode == 'P':
        img = img.convert('RGBA')
    elif img.mode != 'RGBA':
        img = img.convert('RGBA')
        
    return img

def download_and_resize_image(url):
    """Download, automatically clean the URL, extract frames, and resize perfectly."""
    try:
        # AUTOMATICALLY REMOVE '?width=750' to get the pristine original file
        clean_url = url.split('?')[0]
        
        # Download the file
        response = requests.get(clean_url, headers=HEADERS, stream=True, timeout=10, allow_redirects=True)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '').lower()
        content = response.content
        
        # Extract file extension from the clean URL (.gif, .jpg, .png)
        url_ext = os.path.splitext(clean_url.lower())[1]

        # Check if it's a video file type
        video_extensions = ('.webm', '.mp4', '.mov', '.avi', '.m4v')
        is_video = 'video' in content_type or url_ext in video_extensions

        img = None
        if is_video:
            ext_to_use = url_ext if url_ext in video_extensions else '.mp4'
            img = extract_frame_from_video(content, ext_to_use)
        
        # Handle Still Images & Animated GIFs (.gif, .jpg, .png, .webp)
        if img is None:
            img = Image.open(io.BytesIO(content))
            img = process_gif_frame(img)

        if img:
            # Resize using LANCZOS for the sharpest, highest-quality result for anime cards
            resized_img = img.resize((IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX), Image.Resampling.LANCZOS)
            return resized_img
            
    except Exception as e:
        print(f"Failed to process {url}: {e}")
        return None
    return None

def create_image_grid(images, horizontal_spacing, vertical_spacing):
    """Creates a dynamically sized grid based on actual successfully loaded cards."""
    num_images = len(images)
    if num_images == 0:
        return None

    cols = min(3, num_images)
    rows = math.ceil(num_images / cols)

    total_width = cols * IMAGE_WIDTH_PX + (cols - 1) * horizontal_spacing
    total_height = rows * IMAGE_HEIGHT_PX + (rows - 1) * vertical_spacing

    try:
        if os.path.exists(BACKGROUND_IMAGE_PATH):
            background = Image.open(BACKGROUND_IMAGE_PATH).convert("RGBA")
            background = background.resize((total_width, total_height), Image.Resampling.LANCZOS)
        else:
            background = Image.new("RGBA", (total_width, total_height), (255, 255, 255, 255))
    except Exception:
        background = Image.new("RGBA", (total_width, total_height), (255, 255, 255, 255))

    grid_image = background

    for idx, img in enumerate(images):
        row, col = divmod(idx, cols)
        x_offset = col * (IMAGE_WIDTH_PX + horizontal_spacing)
        y_offset = row * (IMAGE_HEIGHT_PX + vertical_spacing)
        
        # Paste the card using itself as a mask to preserve transparent GIF/PNG backgrounds
        grid_image.paste(img, (x_offset, y_offset), img)

    return grid_image

@app.route('/api/combine-images', methods=['GET'])
def combine_images():
    image_urls = [request.args.get(f'pic{i}') for i in range(1, 13)]
    image_urls = [url for url in image_urls if url]

    if not image_urls:
        return "No images provided", 400

    loaded_images = []
    # Multithreading downloads all cards instantly at the same time
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        results = executor.map(download_and_resize_image, image_urls)
        for img in results:
            if img:
                loaded_images.append(img)

    if not loaded_images:
        return "Failed to load any of the provided images", 400

    grid_image = create_image_grid(loaded_images, HORIZONTAL_SPACING_PX, VERTICAL_SPACING_PX)

    if not grid_image:
        return "Failed to generate grid", 500

    img_io = io.BytesIO()
    grid_image.save(img_io, 'PNG')
    img_io.seek(0)

    return send_file(img_io, mimetype='image/png')

if __name__ == '__main__':
    os.makedirs("./Background_image", exist_ok=True)
    app.run(debug=True, port=5000)
