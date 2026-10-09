from flask import Flask, request, send_file
from flask_cors import CORS
from PIL import Image, ImageSequence
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

# Realistic Browser Header
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

def extract_frame_from_video(video_content, ext=".mp4"):
    """Saves video to a temp file, safely closes it, and extracts the first frame."""
    # Use mkstemp to avoid Windows file-locking issues with OpenCV
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
        # Clean up temp file safely
        if os.path.exists(temp_video_path):
            try:
                os.remove(temp_video_path)
            except Exception:
                pass
    
    return None

def process_gif_frame(img):
    """Safely extracts the first frame of a GIF/WebP and preserves perfect transparency."""
    img.seek(0)
    
    # If it's a palette image, we must convert to RGBA carefully to preserve transparency
    if img.mode == 'P':
        img = img.convert('RGBA')
    elif img.mode != 'RGBA':
        img = img.convert('RGBA')
        
    return img

def download_and_resize_image(url):
    """Download an image/gif or video frame, preserve transparency perfectly, and resize it."""
    try:
        response = requests.get(url, headers=HEADERS, stream=True, timeout=10, allow_redirects=True)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '').lower()
        content = response.content
        url_ext = os.path.splitext(url.lower().split('?')[0])[1]

        # Check if it's a video
        video_extensions = ('.webm', '.mp4', '.mov', '.avi', '.m4v')
        is_video = 'video' in content_type or url_ext in video_extensions

        img = None
        if is_video:
            ext_to_use = url_ext if url_ext in video_extensions else '.mp4'
            img = extract_frame_from_video(content, ext_to_use)
        
        # If not a video, handle as Image/GIF/WebP
        if img is None:
            img = Image.open(io.BytesIO(content))
            img = process_gif_frame(img) # Fixes GIF transparency bugs

        if img:
            # Resize using LANCZOS for highest quality
            resized_img = img.resize((IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX), Image.Resampling.LANCZOS)
            return resized_img
            
    except Exception as e:
        print(f"Failed to process {url}: {e}")
        return None
    return None

def create_image_grid(images, horizontal_spacing, vertical_spacing):
    """Creates a dynamically sized grid based on actual successfully loaded images."""
    num_images = len(images)
    if num_images == 0:
        return None

    # Dynamically calculate rows and columns (Max 3 columns)
    cols = min(3, num_images)
    rows = math.ceil(num_images / cols)

    total_width = cols * IMAGE_WIDTH_PX + (cols - 1) * horizontal_spacing
    total_height = rows * IMAGE_HEIGHT_PX + (rows - 1) * vertical_spacing

    # Load and scale background
    try:
        if os.path.exists(BACKGROUND_IMAGE_PATH):
            background = Image.open(BACKGROUND_IMAGE_PATH).convert("RGBA")
            background = background.resize((total_width, total_height), Image.Resampling.LANCZOS)
        else:
            background = Image.new("RGBA", (total_width, total_height), (255, 255, 255, 255))
    except Exception:
        background = Image.new("RGBA", (total_width, total_height), (255, 255, 255, 255))

    grid_image = background

    # Paste images
    for idx, img in enumerate(images):
        row, col = divmod(idx, cols)
        x_offset = col * (IMAGE_WIDTH_PX + horizontal_spacing)
        y_offset = row * (IMAGE_HEIGHT_PX + vertical_spacing)
        
        # Paste using the image itself as a mask to support transparent PNGs/GIFs
        grid_image.paste(img, (x_offset, y_offset), img)

    return grid_image

@app.route('/api/combine-images', methods=['GET'])
def combine_images():
    image_urls = [request.args.get(f'pic{i}') for i in range(1, 13)]
    image_urls = [url for url in image_urls if url]

    if not image_urls:
        return "No images provided", 400

    # MULTI-THREADING: Download up to 12 images at the exact same time
    # This turns a 12-second load time into a 1-2 second load time.
    loaded_images = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        # Keep them in the exact order requested
        results = executor.map(download_and_resize_image, image_urls)
        for img in results:
            if img:
                loaded_images.append(img)

    if not loaded_images:
        return "Failed to load any of the provided images", 400

    # Create grid
    grid_image = create_image_grid(loaded_images, HORIZONTAL_SPACING_PX, VERTICAL_SPACING_PX)

    if not grid_image:
        return "Failed to generate grid", 500

    # Output to Memory
    img_io = io.BytesIO()
    # Save as PNG to maintain overall transparency if needed
    grid_image.save(img_io, 'PNG')
    img_io.seek(0)

    return send_file(img_io, mimetype='image/png')

if __name__ == '__main__':
    # Ensure background directory exists for local testing
    os.makedirs("./Background_image", exist_ok=True)
    app.run(debug=True, port=5000)
