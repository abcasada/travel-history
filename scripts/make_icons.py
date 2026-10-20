"""Generate the PWA icons (no external assets). Run inside the backend dev image:
    docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/repo" -w /repo \
        travel-history-backend-dev python scripts/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path("frontend/public/icons")
BLUE = (29, 78, 216, 255)
WHITE = (255, 255, 255, 255)
SCALE = 4  # draw large, downsample for smooth edges


def draw(size: int, *, maskable: bool) -> Image.Image:
    s = size * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        d.rectangle((0, 0, s, s), fill=BLUE)
        inset = 0.2  # keep the motif inside the maskable safe zone
    else:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=BLUE)
        inset = 0.12

    def p(x: float, y: float) -> tuple[float, float]:
        return (s * (inset + x * (1 - 2 * inset)), s * (inset + y * (1 - 2 * inset)))

    route = [p(0.18, 0.78), p(0.32, 0.55), p(0.52, 0.62), p(0.62, 0.38), p(0.82, 0.22)]
    d.line(route, fill=WHITE, width=int(s * 0.06), joint="curve")
    for x, y, r in ((0.18, 0.78, 0.07), (0.82, 0.22, 0.09)):
        cx, cy = p(x, y)
        rad = s * r
        d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=WHITE)
    cx, cy = p(0.82, 0.22)
    rad = s * 0.04
    d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=BLUE)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw(192, maskable=False).save(OUT / "icon-192.png", optimize=True)
    draw(512, maskable=False).save(OUT / "icon-512.png", optimize=True)
    draw(512, maskable=True).save(OUT / "maskable-512.png", optimize=True)
    draw(180, maskable=True).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    draw(64, maskable=False).save(OUT / "favicon-64.png", optimize=True)


if __name__ == "__main__":
    main()
