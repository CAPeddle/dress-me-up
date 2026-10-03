"""Synthetic pages and cutouts the tests run against, with no pytest in sight.

A module of its own rather than helpers on `conftest`, because a test that does
`from conftest import ...` is reaching for whichever file pytest happened to bind
that name to first -- and with more than one test directory, that is decided by
the alphabet. Importing them from here says which module is meant.
"""

from PIL import Image, ImageDraw


def make_item_image(width=300, height=400, alpha=255, margin=40):
    """An RGBA cutout: transparent margin around a solid, fully opaque body."""
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle([margin, margin, width - margin, height - margin], fill=(180, 60, 90, alpha))
    return image


def make_border_doll_page():
    """The orientation tests' doll page: a figure between two bleeding border strips.

    Head-heavy and shoulder-wide on purpose. Shared with the triage tests so that
    the page both stages are pinned against is literally the same one.
    """
    page = Image.new("RGB", (660, 700), "white")
    draw = ImageDraw.Draw(page)
    draw.rectangle([0, 0, 90, 700], fill=(60, 110, 70))      # decoration, off the left edge
    draw.rectangle([570, 0, 660, 700], fill=(70, 90, 140))   # decoration, off the right edge
    draw.rectangle([325, 130, 365, 350], fill=(226, 188, 160))   # torso
    draw.rectangle([300, 150, 390, 195], fill=(226, 188, 160))   # outstretched arms — widest
    draw.rectangle([328, 350, 342, 660], fill=(226, 188, 160))   # legs
    draw.rectangle([348, 350, 362, 660], fill=(226, 188, 160))
    draw.ellipse([320, 40, 370, 140], fill=(45, 30, 25))         # head — darkest
    return page


def make_doll_page(size=(600, 800), dolls=((260, 60, 340, 760),), border=True):
    """A base-body page the way the scans are: dolls on a smooth colour wash.

    Each doll is (left, top, right, bottom) in pixels and is drawn the way the
    books print them: a filled, dark-outlined line figure -- head, torso,
    outstretched arms, two legs -- so it is tall, floats clear of the side edges
    and has the anatomy the orientation gates expect. The wash is a vertical
    gradient whose luminance sits within a few levels of the skin tone, so only
    the outlines separate doll from background, exactly as on the scans; a
    border strip runs off the left edge like the printed pages.
    """
    width, height = size
    page = Image.new("RGB", size)
    pixels = page.load()
    for y in range(height):
        t = y / max(1, height - 1)
        pixels_row = (int(205 - 30 * t), int(190 - 25 * t), int(225 - 20 * t))
        for x in range(width):
            pixels[x, y] = pixels_row
    draw = ImageDraw.Draw(page)
    if border:
        draw.rectangle([0, 0, int(width * 0.08), height], fill=(60, 110, 70))
    for left, top, right, bottom in dolls:
        w, h = right - left, bottom - top
        cx = (left + right) // 2
        skin = (226, 188, 160)
        line = dict(outline=(40, 30, 30), width=2)
        head_h = int(h * 0.14)
        torso_top = top + head_h - 2
        torso_bottom = top + int(h * 0.5)
        half = int(w * 0.25)
        draw.rectangle([cx - half, torso_top, cx + half, torso_bottom], fill=skin, **line)
        arm_top = torso_top + int(h * 0.03)
        draw.rectangle([left, arm_top, right - 1, arm_top + int(h * 0.07)], fill=skin, **line)
        leg_w = max(4, int(w * 0.1))
        draw.rectangle([cx - half, torso_bottom, cx - half + leg_w, bottom - 1], fill=skin, **line)
        draw.rectangle([cx + half - leg_w, torso_bottom, cx + half, bottom - 1], fill=skin, **line)
        draw.ellipse([cx - int(w * 0.3), top, cx + int(w * 0.3), top + head_h], fill=(45, 30, 25), **line)
    return page
