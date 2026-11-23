"""Preview images and videos of the Blender Extensions listing, from the pictures of site/images.

extensions.blender.org shows previews in a 16:9 frame: each picture is padded to 16:9 on a dark
background, at its own resolution (no upscaling). Videos stay mp4 (gif is not accepted).

    python3 addon/listing/build_previews.py   ->  addon/listing/previews/

The cover (featured.png) and the icon (icon.png) are exported from cover.vectorcraft, not here.
"""
import shutil
import subprocess
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
IMAGES = HERE.parents[1] / "site" / "images"
OUT = HERE / "previews"
BG = (29, 29, 29)

# (output name, source in site/images); the order is the order of the listing
PREVIEWS = [
    ("02-chrono-hud.mp4", "showcase-chrono-hud.mp4"),
    ("03-metaball-symphony.mp4", "showcase-metaball-symphony.mp4"),
    ("04-differential-growth.mp4", "showcase-differential-growth.mp4"),
    ("05-reaction-diffusion.mp4", "showcase-reaction-diffusion.mp4"),
    ("06-tuple-tiles-nodes.png", "tuple-tiles-nodes.png"),
    ("07-tuple-tiles.png", "showcase-tuple-tiles.png"),
    ("08-sdf2d.png", "sdf2d.png"),
    ("09-curves2d.png", "curves2d.png"),
    ("10-patterns2d.png", "patterns2d.png"),
    ("11-qc.png", "qc.png"),
    ("12-stmap.png", "stmap.png"),
]


def frame(w, h):
    """The smallest 16:9 frame, in even pixels, that holds w x h."""
    if w * 9 >= h * 16:
        fw, fh = w, -(-w * 9 // 16)
    else:
        fw, fh = -(-h * 16 // 9), h
    return fw + fw % 2, fh + fh % 2


def image(src, dst):
    im = Image.open(src).convert("RGB")
    fw, fh = frame(*im.size)
    out = Image.new("RGB", (fw, fh), BG)
    out.paste(im, ((fw - im.width) // 2, (fh - im.height) // 2))
    out.save(dst, optimize=True)


def video(src, dst):
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(src)],
                           check=True, capture_output=True, text=True).stdout
    w, h = (int(v) for v in probe.strip().split(","))
    fw, fh = frame(w, h)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf",
                    f"pad={fw}:{fh}:(ow-iw)/2:(oh-ih)/2:color=0x1d1d1d", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "18", "-an", "-movflags", "+faststart", str(dst)],
                   check=True)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copy(HERE / "featured.png", OUT / "01-cover.png")
    for name, source in PREVIEWS:
        (video if name.endswith(".mp4") else image)(IMAGES / source, OUT / name)
    for path in sorted(OUT.iterdir()):
        print(f"{path.name}: {path.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
