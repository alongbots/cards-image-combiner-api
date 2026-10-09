
from flask import Flask, request, send_file
from PIL import Image, ImageOps, ImageFile
from flask_cors import CORS
from urllib.parse import urlparse, urljoin
from urllib.request import url2pathname
import requests
import io
import os
import cv2
import socket
import ipaddress
import tempfile
import numpy as np

app = Flask(__name__)
CORS(app)

# ---------------- CONFIGURATION ----------------

BACKGROUND_IMAGE_PATH = "./Background_image/ALONGBOTS.jpg"

IMAGE_WIDTH_PX = 576
IMAGE_HEIGHT_PX = 756
HORIZONTAL_SPACING_PX = 14
VERTICAL_SPACING_PX = 20

MAX_IMAGES = 12
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # 20 MB per URL
MAX_URL_LENGTH = 4096
REQUEST_TIMEOUT = (5, 15)

# Pillow can load truncated files when explicitly enabled.
# Leave this disabled for safer, predictable decoding.
ImageFile.LOAD_TRUNCATED_IMAGES = False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "image/avif,image/webp,image/apng,image/svg+xml,"
        "image/*,video/*;q=0.9,*/*;q=0.8"
    ),
}

IMAGE_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".webp", ".bmp",
    ".gif", ".tif", ".tiff", ".ico", ".avif", ".jfif"
)

VIDEO_EXTENSIONS = (
    ".mp4", ".webm", ".mov", ".avi", ".m4v",
    ".mkv", ".mpeg", ".mpg", ".3gp", ".ogv"
)

# ---------------- URL VALIDATION ----------------

def validate_public_url(url):
    """Allow HTTP(S) URLs while blocking private/local destinations."""
    if not url or len(url) > MAX_URL_LENGTH:
        raise ValueError("Invalid or excessively long URL")

    parsed = urlparse(url)

    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("Only HTTP and HTTPS URLs are supported")

    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid URL or embedded credentials")

    hostname = parsed.hostname

    # Block local hostnames.
    if hostname.lower() in ("localhost", "localhost.localdomain"):
        raise ValueError("Local hosts are not allowed")

    try:
        addresses = socket.getaddrinfo(
            hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )

        if not addresses:
            raise ValueError("Hostname could not be resolved")

        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])

            if (
                not ip.is_global
                or ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise ValueError("Private or restricted network address")

    except socket.gaierror:
        raise ValueError("Could not resolve hostname")

    return url


# ---------------- DOWNLOAD CONTENT ----------------

def download_content(url):
    """
    Download content with redirect checks, a timeout,
    and a maximum response size.
    """
    current_url = url

    with requests.Session() as session:
        session.headers.update(HEADERS)

        for _ in range(6):
            validate_public_url(current_url)

            response = session.get(
                current_url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
                stream=True,
            )

            try:
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("Location")

                    if not location:
                        raise ValueError("Redirect has no destination")

                    current_url = urljoin(current_url, location)
                    continue

                response.raise_for_status()

                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > MAX_DOWNLOAD_BYTES:
                            raise ValueError("File exceeds size limit")
                    except ValueError as exc:
                        if str(exc) == "File exceeds size limit":
                            raise

                chunks = []
                total = 0

                for chunk in response.iter_content(64 * 1024):
                    if not chunk:
                        continue

                    total += len(chunk)

                    if total > MAX_DOWNLOAD_BYTES:
                        raise ValueError("File exceeds size limit")

                    chunks.append(chunk)

                content = b"".join(chunks)
                content_type = response.headers.get(
                    "Content-Type", ""
                ).split(";")[0].strip().lower()

                return content, content_type, current_url

            finally:
                response.close()

        raise ValueError("Too many redirects")


# ---------------- VIDEO FRAME EXTRACTION ----------------

def extract_video_frame(content):
    """Extract the first readable frame from a supported video."""
    temp_path = None
    capture = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".video", delete=False
        ) as temp:
            temp.write(content)
            temp_path = temp.name

        capture = cv2.VideoCapture(temp_path)

        if not capture.isOpened():
            return None

        success, frame = capture.read()

        if not success or frame is None:
            return None

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame)

    except Exception as exc:
        print("Video decode error:", exc)
        return None

    finally:
        if capture is not None:
            capture.release()

        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


