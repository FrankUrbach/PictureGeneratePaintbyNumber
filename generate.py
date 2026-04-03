import argparse
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from sklearn.cluster import KMeans


MAX_WIDTH = 1000
MIN_REGION_PIXELS = 200  # smaller regions get merged into nearest neighbor


def load_and_prepare(path: str, blur_radius: int = 0) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if w > MAX_WIDTH:
        scale = MAX_WIDTH / w
        img = img.resize((MAX_WIDTH, int(h * scale)), Image.LANCZOS)
    rgb = np.array(img)
    if blur_radius > 0:
        # Gaussian blur before clustering to smooth color transitions
        ksize = blur_radius * 2 + 1  # must be odd
        rgb = cv2.GaussianBlur(rgb, (ksize, ksize), 0)
    return rgb


def reduce_colors(rgb: np.ndarray, n_colors: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (label_image, palette) where palette[i] is the RGB color for label i."""
    h, w, _ = rgb.shape
    pixels = rgb.reshape(-1, 3).astype(np.float64)
    km = KMeans(n_clusters=n_colors, n_init=10, random_state=42)
    labels = km.fit_predict(pixels)
    palette = km.cluster_centers_.astype(np.uint8)
    label_img = labels.reshape(h, w).astype(np.int32)
    return label_img, palette


def remove_small_regions(label_img: np.ndarray, palette: np.ndarray, min_pixels: int) -> np.ndarray:
    """Merge regions smaller than min_pixels into the nearest surrounding label."""
    result = label_img.copy()
    n_colors = palette.shape[0]

    for color_idx in range(n_colors):
        mask = (result == color_idx).astype(np.uint8)
        num, components, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for comp_id in range(1, num):  # 0 is background
            area = stats[comp_id, cv2.CC_STAT_AREA]
            if area < min_pixels:
                comp_mask = (components == comp_id)
                # dilate the component to find its neighbors
                dilated = cv2.dilate(comp_mask.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=3)
                neighbor_mask = dilated.astype(bool) & ~comp_mask
                neighbor_labels = result[neighbor_mask]
                if len(neighbor_labels) == 0:
                    continue
                # pick the most common neighbor label
                counts = np.bincount(neighbor_labels.astype(np.int64), minlength=n_colors)
                counts[color_idx] = 0  # don't reassign to itself
                best = int(np.argmax(counts))
                result[comp_mask] = best

    return result


def smooth_labels(label_img: np.ndarray, radius: int) -> np.ndarray:
    """Smooth region boundaries via median filter on the label image."""
    ksize = radius * 2 + 1  # must be odd
    # cv2.medianBlur requires uint8; labels fit easily within that range (<256 colors)
    return cv2.medianBlur(label_img.astype(np.uint8), ksize).astype(np.int32)


def build_outline(label_img: np.ndarray) -> np.ndarray:
    """Return a binary mask (uint8, 255=border) of region boundaries."""
    border = np.zeros(label_img.shape, dtype=np.uint8)
    for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        shifted = np.roll(label_img, (dy, dx), axis=(0, 1))
        border |= (label_img != shifted).astype(np.uint8)
    return border * 255


def region_centroids(label_img: np.ndarray, n_colors: int) -> dict[int, list[tuple[int, int]]]:
    """Return mapping color_idx -> list of (cx, cy) centroids for each connected component."""
    centroids: dict[int, list[tuple[int, int]]] = {}
    for color_idx in range(n_colors):
        mask = (label_img == color_idx).astype(np.uint8)
        num, components, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        pts = []
        for comp_id in range(1, num):
            area = stats[comp_id, cv2.CC_STAT_AREA]
            cx = stats[comp_id, cv2.CC_STAT_LEFT] + stats[comp_id, cv2.CC_STAT_WIDTH] // 2
            cy = stats[comp_id, cv2.CC_STAT_TOP] + stats[comp_id, cv2.CC_STAT_HEIGHT] // 2
            pts.append((cx, cy, area))
        centroids[color_idx] = pts
    return centroids


def font_size_for_area(area: int) -> int:
    if area < 500:
        return 8
    if area < 2000:
        return 10
    if area < 8000:
        return 13
    return 16


def draw_numbers(outline_img: Image.Image, centroids: dict, color_numbers: dict[int, int]) -> Image.Image:
    draw = ImageDraw.Draw(outline_img)
    for color_idx, regions in centroids.items():
        number = color_numbers[color_idx]
        for cx, cy, area in regions:
            if area < MIN_REGION_PIXELS:
                continue
            size = font_size_for_area(area)
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
            except Exception:
                font = ImageFont.load_default()
            text = str(number)
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text((cx - tw // 2, cy - th // 2), text, fill=0, font=font)
    return outline_img


def generate(input_path: str, n_colors: int, output_dir: str, blur: int = 4) -> None:
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading image: {input_path}")
    rgb = load_and_prepare(input_path, blur_radius=blur)

    print(f"Running K-Means with k={n_colors}…")
    label_img, palette = reduce_colors(rgb, n_colors)

    print("Smoothing region boundaries…")
    label_img = smooth_labels(label_img, radius=blur)

    print("Removing small regions…")
    label_img = remove_small_regions(label_img, palette, MIN_REGION_PIXELS)

    # Assign a display number to each color (1-based)
    color_numbers = {i: i + 1 for i in range(palette.shape[0])}

    # --- preview.png (colored result) ---
    preview_rgb = palette[label_img]
    preview = Image.fromarray(preview_rgb.astype(np.uint8))
    preview.save(os.path.join(output_dir, "preview.png"))
    print("Saved preview.png")

    # --- outline.png (white + black borders + numbers) ---
    border_mask = build_outline(label_img)
    h, w = border_mask.shape
    outline_arr = np.ones((h, w, 3), dtype=np.uint8) * 255
    outline_arr[border_mask == 255] = [0, 0, 0]
    outline_img = Image.fromarray(outline_arr)
    centroids = region_centroids(label_img, palette.shape[0])
    outline_img = draw_numbers(outline_img, centroids, color_numbers)
    outline_img.save(os.path.join(output_dir, "outline.png"))
    print("Saved outline.png")

    # --- palette.json ---
    palette_data = {
        str(color_numbers[i]): "#{:02X}{:02X}{:02X}".format(*palette[i].tolist())
        for i in range(palette.shape[0])
    }
    with open(os.path.join(output_dir, "palette.json"), "w") as f:
        json.dump(palette_data, f, indent=2)
    print("Saved palette.json")
    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert an image to a paint-by-numbers template.")
    parser.add_argument("--input", required=True, help="Path to input image")
    parser.add_argument("--colors", type=int, default=15, help="Number of colors (default: 15)")
    parser.add_argument("--output", default="./output", help="Output directory (default: ./output)")
    parser.add_argument("--blur", type=int, default=4, help="Smoothing radius for edges, 0=off (default: 4)")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    if not (2 <= args.colors <= 64):
        print("Error: --colors must be between 2 and 30", file=sys.stderr)
        sys.exit(1)

    generate(args.input, args.colors, args.output, blur=args.blur)


if __name__ == "__main__":
    main()
