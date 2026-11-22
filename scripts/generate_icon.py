"""Generate multi-resolution Windows .ico asset from source .png or .svg using Pillow.

Ensures independent Lanczos resampling from the 2048x2048 master source for each
canonical Windows icon resolution: 16x16, 24x24, 32x32, 48x48, 64x64, 128x128, and 256x256.
Applies UnsharpMask sharpening to small frames (<=32px) for crisp rendering in taskbars.
Supports master rasterization (--rasterize), header verification (--verify), and debug
visual exports (--export-debug).
"""

import argparse
import io
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PNG = REPO_ROOT / "assets" / "icon.png"
DEFAULT_ICO = REPO_ROOT / "assets" / "icon.ico"
DEFAULT_SVG = REPO_ROOT / "frontend" / "public" / "favicon.svg"
DEFAULT_FAVICON_ICO = REPO_ROOT / "frontend" / "public" / "favicon.ico"

ICON_SIZES: List[Tuple[int, int]] = [
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
]


def find_chrome() -> Path:
    """Find Chrome or Chromium executable on the host system."""
    for binary in ["chrome", "google-chrome", "chromium", "brave"]:
        found = shutil.which(binary)
        if found:
            return Path(found)

    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for c in candidates:
        if c.is_file():
            return c

    raise FileNotFoundError("Could not locate Google Chrome or Chromium executable.")


def rasterize_svg_to_png(svg_path: Path, target_png: Path, size: int = 2048) -> Path:
    """Rasterize vector SVG to high-res master PNG using headless Chrome."""
    if not svg_path.is_file():
        raise FileNotFoundError(f"Source SVG not found at: {svg_path}")

    chrome_bin = find_chrome()
    svg_content = svg_path.read_text(encoding="utf-8")
    # Ensure SVG viewport scales to full target resolution without fixed-dimension constraints
    scaled_svg = re.sub(
        r'width="\d+"(?:\.\d+)?\s+height="\d+"(?:\.\d+)?',
        'width="100%" height="100%"',
        svg_content,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_svg = Path(tmp_dir) / "render.svg"
        tmp_svg.write_text(scaled_svg, encoding="utf-8")
        target_png.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(chrome_bin),
            "--headless=new",
            f"--screenshot={target_png.resolve()}",
            f"--window-size={size},{size}",
            "--hide-scrollbars",
            "--default-background-color=00000000",
            tmp_svg.as_uri(),
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)

    with Image.open(target_png) as img:
        if img.size != (size, size):
            raise ValueError(f"Rasterized image size {img.size} does not match expected ({size}, {size})")
        if img.mode != "RGBA":
            img.convert("RGBA").save(target_png, format="PNG")

    print(f"[OK] Rasterized master icon at: {target_png} ({size}x{size} RGBA)")
    return target_png


def compose_master_icon(source_png: Path, target_png: Path) -> Path:
    """Composite logo onto rounded dark WinUI 3 canvas using 2x supersampling.

    Renders a 4096x4096 rounded rectangle (fill (32, 32, 32, 255), radius 768),
    composites the source logo resampled with Lanczos, and downsamples
    with Lanczos to 2048x2048 master PNG.
    """
    if not source_png.is_file():
        raise FileNotFoundError(f"Source PNG not found at: {source_png}")

    target_res = 4096
    canvas = Image.new("RGBA", (target_res, target_res), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([0, 0, target_res - 1, target_res - 1], radius=768, fill=(32, 32, 32, 255))

    with Image.open(source_png) as src:
        logo = src.convert("RGBA")
        if logo.size != (target_res, target_res):
            logo = logo.resize((target_res, target_res), Image.Resampling.LANCZOS)
        canvas.alpha_composite(logo)

    master = canvas.resize((2048, 2048), Image.Resampling.LANCZOS)
    target_png.parent.mkdir(parents=True, exist_ok=True)
    master.save(target_png, format="PNG")
    print(f"[OK] Generated master icon at: {target_png} ({master.size[0]}x{master.size[1]})")
    return target_png


def generate_ico(
    png_path: Path,
    ico_path: Path,
    favicon_path: Optional[Path] = DEFAULT_FAVICON_ICO,
) -> Path:
    """Generate multi-resolution .ico from source png using Lanczos and UnsharpMask."""
    if not png_path.is_file():
        raise FileNotFoundError(f"Source PNG not found at: {png_path}")

    with Image.open(png_path) as src:
        src_rgba = src.convert("RGBA")

        # Resample each target resolution independently from the full-resolution source
        frames = {}
        for size in ICON_SIZES:
            frame = src_rgba.resize(size, Image.Resampling.LANCZOS)
            if size[0] <= 32:
                frame = frame.filter(ImageFilter.UnsharpMask(radius=0.6, percent=70, threshold=2))
            frames[size] = frame

        ico_path.parent.mkdir(parents=True, exist_ok=True)

        # Save multi-resolution ICO with 256x256 as primary and remaining sizes appended
        append_frames = [frames[s] for s in ICON_SIZES if s != (256, 256)]
        frames[(256, 256)].save(
            ico_path,
            format="ICO",
            sizes=ICON_SIZES,
            append_images=append_frames,
        )

    print(f"[OK] Generated multi-res icon at: {ico_path} ({ico_path.stat().st_size} bytes)")

    if favicon_path is not None:
        favicon_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ico_path, favicon_path)
        print(f"[OK] Copied favicon.ico to: {favicon_path} ({favicon_path.stat().st_size} bytes)")

    return ico_path


