"""Draw the profile of crater_profile (step 2 of the lunar ground tutorial) as an SVG.

  python3 examples/tutorials/lunar_ground/profile.py

The three curves and their blend use the defaults of crater_profile and the smooth minimum of
Blender's Math node, so the figure is the graph's own curve: site/images/tutorials/lunar-ground-profile.svg.
"""

from pathlib import Path

FLOOR, RIM_WIDTH, RIM_STEEPNESS, SMOOTHNESS = -0.6, 0.5, 0.8, 0.25
OUT = Path(__file__).resolve().parents[3] / "site" / "images" / "tutorials" / "lunar-ground-profile.svg"


def smooth_min(a, b, k):
    """Math node, Smooth Minimum."""
    h = max(k - abs(a - b), 0.0) / k
    return min(a, b) - h * h * h * k / 6.0


def smooth_max(a, b, k):
    return -smooth_min(-a, -b, k)


def bowl(x):
    return x * x - 1.0


def rim(x):
    outside = min(x - 1.0 - RIM_WIDTH, 0.0)
    return RIM_STEEPNESS * outside * outside


def crater(x):
    return smooth_min(smooth_max(bowl(x), FLOOR, SMOOTHNESS), rim(x), SMOOTHNESS)


W, H, LEFT, RIGHT, TOP, BOTTOM = 720, 330, 56, 20, 24, 44
X0, X1, Y0, Y1 = 0.0, 2.0, -1.1, 0.5


def sx(x):
    return LEFT + (x - X0) / (X1 - X0) * (W - LEFT - RIGHT)


def sy(y):
    return TOP + (Y1 - y) / (Y1 - Y0) * (H - TOP - BOTTOM)


def path(f, lo=X0, hi=X1, n=200):
    pts = []
    for i in range(n + 1):
        x = lo + (hi - lo) * i / n
        y = max(min(f(x), Y1), Y0)
        pts.append(f"{sx(x):.1f},{sy(y):.1f}")
    return "M" + " L".join(pts)


def main():
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="12">',
        f'<rect width="{W}" height="{H}" rx="6" fill="#161920"/>',
    ]
    # Grid: heights every 0.5, distances every 0.5 radius
    for y in (-1.0, -0.5, 0.0, 0.5):
        parts.append(f'<line x1="{LEFT}" x2="{W - RIGHT}" y1="{sy(y):.1f}" y2="{sy(y):.1f}" stroke="#262b36"/>')
        parts.append(f'<text x="{LEFT - 8}" y="{sy(y) + 4:.1f}" fill="#939ab0" text-anchor="end">{y:+.1f}</text>')
    for x in (0.0, 0.5, 1.0, 1.5, 2.0):
        parts.append(f'<line x1="{sx(x):.1f}" x2="{sx(x):.1f}" y1="{TOP}" y2="{H - BOTTOM}" stroke="#262b36"/>')
        parts.append(f'<text x="{sx(x):.1f}" y="{H - BOTTOM + 18}" fill="#939ab0" text-anchor="middle">{x:g}</text>')
    parts.append(f'<text x="{W - RIGHT}" y="{H - 6}" fill="#939ab0" text-anchor="end">x: distance to the centre, in radii</text>')
    # The three curves, then the crater they make
    curves = [
        (path(bowl, 0.0, 1.22), "#79c0ff", "bowl = x² − 1", 0.04, -0.8),
        (path(lambda x: FLOOR), "#f2cc60", "floor_depth", 1.62, FLOOR - 0.08),
        (path(rim, 0.72, 2.0), "#ff7b72", "rim", 1.3, 0.2),
    ]
    for d, color, label, lx, ly in curves:
        parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.5" stroke-dasharray="5 4"/>')
        parts.append(f'<text x="{sx(lx):.1f}" y="{sy(ly):.1f}" fill="{color}">{label}</text>')
    parts.append(f'<path d="{path(crater)}" fill="none" stroke="#e6e9ef" stroke-width="3"/>')
    parts.append(f'<text x="{sx(1.62):.1f}" y="{sy(0.0) - 8:.1f}" fill="#e6e9ef">height</text>')
    parts.append("</svg>")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


main()
