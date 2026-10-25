"""Draws overlay/icon.png (1024 px) and overlay/icon.ico with code, no stock art: a smoked-glass tile, one glass
card with the recognised-mint dot, and the four-point AI sparkle. icon.icns comes from sips + iconutil (see README).

    UV_PROJECT_ENVIRONMENT=$HOME/Developer/hacktx/.venv uv run --no-sync python overlay/make-icon.py
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
SIZE, SCALE = 1024, 4  # drawn at 4x and shrunk, so every edge is smooth
S = SIZE * SCALE


def bezier(p0, p1, p2, p3, steps=48):
    return [tuple(((1 - t) ** 3) * a + 3 * ((1 - t) ** 2) * t * b + 3 * (1 - t) * (t**2) * c + (t**3) * d for a, b, c, d in zip(p0, p1, p2, p3))
            for t in (i / steps for i in range(steps + 1))]


def sparkle(cx, cy, r):
    """The overlay's four-point sparkle (index.html #sparkle), as a polygon around (cx, cy) with radius r."""
    pts = []
    for i in range(4):
        # each arm: from one tip, a concave curve to the next tip, pulled toward the centre
        a0, a1 = math.pi / 2 * i - math.pi / 2, math.pi / 2 * (i + 1) - math.pi / 2
        tip0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
        tip1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
        pull = 0.2
        c0 = (cx + r * pull * math.cos(a0), cy + r * pull * math.sin(a0))
        c1 = (cx + r * pull * math.cos(a1), cy + r * pull * math.sin(a1))
        pts += bezier(tip0, c0, c1, tip1)
    return pts


def rounded(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    pad = int(S * 0.10)  # macOS icons keep a margin inside the canvas
    tile = (pad, pad, S - pad, S - pad)
    radius = int((S - 2 * pad) * 0.225)

    # the tile: deep smoke with a soft light falling in from the top left
    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    rounded(d, tile, radius, fill=(20, 22, 28, 255))
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((pad - S * 0.25, pad - S * 0.35, pad + S * 0.75, pad + S * 0.45), fill=(96, 110, 140, 150))
    g.ellipse((S * 0.45, S * 0.55, S * 1.2, S * 1.25), fill=(126, 226, 176, 40))
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.09))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(tile, radius=radius, fill=255)
    base.alpha_composite(Image.composite(glow, Image.new("RGBA", (S, S), (0, 0, 0, 0)), mask))
    d = ImageDraw.Draw(base)
    rounded(d, tile, radius, outline=(255, 255, 255, 46), width=int(S * 0.004))
    img.alpha_composite(base)

    # one glass name card, as beside a face in a call
    w, h = S * 0.50, S * 0.30
    cx, cy = S * 0.50, S * 0.56
    card = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    rounded(ld, card, int(h * 0.19), fill=(255, 255, 255, 30), outline=(255, 255, 255, 70), width=int(S * 0.004))
    # the recognised dot and two text lines
    dot_r = h * 0.06
    dx, dy = card[0] + w * 0.12, card[1] + h * 0.30
    ld.ellipse((dx - dot_r, dy - dot_r, dx + dot_r, dy + dot_r), fill=(126, 226, 176, 255))
    line_h = h * 0.085
    ld.rounded_rectangle((dx + dot_r * 2.6, dy - line_h / 2, card[0] + w * 0.62, dy + line_h / 2), radius=line_h / 2, fill=(255, 255, 255, 235))
    for i, frac in enumerate((0.78, 0.56)):
        y = card[1] + h * (0.56 + 0.18 * i)
        ld.rounded_rectangle((card[0] + w * 0.12, y - line_h / 2.6, card[0] + w * frac, y + line_h / 2.6), radius=line_h / 2, fill=(255, 255, 255, 120))
    img.alpha_composite(layer)

    # the AI sparkle, floating off the card's top-right corner, with a soft halo
    sx, sy, sr = card[2] - w * 0.02, card[1] - h * 0.02, S * 0.115
    halo = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(halo).polygon(sparkle(sx, sy, sr * 1.25), fill=(255, 255, 255, 110))
    img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(S * 0.02)))
    star = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(star).polygon(sparkle(sx, sy, sr), fill=(255, 255, 255, 255))
    ImageDraw.Draw(star).polygon(sparkle(sx - sr * 1.15, sy - sr * 0.95, sr * 0.36), fill=(255, 255, 255, 255))
    img.alpha_composite(star)

    out = img.resize((SIZE, SIZE), Image.LANCZOS)
    out.save(HERE / "icon.png")
    out.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote icon.png and icon.ico")


if __name__ == "__main__":
    main()
