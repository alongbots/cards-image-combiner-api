from flask import Flask, request, send_file
from PIL import Image
import requests
import io
import tempfile
import os
import cv2
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

def extract_frame_from_video(video_content, ext=".mp4"):
    """Saves video to a temp file and extracts the first frame."""
    # Use the proper extension from the URL so OpenCV knows how to decode it
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_video:
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
    """Download an image/gif or video frame, preserve transparency, and resize it."""
    try:
        # Use headers and allow redirects to handle 'any' website
        response = requests.get(url, headers=HEADERS, stream=True, timeout=10, allow_redirects=True)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '').lower()
        content = response.content

        # Removed .gif from video_extensions because PIL handles GIFs perfectly
        video_extensions = ('.webm', '.mp4', '.mov', '.avi', '.m4v')
        
        # Extract extension to help cv2
        url_ext = os.path.splitext(url.lower().split('?')[0])[1]
        is_video = 'video' in content_type or url_ext in video_extensions

        img = None
        if is_video:
            ext_to_use = url_ext if url_ext in video_extensions else '.mp4'
            img = extract_frame_from_video(content, ext_to_use)
        
        # If not a video or video frame extraction failed, try opening as an image (PNG, JPG, GIF, WebP)
        if img is None:
            img = Image.open(io.BytesIO(content))
            
            # Ensure we are at the first frame (crucial for animated GIFs / WebP)
            img.seek(0)
            
            # Preserve transparency if present
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                img = img.convert("RGBA")
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

    # Try to load background, convert to RGBA to properly layer transparent images
    try:
        if os.path.exists(BACKGROUND_IMAGE_PATH):
            background = Image.open(BACKGROUND_IMAGE_PATH).convert("RGBA")
            background = background.resize((total_width, total_height))
        else:
            background = Image.new("RGBA", (total_width, total_height), (255, 255, 255, 255))
    except Exception:
        background = Image.new("RGBA", (total_width, total_height), (255, 255, 255, 255))

    grid_image = background

    for idx, url in enumerate(image_urls):
        if idx >= rows * cols:
            break
        
        img = download_and_resize_image(url)
        if img:
            row, col = divmod(idx, cols)
            x_offset = col * (IMAGE_WIDTH_PX + horizontal_spacing)
            y_offset = row * (IMAGE_HEIGHT_PX + vertical_spacing)
            
            # If the image has transparency (RGBA), use itself as a mask to preserve it
            if img.mode == 'RGBA':
                grid_image.paste(img, (x_offset, y_offset), img)
            else:
                grid_image.paste(img, (x_offset, y_offset))

    # Convert back to RGB right before saving if you don't need a transparent final output 
    # (Though PNG supports RGBA, so we can leave it as RGBA)
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
