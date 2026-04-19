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
OUTPUT_SCALE = 2         # outline.png and preview.png are rendered at this multiplier
REPEAT_AREA_THRESHOLD = 15000  # original pixels; larger regions get a grid of numbers


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


def build_outline_aa(label_img: np.ndarray, scale: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Scale up label_img by `scale` (nearest-neighbor) and return:
    - border_aa: float32 array [0..255], anti-aliased border mask at high resolution
    - scaled_label: int32 scaled label image (same resolution as border_aa)
    """
    h, w = label_img.shape
    sh, sw = h * scale, w * scale

    # Scale label image: nearest-neighbor preserves exact label values
    scaled = cv2.resize(label_img.astype(np.uint8), (sw, sh),
                        interpolation=cv2.INTER_NEAREST).astype(np.int32)

    # Detect 1px borders where adjacent labels differ
    border = np.zeros((sh, sw), dtype=np.uint8)
    for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        shifted = np.roll(scaled, (dy, dx), axis=(0, 1))
        border |= (scaled != shifted).astype(np.uint8)

    # Anti-alias: gentle Gaussian blur softens the hard pixel edges
    border_float = border.astype(np.float32) * 255.0
    border_aa = cv2.GaussianBlur(border_float, (3, 3), 0.8)

    # Normalize so peak stays at 255
    max_val = border_aa.max()
    if max_val > 0:
        border_aa = border_aa * (255.0 / max_val)

    return border_aa, scaled


def compute_number_placements(
    label_img: np.ndarray, n_colors: int, scale: int
) -> tuple[dict[int, list[tuple[int, int, float]]], set[int]]:
    """
    Return (placements, numberless_idxs).

    placements: color_idx -> [(sx, sy, max_r_scaled), ...] at scaled coordinates.
    numberless_idxs: color indices where at least one connected component was too
    thin to receive a number (max inscribed radius < MIN_RADIUS).

    Placement uses the distance transform: each number sits at the deepest interior
    point of a region. Large regions (>= REPEAT_AREA_THRESHOLD) get a grid so
    every sub-area has its own number.
    """
    MIN_RADIUS = 4  # original pixels; thinner regions get no number

    placements: dict[int, list[tuple[int, int, float]]] = {}
    numberless_idxs: set[int] = set()

    for color_idx in range(n_colors):
        mask = (label_img == color_idx).astype(np.uint8)
        dist_full = cv2.distanceTransform(mask, cv2.DIST_L2, 5)

        num, components, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        pts: list[tuple[int, int, float]] = []
        for comp_id in range(1, num):
            area = stats[comp_id, cv2.CC_STAT_AREA]
            if area < MIN_REGION_PIXELS:
                continue

            bx = stats[comp_id, cv2.CC_STAT_LEFT]
            by = stats[comp_id, cv2.CC_STAT_TOP]
            bw = stats[comp_id, cv2.CC_STAT_WIDTH]
            bh = stats[comp_id, cv2.CC_STAT_HEIGHT]

            comp_mask = (components == comp_id).astype(np.uint8)
            dist = dist_full * comp_mask

            if area >= REPEAT_AREA_THRESHOLD:
                grid_cols = max(2, bw // 150)
                grid_rows = max(2, bh // 150)
                step_x = bw // grid_cols
                step_y = bh // grid_rows
                placed = False
                for row in range(grid_rows):
                    for col in range(grid_cols):
                        x0 = bx + col * step_x
                        y0 = by + row * step_y
                        x1 = min(x0 + step_x, bx + bw)
                        y1 = min(y0 + step_y, by + bh)
                        cell = dist[y0:y1, x0:x1]
                        local_max = float(cell.max())
                        if local_max < MIN_RADIUS:
                            continue
                        loc = np.unravel_index(cell.argmax(), cell.shape)
                        lx, ly = x0 + loc[1], y0 + loc[0]
                        pts.append((lx * scale, ly * scale, local_max * scale))
                        placed = True
                if not placed:
                    _, max_r, _, max_loc = cv2.minMaxLoc(dist)
                    if max_r >= MIN_RADIUS:
                        pts.append((max_loc[0] * scale, max_loc[1] * scale, float(max_r) * scale))
                    else:
                        numberless_idxs.add(color_idx)
            else:
                _, max_r, _, max_loc = cv2.minMaxLoc(dist)
                if max_r < MIN_RADIUS:
                    numberless_idxs.add(color_idx)
                    continue
                pts.append((max_loc[0] * scale, max_loc[1] * scale, float(max_r) * scale))

        placements[color_idx] = pts
    return placements, numberless_idxs


def font_size_for_radius(max_r_scaled: float, scale: int) -> int:
    """
    Derive font size from the inscribed-circle radius at scaled resolution.
    The number height is set to 75 % of the available diameter, clamped so
    numbers are always legible (min) but don't overflow narrow regions (max).
    """
    size = int(max_r_scaled * 2 * 0.75)
    return max(12 * scale, min(40 * scale, size))


def draw_numbers(
    outline_img: Image.Image,
    placements: dict[int, list[tuple[int, int, float]]],
    color_numbers: dict[int, int],
    scale: int,
) -> Image.Image:
    img_w, img_h = outline_img.size
    draw = ImageDraw.Draw(outline_img)
    for color_idx, regions in placements.items():
        number = color_numbers[color_idx]
        for sx, sy, max_r_scaled in regions:
            size = font_size_for_radius(max_r_scaled, scale)
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
            except Exception:
                font = ImageFont.load_default()
            text = str(number)
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            # Center on placement point, then clamp so the full text stays inside
            tx = max(0, min(sx - tw // 2, img_w - tw))
            ty = max(0, min(sy - th // 2, img_h - th))
            draw.text((tx, ty), text, fill=0, font=font)
    return outline_img


def generate(input_path: str, n_colors: int, output_dir: str, blur: int = 4, scale: int = OUTPUT_SCALE) -> list[int]:
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

    # --- preview.png (colored result, scaled up for crisp display) ---
    preview_rgb = palette[label_img]
    h, w = label_img.shape
    preview = Image.fromarray(preview_rgb.astype(np.uint8))
    preview = preview.resize((w * scale, h * scale), Image.LANCZOS)
    preview.save(os.path.join(output_dir, "preview.png"))
    print("Saved preview.png")

    # --- outline.png (anti-aliased borders + numbers, high resolution) ---
    print("Building anti-aliased outline…")
    border_aa, _ = build_outline_aa(label_img, scale)
    sh, sw = border_aa.shape

    # Compose: white background blended with anti-aliased black border
    alpha = border_aa / 255.0  # [0..1]; 1 = full black border
    outline_arr = np.ones((sh, sw, 3), dtype=np.float32) * 255.0
    for c in range(3):
        outline_arr[:, :, c] *= (1.0 - alpha)
    outline_img = Image.fromarray(np.clip(outline_arr, 0, 255).astype(np.uint8))

    placements, numberless_idxs = compute_number_placements(label_img, palette.shape[0], scale)
    outline_img = draw_numbers(outline_img, placements, color_numbers, scale)
    outline_img.save(os.path.join(output_dir, "outline.png"))
    print("Saved outline.png")

    # --- regions.png (scaled up with nearest-neighbor to match outline/preview resolution) ---
    # Nearest-neighbor preserves exact color-number values (no interpolation blending).
    regions_arr = np.vectorize(color_numbers.get)(label_img).astype(np.uint8)
    regions_img = Image.fromarray(regions_arr)
    regions_img = regions_img.resize((w * scale, h * scale), Image.NEAREST)
    regions_img.save(os.path.join(output_dir, "regions.png"))
    print("Saved regions.png")

    # --- palette.json ---
    palette_data = {
        str(color_numbers[i]): "#{:02X}{:02X}{:02X}".format(*palette[i].tolist())
        for i in range(palette.shape[0])
    }
    with open(os.path.join(output_dir, "palette.json"), "w") as f:
        json.dump(palette_data, f, indent=2)
    print("Saved palette.json")

    numberless = sorted(color_numbers[i] for i in numberless_idxs)
    if numberless:
        print(f"Regions without number (too thin): color numbers {numberless}")
    print("Done.")
    return numberless


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert an image to a paint-by-numbers template.")
    parser.add_argument("--input", required=True, help="Path to input image")
    parser.add_argument("--colors", type=int, default=15, help="Number of colors (default: 15)")
    parser.add_argument("--output", default="./output", help="Output directory (default: ./output)")
    parser.add_argument("--blur", type=int, default=4, help="Smoothing radius for edges, 0=off (default: 4)")
    parser.add_argument("--scale", type=int, default=OUTPUT_SCALE,
                        help=f"Output resolution multiplier for outline/preview (default: {OUTPUT_SCALE})")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    if not (2 <= args.colors <= 64):
        print("Error: --colors must be between 2 and 30", file=sys.stderr)
        sys.exit(1)

    numberless = generate(args.input, args.colors, args.output, blur=args.blur, scale=args.scale)
    if numberless:
        print(f"Note: color numbers {numberless} have regions too thin to print a number.")


if __name__ == "__main__":
    main()
