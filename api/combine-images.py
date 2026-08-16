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

BACKGROUND_IMAGE_PATH = "./Background_image/ALONGBOTS.jpg"
SPACING_PX = 20
HORIZONTAL_SPACING_PX = 14
VERTICAL_SPACING_PX = SPACING_PX

IMAGE_WIDTH_PX = 576
IMAGE_HEIGHT_PX = 756

def extract_frame_from_video(video_content):
    """Saves video to a temp file and extracts the first frame."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_video:
        temp_video.write(video_content)
        temp_video_path = temp_video.name

    try:
        vidcap = cv2.VideoCapture(temp_video_path)
        success, image = vidcap.read()
        vidcap.release()
        os.remove(temp_video_path) # Clean up video file immediately

        if success:
            # Convert BGR (OpenCV) to RGB (PIL)
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            return Image.fromarray(image)
    except Exception as e:
        print(f"Error processing video frame: {e}")
    
    return None

def download_and_resize_image(url):
    """Download an image or video frame and resize it."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').lower()
        content = response.content

        # Check if the content is a video
        video_extensions = ('.webm', '.mp4', '.mov', '.avi', '.m4v')
        is_video = 'video' in content_type or url.lower().endswith(video_extensions)

        if is_video:
            img = extract_frame_from_video(content)
        else:
            img = Image.open(io.BytesIO(content))
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

    try:
        background = Image.open(BACKGROUND_IMAGE_PATH)
        background = background.resize((total_width, total_height))
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
    # Supports up to 12 images/videos via pic1, pic2... query params
    image_urls = [request.args.get(f'pic{i}') for i in range(1, 13)]
    image_urls = [url for url in image_urls if url]

    if not image_urls:
        return "No images provided", 400

    rows, cols = 4, 3
    grid_image = create_image_grid(image_urls, rows, cols, HORIZONTAL_SPACING_PX, VERTICAL_SPACING_PX)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
        temp_path = temp_file.name
        grid_image.save(temp_path)

    response = send_file(temp_path, mimetype='image/png')

    @response.call_on_close
    def cleanup_temp_file():
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return response

if __name__ == '__main__':
    app.run(debug=True)