# ---------------- IMAGE DECODING ----------------

def decode_image(content):
    """
    Decode an image based on its actual file contents,
    not just its extension or the server's Content-Type.
    """
    try:
        with Image.open(io.BytesIO(content)) as source:
            # GIF and animated image formats become a static first frame.
            source.seek(0)
            frame = ImageOps.exif_transpose(source.copy())
            frame.load()

            # Handle transparency against a white background.
            if frame.mode in ("RGBA", "LA") or (
                frame.mode == "P" and "transparency" in frame.info
            ):
                frame = frame.convert("RGBA")
                white = Image.new("RGBA", frame.size, "white")
                white.alpha_composite(frame)
                frame = white.convert("RGB")
            else:
                frame = frame.convert("RGB")

            return frame

    except Exception:
        return None


def download_and_resize_image(url):
    """Download, decode, and resize one image or video."""
    try:
        content, content_type, final_url = download_content(url)

        if not content:
            raise ValueError("Downloaded file is empty")

        path = urlparse(final_url).path.lower()

        looks_like_video = (
            content_type.startswith("video/")
            or path.endswith(VIDEO_EXTENSIONS)
        )

        # Do not classify GIF as video: Pillow handles animated GIFs.
        if looks_like_video:
            image = extract_video_frame(content)
        else:
            image = decode_image(content)

        # Some hosts report an incorrect MIME type.
        # Try image decoding if video decoding did not work.
        if image is None:
            image = decode_image(content)

        if image is None:
            raise ValueError(
                "Unsupported format, corrupt file, or unreadable content"
            )

        # Keep the original proportions and fit within the card dimensions.
        image = ImageOps.fit(
            image,
            (IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

        return image

    except Exception as exc:
        print(f"Skipping URL {url!r}: {exc}")
        return None


# ---------------- GRID GENERATION ----------------

def create_image_grid(
    image_urls,
    rows,
    cols,
    horizontal_spacing,
    vertical_spacing,
):
    total_width = (
        cols * IMAGE_WIDTH_PX
        + (cols - 1) * horizontal_spacing
    )
    total_height = (
        rows * IMAGE_HEIGHT_PX
        + (rows - 1) * vertical_spacing
    )

    try:
        if os.path.exists(BACKGROUND_IMAGE_PATH):
            with Image.open(BACKGROUND_IMAGE_PATH) as source:
                background = source.convert("RGB").resize(
                    (total_width, total_height),
                    Image.Resampling.LANCZOS,
                )
        else:
            background = Image.new(
                "RGB", (total_width, total_height), "white"
            )
    except Exception as exc:
        print("Background loading error:", exc)
        background = Image.new(
            "RGB", (total_width, total_height), "white"
        )

    loaded = 0

    for idx, url in enumerate(image_urls[:rows * cols]):
        image = download_and_resize_image(url)

        # A bad link only leaves its own space empty.
        if image is None:
            continue

        row, col = divmod(idx, cols)

        x = col * (IMAGE_WIDTH_PX + horizontal_spacing)
        y = row * (IMAGE_HEIGHT_PX + vertical_spacing)

        background.paste(image, (x, y))
        loaded += 1

    return background, loaded


# ---------------- API ENDPOINT ----------------

@app.route("/api/combine-images", methods=["GET"])
def combine_images():
    image_urls = [
        request.args.get(f"pic{i}", "").strip()
        for i in range(1, MAX_IMAGES + 1)
    ]

    image_urls = [url for url in image_urls if url]

    if not image_urls:
        return {"error": "No image URLs provided"}, 400

    if any(len(url) > MAX_URL_LENGTH for url in image_urls):
        return {"error": "A URL is too long"}, 400

    rows, cols = 4, 3

    grid_image, loaded = create_image_grid(
        image_urls,
        rows,
        cols,
        HORIZONTAL_SPACING_PX,
        VERTICAL_SPACING_PX,
    )

    output = io.BytesIO()
    grid_image.save(output, format="PNG", optimize=True)
    output.seek(0)

    response = send_file(
        output,
        mimetype="image/png",
        as_attachment=False,
        download_name="alongbots-grid.png",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Images-Loaded"] = str(loaded)

    return response


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
    )