def verify_ico(ico_path: Path) -> bool:
    """Inspect and verify ICO binary header and resolution directory entries."""
    if not ico_path.is_file():
        print(f"[FAIL] ICO file does not exist: {ico_path}")
        return False

    raw = ico_path.read_bytes()
    if len(raw) < 6:
        print(f"[FAIL] ICO file too small: {len(raw)} bytes")
        return False

    reserved, ico_type, count = struct.unpack("<HHH", raw[:6])
    if reserved != 0 or ico_type != 1:
        print(f"[FAIL] Invalid ICO header: reserved={reserved}, type={ico_type}")
        return False

    print(f"ICO Header: Type=1 (ICO), Total Directory Entries={count}")
    expected_sizes = set(ICON_SIZES)
    found_sizes = set()

    for i in range(count):
        offset = 6 + i * 16
        entry = raw[offset : offset + 16]
        w, h, colors, res, planes, bpp, size_bytes, img_offset = struct.unpack("<BBBBHHII", entry)
        actual_w = 256 if w == 0 else w
        actual_h = 256 if h == 0 else h
        found_sizes.add((actual_w, actual_h))
        print(f"  Entry {i}: {actual_w}x{actual_h}, bpp={bpp}, size={size_bytes}B, offset={img_offset}")

    if not expected_sizes.issubset(found_sizes):
        print(f"[FAIL] Missing expected sizes! Found: {found_sizes}, Expected: {expected_sizes}")
        return False

    print(f"[PASS] ICO verified successfully: contains all expected resolutions {sorted(found_sizes)}")
    return True


def export_debug_frames(ico_path: Path, out_dir: Path) -> List[Path]:
    """Extract 16x16 and 32x32 frames directly from ICO binary and upscale via nearest-neighbor."""
    if not ico_path.is_file():
        raise FileNotFoundError(f"ICO file not found: {ico_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    exported = []

    raw = ico_path.read_bytes()
    reserved, ico_type, count = struct.unpack("<HHH", raw[:6])

    extracted_frames = {}
    for i in range(count):
        offset = 6 + i * 16
        w, h, colors, res, planes, bpp, size_bytes, img_offset = struct.unpack("<BBBBHHII", raw[offset : offset + 16])
        actual_w = 256 if w == 0 else w
        actual_h = 256 if h == 0 else h
        frame_bytes = raw[img_offset : img_offset + size_bytes]
        frame_img = Image.open(io.BytesIO(frame_bytes))
        extracted_frames[(actual_w, actual_h)] = frame_img

    for target_size in [(16, 16), (32, 32)]:
        frame = extracted_frames.get(target_size)
        if frame is None:
            raise ValueError(f"Target size {target_size} not found in ICO binary!")

        upscaled = frame.resize((256, 256), Image.Resampling.NEAREST)
        out_file = out_dir / f"debug_icon_{target_size[0]}.png"
        upscaled.save(out_file)
        exported.append(out_file)
        print(f"[OK] Extracted and exported debug preview: {out_file} (extracted {target_size[0]}x{target_size[1]} -> 256x256)")

    return exported


def main() -> None:
    """CLI entry point for icon generator."""
    parser = argparse.ArgumentParser(description="Generate and verify AksaraSight Windows ICO asset.")
    parser.add_argument("--svg", type=Path, default=DEFAULT_SVG, help="Path to source vector SVG for rasterization")
    parser.add_argument("--source", "--src-png", dest="src_png", type=Path, default=None, help="Path to source logo PNG for composition")
    parser.add_argument("--png", type=Path, default=DEFAULT_PNG, help="Path to destination/intermediate master PNG")
    parser.add_argument("--ico", type=Path, default=DEFAULT_ICO, help="Path to destination ICO")
    parser.add_argument("--favicon-ico", type=Path, default=DEFAULT_FAVICON_ICO, help="Path to frontend favicon ICO")
    parser.add_argument("--rasterize", action="store_true", help="Force master PNG rasterization from SVG")
    parser.add_argument("--compose", action="store_true", help="Force master icon PNG composition before ICO generation")
    parser.add_argument("--verify", action="store_true", help="Verify ICO header and entries")
    parser.add_argument("--export-debug", action="store_true", help="Export upscaled 16x16 and 32x32 previews")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT, help="Directory for debug exports")
    args = parser.parse_args()

    if args.verify:
        success = verify_ico(args.ico)
        sys.exit(0 if success else 1)

    if args.rasterize or (not args.png.is_file() and args.svg.is_file()):
        rasterize_svg_to_png(args.svg, args.png)
    elif args.compose or (args.src_png and args.src_png.is_file() and args.src_png.resolve() != args.png.resolve()):
        compose_master_icon(args.src_png or args.png, args.png)

    generate_ico(args.png, args.ico, favicon_path=args.favicon_ico)
    verify_ico(args.ico)

    if args.export_debug:
        export_debug_frames(args.ico, args.out_dir)


if __name__ == "__main__":
    main()
