"""Generate multi-resolution Windows .ico asset from source .png using Pillow.

Ensures independent Lanczos resampling from the 2000x2000 source for each
canonical Windows icon resolution: 16x16, 32x32, 48x48, and 256x256.
Supports header verification (--verify) and debug visual exports (--export-debug).
"""

import argparse
import io
from pathlib import Path
import struct
import sys
from typing import List, Tuple

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PNG = REPO_ROOT / "gui" / "assets" / "icon.png"
DEFAULT_ICO = REPO_ROOT / "gui" / "assets" / "icon.ico"

ICON_SIZES: List[Tuple[int, int]] = [
    (16, 16),
    (32, 32),
    (48, 48),
    (256, 256),
]


def generate_ico(png_path: Path, ico_path: Path) -> Path:
    """Generate multi-resolution .ico from source png using Lanczos resampling."""
    if not png_path.is_file():
        raise FileNotFoundError(f"Source PNG not found at: {png_path}")

    with Image.open(png_path) as src:
        src_rgba = src.convert("RGBA")

        # Resample each target resolution independently from the full-resolution source
        frames = {}
        for size in ICON_SIZES:
            frames[size] = src_rgba.resize(size, Image.Resampling.LANCZOS)

        ico_path.parent.mkdir(parents=True, exist_ok=True)

        # Save multi-resolution ICO with 256x256 as primary and 16, 32, 48 appended
        frames[(256, 256)].save(
            ico_path,
            format="ICO",
            sizes=ICON_SIZES,
            append_images=[frames[(16, 16)], frames[(32, 32)], frames[(48, 48)]],
        )

    print(f"[OK] Generated multi-res icon at: {ico_path} ({ico_path.stat().st_size} bytes)")
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
    parser.add_argument("--png", type=Path, default=DEFAULT_PNG, help="Path to source PNG")
    parser.add_argument("--ico", type=Path, default=DEFAULT_ICO, help="Path to destination ICO")
    parser.add_argument("--verify", action="store_true", help="Verify ICO header and entries")
    parser.add_argument("--export-debug", action="store_true", help="Export upscaled 16x16 and 32x32 previews")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT, help="Directory for debug exports")
    args = parser.parse_args()

    if args.verify:
        success = verify_ico(args.ico)
        sys.exit(0 if success else 1)

    generate_ico(args.png, args.ico)
    verify_ico(args.ico)

    if args.export_debug:
        export_debug_frames(args.ico, args.out_dir)


if __name__ == "__main__":
    main()
