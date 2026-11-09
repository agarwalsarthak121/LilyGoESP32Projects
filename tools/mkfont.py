"""Render a TTF/OTF into a 1-bit BDF font (then convert to PCF with bdftopcf)."""
import sys
from PIL import Image, ImageDraw, ImageFont


def make_bdf(ttf, px, chars, out, threshold=110):
    font = ImageFont.truetype(ttf, px)
    ascent, descent = font.getmetrics()
    glyphs = []
    for ch in chars:
        adv = int(round(font.getlength(ch)))
        bbox = font.getbbox(ch)  # relative to drawing origin (top of ascent)
        x0, y0, x1, y1 = bbox
        w, h = max(x1 - x0, 0), max(y1 - y0, 0)
        rows = []
        if w and h:
            img = Image.new("L", (w, h), 0)
            ImageDraw.Draw(img).text((-x0, -y0), ch, font=font, fill=255)
            px_ = img.load()
            for y in range(h):
                bits = 0
                nbytes = (w + 7) // 8
                for x in range(w):
                    if px_[x, y] >= threshold:
                        bits |= 1 << (nbytes * 8 - 1 - x)
                rows.append(f"{bits:0{nbytes * 2}X}")
        else:
            w = h = 0
            x0 = 0
            y1 = ascent
        yoff = ascent - y1  # bottom of bitmap relative to baseline
        glyphs.append((ord(ch), adv, w, h, x0, yoff, rows))

    with open(out, "w") as f:
        f.write("STARTFONT 2.1\n")
        f.write(f"FONT -custom-dash-bold-r-normal--{px}-{px * 10}-75-75-p-0-iso10646-1\n")
        f.write(f"SIZE {px} 75 75\n")
        f.write(f"FONTBOUNDINGBOX {px * 2} {ascent + descent} 0 {-descent}\n")
        f.write("STARTPROPERTIES 2\n")
        f.write(f"FONT_ASCENT {ascent}\nFONT_DESCENT {descent}\n")
        f.write("ENDPROPERTIES\n")
        f.write(f"CHARS {len(glyphs)}\n")
        for code, adv, w, h, xo, yo, rows in glyphs:
            f.write(f"STARTCHAR U+{code:04X}\nENCODING {code}\n")
            f.write(f"SWIDTH {adv * 1000 // px} 0\nDWIDTH {adv} 0\n")
            f.write(f"BBX {w} {h} {xo} {yo}\nBITMAP\n")
            for r in rows:
                f.write(r + "\n")
            f.write("ENDCHAR\n")
        f.write("ENDFONT\n")


if __name__ == "__main__":
    ttf, px, which, out = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    if which == "digits":
        chars = "0123456789.-"
    elif which == "money":
        chars = "0123456789+-.,%LCr\u20b9 "
    else:
        chars = "".join(chr(c) for c in range(32, 127)) + "°\u20b9"
    make_bdf(ttf, px, chars, out)
