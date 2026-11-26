"""Tegner appens ikon (packaging/icon.ico): hvidt hjerte på en magenta→pink flade i Byens IT-farver.
Kræver Pillow (er i requirements-build.txt). Køres af build_windows.ps1, når icon.ico mangler."""
import math
from pathlib import Path

from PIL import Image, ImageDraw

SIZE, SS = 256, 4                          # tegnes i 4x størrelse og skaleres ned = bløde kanter
TOP, BOTTOM = (186, 1, 196), (240, 69, 143)   # #ba01c4 → #f0458f


def icon() -> Image.Image:
    big = SIZE * SS
    gradient = Image.new("RGBA", (big, big))
    draw = ImageDraw.Draw(gradient)
    for y in range(big):   # diagonal-agtig overgang: lodret er nok i så lille et ikon
        t = y / (big - 1)
        draw.line([(0, y), (big, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)) + (255,))

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * 0.22), fill=255)
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(gradient, (0, 0), mask)

    # Hjertekurven: x = 16 sin³t, y = 13 cos t − 5 cos 2t − 2 cos 3t − cos 4t
    scale, cx, cy = big / 44, big / 2, big * 0.47
    points = [(cx + scale * 16 * math.sin(t) ** 3,
               cy - scale * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
              for t in (i * 2 * math.pi / 720 for i in range(720))]
    ImageDraw.Draw(out).polygon(points, fill=(255, 255, 255, 255))
    return out.resize((SIZE, SIZE), Image.LANCZOS)


if __name__ == "__main__":
    path = Path(__file__).with_name("icon.ico")
    icon().save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Skrev {path}")
