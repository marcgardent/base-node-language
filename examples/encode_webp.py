"""Encode a folder of frame_%04d.png as an animated WebP that loops for ever, with Pillow.

  python3 -I examples/encode_webp.py FRAMES_DIR OUT.webp [FPS] [QUALITY]

The render scripts run it with the system Python, Blender's having no Pillow. ffmpeg's libwebp_anim
left faint square blocks on dark, flat backgrounds; Pillow's encoder does not.
"""

import sys
from pathlib import Path

from PIL import Image


def main():
    frames_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    fps = int(sys.argv[3]) if len(sys.argv) > 3 else 24
    quality = int(sys.argv[4]) if len(sys.argv) > 4 else 80
    frames = [Image.open(p).convert("RGB") for p in sorted(frames_dir.glob("frame_*.png"))]
    if not frames:
        sys.exit(f"no frame_*.png in {frames_dir}")
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=round(1000 / fps), loop=0,
                   quality=quality, method=6)
    print("Encoded WebP:", out, out.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
