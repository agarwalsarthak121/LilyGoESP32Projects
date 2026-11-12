"""harness.py, but drawing outside a bitmap fails the way it does on the board."""
import os, bitmaptools
_dl = bitmaptools.draw_line
_fr = bitmaptools.fill_region
def strict_line(b, x0, y0, x1, y1, v):
    for x, y in ((x0, y0), (x1, y1)):
        assert 0 <= x < b.width and 0 <= y < b.height, ("draw_line off bitmap", x, y, b.width, b.height)
    return _dl(b, x0, y0, x1, y1, v)
def strict_fill(b, x1, y1, x2, y2, v):
    assert 0 <= min(x1, x2) and max(x1, x2) <= b.width and 0 <= min(y1, y2) and max(y1, y2) <= b.height, \
        ("fill_region off bitmap", (x1, y1, x2, y2), (b.width, b.height))
    return _fr(b, x1, y1, x2, y2, v)
bitmaptools.draw_line = strict_line
bitmaptools.fill_region = strict_fill
HERE = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE, "harness.py")).read())
