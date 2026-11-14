# Desk dashboard for the LilyGO T-Display-S3 (CircuitPython 10)
# https://github.com/agarwalsarthak121/LilyGoESP32Projects
# Screens: weather + analog clock, Zerodha portfolio, market indices, live cricket,
# top news, and a dim analog clock at night.
# Weather layout inspired by VolosR/tDisplayS3WeatherStation.
# Weather/air: Open-Meteo (no key).  Portfolio: Kite Connect Personal API (free).
#
# settings.toml keys used (all strings, all optional except the Kite ones):
#   WEATHER_TOWN="Delhi"  WEATHER_LAT="28.61"  WEATHER_LON="77.21"
#   KITE_API_KEY="..."    KITE_API_SECRET="..."
#   SCREEN_SECONDS="15"   (how long each screen shows before rotating)
#   AUTO_ROTATE="off"     (screens change only when you press the KEY button;
#                          can also be switched from the board's web page)
#   CRICKET_API_KEY="..." (free key from cricketdata.org)
#   CRICKET_TEAM="India"  (optional: follow this team's live matches; several, comma separated)
#   CRICKET_EVERY="300"   (seconds between score updates while a match is live)
#
#   FMP_API_KEY="..."     (free key from financialmodelingprep.com, for the MARKETS screen)
#   SCREEN_ORDER="weather,portfolio,markets,cricket,news"   (add "clock" for the big clock by day)
#   NEWS_FEED="..."       (any RSS feed; default: Google News India top stories)
#   NEWS_COUNT="10"       (how many top headlines to cycle through)
#   NEWS_SECONDS="6"      (how long each headline stays up)
#   NEWS_PER_VISIT="10"   (headlines shown before auto-rotate moves on; "2" = short visits)
#   THEME="aura"          (a different style per screen; "classic" = the original grey look)
#   NIGHT_SCREEN="clock"  (or "matrix", "fire", "stars", "cycle" = a different one each hour)
#   STAT_PLAYERS="253802:Virat Kohli,625383:Jasprit Bumrah:bowl"  (Cricinfo id:name[:bowl])
#   STAT_CLASS="11"       (11 all internationals, 1 Tests, 2 ODIs, 3 T20Is)
#   TRIVIA_SECONDS="30"   TRIVIA_SOURCE="india" (or "world" = Open Trivia DB, "mix")
#   PET_NAME="Sheru"      PING_HOST="1.1.1.1"
#   WATCHDOG="off"        (turn off the hang watchdog, e.g. while debugging over the REPL)
#   NIGHT_HOURS="23-7"    (dark, dim clock only at night; "" turns night mode off)
#   DAY_BRIGHTNESS="0.6"  NIGHT_BRIGHTNESS="0.05"
#
# Kite needs a login once a day: open http://<board-ip>:8080 on your phone.
# Pick a cricket match at http://<board-ip>:8080/cricket

import os
import time
import struct
import gc
import json
import random
import ipaddress
import board
import displayio
import vectorio
import bitmaptools
import digitalio
import microcontroller
import rtc
import terminalio
import wifi
import adafruit_connection_manager
import adafruit_requests
from adafruit_bitmap_font import bitmap_font
from adafruit_display_text.bitmap_label import Label
from adafruit_display_shapes.roundrect import RoundRect
from adafruit_httpserver import Server, Request, Response

# ------------------------------------------------------------- settings store
# settings.toml holds the defaults. Anything changed on the board's Settings page
# (http://<board>:8080/settings) is kept in NVM and wins over settings.toml.
CFG_NVM = 128        # nvm[128:130] = length, then the settings as JSON


def _load_cfg():
    try:
        nv = microcontroller.nvm
        n = nv[CFG_NVM] | (nv[CFG_NVM + 1] << 8)
        if 2 <= n <= 3000:
            return json.loads(bytes(nv[CFG_NVM + 2:CFG_NVM + 2 + n]).decode())
    except Exception as e:  # noqa: BLE001
        print("settings in NVM unreadable:", repr(e))
    return {}


CFG = _load_cfg()


def cfg(key):
    """A setting: the Settings page's value if set there, else settings.toml's."""
    v = CFG.get(key)
    return os.getenv(key) if v is None else v


def save_cfg():
    b = json.dumps(CFG).encode()
    microcontroller.nvm[CFG_NVM:CFG_NVM + 2 + len(b)] = bytes([len(b) & 255, len(b) >> 8]) + b


try:    # if code.py ever dies with an error, restart it instead of leaving a dead screen
    import supervisor
    supervisor.set_next_code_file(None, reload_on_error=True)
except Exception as _e:  # noqa: BLE001
    print("auto-restart on error unavailable:", repr(_e))

try:
    import hashlib
    hashlib.sha256(b"x")
except Exception:  # noqa: BLE001 - fall back to the pure-Python version
    import adafruit_hashlib as hashlib

# ------------------------------------------------------------- settings
TOWN = cfg("WEATHER_TOWN") or "Delhi"
LAT = cfg("WEATHER_LAT") or "28.61"
LON = cfg("WEATHER_LON") or "77.21"
KITE_KEY = os.getenv("KITE_API_KEY") or ""
KITE_SECRET = os.getenv("KITE_API_SECRET") or ""
SCREEN_SECONDS = int(cfg("SCREEN_SECONDS") or "15")
auto_rotate = (cfg("AUTO_ROTATE") or "on").strip().lower() not in ("off", "0", "no", "false") \
    and SCREEN_SECONDS > 0
CRIC_KEY = os.getenv("CRICKET_API_KEY") or ""
CRIC_TEAM = (cfg("CRICKET_TEAM") or "").lower()
# cricket source: "cricbuzz" = Cricbuzz's match data (default; free, no key: score, overs,
#                              batters, bowler, run rates)
#                 "rss" = ESPNcricinfo live-scores feed (free, no key; scores, details when Cricinfo allows)
#                 "cricapi" = CricketData.org (needs key, 100 hits/day)
CRIC_SOURCE = (os.getenv("CRICKET_SOURCE") or "cricbuzz").lower()
CRIC_RSS = CRIC_SOURCE == "rss"
CRIC_CB = CRIC_SOURCE == "cricbuzz"
CRIC_ON = CRIC_RSS or CRIC_CB or bool(CRIC_KEY)
CRIC_EVERY = int(os.getenv("CRICKET_EVERY") or ("30" if (CRIC_RSS or CRIC_CB) else "300"))
CRIC_API = "https://api.cricapi.com/v1/"
RSS_URL = "https://static.cricinfo.com/rss/livescores.xml"
LOGIN_PORT = 8080

# look: "aura" (default, a different style per screen) or "classic" (the original grey).
# A choice made on the board's web page is kept in NVM and wins over settings.toml.
THEMES = ("aura", "classic")
THEME = (os.getenv("THEME") or "aura").strip().lower()
THEME_FROM_WEB = False
try:
    if microcontroller.nvm[0] in (1, 2):
        THEME = THEMES[microcontroller.nvm[0] - 1]
        THEME_FROM_WEB = True
except Exception:  # noqa: BLE001 - no NVM on this build
    pass
if THEME not in THEMES:
    THEME = "aura"
CLASSIC = THEME == "classic"

WEATHER_EVERY = 10 * 60
AIR_EVERY = 30 * 60
NTP_EVERY = 6 * 60 * 60
KITE_EVERY_FAST = int(os.getenv("KITE_EVERY") or "5")   # market hours, portfolio or My stocks on screen
KITE_EVERY_OPEN = 60          # market hours, other screens showing
KITE_EVERY_CLOSED = 15 * 60   # outside market hours

WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude=" + LAT + "&longitude=" + LON
    + "&current=temperature_2m,relative_humidity_2m,pressure_msl,wind_speed_10m,"
    "weather_code,apparent_temperature,is_day"
    "&hourly=temperature_2m&past_hours=23&forecast_hours=1"
    "&timezone=auto&wind_speed_unit=ms"
)
AIR_URL = (
    "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=" + LAT
    + "&longitude=" + LON + "&current=pm2_5,pm10,us_aqi&timezone=auto"
)
KITE_API = "https://api.kite.trade"

WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain",
    67: "Freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Rain showers", 81: "Rain showers",
    82: "Violent showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail",
}

# ------------------------------------------------------------- palette
GREYS = []
c = 210
for _ in range(11):
    GREYS.append((c << 16) | (c << 8) | c)
    c -= 20
BLACK = 0x000000
WHITE = 0xFFFFFF
GREEN = 0x4CD964
RED = 0xFF5A5A

pal = displayio.Palette(len(GREYS) + 2)
for i, g in enumerate(GREYS):
    pal[i] = g
I_BLACK = len(GREYS)
I_WHITE = len(GREYS) + 1
pal[I_BLACK] = BLACK
pal[I_WHITE] = WHITE

# ------------------------------------------------------------- fonts
F_BIG = bitmap_font.load_font("/fonts/big.pcf")
F_MONEY = bitmap_font.load_font("/fonts/money.pcf")
F_TIME = bitmap_font.load_font("/fonts/time.pcf")
F_TITLE = bitmap_font.load_font("/fonts/title.pcf")
F_MED = bitmap_font.load_font("/fonts/med.pcf")
F_NEWS = bitmap_font.load_font("/fonts/news24.pcf")    # headline, readable across the room
F_NEWS2 = bitmap_font.load_font("/fonts/news20.pcf")   # for headlines too long for 24 px
F_SMALL = terminalio.FONT

# ------------------------------------------------------------- drawing helpers
display = board.DISPLAY
try:
    display.brightness = 0.6
except Exception:  # noqa: BLE001
    pass

root = None   # the group the helpers below draw into


def rect(x, y, w, h, idx):
    root.append(vectorio.Rectangle(pixel_shader=pal, width=w, height=h, x=x, y=y,
                                   color_index=idx))


def rrect(x, y, w, h, r, idx):
    root.append(RoundRect(x, y, w, h, r, fill=GREYS[idx]))


def text(font, s, x, y, color, center=False, right=False):
    ax = 0.5 if center else (1.0 if right else 0.0)
    lbl = Label(font, text=s, color=color,
                anchor_point=(ax, 0.5 if center else 0.0), anchored_position=(x, y))
    root.append(lbl)
    return lbl


def px_width(font, t):
    w = 0
    for ch in t:
        g = font.get_glyph(ord(ch))
        if g:
            w += g.shift_x
    return w


def wrap_px(font, t, width, lines):
    """Word-wrap `t` to `width` pixels. Returns (lines, fits)."""
    out, cur = [], ""
    space = px_width(font, " ")
    cur_w = 0
    for word in t.split():
        ww = px_width(font, word)
        if cur and cur_w + space + ww <= width:
            cur += " " + word
            cur_w += space + ww
            continue
        if cur:
            out.append(cur)
        cur, cur_w = word, ww
        while cur_w > width and len(cur) > 1:      # one very long "word"
            k = len(cur) - 1
            while k > 1 and px_width(font, cur[:k]) > width:
                k -= 1
            out.append(cur[:k])
            cur = cur[k:]
            cur_w = px_width(font, cur)
    if cur:
        out.append(cur)
    if len(out) <= lines:
        return out, True
    out = out[:lines]
    last = out[-1]
    while last and px_width(font, last + "...") > width:
        last = last[:last.rfind(" ")] if " " in last else last[:-1]
    out[-1] = last.rstrip(",;:-") + "..."
    return out, False


def render_strip(font, s, height, base):
    """Render a string into a 2-colour Bitmap (for scrolling tickers)."""
    width = 0
    for ch in s:
        g = font.get_glyph(ord(ch))
        if g:
            width += g.shift_x
    bmp = displayio.Bitmap(max(width, 1), height, 2)
    x = 0
    for ch in s:
        g = font.get_glyph(ord(ch))
        if not g:
            continue
        gy = base - g.height - g.dy
        sx = g.tile_index * g.width if g.bitmap.width > g.width else 0
        if g.width and g.height:
            for yy in range(g.height):
                ty = gy + yy
                if 0 <= ty < height:
                    for xx in range(g.width):
                        if g.bitmap[sx + xx, yy]:
                            tx = x + g.dx + xx
                            if 0 <= tx < bmp.width:
                                bmp[tx, ty] = 1
        x += g.shift_x
    return bmp


class Ticker:
    """A scrolling one-line message box."""

    H = 14

    def __init__(self, x, y, w=166, bg=None, fg=None, box=10):
        self.W = w
        if box is not None:
            rrect(x - 4, y - 2, w + 8, 18, 3, box)
        self.bmp = displayio.Bitmap(self.W, self.H, 2)
        p = displayio.Palette(2)
        p[0] = GREYS[10] if bg is None else bg
        p[1] = GREYS[1] if fg is None else fg
        self.pal = p
        root.append(displayio.TileGrid(self.bmp, pixel_shader=p, x=x, y=y))
        self.src = render_strip(F_SMALL, " ", self.H, 10)
        self.x = -self.W

    def set(self, msg):
        self.src = render_strip(F_SMALL, msg + "      ", self.H, 10)
        self.x = -self.W

    def step(self):
        self.x += 1
        if self.x > self.src.width:
            self.x = -self.W
        self.bmp.fill(0)
        x1 = max(self.x, 0)
        x2 = min(self.x + self.W, self.src.width)
        if x2 > x1:
            bitmaptools.blit(self.bmp, self.src, x1 - self.x, 0,
                             x1=x1, y1=0, x2=x2, y2=self.H)


def stamp():
    t = time.localtime()
    return "  #Updated %02d:%02d" % (t.tm_hour, t.tm_min)


# ============================================================= ANALOG CLOCK
import math


def _circle(bmp, cx, cy, r, v):
    for yy in range(-r, r + 1):
        y = cy + yy
        if not 0 <= y < bmp.height:              # clipped, as in _ellipse
            continue
        half = int((r * r - yy * yy) ** 0.5 + 0.5)
        x1, x2 = max(0, cx - half), min(bmp.width, cx + half + 1)
        if x1 < x2:
            bitmaptools.fill_region(bmp, x1, y, x2, y + 1, v)


class AnalogClock:
    """Clock face in a bitmap + hour/minute/second hands as vectorio polygons.
    The second hand sweeps smoothly (it's redrawn every frame)."""

    def __init__(self, group, cx, cy, r, numbers=False, tip=False, blunt=False):
        self.cx, self.cy, self.r = cx, cy, r
        self.blunt = blunt              # straight-sided hands (station-clock style)
        c = r + 1
        self.fpal = displayio.Palette(5)            # 0 clear, 1 face, 2 rim, 3 minute ticks, 4 hour ticks
        self.fpal.make_transparent(0)
        face = displayio.Bitmap(2 * r + 3, 2 * r + 3, 5)
        _circle(face, c, c, r, 2)
        _circle(face, c, c, r - 2, 1)
        for k in range(60):
            a = k * math.pi / 30
            dx, dy = math.sin(a), -math.cos(a)
            major = k % 5 == 0
            r_out = r - 4
            r_in = r_out - (max(5, r // 7) if major else max(2, r // 22))
            x0, y0 = c + dx * r_in, c + dy * r_in
            x1, y1 = c + dx * r_out, c + dy * r_out
            widths = (-1, 0, 1) if (major and r >= 50) else ((0, 1) if major else (0,))
            for w in widths:                         # thicker hour marks
                ox, oy = -dy * w, dx * w
                bitmaptools.draw_line(face, int(x0 + ox + 0.5), int(y0 + oy + 0.5),
                                      int(x1 + ox + 0.5), int(y1 + oy + 0.5), 4 if major else 3)
        group.append(displayio.TileGrid(face, pixel_shader=self.fpal, x=cx - c, y=cy - c))
        self.nums = []
        if numbers:
            rn = r - max(5, r // 7) - 21
            for n, (dx, dy) in (("12", (0, -1)), ("3", (1, 0)), ("6", (0, 1)), ("9", (-1, 0))):
                lbl = Label(F_MED, text=n, color=0xFFFFFF, anchor_point=(0.5, 0.5),
                            anchored_position=(cx + int(dx * rn), cy + int(dy * rn) - 3))
                group.append(lbl)
                self.nums.append(lbl)
        self.hpal = displayio.Palette(4)             # hour, minute, second, centre cap
        dummy = [(0, 0), (1, 0), (0, 1)]
        self.hour = vectorio.Polygon(pixel_shader=self.hpal, points=dummy, x=cx, y=cy, color_index=0)
        self.minute = vectorio.Polygon(pixel_shader=self.hpal, points=dummy, x=cx, y=cy, color_index=1)
        self.second = vectorio.Polygon(pixel_shader=self.hpal, points=dummy, x=cx, y=cy, color_index=2)
        for h in (self.hour, self.minute, self.second):
            group.append(h)
        group.append(vectorio.Circle(pixel_shader=self.hpal, radius=max(2, r // 18),
                                     x=cx, y=cy, color_index=3))
        self.tip = None                 # the red disc near the end of a Swiss seconds hand
        if tip:
            self.tip = vectorio.Circle(pixel_shader=self.hpal, radius=max(3, r // 10),
                                       x=cx, y=cy, color_index=2)
            group.append(self.tip)
        self._last = [None, None, None]

    def _hand(self, i, poly, angle, length, width, tail):
        dx, dy = math.sin(angle), -math.cos(angle)
        px, py = -dy, dx                              # perpendicular
        hw = width / 2
        tw = hw * 0.8 if self.blunt and i < 2 else max(0.6, width / 5)
        pts = [(round(-dx * tail + px * hw), round(-dy * tail + py * hw)),
               (round(dx * length + px * tw), round(dy * length + py * tw)),
               (round(dx * length - px * tw), round(dy * length - py * tw)),
               (round(-dx * tail - px * hw), round(-dy * tail - py * hw))]
        if pts != self._last[i]:                      # only redraw when it actually moves
            self._last[i] = pts
            poly.points = pts

    def update(self, h, m, s, frac=0.0):
        r = self.r
        sec = s + frac
        mins = m + sec / 60
        hrs = (h % 12) + mins / 60
        self._hand(0, self.hour, hrs * math.pi / 6, r * 0.52, max(4, r * 0.09), r * 0.08)
        self._hand(1, self.minute, mins * math.pi / 30, r * 0.80, max(3, r * 0.06), r * 0.08)
        a = sec * math.pi / 30
        self._hand(2, self.second, a, r * 0.88, 2 if r < 60 else 3, r * 0.2)
        if self.tip:
            tx = self.cx + round(math.sin(a) * r * 0.62)
            ty = self.cy - round(math.cos(a) * r * 0.62)
            if (tx, ty) != (self.tip.x, self.tip.y):
                self.tip.x, self.tip.y = tx, ty

    def colours(self, face, rim, minor, major, hour, minute, second, numbers=None):
        for i, col in enumerate((face, rim, minor, major)):
            self.fpal[i + 1] = col
        for i, col in enumerate((hour, minute, second, second)):
            self.hpal[i] = col
        for n in self.nums:
            n.color = numbers if numbers is not None else major


# ============================================================= THEME KIT
# THEME="aura" (default): every screen gets its own look - a living sky for the
# weather, a P&L dial whose glow follows the market, an amber trading terminal,
# broadcast-style cricket scorebug, a news lower-third and a station clock.
# THEME="classic": the original grey look.  The board's web page can switch too.

def mix(a, b, t):
    """Blend colour a towards colour b by t (0..1)."""
    out = 0
    for sh in (16, 8, 0):
        ca, cb = (a >> sh) & 255, (b >> sh) & 255
        out |= int(ca + (cb - ca) * t + 0.5) << sh
    return out


def ramp(stops, n):
    """n colours spread evenly along a list of colour stops."""
    out = []
    for i in range(n):
        p = i / (n - 1) * (len(stops) - 1)
        k = min(int(p), len(stops) - 2)
        out.append(mix(stops[k], stops[k + 1], p - k))
    return out


def luma(c):
    return (((c >> 16) & 255) * 299 + ((c >> 8) & 255) * 587 + (c & 255) * 114) // 1000


class Ghost:
    """Stands in for a label that a theme doesn't show."""

    def __init__(self):
        self.text = ""
        self.color = 0
        self.hidden = True
        self.anchored_position = (0, 0)


_DITHER = (0.0, 0.5, 0.25, 0.75)


class Backdrop:
    """Full-screen vertical gradient with frosted 'glass' cards, drawn once.
    Recolouring only rewrites the palette, so a new sky or mood is instant."""

    N = 16

    def __init__(self, group, cards=(), stripes=0):
        n = self.N
        self.bmp = displayio.Bitmap(320, 170, 2 * n)
        self.pal = displayio.Palette(2 * n)
        for y in range(170):
            v = y / 169 * (n - 1)
            lv = int(v)
            if v - lv > _DITHER[y % 4] and lv < n - 1:   # ordered dither: no banding
                lv += 1
            bitmaptools.fill_region(self.bmp, 0, y, 320, y + 1, lv)
            if stripes and lv < n - 1:                    # mown-pitch stripes
                for sx in range(stripes, 320, 2 * stripes):
                    bitmaptools.fill_region(self.bmp, sx, y, min(320, sx + stripes), y + 1, lv + 1)
            for cx, cy, cw, ch, r in cards:
                if cy <= y < cy + ch:
                    dy = cy + r - y if y < cy + r else (y - (cy + ch - r - 1) if y >= cy + ch - r else 0)
                    inset = r - int((r * r - dy * dy) ** 0.5) if dy > 0 else 0
                    bitmaptools.fill_region(self.bmp, cx + inset, y, cx + cw - inset, y + 1, n + lv)
        group.append(displayio.TileGrid(self.bmp, pixel_shader=self.pal))

    def colours(self, stops, glass=0x000000, amount=0.32):
        for i, c in enumerate(ramp(stops, self.N)):
            self.pal[i] = c
            self.pal[self.N + i] = mix(c, glass, amount)

    def glass_at(self, y):
        return self.pal[self.N + min(self.N - 1, int(y / 169 * (self.N - 1) + 0.5))]

    def colour_at(self, y):
        return self.pal[min(self.N - 1, int(y / 169 * (self.N - 1) + 0.5))]


def ring(group, x, y, r, colour, width=2):
    """A small hollow circle (the degree sign for big numbers)."""
    bmp = displayio.Bitmap(2 * r + 1, 2 * r + 1, 2)
    p = displayio.Palette(2)
    p.make_transparent(0)
    p[1] = colour
    _circle(bmp, r, r, r, 1)
    _circle(bmp, r, r, r - width, 0)
    tg = displayio.TileGrid(bmp, pixel_shader=p, x=x, y=y)
    group.append(tg)
    return tg


class WeatherIcon:
    """Weather symbol drawn with circles and lines (sun, moon, cloud, rain...)."""

    W, H = 60, 50
    COLS = (0, 0xFFC23D, 0xFFE08A, 0xF4F6F8, 0xA9B5C2, 0x7CC8FF, 0xFFE14D, 0xF3EBCF)

    def __init__(self, group, x, y):
        self.bmp = displayio.Bitmap(self.W, self.H, len(self.COLS))
        p = displayio.Palette(len(self.COLS))
        for i, c in enumerate(self.COLS):
            p[i] = c
        p.make_transparent(0)
        group.append(displayio.TileGrid(self.bmp, pixel_shader=p, x=x, y=y))
        self.kind = None

    def _thick(self, x0, y0, x1, y1, v, w=2):
        mx, my = self.W - 1, self.H - 1
        for o in range(w):                    # clamp: the board rejects off-bitmap lines
            bitmaptools.draw_line(self.bmp, max(0, min(mx, int(x0 + o))), max(0, min(my, int(y0))),
                                  max(0, min(mx, int(x1 + o))), max(0, min(my, int(y1))), v)

    def _sun(self, cx, cy, r):
        for k in range(8):
            a = k * math.pi / 4
            dx, dy = math.cos(a), math.sin(a)
            self._thick(cx + dx * (r + 4), cy + dy * (r + 4), cx + dx * (r + 9), cy + dy * (r + 9), 2)
        _circle(self.bmp, cx, cy, r, 1)

    def _moon(self, cx, cy, r):
        _circle(self.bmp, cx, cy, r, 7)
        _circle(self.bmp, int(cx + r * 0.55), int(cy - r * 0.45), int(r * 0.8), 0)

    def _cloud(self, cx, cy, s, col=3, shade=4):
        for dx, dy, v in ((3, 3, shade), (0, 0, col)):
            for ox, oy, rr in ((-0.55, 0.12, 0.42), (-0.05, -0.2, 0.56), (0.5, 0.06, 0.4)):
                _circle(self.bmp, int(cx + ox * s + dx), int(cy + oy * s + dy), int(rr * s), v)
            bitmaptools.fill_region(self.bmp, int(cx - 0.55 * s + dx), int(cy + 0.12 * s + dy),
                                    int(cx + 0.5 * s + dx), int(cy + 0.5 * s + dy), v)

    def show(self, kind, day=True):
        if (kind, day) == self.kind:
            return
        self.kind = (kind, day)
        shown, self.bmp = self.bmp, displayio.Bitmap(self.W, self.H, len(self.COLS))   # draw off-screen
        b = self.bmp
        if kind in ("clear", "partly"):
            if day:
                self._sun(22 if kind == "partly" else 30, 20 if kind == "partly" else 24, 10 if kind == "partly" else 11)
            else:
                self._moon(24 if kind == "partly" else 30, 18 if kind == "partly" else 24, 13)
            if kind == "partly":
                self._cloud(36, 32, 17)
        elif kind == "fog":
            for i, w in enumerate((44, 52, 40)):
                y = 14 + i * 9
                bitmaptools.fill_region(b, 30 - w // 2, y, 30 + w // 2, y + 4, 3 if i != 1 else 4)
        else:
            self._cloud(31, 18, 20, 3 if kind == "cloudy" else 4, 4 if kind == "cloudy" else 3)
            if kind in ("drizzle", "rain"):
                for k in range(4 if kind == "rain" else 3):
                    x0 = 16 + k * 9 + (0 if kind == "rain" else 4)
                    self._thick(x0, 36, x0 - 4, 36 + (10 if kind == "rain" else 6), 5)
            elif kind == "snow":
                for x, y in ((16, 38), (28, 44), (40, 38), (22, 47), (46, 46)):
                    _circle(b, x, y, 2, 3)
            elif kind == "storm":
                for o in range(3):
                    bitmaptools.draw_line(b, 34 + o, 32, 26 + o, 41, 6)
                    bitmaptools.draw_line(b, 26 + o, 41, 35 + o, 41, 6)
                    bitmaptools.draw_line(b, 35 + o, 41, 27 + o, 49, 6)
        bitmaptools.blit(shown, b, 0, 0)
        self.bmp = shown


class Gauge:
    """Semicircle dial (red -> green) with a needle that eases to its target."""

    BANDS = (0xD83B3B, 0xE5674A, 0xE7A04F, 0x8A9099, 0x8CCB5E, 0x4CC66B, 0x23A55A)

    def __init__(self, group, cx, cy, r, span=3.0, ring_w=9):
        self.cx, self.cy, self.r, self.span = cx, cy, r, span
        nb = len(self.BANDS)
        bmp = displayio.Bitmap(2 * r + 1, r + 2, nb + 3)
        p = displayio.Palette(nb + 3)
        p.make_transparent(0)
        for i, c in enumerate(self.BANDS):
            p[i + 1] = c
        p[nb + 1] = 0xE8E8E8                     # ticks
        p[nb + 2] = 0x2A2E33
        ri = r - ring_w
        for yy in range(r + 1):
            dy = r - yy
            xo = int((r * r - dy * dy) ** 0.5)
            xi = int((ri * ri - dy * dy) ** 0.5) if dy < ri else 0
            for xx in list(range(r - xo, r - xi + 1)) + list(range(r + xi, r + xo + 1)):
                a = math.atan2(dy, xx - r)                         # 0 right .. pi left
                band = int((1 - a / math.pi) * nb * 0.9999)
                bmp[xx, yy] = 1 + max(0, min(nb - 1, band))
        steps = int(span)
        for k in range(-steps, steps + 1):                         # a tick every 1 %
            a = math.pi * (1 - (k + span) / (2 * span))
            dx, dy = math.cos(a), -math.sin(a)
            for o in (0, 0.6):
                bitmaptools.draw_line(bmp, int(r + dx * (ri - 7) + o), int(r + dy * (ri - 7)),
                                      int(r + dx * (ri - 2) + o), int(r + dy * (ri - 2)), nb + 1)
        group.append(displayio.TileGrid(bmp, pixel_shader=p, x=cx - r, y=cy - r))
        self.npal = displayio.Palette(2)
        self.npal[0] = 0xFFFFFF
        self.npal[1] = 0x16191D
        self.needle = vectorio.Polygon(pixel_shader=self.npal, points=[(0, 0), (1, 0), (0, 1)],
                                       x=cx, y=cy, color_index=0)
        group.append(self.needle)
        group.append(vectorio.Circle(pixel_shader=self.npal, radius=6, x=cx, y=cy, color_index=0))
        group.append(vectorio.Circle(pixel_shader=self.npal, radius=2, x=cx, y=cy, color_index=1))
        self.v = 0.0
        self.target = 0.0
        self._pts = None
        self._draw()

    def set(self, value):
        self.target = max(-self.span * 1.04, min(self.span * 1.04, value))

    def _draw(self):
        a = math.pi * (1 - (self.v + self.span) / (2 * self.span))
        dx, dy = math.cos(a), -math.sin(a)
        px, py = -dy, dx
        L, tail = self.r - 13, 8
        pts = [(round(-dx * tail + px * 3), round(-dy * tail + py * 3)),
               (round(dx * L), round(dy * L)),
               (round(-dx * tail - px * 3), round(-dy * tail - py * 3))]
        if pts != self._pts:
            self._pts = pts
            self.needle.points = pts

    def step(self):
        d = self.target - self.v
        if abs(d) > 0.002:
            self.v += d * 0.12 if abs(d) > 0.02 else d
            self._draw()


# broadcast-style team colours (country sides and IPL franchises)
TEAM_COLOURS = {
    "chennai super kings": 0xF9CD05, "mumbai indians": 0x004BA0, "royal challengers": 0xD1121B,
    "kolkata knight riders": 0x3A225D, "sunrisers hyderabad": 0xF26522, "delhi capitals": 0x17449B,
    "rajasthan royals": 0xEA1A85, "punjab kings": 0xDD1F2D, "gujarat titans": 0x2C3E66,
    "lucknow super giants": 0x00AEEF, "south africa": 0x007A4D, "new zealand": 0x3A3A3A,
    "sri lanka": 0x1B3F8B, "west indies": 0x7B1E3A, "afghanistan": 0x1559B7,
    "bangladesh": 0x006A4E, "netherlands": 0xF36C21, "zimbabwe": 0xD40000, "australia": 0xF2C200,
    "pakistan": 0x0B6B3A, "scotland": 0x2A3F8F, "ireland": 0x169B62, "england": 0x1B3A73,
    "india": 0x1F5FBF, "nepal": 0xDC143C, "oman": 0xC8102E, "uae": 0x00843D, "usa": 0x1C3F94,
    "csk": 0xF9CD05, "mi": 0x004BA0, "rcb": 0xD1121B, "kkr": 0x3A225D, "srh": 0xF26522,
    "dc": 0x17449B, "rr": 0xEA1A85, "pbks": 0xDD1F2D, "gt": 0x2C3E66, "lsg": 0x00AEEF,
    "ind": 0x1F5FBF, "aus": 0xF2C200, "eng": 0x1B3A73, "pak": 0x0B6B3A, "sa": 0x007A4D,
    "rsa": 0x007A4D, "nz": 0x3A3A3A, "sl": 0x1B3F8B, "wi": 0x7B1E3A, "afg": 0x1559B7,
    "ban": 0x006A4E, "ned": 0xF36C21, "zim": 0xD40000, "ire": 0x169B62, "sco": 0x2A3F8F,
}
_SPARE = (0x7A3E9D, 0x0E7C86, 0xB5532A, 0x3B6E22, 0x8C1C4A, 0x2D5DA8)


def team_colour(name):
    n = (name or "").lower().strip()
    if not n:
        return 0x2A2F36
    if n in TEAM_COLOURS:
        return TEAM_COLOURS[n]
    for key in sorted(TEAM_COLOURS, key=len, reverse=True):     # "India Women" -> india
        if len(key) > 3 and key in n:
            return TEAM_COLOURS[key]
    return _SPARE[sum(ord(ch) for ch in n) % len(_SPARE)]


def _nop(*_a):
    pass


# screen hooks: the classic theme needs none of these, aura fills them in below
th_weather = th_air = th_port = th_index = th_team = th_minute = th_second = th_frame = _nop
NEWS_X = 5
SEG_COLS = (1, 7, 10)          # news progress: current, other headlines, unused


def show_index_error(i, msg):
    mkt_chg[i].text = msg
    mkt_chg[i].color = GREYS[6]


# ============================================================= WEATHER SCREEN
if CLASSIC:
    weather_grp = displayio.Group()
    root = weather_grp

    rect(138, 8, 1, 156, 6)
    rect(98, 106, 36, 1, 6)
    text(F_TITLE, "WEATHER", 5, 4, GREYS[1])
    text(F_SMALL, "INTERNET", 90, 4, GREYS[5])
    text(F_SMALL, "STATION", 90, 15, GREYS[5])
    root.append(vectorio.Circle(pixel_shader=pal, radius=2, x=8, y=40, color_index=2))
    text(F_MED, "C", 12, 34, GREYS[2])
    lbl_temp = text(F_BIG, "--.-", 72, 72, GREYS[0], center=True)
    text(F_MED, "TOWN:", 5, 108, GREYS[7])
    text(F_MED, TOWN[:6].upper(), 58, 108, GREYS[3])
    lbl_feels = text(F_MED, "", 5, 128, GREYS[4])
    lbl_range = text(F_SMALL, "Low --  High --", 5, 151, GREYS[6])

    # clock panel (replaces the old "last 24h" graph and digital clock)
    rrect(144, 6, 174, 86, 6, 10)
    wx_clock = AnalogClock(root, 188, 49, 40)
    wx_clock.colours(0x0C0C0C, 0x3A3A3A, 0x5A5A5A, 0xD0D0D0, 0xD8D8D8, 0xF4F4F4, 0xE84040)
    lbl_wday = text(F_TITLE, "---", 238, 12, GREYS[1])
    lbl_wdate = text(F_MED, "", 238, 36, GREYS[3])
    lbl_wdaypct = text(F_SMALL, "", 238, 62, GREYS[6])
    wx_daybar = displayio.Bitmap(72, 3, 3)
    wx_daypal = displayio.Palette(3)
    wx_daypal[0], wx_daypal[1], wx_daypal[2] = GREYS[8], GREEN, GREYS[10]
    root.append(displayio.TileGrid(wx_daybar, pixel_shader=wx_daypal, x=238, y=78))

    tile_vals = []
    for i, name in enumerate(("HUM %", "WIND m/s", "PM2.5")):
        x = 144 + i * 60
        rrect(x, 97, 54, 34, 4, 9)
        text(F_SMALL, name, x + 27, 104, GREYS[3], center=True)
        tile_vals.append(text(F_MED, "--", x + 27, 117, GREYS[2], center=True))
    text(F_SMALL, "CURRENT WEATHER", 168, 135, GREYS[4])
    lbl_counter = text(F_SMALL, "0", 308, 135, GREYS[9])
    weather_ticker = Ticker(148, 150)
else:
    # Living sky: the background is the weather report (time of day + conditions),
    # frosted-glass cards, a big symbol and a Swiss station clock.
    weather_grp = displayio.Group()
    root = weather_grp
    wx_bg = Backdrop(root, cards=((164, 6, 150, 88, 9), (164, 100, 47, 40, 7),
                                  (215, 100, 47, 40, 7), (266, 100, 48, 40, 7),
                                  (4, 146, 312, 21, 7)))
    text(F_TITLE, TOWN[:13].upper(), 8, 6, WHITE)
    wx_icon = WeatherIcon(root, 2, 28)
    lbl_temp = text(F_BIG, "--", 66, 27, WHITE)
    wx_deg = ring(root, 120, 30, 5, WHITE, 2)
    lbl_cond = text(F_MED, "", 8, 82, WHITE)
    lbl_feels = text(F_MED, "", 8, 103, 0xE6EDF5)
    lbl_range = text(F_MED, "", 8, 123, 0xE6EDF5)
    wx_clock = AnalogClock(root, 206, 50, 38, tip=True, blunt=True)
    wx_clock.colours(0xF6F6F2, 0xC9CED4, 0x55595E, 0x141414, 0x141414, 0x141414, 0xD22630)
    lbl_wday = text(F_TITLE, "---", 252, 13, WHITE)
    lbl_wdate = text(F_MED, "", 252, 35, 0xEEF3F8)
    lbl_wdaypct = text(F_SMALL, "", 252, 60, 0xD5DEE8)
    wx_daybar = displayio.Bitmap(56, 3, 3)
    wx_daypal = displayio.Palette(3)
    wx_daypal[0], wx_daypal[1], wx_daypal[2] = 0x5C6B7A, 0xFFD27A, 0
    root.append(displayio.TileGrid(wx_daybar, pixel_shader=wx_daypal, x=252, y=78))
    tile_vals = []
    for i, name in enumerate(("HUM %", "WIND", "PM2.5")):
        x = 164 + i * 51
        text(F_SMALL, name, x + 23, 107, 0xD5DEE8, center=True)
        tile_vals.append(text(F_MED, "--", x + 23, 121, WHITE, center=True))
    lbl_counter = Ghost()
    weather_ticker = Ticker(10, 149, 300, bg=0x203040, fg=WHITE, box=None)
    wx_code, wx_isday = 0, 1

    SKY = {   # top, middle, bottom of the sky for clear weather
        "day": (0x0A47A3, 0x2C7BD6, 0x63A8E8), "dawn": (0x22285C, 0x784886, 0xEE946A),
        "dusk": (0x15153E, 0x672C6C, 0xE2663D), "night": (0x03060F, 0x0A1430, 0x1A2952)}
    COND = {  # (day, night) skies for other weather
        "cloudy": ((0x3B4859, 0x667586, 0x8F9CAB), (0x0B0E14, 0x1A202B, 0x2C3442)),
        "fog": ((0x535C68, 0x79828E, 0x9DA5AE), (0x14171C, 0x262A31, 0x3A3F47)),
        "rain": ((0x1D2A3A, 0x33465B, 0x4E647C), (0x05080D, 0x0F1622, 0x1D2838)),
        "storm": ((0x14111F, 0x2B2440, 0x4A3F66), (0x05040A, 0x120F1D, 0x241E36)),
        "snow": ((0x46607D, 0x7790AB, 0xA6B8CC), (0x0E1420, 0x22304A, 0x3B4D6B))}

    def wx_kind(code):
        if code in (0, 1):
            return "clear"
        if code == 2:
            return "partly"
        if code == 3:
            return "cloudy"
        if code in (45, 48):
            return "fog"
        if 51 <= code <= 57:
            return "drizzle"
        if 61 <= code <= 67 or 80 <= code <= 82:
            return "rain"
        if 71 <= code <= 77 or code in (85, 86):
            return "snow"
        return "storm" if code >= 95 else "cloudy"

    def wx_sky():
        h = time.localtime().tm_hour
        phase = ("dawn" if h < 8 else "dusk" if h >= 17 else "day") if wx_isday else "night"
        kind = wx_kind(wx_code)
        cond = {"drizzle": "rain"}.get(kind, kind)
        if cond in COND:
            day, night = COND[cond]
            stops = night if phase == "night" else day
            if phase in ("dawn", "dusk"):          # a hint of sunrise/sunset behind the clouds
                stops = tuple(mix(a, b, 0.35) for a, b in zip(stops, SKY[phase]))
        else:
            stops = SKY[phase]
        wx_bg.colours(stops, 0x000000, 0.34)
        weather_ticker.pal[0] = wx_bg.glass_at(156)
        wx_icon.show(kind, phase != "night")

    def th_weather(cur, d):
        global wx_code, wx_isday
        wx_code = cur.get("weather_code", 0)
        wx_isday = cur.get("is_day", 1)
        lbl_temp.text = "%d" % round(cur["temperature_2m"])
        wx_deg.x = 66 + px_width(F_BIG, lbl_temp.text) + 4
        lbl_cond.text = WMO.get(wx_code, "")[:17]
        lbl_feels.text = "Feels like %d°" % round(cur["apparent_temperature"])
        vals = [t for t in d["hourly"]["temperature_2m"] if t is not None][-24:]
        if vals:
            lbl_range.text = "Low %d°  High %d°" % (round(min(vals)), round(max(vals)))
        wx_sky()

    def th_air(cur):
        pm = cur["pm2_5"]
        tile_vals[2].color = (0x7CE38B if pm <= 30 else 0xC6E36B if pm <= 60 else 0xFFD84D
                              if pm <= 90 else 0xFF9F43 if pm <= 120 else 0xFF6B6B
                              if pm <= 250 else 0xD08CFF)

    wx_sky()


# ============================================================= PORTFOLIO SCREEN
if CLASSIC:
    port_grp = displayio.Group()
    root = port_grp

    text(F_TITLE, "PORTFOLIO", 5, 4, GREYS[1])
    text(F_SMALL, "ZERODHA", 98, 4, GREYS[5])
    text(F_SMALL, "HOLDINGS", 98, 15, GREYS[5])
    lbl_pclock = text(F_TITLE, "--:--", 315, 4, GREYS[4], right=True)
    rect(5, 30, 310, 1, 8)
    rect(160, 38, 1, 64, 6)

    text(F_SMALL, "TODAY'S P&L", 6, 38, GREYS[5])
    lbl_day = text(F_MONEY, "--", 6, 54, GREYS[0])
    lbl_day_pct = text(F_MED, "", 6, 86, GREYS[3])
    text(F_SMALL, "TOTAL P&L", 168, 38, GREYS[5])
    lbl_tot = text(F_MONEY, "--", 168, 54, GREYS[0])
    lbl_tot_pct = text(F_MED, "", 168, 86, GREYS[3])

    port_tiles = []
    for i, name in enumerate(("INVESTED", "CURRENT", "STOCKS")):
        x = 5 + i * 105
        w = 100
        rrect(x, 110, w, 34, 4, 9)
        text(F_SMALL, name, x + w // 2, 117, GREYS[3], center=True)
        port_tiles.append(text(F_MED, "--", x + w // 2, 128, GREYS[2], center=True))

    text(F_SMALL, "MOVERS", 6, 151, GREYS[4])
    port_ticker = Ticker(54, 150, 260)
else:
    # Mood: the backdrop glows green or red with the day, and a dial (a preview of
    # the servo gauge project) swings to today's % move.
    port_grp = displayio.Group()
    root = port_grp
    port_bg = Backdrop(root, cards=((5, 29, 152, 114, 9), (4, 146, 312, 21, 7)))
    text(F_TITLE, "PORTFOLIO", 8, 5, WHITE)
    lbl_pstocks = text(F_SMALL, "ZERODHA", 104, 9, 0x9AA3AD)
    lbl_pclock = text(F_TITLE, "--:--", 314, 5, 0xB8C0C8, right=True)
    port_gauge = Gauge(root, 81, 112, 66, span=3.0)
    text(F_SMALL, "-3%", 13, 118, 0xB0B7BF)
    text(F_SMALL, "+3%", 149, 118, 0xB0B7BF, right=True)
    text(F_SMALL, "TODAY", 81, 36, 0xB0B7BF, center=True)
    lbl_day_pct = text(F_MED, "", 81, 126, WHITE, center=True)
    text(F_SMALL, "TODAY'S P&L", 166, 32, 0x9AA3AD)
    lbl_day = text(F_MONEY, "--", 165, 44, WHITE)
    text(F_SMALL, "TOTAL P&L", 166, 77, 0x9AA3AD)
    lbl_tot = text(F_TITLE, "--", 166, 88, WHITE)
    lbl_tot_pct = text(F_SMALL, "", 314, 92, WHITE, right=True)
    rect(166, 111, 148, 1, 9)
    text(F_SMALL, "INVESTED", 166, 117, 0x9AA3AD)
    text(F_SMALL, "CURRENT", 166, 131, 0x9AA3AD)
    port_tiles = [text(F_MED, "--", 314, 113, 0xE6EAEE, right=True),
                  text(F_MED, "--", 314, 127, 0xE6EAEE, right=True), Ghost()]
    port_ticker = Ticker(10, 149, 300, bg=0x101418, fg=WHITE, box=None)

    def port_mood(sign):
        glow = {1: 0x0F5A2C, -1: 0x6A1218}.get(sign, 0x22272D)
        port_bg.colours((0x07090B, mix(0x07090B, glow, 0.35), glow), 0xFFFFFF, 0.07)
        port_ticker.pal[0] = port_bg.glass_at(156)

    def th_port(v):
        if v is None:                                   # logged out
            port_mood(0)
            port_gauge.set(0)
            lbl_pstocks.text = "ZERODHA"
            return
        day, day_pct, total, total_pct, invested, current, n = v
        port_mood(1 if day >= 0 else -1)
        port_gauge.set(day_pct)
        lbl_tot_pct.text = "%+.2f%%" % total_pct
        npos = pos_cache[2] if pos_cache else 0
        lbl_pstocks.text = "ZERODHA - %d STOCKS%s" % (n, (", %d POS" % npos) if npos else "")

    def th_frame(showing):
        if showing == "portfolio":
            port_gauge.step()
        elif showing == "cricket":
            cric_sync()

    port_mood(0)


# ============================================================= CRICKET SCREEN
if CLASSIC:
    cric_grp = displayio.Group()
    root = cric_grp

    text(F_TITLE, "CRICKET", 5, 4, GREYS[1])
    lbl_ctype = text(F_SMALL, "", 82, 4, GREYS[5])
    lbl_clive = text(F_SMALL, "", 82, 15, GREYS[5])
    lbl_cclock = text(F_TITLE, "--:--", 315, 4, GREYS[4], right=True)
    lbl_cpage = text(F_SMALL, "", 262, 10, GREYS[5], right=True)       # "1/3": followed matches
    rect(5, 30, 310, 1, 8)
    lbl_cname = text(F_SMALL, "No match selected", 6, 34, GREYS[3])
    cric_team, cric_overs, cric_score = [], [], []
    for i in range(2):
        y0 = 52 + i * 46
        rrect(5, y0, 310, 42, 4, 10)
        cric_team.append(text(F_TITLE, "---", 14, y0 + 2, GREYS[2]))
        cric_overs.append(text(F_SMALL, "", 14, y0 + 26, GREYS[5]))
        cric_score.append(text(F_TIME, "", 306, y0 + 4, GREYS[2], right=True))
    cric_ticker = Ticker(10, 150, 300)
else:
    # Broadcast scorebug: team-colour blocks, big score, mown-pitch backdrop.
    cric_grp = displayio.Group()
    root = cric_grp
    cric_bg = Backdrop(root, cards=((5, 45, 310, 44, 6), (5, 93, 310, 44, 6), (4, 146, 312, 21, 7)),
                       stripes=20)
    cric_bg.colours((0x0A2414, 0x0F3A1F, 0x15502B), 0x000000, 0.55)
    text(F_TITLE, "CRICKET", 8, 5, WHITE)
    cric_pill = RoundRect(84, 6, 58, 16, 4, fill=0xE0242F)
    root.append(cric_pill)
    lbl_clive = text(F_SMALL, "", 113, 14, WHITE, center=True)
    lbl_ctype = Ghost()
    lbl_cclock = text(F_TITLE, "--:--", 314, 5, 0xCFE3D6, right=True)
    lbl_cpage = text(F_SMALL, "", 262, 10, 0xCFE3D6, right=True)       # "1/3": followed matches
    lbl_cname = text(F_SMALL, "No match selected", 8, 30, 0xE8F2EB)
    cric_team, cric_overs, cric_score, cric_block, cric_bat = [], [], [], [], []
    for i in range(2):
        y0 = 45 + i * 48
        bp = displayio.Palette(1)
        bp[0] = 0x2A2F36
        blk = vectorio.Rectangle(pixel_shader=bp, width=64, height=44, x=5, y=y0)
        root.append(blk)
        cric_block.append(bp)
        cric_team.append(text(F_TITLE, "", 37, y0 + 19, WHITE, center=True))
        cric_overs.append(text(F_SMALL, "", 78, y0 + 26, 0xBFD3C6))
        cric_score.append(text(F_TIME, "", 306, y0 + 9, WHITE, right=True))
        dot_pal = displayio.Palette(1)
        dot_pal[0] = 0xE0242F
        dot = vectorio.Circle(pixel_shader=dot_pal, radius=4, x=84, y=y0 + 14)
        dot.hidden = True
        root.append(dot)
        cric_bat.append(dot)
    cric_names = [text(F_MED, "", 78, 51 + i * 48, WHITE) for i in range(2)]
    cric_ticker = Ticker(10, 149, 300, bg=cric_bg.glass_at(156), fg=WHITE, box=None)

    def th_team(i, name, batting):
        c = team_colour(name if name else "")
        cric_block[i][0] = c
        cric_team[i].color = 0x111111 if luma(c) > 150 else WHITE
        cric_bat[i].hidden = not batting
        x = 96 if batting else 78
        room = 306 - px_width(F_TIME, cric_score[i].text) - 8 - x      # Test scores get long
        nm = _fit(F_MED, (name or "")[:14], room) if room > 24 else ""
        cric_names[i].text = nm
        cric_names[i].anchored_position = (x, 51 + i * 48)
        cric_names[i].color = WHITE if batting else 0xA9BDB0
        cric_score[i].color = WHITE if batting else 0xA9BDB0
        info = cric_overs[i].text.replace("  BATTING", "")
        cric_overs[i].text = "" if info.strip().lower() == (name or "").strip().lower()[:24] else info

    cric_pill_state = [None]

    def cric_sync():
        """Keep the LIVE/RESULT pill in step with the status label."""
        live = lbl_clive.text
        if live == cric_pill_state[0]:
            return
        cric_pill_state[0] = live
        cric_pill.hidden = not live
        lbl_clive.color = WHITE
        if live:
            cric_pill.fill = 0xE0242F if live == "LIVE" else 0x3A4A40


# ============================================================= MARKETS SCREEN
if CLASSIC:
    mkt_grp = displayio.Group()
    root = mkt_grp

    text(F_TITLE, "MARKETS", 5, 4, GREYS[1])
    text(F_SMALL, "INDIA", 92, 4, GREYS[5])
    text(F_SMALL, "USA", 92, 15, GREYS[5])
    lbl_mclock = text(F_TITLE, "--:--", 315, 4, GREYS[4], right=True)
    rect(5, 30, 310, 1, 8)
    INDICES = (
        {"name": "SENSEX", "yahoo": "%5EBSESN", "mkt": "in"},
        {"name": "NIFTY 50", "yahoo": "%5ENSEI", "mkt": "in"},
        {"name": "NASDAQ", "fmp": "^IXIC", "mkt": "us"},
        {"name": "S&P 500", "fmp": "^GSPC", "mkt": "us"},
    )
    mkt_val, mkt_chg, mkt_state = [], [], []
    for i, ix in enumerate(INDICES):
        x = 5 + (i % 2) * 157
        y = 35 + (i // 2) * 56
        rrect(x, y, 153, 52, 4, 10)
        text(F_SMALL, ix["name"], x + 7, y + 3, GREYS[4])
        mkt_state.append(text(F_SMALL, "", x + 147, y + 3, GREYS[6], right=True))
        mkt_val.append(text(F_TITLE, "--", x + 7, y + 14, GREYS[0]))
        mkt_chg.append(text(F_MED, "", x + 7, y + 32, GREYS[3]))
    mkt_ticker = Ticker(10, 150, 300)
else:
    # Trading terminal: amber on black, one row per index with a change bar.
    mkt_grp = displayio.Group()
    root = mkt_grp
    AMBER = 0xFFA028
    mkt_band_pal = displayio.Palette(1)
    mkt_band_pal[0] = AMBER
    root.append(vectorio.Rectangle(pixel_shader=mkt_band_pal, width=320, height=25, x=0, y=0))
    text(F_TITLE, "MARKETS", 7, 2, 0x000000)
    text(F_SMALL, "INDIA  USA", 92, 7, 0x4A2A00)
    lbl_mclock = text(F_TITLE, "--:--", 314, 2, 0x000000, right=True)
    INDICES = (
        {"name": "SENSEX", "yahoo": "%5EBSESN", "mkt": "in"},
        {"name": "NIFTY 50", "yahoo": "%5ENSEI", "mkt": "in"},
        {"name": "NASDAQ", "fmp": "^IXIC", "mkt": "us"},
        {"name": "S&P 500", "fmp": "^GSPC", "mkt": "us"},
    )
    mkt_val, mkt_chg, mkt_abs, mkt_dot, mkt_bar, mkt_barpal = [], [], [], [], [], []
    mkt_state = [Ghost() for _ in INDICES]       # open/closed is the dot's colour
    for i, ix in enumerate(INDICES):
        y = 29 + i * 29
        if i:
            rect(6, y, 308, 1, 9)
        dp = displayio.Palette(1)
        dp[0] = 0x3A3A3A
        root.append(vectorio.Circle(pixel_shader=dp, radius=4, x=11, y=y + 14))
        mkt_dot.append(dp)
        text(F_MED, ix["name"], 20, y + 6, AMBER)
        mkt_val.append(text(F_TITLE, "--", 196, y + 5, 0xF2F2F2, right=True))
        mkt_chg.append(text(F_MED, "", 262, y + 6, 0xB0B0B0, right=True))
        mkt_abs.append(text(F_SMALL, "", 314, y + 3, 0x8C8C8C, right=True))
        rect(268, y + 21, 46, 1, 8)
        rect(290, y + 17, 1, 9, 6)
        bp = displayio.Palette(1)
        bp[0] = GREEN
        bar = vectorio.Rectangle(pixel_shader=bp, width=1, height=5, x=290, y=y + 19)
        bar.hidden = True
        root.append(bar)
        mkt_bar.append(bar)
        mkt_barpal.append(bp)
    rect(6, 146, 308, 1, 8)
    mkt_ticker = Ticker(10, 151, 300, bg=0x000000, fg=AMBER, box=None)

    def th_index(i, last, change, pct, is_open):
        mkt_chg[i].text = "%+.2f%%" % pct
        mkt_abs[i].text = "%+.2f" % change
        mkt_dot[i][0] = GREEN if is_open else 0x4A4A4A
        w = min(23, max(1, int(abs(pct) / 2.0 * 23 + 0.5)))      # full bar = 2 %
        mkt_barpal[i][0] = GREEN if change >= 0 else RED
        mkt_bar[i].width = w
        mkt_bar[i].x = 291 if change >= 0 else 290 - w
        mkt_bar[i].hidden = False

    def show_index_error(i, msg):
        mkt_chg[i].text = ""
        mkt_abs[i].text = msg
        mkt_abs[i].color = 0x8C8C8C
        mkt_bar[i].hidden = True


# ============================================================= NEWS SCREEN
if CLASSIC:
    news_grp = displayio.Group()
    root = news_grp

    text(F_TITLE, "NEWS", 5, 4, GREYS[1])
    lbl_ncount = text(F_TITLE, "", 62, 4, GREYS[5])           # "3/10"
    lbl_nclock = text(F_TITLE, "--:--", 315, 4, GREYS[4], right=True)
    # progress bar: one segment per headline, the current one lit
    NEWS_COUNT = max(1, min(15, int(cfg("NEWS_COUNT") or "10")))
    news_seg = []
    _sw = (310 - (NEWS_COUNT - 1) * 2) // NEWS_COUNT
    for i in range(NEWS_COUNT):
        news_seg.append(vectorio.Rectangle(pixel_shader=pal, width=_sw, height=3,
                                           x=5 + i * (_sw + 2), y=28, color_index=9))
        root.append(news_seg[i])
    # headline: 4 lines at 24 px, or 5 lines at 20 px when it is long
    NEWS_TOP, NEWS_BOT, NEWS_W = 36, 147, 310
    news_big = [text(F_NEWS, "", 5, 0, GREYS[0]) for _ in range(4)]
    news_med = [text(F_NEWS2, "", 5, 0, GREYS[0]) for _ in range(5)]
    lbl_nsrc = text(F_SMALL, "", 5, 158, GREYS[4])
    lbl_nfoot = text(F_SMALL, "", 315, 158, GREYS[6], right=True)
else:
    # Lower third: red story tag, big white headline, progress dots.
    news_grp = displayio.Group()
    root = news_grp
    news_bg = Backdrop(root)
    news_bg.colours((0x0C1A3A, 0x08122A, 0x04070F))
    tag = displayio.Palette(1)
    tag[0] = 0xD7192A
    root.append(vectorio.Rectangle(pixel_shader=tag, width=104, height=23, x=0, y=0))
    root.append(vectorio.Rectangle(pixel_shader=tag, width=3, height=106, x=7, y=38))
    text(F_TITLE, "TOP STORY", 7, 4, WHITE)
    lbl_ncount = text(F_TITLE, "", 112, 4, 0x8FA3C7)
    lbl_nclock = text(F_TITLE, "--:--", 314, 4, 0x8FA3C7, right=True)
    NEWS_COUNT = max(1, min(15, int(cfg("NEWS_COUNT") or "10")))
    news_seg = []
    for i in range(NEWS_COUNT):
        dot = vectorio.Circle(pixel_shader=pal, radius=2, x=314 - (NEWS_COUNT - 1 - i) * 9, y=161,
                              color_index=9)
        root.append(dot)
        news_seg.append(dot)
    SEG_COLS = (I_WHITE, 6, 9)
    NEWS_TOP, NEWS_BOT, NEWS_W, NEWS_X = 30, 150, 298, 17
    news_big = [text(F_NEWS, "", NEWS_X, 0, WHITE) for _ in range(4)]
    news_med = [text(F_NEWS2, "", NEWS_X, 0, WHITE) for _ in range(5)]
    lbl_nsrc = text(F_SMALL, "", 8, 156, 0xFF5A66)
    lbl_nfoot = Ghost()


# ============================================================= ANALOG CLOCK SCREEN
# Big analog clock; also used (dark and dimmed) as the night screen.
if CLASSIC:
    clock_grp = displayio.Group()
    root = clock_grp

    big_clock = AnalogClock(root, 86, 85, 80, numbers=True)
    lbl_cday = text(F_TITLE, "", 180, 8, GREYS[1])
    lbl_cdate = text(F_TIME, "", 180, 28, GREYS[0])
    lbl_cyear = text(F_SMALL, "", 182, 64, GREYS[5])
    lbl_ctemp = text(F_MED, "", 180, 84, GREYS[2])
    lbl_cdesc = text(F_SMALL, "", 182, 106, GREYS[5])
    lbl_cpct = text(F_SMALL, "", 182, 128, GREYS[6])
    day_bar = displayio.Bitmap(130, 5, 3)
    day_pal = displayio.Palette(3)
    day_pal[0], day_pal[1], day_pal[2] = GREYS[9], GREEN, GREYS[10]
    root.append(displayio.TileGrid(day_bar, pixel_shader=day_pal, x=182, y=146))
    CLK_TEXT = (lbl_cday, lbl_cdate, lbl_cyear, lbl_ctemp, lbl_cdesc, lbl_cpct)
    CLK_DAY_COL = (GREYS[1], GREYS[0], GREYS[5], GREYS[2], GREYS[5], GREYS[6])
    night_mode = False


    def clock_theme(night):
        if night:
            big_clock.colours(0x000000, 0x1A1A1A, 0x262626, 0x5A5A5A, 0x6A6A6A, 0x7A7A7A, 0x6A1A1A,
                              numbers=0x444444)
            for lbl in CLK_TEXT:
                lbl.color = 0x4A4A4A
            day_pal[0], day_pal[1] = 0x141414, 0x1E4A2E
        else:
            big_clock.colours(0x0C0C0C, 0x4A4A4A, 0x6A6A6A, 0xE6E6E6, 0xE0E0E0, 0xFFFFFF, 0xFF4848,
                              numbers=0xB4B4B4)
            for lbl, col in zip(CLK_TEXT, CLK_DAY_COL):
                lbl.color = col
            day_pal[0], day_pal[1] = GREYS[9], GREEN
else:
    # Station clock by day (white Swiss face, red "lollipop" seconds hand);
    # warm amber at night so the bedroom isn't lit blue.
    clock_grp = displayio.Group()
    root = clock_grp
    big_clock = AnalogClock(root, 86, 85, 80, numbers=True, tip=True, blunt=True)
    lbl_cday = text(F_TITLE, "", 180, 8, GREYS[1])
    lbl_cdate = text(F_TIME, "", 180, 28, GREYS[0])
    lbl_cyear = text(F_SMALL, "", 182, 64, GREYS[5])
    lbl_ctemp = text(F_MED, "", 180, 84, GREYS[2])
    lbl_cdesc = text(F_SMALL, "", 182, 106, GREYS[5])
    lbl_cpct = text(F_SMALL, "", 182, 128, GREYS[6])
    day_bar = displayio.Bitmap(130, 5, 3)
    day_pal = displayio.Palette(3)
    day_pal[0], day_pal[1], day_pal[2] = GREYS[9], GREEN, GREYS[10]
    root.append(displayio.TileGrid(day_bar, pixel_shader=day_pal, x=182, y=146))
    CLK_TEXT = (lbl_cday, lbl_cdate, lbl_cyear, lbl_ctemp, lbl_cdesc, lbl_cpct)
    CLK_DAY_COL = (0xFFFFFF, 0xFFFFFF, 0x9A9A9A, 0xE0E0E0, 0x9A9A9A, 0x8A8A8A)
    night_mode = False

    def clock_theme(night):
        if night:
            big_clock.colours(0x000000, 0x1C1000, 0x2A1A04, 0x6A4208, 0x8A5A12, 0xA0691A, 0x6A1A08,
                              numbers=0x5A3A0A)
            for lbl in CLK_TEXT:
                lbl.color = 0x6A4612
            day_pal[0], day_pal[1] = 0x140C02, 0x5A3A0A
        else:
            big_clock.colours(0xF6F6F2, 0x8A8F96, 0x3A3D42, 0x111111, 0x111111, 0x111111, 0xD22630,
                              numbers=0x111111)
            for lbl, col in zip(CLK_TEXT, CLK_DAY_COL):
                lbl.color = col
            day_pal[0], day_pal[1] = 0x2A2A2A, 0xD22630

DAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def clock_minute(t):
    lbl_cday.text = DAYS[t.tm_wday]
    lbl_cdate.text = "%02d %s" % (t.tm_mday, MONTHS[t.tm_mon - 1])
    lbl_cyear.text = str(t.tm_year)
    lbl_wday.text = DAYS[t.tm_wday][:3]
    lbl_wdate.text = "%02d %s" % (t.tm_mday, MONTHS[t.tm_mon - 1])
    frac = (t.tm_hour * 60 + t.tm_min) / 1440
    lbl_cpct.text = "%d%% OF THE DAY GONE" % int(frac * 100)
    lbl_wdaypct.text = "DAY %d%%" % int(frac * 100)
    day_bar.fill(0)
    if int(130 * frac):
        bitmaptools.fill_region(day_bar, 0, 0, int(130 * frac), 5, 1)
    wx_daybar.fill(0)
    if int(wx_daybar.width * frac):
        bitmaptools.fill_region(wx_daybar, 0, 0, int(wx_daybar.width * frac), 3, 1)
    th_minute(t)


clock_theme(False)

# ============================================================= EXTRA SCREENS
# Stat of the day, holdings heatmap, internet health, trivia, a virtual pet and three
# night screensavers (matrix, fire, stars). Each one is a Screen: the main loop calls
# tick() every pass (background refresh), enter() when it appears, frame() while it is
# showing, boot() for the BOOT button and second() once a second.

class Screen:
    dwell = None                    # seconds on screen when auto-rotating (None = SCREEN_SECONDS)

    def __init__(self):
        self.grp = displayio.Group()

    def tick(self, now):
        pass

    def enter(self, now):
        pass

    def frame(self, now):
        pass

    def boot(self, now):
        pass

    def second(self, hhmm):
        if self.clock is not None:
            self.clock.text = hhmm

    def skip(self):
        return False

    def refresh(self):
        pass

    clock = None


def _head(title, accent, sub=""):
    """Common header: an accent bar, the title, an optional subtitle and the clock."""
    p = displayio.Palette(1)
    p[0] = accent
    root.append(vectorio.Rectangle(pixel_shader=p, width=3, height=18, x=0, y=3))
    text(F_TITLE, title, 8, 3, WHITE)
    s = text(F_SMALL, sub, 8 + px_width(F_TITLE, title) + 8, 8, 0x8A9099)
    c = text(F_TITLE, "--:--", 314, 3, 0x9AA3AD, right=True)
    return s, c


def _tile(x, y, w, h, label, fill=0x1A1E23, both=False):
    root.append(RoundRect(x, y, w, h, 5, fill=fill))
    lab = text(F_SMALL, label, x + 6, y + 4, 0x8A9099)
    val = text(F_MED, "--", x + 6, y + 17, WHITE)
    return (lab, val) if both else val


def _shuffle(items):
    for i in range(len(items) - 1, 0, -1):
        j = random.randint(0, i)
        items[i], items[j] = items[j], items[i]
    return items


def _tagless(h):
    """Text of an HTML fragment: tags removed, a few entities decoded, trimmed."""
    while True:
        a = h.find("<")
        if a < 0:
            break
        b = h.find(">", a)
        if b < 0:
            h = h[:a]
            break
        h = h[:a] + h[b + 1:]
    return h.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'").strip()


def _cells(row, tag="<td"):
    return [_tagless(c[c.find(">") + 1:]) for c in row.split(tag)[1:]]


def _ago(secs):
    secs = int(max(0, secs))
    if secs < 90:
        return "%ds" % secs
    if secs < 3600:
        return "%dm" % (secs // 60)
    if secs < 172800:
        return "%dh %dm" % (secs // 3600, secs // 60 % 60)
    return "%dd %dh" % (secs // 86400, secs // 3600 % 24)


EXTRA = {}
port_day_pct = None             # today's portfolio move, set by get_portfolio (None = no data)


# ------------------------------------------------------------- stat of the day
# A player's international numbers for this year, from ESPNcricinfo Statsguru.
# STAT_PLAYERS = "253802:Virat Kohli,625383:Jasprit Bumrah:bowl"  (Cricinfo player id:name[:bowl])
# The BOOT button moves to the next player. Without data it shows a cricket fact instead.
STAT_DEFAULT = ("253802:Virat Kohli,34102:Rohit Sharma,625383:Jasprit Bumrah:bowl,"
                "1070173:Shubman Gill")


def parse_players(text_):
    out = []
    for p in (text_ or STAT_DEFAULT).split(","):
        f = [x.strip() for x in p.split(":")]
        if len(f) >= 2 and f[0].isdigit():
            out.append((f[0], f[1], len(f) > 2 and f[2].lower().startswith("bowl")))
    return out


STAT_PLAYERS = parse_players(cfg("STAT_PLAYERS"))
STAT_CLASS = cfg("STAT_CLASS") or "11"          # 11 all internationals, 1 Tests, 2 ODIs, 3 T20Is
STAT_URL = ("https://stats.espncricinfo.com/ci/engine/player/%s.html"
            "?class=%s;template=results;type=%s;view=year")
STAT_FORMAT = {"1": "Tests", "2": "ODIs", "3": "T20Is", "11": "internationals"}.get(STAT_CLASS, "matches")
CRICKET_FACTS = (
    ("100", "international hundreds", "Sachin Tendulkar is the only player with 100 international centuries."),
    ("264", "highest ODI score", "Rohit Sharma against Sri Lanka at Eden Gardens, Kolkata, 2014."),
    ("99.94", "Test batting average", "Don Bradman's career average - nobody else is close."),
    ("800", "Test wickets", "Muttiah Muralidaran, the most in Test history."),
    ("15,921", "Test runs", "Sachin Tendulkar, the most in Test history."),
    ("18,426", "ODI runs", "Sachin Tendulkar, the most in ODI history."),
    ("619", "Test wickets", "Anil Kumble, India's leading Test wicket-taker."),
    ("10", "wickets in an innings", "Anil Kumble took all ten against Pakistan in Delhi, 1999."),
    ("6", "sixes in an over", "Yuvraj Singh off Stuart Broad, T20 World Cup, Durban, 2007."),
    ("3", "ODI double hundreds", "Rohit Sharma is the only player with three."),
    ("50", "ODI hundreds", "Virat Kohli passed Sachin's 49 in the 2023 World Cup semi-final."),
    ("400", "highest Test score", "Brian Lara, 400 not out against England, Antigua, 2004."),
    ("175", "runs from 17 for 5", "Kapil Dev against Zimbabwe, 1983 World Cup, Tunbridge Wells."),
    ("1983", "first World Cup", "Kapil Dev's India beat West Indies in the final at Lord's."),
    ("2007", "first T20 World Cup", "India beat Pakistan in the final in Johannesburg."),
    ("2011", "World Cup at home", "MS Dhoni finished the final with a six at the Wankhede."),
    ("2024", "T20 World Cup", "India beat South Africa in the final in Barbados."),
    ("36", "all out", "India's lowest Test total, against Australia in Adelaide, 2020."),
)


class StatScreen(Screen):
    def __init__(self):
        global root
        Screen.__init__(self)
        root = self.grp
        self.sub, self.clock = _head("STAT OF THE DAY", 0x1F5FBF)
        self.name = text(F_TITLE, "", 8, 30, WHITE)
        self.big = text(F_MONEY, "", 8, 52, 0xFFD27A)
        self.unit = text(F_MED, "", 120, 63, 0xE6EAEE)
        self.tile_grp = displayio.Group()
        root.append(self.tile_grp)
        root = self.tile_grp
        self.tiles = []
        self.tile_lbls = []
        for i in range(5):
            x = 4 + i * 63
            root.append(RoundRect(x, 92, 60, 38, 5, fill=0x1A1E23))
            self.tile_lbls.append(text(F_SMALL, "", x + 30, 99, 0x8A9099, center=True))
            self.tiles.append(text(F_MED, "", x + 30, 118, WHITE, center=True))
        root = self.grp
        self.fact_lbls = [text(F_MED, "", 8, 96, 0xE6EAEE), text(F_MED, "", 8, 116, 0xE6EAEE)]
        self.note = text(F_SMALL, "", 8, 140, 0xB8C0C8)
        self.foot = text(F_SMALL, "", 8, 157, 0x6A727B)
        self.cache = {}             # player id -> (time fetched, data dict or None, error)
        self.offset = 0
        self.last_try = -1e6
        self.debug = "not fetched yet"

    def player(self):
        if not STAT_PLAYERS:
            return None
        day = time.localtime().tm_yday
        return STAT_PLAYERS[(day + self.offset) % len(STAT_PLAYERS)]

    def refresh(self):
        self.cache = {}
        self.last_try = -1e6

    def tick(self, now):
        p = self.player()
        if not p:
            return
        got = self.cache.get(p[0])
        stale = got is None or now - got[0] > (6 * 3600 if got[1] else 1800)
        if stale and now - self.last_try > 60:
            self.last_try = now
            safe(lambda: self.fetch(p, now), "stat")
            self.show()

    def fetch(self, p, now):
        pid, name, bowl = p
        url = STAT_URL % (pid, STAT_CLASS, "bowling" if bowl else "batting")
        status = None
        body = bytearray()
        try:
            with requests.get(url, headers=YAHOO_HDR, timeout=NET_TIMEOUT) as r:
                status = r.status_code
                for chunk in r.iter_content(chunk_size=2048):
                    body.extend(chunk)
                    dog()
                    if len(body) > 700000:
                        break
        except Exception as e:  # noqa: BLE001
            self.cache[pid] = (now, None, "network: %r" % e)
            self.debug = "%s: %r" % (url, e)
            raise
        html = _text(bytes(body))
        data = self.parse(html, bowl)
        self.debug = "%s\nHTTP %s, %d bytes\nparsed: %r" % (url, status, len(body), data)
        self.cache[pid] = (now, data, None if data else "HTTP %s, no table found" % status)

    def parse(self, html, bowl):
        yr = time.localtime().tm_year
        out = {"year": yr}
        for key, label in (("now", "year %d" % yr), ("career", "unfiltered")):
            i = html.find(label)
            if i < 0:
                continue
            rs = html.rfind("<tr", 0, i)
            re_ = html.find("</tr>", i)
            vals = _cells(html[rs:re_])
            th = html.rfind("<thead", 0, rs)
            names = _cells(html[th:html.find("</thead>", th)], "<th") if th >= 0 else []
            if len(names) != len(vals):          # unexpected layout: assume the usual columns
                names = (["", "Span", "Mat", "Inns", "Overs", "Mdns", "Runs", "Wkts", "BBI", "Ave",
                          "Econ", "SR", "4", "5"] if bowl else
                         ["", "Span", "Mat", "Inns", "NO", "Runs", "HS", "Ave", "BF", "SR",
                          "100", "50", "0", "4s", "6s"])
            out[key] = dict(zip(names, vals))
        return out if ("now" in out or "career" in out) else None

    def enter(self, now):
        self.show()

    def boot(self, now):
        self.offset += 1
        self.last_try = -1e6            # fetch the next player's numbers straight away
        self.show()

    def show(self):
        p = self.player()
        got = self.cache.get(p[0]) if p else None
        data = got[1] if got else None
        if not data:
            self.fact()
            if p and got and got[2]:
                self.foot.text = ("%s: no stats (%s)" % (p[1], got[2]))[:52]
            return
        pid, name, bowl = p
        now_d = data.get("now") or {}
        car = data.get("career") or {}
        self.sub.text = STAT_FORMAT.upper()
        self.name.text = name
        self.tile_grp.hidden = False
        self.fact_lbls[0].text = self.fact_lbls[1].text = ""
        main = "Wkts" if bowl else "Runs"
        if now_d:
            self.big.text = commas(now_d.get(main, "0"))
            self.unit.text = "%s in %d" % ("wickets" if bowl else "runs", data["year"])
        else:
            self.big.text = "0"
            self.unit.text = "%s yet in %d" % (STAT_FORMAT, data["year"])
        self.unit.anchored_position = (8 + px_width(F_MONEY, self.big.text) + 8, 63)
        cols = (("MAT", "Mat"), ("AVE", "Ave"), ("ECON", "Econ"), ("BEST", "BBI"), ("5W", "5")) if bowl \
            else (("MAT", "Mat"), ("INNS", "Inns"), ("AVE", "Ave"), ("SR", "SR"), ("100/50", None))
        for i, (lab, key) in enumerate(cols):
            self.tile_lbls[i].text = lab
            if key is None:
                v = "%s/%s" % (now_d.get("100", "-"), now_d.get("50", "-")) if now_d else "-"
            else:
                v = now_d.get(key, "-") if now_d else "-"
            self.tiles[i].text = v[:7]
        if car:
            line = ("Career: %s wickets at %s, best %s" % (car.get("Wkts", "?"), car.get("Ave", "?"),
                                                          car.get("BBI", "?")) if bowl else
                    "Career: %s runs at %s, %s hundreds" % (commas(car.get("Runs", "?")),
                                                           car.get("Ave", "?"), car.get("100", "?")))
        else:
            line = ""
        self.note.text = line[:52]
        t = time.localtime()
        self.foot.text = "Statsguru  -  player %d/%d  -  BOOT for next" % (
            (t.tm_yday + self.offset) % len(STAT_PLAYERS) + 1, len(STAT_PLAYERS))

    def fact(self):
        t = time.localtime()
        big, unit, detail = CRICKET_FACTS[(t.tm_yday + self.offset) % len(CRICKET_FACTS)]
        self.sub.text = "CRICKET FACT"
        self.name.text = ""
        self.big.text = big
        self.unit.text = unit
        self.unit.anchored_position = (8 + px_width(F_MONEY, big) + 8, 63)
        self.tile_grp.hidden = True          # the detail sits where the tiles would be
        rows, _ = wrap_px(F_MED, detail, 304, 2)
        self.note.text = ""
        self.fact_lbls[0].text = rows[0] if rows else ""
        self.fact_lbls[1].text = rows[1] if len(rows) > 1 else ""
        self.foot.text = "BOOT for another"


def commas(s):
    """'12345' -> '12,345' (leaves anything else alone)."""
    s = str(s).strip()
    if not s.isdigit() or len(s) < 4:
        return s
    out = ""
    while len(s) > 3:
        out = "," + s[-3:] + out
        s = s[:-3]
    return s + out


stat_screen = StatScreen()
EXTRA["stat"] = stat_screen


# ------------------------------------------------------------- holdings heatmap
# One tile per stock, sized by its value and coloured by today's move (squarified treemap).
def squarify(vals, x, y, w, h):
    """Rectangles (x, y, w, h) for values sorted largest first, as square as possible."""
    total = float(sum(vals)) or 1.0
    areas = [v * w * h / total for v in vals]
    out = []

    def worst(row, side):
        s = sum(row)
        return max(side * side * max(row) / (s * s), s * s / (side * side * min(row)))

    i = 0
    while i < len(areas):
        side = min(w, h) or 1
        row = [areas[i]]
        i += 1
        while i < len(areas) and worst(row + [areas[i]], side) <= worst(row, side):
            row.append(areas[i])
            i += 1
        s = sum(row)
        if w >= h:                          # a column on the left
            cw = s / h if h else 0
            yy = y
            for a in row:
                rh = a / cw if cw else 0
                out.append((x, yy, cw, rh))
                yy += rh
            x += cw
            w -= cw
        else:                               # a row along the top
            rh = s / w if w else 0
            xx = x
            for a in row:
                rw = a / rh if rh else 0
                out.append((xx, y, rw, rh))
                xx += rw
            y += rh
            h -= rh
    return out


def move_colour(pct):
    t = min(1.0, abs(pct) / 3.0) ** 0.7
    return mix(0x2B3037, 0x1E9E50 if pct >= 0 else 0xD23A3A, 0.25 + 0.75 * t if pct else 0)


class HeatScreen(Screen):
    MAX = 16

    def __init__(self):
        global root
        Screen.__init__(self)
        root = self.grp
        self.sub, self.clock = _head("HOLDINGS", 0x1E9E50, "TODAY")
        self.tiles = []
        for _ in range(self.MAX):
            p = displayio.Palette(1)
            p[0] = 0x2B3037
            r = vectorio.Rectangle(pixel_shader=p, width=1, height=1, x=0, y=0)
            r.hidden = True
            root.append(r)
            self.tiles.append((r, p, text(F_MED, "", 0, 0, WHITE), text(F_SMALL, "", 0, 0, WHITE),
                               text(F_SMALL, "", 0, 0, 0xE6EAEE)))
        self.msg = text(F_MED, "Log in to Kite to see your holdings", 160, 95, 0x8A9099, center=True)
        self.rows = None

    def update(self, rows):
        """rows: [(symbol, value, day %)] or None when logged out."""
        self.rows = rows
        if self.grp is display.root_group:
            self.draw()

    def enter(self, now):
        self.draw()

    def skip(self):
        return not self.rows

    def draw(self):
        rows = sorted(self.rows or [], key=lambda r: -r[1])
        for r, p, big, small, pct in self.tiles:
            r.hidden = True
            big.text = small.text = pct.text = ""
        if not rows:
            self.msg.text = "Log in to Kite to see your holdings"
            self.sub.text = "TODAY"
            return
        self.msg.text = ""
        total = sum(v for _, v, _ in rows) or 1
        day = sum(v * p / (100 + p) for _, v, p in rows)          # rupees moved today
        self.sub.text = "%d STOCKS  %+.2f%% TODAY" % (len(rows), day / (total - day) * 100)
        if len(rows) > self.MAX:                                  # fold the tail into one tile
            rest = rows[self.MAX - 1:]
            rv = sum(v for _, v, _ in rest)
            rows = rows[:self.MAX - 1] + [("+%d MORE" % len(rest), rv,
                                           sum(v * p for _, v, p in rest) / rv if rv else 0)]
        rects = squarify([max(v, total * 0.002) for _, v, _ in rows], 2, 25, 316, 143)
        for (sym, v, pct), (x, y, w, h), (r, p, big, small, plab) in zip(rows, rects, self.tiles):
            x0, y0 = int(x + 0.5), int(y + 0.5)
            x1, y1 = int(x + w + 0.5), int(y + h + 0.5)
            r.x, r.y = x0 + 1, y0 + 1
            r.width, r.height = max(1, x1 - x0 - 2), max(1, y1 - y0 - 2)
            p[0] = move_colour(pct)
            r.hidden = False
            tw, th = x1 - x0, y1 - y0
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            if tw >= 62 and th >= 38 and px_width(F_MED, sym) <= tw - 6:
                big.text = sym
                big.anchor_point = (0.5, 0.5)
                big.anchored_position = (cx, cy - 9)
                plab.text = "%+.1f%%" % pct
                plab.anchor_point = (0.5, 0.5)
                plab.anchored_position = (cx, cy + 12)
            elif tw >= 24 and th >= 14:
                n = max(2, (tw - 4) // 6)
                small.text = sym[:n]
                small.anchor_point = (0.5, 0.5)
                small.anchored_position = (cx, cy - (6 if th >= 28 else 0))
                if th >= 28 and tw >= 36:
                    plab.text = "%+.1f%%" % pct
                    plab.anchor_point = (0.5, 0.5)
                    plab.anchored_position = (cx, cy + 7)


heat_screen = HeatScreen()
EXTRA["heatmap"] = heat_screen


# ------------------------------------------------------------- internet health
# Ping to the internet and the router, Wi-Fi signal, a speed test of the board's own
# download speed, router uptime over UPnP (if the router allows it) and the outage log.
PING_HOST = cfg("PING_HOST") or "1.1.1.1"
# speed test servers, tried in order: plain HTTP first (TLS is slow and memory-hungry on the
# board), a CDN close to India, then fallbacks
SPEED_URLS = ("http://cachefly.cachefly.net/1mb.test",
              "https://speed.cloudflare.com/__down?bytes=1000000",
              "http://speedtest.tele2.net/1MB.zip")
SPEED_HDR = {"User-Agent": "Mozilla/5.0 (T-Display-S3 desk dashboard)"}
net_log = []          # (wall time it went down, wall time it came back)
net_down_at = None


def net_note(state):
    """Called by the outage code: remembers when the connection dropped and came back."""
    global net_down_at
    if state == "down" and net_down_at is None:
        net_down_at = time.time()
    elif state == "up" and net_down_at is not None:
        net_log.append((net_down_at, time.time()))
        del net_log[:-5]
        net_down_at = None


class NetScreen(Screen):
    N = 52                                  # ping samples in the graph

    def __init__(self):
        global root
        Screen.__init__(self)
        root = self.grp
        self.sub, self.clock = _head("INTERNET", 0x2FA7E0)
        self.pill = RoundRect(112, 5, 70, 15, 4, fill=0x1E9E50)
        root.append(self.pill)
        self.pill_lbl = text(F_SMALL, "ONLINE", 147, 12, WHITE, center=True)
        self.ping_lbl = text(F_SMALL, "PING " + PING_HOST, 8, 26, 0x8A9099)
        self.ping = text(F_NEWS, "--", 8, 36, WHITE)
        self.ping_sub = text(F_SMALL, "", 8, 68, 0x8A9099)
        self.g = displayio.Bitmap(self.N * 3, 46, 5)
        self.g_back = displayio.Bitmap(self.N * 3, 46, 5)
        gp = displayio.Palette(5)
        gp[0], gp[1], gp[2], gp[3], gp[4] = 0x12161A, 0x2FA7E0, 0xFFB020, 0xE0443A, 0x2A3038
        root.append(displayio.TileGrid(self.g, pixel_shader=gp, x=316 - self.N * 3, y=28))
        self.samples = []
        self.t_router = _tile(4, 82, 101, 38, "ROUTER PING")
        self.t_wifi_lab, self.t_wifi = _tile(109, 82, 101, 38, "WI-FI SIGNAL", both=True)
        self.t_speed = _tile(214, 82, 102, 38, "SPEED (BOARD)")
        self.t_rup = _tile(4, 126, 101, 38, "ROUTER UP")
        self.t_on = _tile(109, 126, 101, 38, "ONLINE FOR")
        self.t_out = _tile(214, 126, 102, 38, "LAST OUTAGE")
        self.last_ping = self.last_speed = self.last_upnp = -1e6
        self.speed_now = False
        self.speed_ok = False
        self.speed_log = "not run yet"
        self.upnp_log = "not tried yet"
        self.upnp_ctl = None
        self.upnp_tries = 0
        self.router_up = None           # (uptime seconds, monotonic when read)
        self.started = time.monotonic()

    def refresh(self):
        self.last_ping = -1e6

    def tick(self, now):
        showing_me = self.grp is display.root_group
        if now - self.last_ping > (5 if showing_me else 60):
            self.last_ping = now
            self.do_ping()
        wait = 1800 if self.speed_ok else 120             # after a failure, try again soon
        if net_state == "ok" and (self.speed_now or now - self.last_speed > wait):
            if showing_me or self.speed_now or self.last_speed < 0:
                self.speed_now = False
                self.last_speed = now
                self.t_speed.text = "testing..."
                if not safe(self.speed_test, "speed test"):
                    self.t_speed.text = "failed"
                    self.speed_ok = False
        if net_state == "ok" and showing_me and now - self.last_upnp > 600 and self.upnp_tries < 3:
            self.last_upnp = now
            try:
                self.upnp()
            except Exception as e:  # noqa: BLE001 - many routers have UPnP switched off
                self.upnp_log = "router uptime (UPnP): %r" % e
                print(self.upnp_log)
                self.upnp_tries += 1
                if not self.router_up:
                    self.t_rup.text = "n/a"
                self.upnp_ctl = None
            free_sockets()

    def do_ping(self):
        ms = gw = None
        if wifi_up():
            dog()
            try:
                t = wifi.radio.ping(ipaddress.ip_address(PING_HOST), timeout=1)
                ms = None if t is None else t * 1000
            except Exception as e:  # noqa: BLE001
                print("ping:", repr(e))
            try:
                t = wifi.radio.ping(wifi.radio.ipv4_gateway, timeout=1)
                gw = None if t is None else t * 1000
            except Exception:  # noqa: BLE001
                pass
        self.samples.append(ms)
        del self.samples[:-self.N]
        self.t_router.text = "--" if gw is None else "%d ms" % gw
        try:
            rssi = wifi.radio.ap_info.rssi
            word = "GREAT" if rssi > -55 else "GOOD" if rssi > -67 else "FAIR" if rssi > -75 else "WEAK"
            self.t_wifi.text = "%d dBm" % rssi
            self.t_wifi_lab.text = "WI-FI: " + word
        except Exception:  # noqa: BLE001
            self.t_wifi.text = "--"
        self.draw()

    def draw(self):
        ok = [s for s in self.samples if s is not None]
        last = self.samples[-1] if self.samples else None
        self.ping.text = "timeout" if (self.samples and last is None) else ("--" if last is None
                                                                           else "%d ms" % last)
        self.ping.color = 0xE0443A if last is None else (WHITE if last < 100 else 0xFFB020)
        if self.samples:
            loss = 100 * (len(self.samples) - len(ok)) // len(self.samples)
            self.ping_sub.text = ("avg %d ms  loss %d%%" % (sum(ok) / len(ok), loss)) if ok \
                else "no replies"
        g = self.g_back                              # draw off-screen, then copy in one go
        g.fill(0)
        for y in (11, 22, 33):                       # grid lines every 50 ms
            bitmaptools.fill_region(g, 0, y, g.width, y + 1, 4)
        x = g.width - 3 * len(self.samples)
        for s in self.samples:
            if s is None:
                bitmaptools.fill_region(g, x, 0, x + 2, g.height, 3)
            else:
                h = max(2, min(g.height, int(s / 150 * g.height)))
                bitmaptools.fill_region(g, x, g.height - h, x + 2, g.height, 1 if s < 100 else 2)
            x += 3
        bitmaptools.blit(self.g, g, 0, 0)
        self.status()

    def status(self):
        st = {"ok": ("ONLINE", 0x1E9E50), "noinet": ("OFFLINE", 0xC62828),
              "nowifi": ("NO WI-FI", 0xC62828)}[net_state]
        self.pill_lbl.text, self.pill.fill = st
        wall = time.time()
        if net_down_at is not None:
            self.t_on.text = "down " + _ago(wall - net_down_at)
        else:
            since = net_log[-1][1] if net_log else None
            self.t_on.text = _ago(wall - since) if since else _ago(time.monotonic() - self.started)
        if net_log:
            a, b = net_log[-1]
            t = time.localtime(int(a))
            self.t_out.text = "%02d:%02d %s" % (t.tm_hour, t.tm_min, _ago(b - a))
        else:
            self.t_out.text = "none"
        if self.router_up:
            up, at = self.router_up
            self.t_rup.text = _ago(up + time.monotonic() - at)
        elif self.upnp_tries >= 3:
            self.t_rup.text = "n/a"

    def second(self, hhmm):
        Screen.second(self, hhmm)
        if self.grp is display.root_group:
            self.status()

    def boot(self, now):
        self.speed_now = True               # BOOT on this screen: run a speed test now

    def _download(self, url):
        """Bytes received and seconds taken (up to 1 MB or 8 s, timed from the first byte)."""
        n = 0
        with requests.get(url, headers=SPEED_HDR, timeout=NET_TIMEOUT) as r:
            if r.status_code != 200:
                raise RuntimeError("HTTP %s" % r.status_code)
            t0 = time.monotonic()
            for chunk in r.iter_content(chunk_size=4096):
                n += len(chunk)
                dog()
                if n >= 1000000 or time.monotonic() - t0 > 8:
                    break
            secs = time.monotonic() - t0
        free_sockets()                  # a half-read connection must never be reused
        return n, max(0.001, secs)

    def speed_test(self):
        tried = []
        for url in SPEED_URLS:
            host = url.split("/")[2]
            self.t_speed.text = "testing..."
            try:
                n, secs = self._download(url)
            except Exception as e:  # noqa: BLE001 - try the next server
                free_sockets()
                tried.append("%s: %r" % (host, e))
                continue
            if n < 100000:
                tried.append("%s: only %d bytes" % (host, n))
                continue
            mbps = n * 8 / secs / 1e6
            self.t_speed.text = "%.1f Mbps" % mbps if mbps < 100 else "%d Mbps" % mbps
            self.speed_ok = True
            t = time.localtime()
            self.speed_log = "%02d:%02d  %s: %d KB in %.1f s = %.2f Mbps%s" % (
                t.tm_hour, t.tm_min, host, n // 1024, secs, mbps,
                ("  (failed first: %s)" % "; ".join(tried)) if tried else "")
            return
        self.speed_ok = False
        self.t_speed.text = "failed"
        self.speed_log = "all servers failed: " + "; ".join(tried)
        log_err("speed test: " + "; ".join(tried))

    def upnp(self):
        """Ask the router how long its internet link has been up (UPnP GetStatusInfo)."""
        if not self.upnp_ctl:
            msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
                   "MX: 2\r\nST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n")
            buf = bytearray(1024)
            with pool.socket(pool.AF_INET, pool.SOCK_DGRAM) as s:
                s.settimeout(3)
                s.sendto(msg.encode(), ("239.255.255.250", 1900))
                n, _ = s.recvfrom_into(buf)
            reply = _text(bytes(buf[:n]))
            loc = None
            for line in reply.split("\r\n"):
                if line.lower().startswith("location:"):
                    loc = line.split(":", 1)[1].strip()
            if not loc:
                raise RuntimeError("no LOCATION in reply")
            with requests.get(loc, timeout=NET_TIMEOUT) as r:
                desc = r.text
            for svc in ("WANIPConnection:1", "WANPPPConnection:1", "WANIPConnection:2"):
                i = desc.find("urn:schemas-upnp-org:service:" + svc)
                if i >= 0:
                    a = desc.find("<controlURL>", i) + 12
                    ctl = desc[a:desc.find("</controlURL>", a)].strip()
                    base = loc[:loc.find("/", 8)]
                    self.upnp_ctl = (ctl if ctl.startswith("http") else base + ctl, svc)
                    break
            if not self.upnp_ctl:
                raise RuntimeError("router has no WAN connection service")
        url, svc = self.upnp_ctl
        st = "urn:schemas-upnp-org:service:" + svc
        body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
                ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                '<u:GetStatusInfo xmlns:u="%s"></u:GetStatusInfo></s:Body></s:Envelope>' % st)
        with requests.post(url, data=body, timeout=NET_TIMEOUT,
                           headers={"Content-Type": 'text/xml; charset="utf-8"',
                                    "SOAPAction": '"%s#GetStatusInfo"' % st}) as r:
            xml = r.text
        a = xml.find("<NewUptime>")
        if a < 0:
            raise RuntimeError("no uptime in reply")
        up = int(xml[a + 11:xml.find("</NewUptime>")].strip())
        self.router_up = (up, time.monotonic())
        self.upnp_tries = 0
        self.upnp_log = "router answered: up %s (%s)" % (_ago(up), url)


net_screen = NetScreen()
EXTRA["net"] = net_screen


# ------------------------------------------------------------- trivia
# A multiple-choice question; the answer lights up after TRIVIA_SECONDS. BOOT reveals it
# early, then moves on. Questions come from trivia_india.txt on the board (about 240 India
# questions - add your own lines). TRIVIA_SOURCE="world" uses Open Trivia DB instead,
# "mix" alternates the two.
TRIVIA_SECONDS = max(5, int(cfg("TRIVIA_SECONDS") or "30"))
TRIVIA_REVEAL = 8
TRIVIA_SOURCE = (cfg("TRIVIA_SOURCE") or "india").strip().lower()
TRIVIA_FILE = os.getenv("TRIVIA_FILE") or "/trivia_india.txt"
TRIVIA_CATEGORY = os.getenv("TRIVIA_CATEGORY") or ""     # Open Trivia DB id, for "world"/"mix"
TRIVIA_FALLBACK = (
    ("Which planet is known as the Red Planet?", "Mars", "Venus", "Jupiter", "Mercury"),
    ("What is the capital of Australia?", "Canberra", "Sydney", "Melbourne", "Perth"),
    ("Which gas do plants absorb from the air for photosynthesis?", "Carbon dioxide", "Oxygen",
     "Nitrogen", "Hydrogen"),
    ("Who wrote the Indian national anthem 'Jana Gana Mana'?", "Rabindranath Tagore",
     "Bankim Chandra Chatterjee", "Sarojini Naidu", "Muhammad Iqbal"),
    ("How many players are on the field for one team in a cricket match?", "11", "9", "10", "12"),
    ("What is the chemical symbol for gold?", "Au", "Ag", "Gd", "Go"),
    ("Which is the longest river in India?", "Ganga", "Godavari", "Yamuna", "Narmada"),
    ("In which year did India launch Chandrayaan-3?", "2023", "2019", "2021", "2008"),
    ("What does 'CPU' stand for?", "Central Processing Unit", "Computer Personal Unit",
     "Central Program Utility", "Core Processing Unit"),
    ("Which is the largest ocean on Earth?", "Pacific", "Atlantic", "Indian", "Arctic"),
    ("Who was the first Indian to go to space?", "Rakesh Sharma", "Kalpana Chawla",
     "Sunita Williams", "Ravish Malhotra"),
    ("What is the hardest natural substance?", "Diamond", "Quartz", "Graphite", "Topaz"),
    ("Which instrument is Ustad Zakir Hussain famous for?", "Tabla", "Sitar", "Sarod", "Santoor"),
    ("How many bits are in a byte?", "8", "4", "16", "10"),
    ("Which city is called the Pink City of India?", "Jaipur", "Udaipur", "Jodhpur", "Bhopal"),
)


def load_trivia(path):
    """CATEGORY|Question|Right|Wrong|Wrong|Wrong lines -> [(question, options, category)]."""
    out = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                p = [x.strip() for x in line.split("|")]
                if len(p) == 6 and all(p):
                    out.append((p[1], p[2:], p[0]))
    except OSError as e:
        print("trivia file:", repr(e))
    return out


class TriviaScreen(Screen):
    dwell = TRIVIA_SECONDS + TRIVIA_REVEAL + 1

    def __init__(self):
        global root
        Screen.__init__(self)
        root = self.grp
        self.sub, self.clock = _head("TRIVIA", 0xFFB020)
        self.bar_pal = displayio.Palette(1)
        self.bar_pal[0] = 0xFFB020
        self.bar = vectorio.Rectangle(pixel_shader=self.bar_pal, width=312, height=3, x=4, y=24)
        root.append(self.bar)
        self.q_med = [text(F_MED, "", 6, 31 + i * 18, WHITE) for i in range(4)]
        self.q_small = [text(F_SMALL, "", 6, 31 + i * 12, WHITE) for i in range(6)]
        self.cells = []
        for i in range(4):
            x, y = 4 + (i % 2) * 158, 108 + (i // 2) * 31
            box = RoundRect(x, y, 154, 28, 5, fill=0x1C2128)
            root.append(box)
            letter = text(F_TITLE, "ABCD"[i], x + 8, y + 4, 0xFFB020)
            med = text(F_MED, "", x + 26, y + 5, 0xE6EAEE)
            small = text(F_SMALL, "", x + 26, y + 8, 0xE6EAEE)
            small.line_spacing = 1.0
            self.cells.append((box, letter, med, small, x, y))
        self.queue = []
        self.bank = load_trivia(TRIVIA_FILE) if TRIVIA_SOURCE != "world" else []
        if not self.bank and TRIVIA_SOURCE != "world":
            self.bank = [(f[0], list(f[1:]), "INDIA") for f in TRIVIA_FALLBACK]
        self.deck = []
        self.turn = 0
        self.q = None
        self.t0 = 0.0
        self.revealed = False
        self.token = None
        self.last_fetch = -1e6
        self.fallback_i = random.randint(0, len(TRIVIA_FALLBACK) - 1)

    def tick(self, now):
        if TRIVIA_SOURCE == "india":
            return
        if len(self.queue) < 3 and now - self.last_fetch > 60 and net_state == "ok":
            self.last_fetch = now
            safe(self.fetch, "trivia")

    def fetch(self):
        if not self.token:
            with requests.get("https://opentdb.com/api_token.php?command=request",
                              timeout=NET_TIMEOUT) as r:
                self.token = r.json().get("token")
        url = "https://opentdb.com/api.php?amount=15&type=multiple&encode=url3986"
        if TRIVIA_CATEGORY:
            url += "&category=" + TRIVIA_CATEGORY
        if self.token:
            url += "&token=" + self.token
        with requests.get(url, timeout=NET_TIMEOUT) as r:
            d = r.json()
        if d.get("response_code") in (3, 4):        # token expired or used up: start a new one
            self.token = None
        for it in d.get("results", []):
            opts = [unquote(it["correct_answer"])] + [unquote(x) for x in it["incorrect_answers"]]
            self.queue.append((unquote(it["question"]), opts, unquote(it.get("category", "")),
                               it.get("difficulty", "")))

    def next(self, now):
        self.turn += 1
        use_bank = self.bank and (TRIVIA_SOURCE == "india" or not self.queue or
                                  (TRIVIA_SOURCE == "mix" and self.turn % 2))
        if use_bank:
            if not self.deck:                        # a fresh shuffled pass through the file
                self.deck = _shuffle(list(range(len(self.bank))))
            q, opts, cat = self.bank[self.deck.pop()]
            diff = ""
        elif self.queue:
            q, opts, cat, diff = self.queue.pop(0)
        else:                                        # offline: the built-in questions
            f = TRIVIA_FALLBACK[self.fallback_i % len(TRIVIA_FALLBACK)]
            self.fallback_i += 1
            q, opts, cat, diff = f[0], list(f[1:]), "India", ""
        right = opts[0]
        opts = _shuffle(list(opts))
        self.q = (q, opts, opts.index(right))
        self.sub.text = ("%s %s" % (cat.split(":")[-1].strip(), diff)).strip().upper()[:26]
        rows, fits = wrap_px(F_MED, q, 306, 4)
        if fits:
            for i, lbl in enumerate(self.q_med):
                lbl.text = rows[i] if i < len(rows) else ""
            for lbl in self.q_small:
                lbl.text = ""
        else:
            rows, _ = wrap_px(F_SMALL, q, 306, 6)
            for i, lbl in enumerate(self.q_small):
                lbl.text = rows[i] if i < len(rows) else ""
            for lbl in self.q_med:
                lbl.text = ""
        for i, (box, letter, med, small, x, y) in enumerate(self.cells):
            o = opts[i]
            box.fill = 0x1C2128
            letter.color = 0xFFB020
            if px_width(F_MED, o) <= 124:
                med.text, small.text = o, ""
            else:                                    # long answer: two lines of small text
                rows, _ = wrap_px(F_SMALL, o, 124, 2)
                med.text = ""
                small.text = "\n".join(rows)
                small.anchored_position = (x + 26, y + (2 if len(rows) > 1 else 8))
            med.color = small.color = 0xE6EAEE
        self.t0 = now
        self.revealed = False
        self.bar_pal[0] = 0xFFB020

    def reveal(self, now):
        self.revealed = True
        self.t0 = now
        self.bar.width = 312
        self.bar_pal[0] = 0x1E9E50
        for i, (box, letter, med, small, x, y) in enumerate(self.cells):
            if i == self.q[2]:
                box.fill = 0x1E9E50
                letter.color = med.color = small.color = WHITE
            else:
                letter.color = med.color = small.color = 0x5A6068

    def enter(self, now):
        if self.q is None or self.revealed:
            self.next(now)
        else:
            self.t0 = now                            # a fresh 30 s for an unanswered question

    def frame(self, now):
        if self.q is None:
            self.next(now)
        el = now - self.t0
        if not self.revealed:
            self.bar.width = max(1, int(312 * (1 - el / TRIVIA_SECONDS)))
            if el >= TRIVIA_SECONDS:
                self.reveal(now)
        elif el >= TRIVIA_REVEAL:
            self.next(now)

    def boot(self, now):
        if self.revealed:
            self.next(now)
        else:
            self.reveal(now)


trivia_screen = TriviaScreen()
EXTRA["trivia"] = trivia_screen


# ------------------------------------------------------------- virtual pet
# Sheru, an Indian indie dog. His tail, ears and face follow today's portfolio move,
# he gets hungry if nobody presses BOOT (feed) for a while, and he sleeps curled up at night.
# Kept in NVM: birthday, last meal and number of meals.
PET_NAME = (cfg("PET_NAME") or "Sheru")[:10]
PET_NVM = 64          # nvm[64] "P", [65:69] born, [69:73] last fed, [73:75] meals
PCOL = (0, 0xD9A066, 0xA8713E, 0xF4DDB3, 0x4A2E1A, 0x1B1B1B, 0xFFFFFF, 0xF2A0A8, 0xFF6F7F,
        0xD23A3A, 0xFFD24A, 0x6EC6FF, 0xB8C0C8, 0x6A737C, 0xC98A3A)
D_FUR, D_SHADE, D_CREAM, D_LINE, D_EYE, D_SHINE, D_PINK, D_TONGUE, D_COLLAR, D_TAG, \
    D_TEAR, D_BOWL, D_BOWL2, D_FOOD = range(1, 15)


def _tri(bmp, p1, p2, p3, v):
    """Filled triangle (scanline)."""
    pts = sorted((p1, p2, p3), key=lambda p: p[1])
    (x1, y1), (x2, y2), (x3, y3) = pts
    for y in range(max(0, y1), min(bmp.height, y3 + 1)):
        xs = []
        for (ax, ay), (bx, by) in (((x1, y1), (x3, y3)), ((x1, y1), (x2, y2)), ((x2, y2), (x3, y3))):
            if ay != by and min(ay, by) <= y <= max(ay, by):
                xs.append(ax + (y - ay) * (bx - ax) / (by - ay))
        if xs:
            l, r = int(min(xs) + 0.5), int(max(xs) + 0.5)
            bitmaptools.fill_region(bmp, max(0, l), y, min(bmp.width, r + 1), y + 1, v)


def _rope(bmp, pts, r, v):
    """A thick curve through points (the tail)."""
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        n = max(abs(bx - ax), abs(by - ay), 1)
        for i in range(n + 1):
            _circle(bmp, int(ax + (bx - ax) * i / n + 0.5), int(ay + (by - ay) * i / n + 0.5), r, v)


def _ellipse(bmp, cx, cy, rx, ry, v):
    # clipped to the bitmap: CircuitPython raises on a fill outside it (the desktop simulator doesn't)
    for dy in range(-ry, ry + 1):
        y = cy + dy
        if not 0 <= y < bmp.height:
            continue
        half = int(rx * (1 - (dy / ry) ** 2) ** 0.5 + 0.5) if ry else rx
        x1, x2 = max(0, cx - half), min(bmp.width, cx + half + 1)
        if x1 < x2:
            bitmaptools.fill_region(bmp, x1, y, x2, y + 1, v)


class PetScreen(Screen):
    W, H = 60, 50

    def __init__(self):
        global root
        Screen.__init__(self)
        root = self.grp
        self.sub, self.clock = _head(PET_NAME.upper(), 0xD9A066, "YOUR PORTFOLIO DOG")
        sh = displayio.Palette(1)
        sh[0] = 0x1C2026
        root.append(vectorio.Polygon(pixel_shader=sh, x=66, y=136, points=[
            (int(32 * math.cos(a * math.pi / 8)), int(5 * math.sin(a * math.pi / 8))) for a in range(16)]))
        self.bmp = displayio.Bitmap(self.W, self.H, len(PCOL))
        pp = displayio.Palette(len(PCOL))
        for i, c in enumerate(PCOL):
            pp[i] = c
        pp.make_transparent(0)
        self.pal = pp
        self.sprite = displayio.Group(scale=2, x=8, y=36)
        self.sprite.append(displayio.TileGrid(self.bmp, pixel_shader=pp))
        root.append(self.sprite)
        hp = displayio.Palette(1)
        hp[0] = 0xFF4D6D
        self.heart = vectorio.Polygon(pixel_shader=hp, points=[(0, 2), (2, 0), (4, 2), (6, 0), (8, 2),
                                                               (4, 7)], x=0, y=0)
        self.heart.hidden = True
        root.append(self.heart)
        tp = displayio.Palette(1)
        tp[0] = 0x6EC6FF
        self.tear = vectorio.Circle(pixel_shader=tp, radius=3, x=0, y=0)
        self.tear.hidden = True
        root.append(self.tear)
        self.zzz = text(F_TITLE, "", 100, 46, 0xB0C4FF)
        root.append(RoundRect(134, 30, 182, 64, 8, fill=0x1C2128))
        self.say = [text(F_MED, "", 142, 36 + i * 18, WHITE) for i in range(3)]
        text(F_SMALL, "FULL", 134, 102, 0x8A9099)
        text(F_SMALL, "MOOD", 134, 120, 0x8A9099)
        self.bars = []
        for y in (103, 121):
            bp = displayio.Palette(2)
            bp[0], bp[1] = 0x2A3038, 0x5BD16B
            b = displayio.Bitmap(140, 8, 2)
            root.append(displayio.TileGrid(b, pixel_shader=bp, x=170, y=y))
            self.bars.append((b, bp))
        self.info = text(F_SMALL, "", 134, 140, 0x8A9099)
        self.hint = text(F_SMALL, "BOOT = feed", 134, 154, 0x5A6068)
        self.born, self.fed, self.meals = self.load()
        self.state = None
        self.face = None
        self.poses = {}
        self.eat_until = 0.0
        self.thanks_until = 0.0
        self.next_blink = 0.0
        self.blink_until = 0.0
        self.anim_t = 0.0
        self.said = None

    # -- persistence
    def load(self):
        try:
            nv = microcontroller.nvm
            if nv[PET_NVM] == ord("P"):
                born, fed, meals = struct.unpack("<IIH", bytes(nv[PET_NVM + 1:PET_NVM + 11]))
                return born, fed, meals
        except Exception:  # noqa: BLE001
            pass
        return 0, 0, 0

    def save(self):
        try:
            microcontroller.nvm[PET_NVM:PET_NVM + 11] = b"P" + struct.pack(
                "<IIH", int(self.born), int(self.fed), self.meals)
        except Exception as e:  # noqa: BLE001
            print("pet save failed:", repr(e))

    def feed(self, now):
        wall = int(time.time())
        if time.localtime().tm_year < 2024:   # clock not set yet: can't keep time
            return
        if not self.born:
            self.born = wall
        self.fed = wall
        self.meals = min(65535, self.meals + 1)
        self.save()
        self.eat_until = now + 3
        self.thanks_until = now + 12

    # -- what it feels
    def hours_hungry(self):
        if not self.fed or time.localtime().tm_year < 2024:
            return 0 if not self.fed and not self.born else 99
        return (time.time() - self.fed) / 3600

    def mood(self, now):
        t = time.localtime()
        if not self.born:
            return "happy" if not (is_night(t) or t.tm_hour < 6) else "sleep"
        if is_night(t) or t.tm_hour < 6:
            return "sleep"
        if now < self.eat_until:
            return "eat"
        if self.born and self.hours_hungry() > 8:
            return "hungry"
        pct = port_day_pct
        if pct is None:
            return "meh"
        if pct >= 1.5:
            return "ecstatic"
        if pct >= 0:
            return "happy"
        return "sad" if pct > -1.5 else "worried"

    def words(self, mood, now):
        pct = port_day_pct
        if now < self.thanks_until and mood != "eat":
            return "Woof! Thank you, that roti was yummy."
        if not self.born:
            return "Woof! I'm %s. Press BOOT to give me my first roti!" % PET_NAME
        closed = not market_open()
        if mood == "sleep":
            return "Zzz... (dreaming of biscuits)"
        if mood == "eat":
            return "Nom nom nom!"
        if mood == "hungry":
            return ("I haven't eaten all day... *whimper*" if self.hours_hungry() > 24
                    else "My bowl is empty! Press BOOT to feed me.")
        if mood == "meh" or pct is None:
            return "Log in to Kite so I know whether to wag!"
        if mood == "ecstatic":
            return "%+.1f%% today! Zoomies time! Woof woof!" % pct
        if mood == "happy":
            return ("Market's shut. We ended %+.1f%%. Good day!" % pct) if closed \
                else "We're up %+.1f%% today. *wags*" % pct
        if mood == "sad":
            return ("Market's shut. We ended %+.1f%%." % pct) if closed \
                else "Down %+.1f%%... can I have a cuddle?" % pct
        return "Ouch, %+.1f%% today. I'll guard the portfolio!" % pct

    # -- drawing: a sitting desi dog, facing right, or curled up asleep
    def pose(self, face):
        """The finished picture for a pose, drawn off-screen once and then reused.
        (Drawing straight onto the visible bitmap let the screen refresh catch it half-done.)"""
        bmp = self.poses.get(face)
        if bmp is None:
            if len(self.poses) > 16:
                self.poses = {}
            bmp = displayio.Bitmap(self.W, self.H, len(PCOL))
            self.draw(bmp, *face)
            self.poses[face] = bmp
        return bmp

    def draw(self, b, mood, blink, mouth_open, wag):

        def blob(cx, cy, rx, ry, v):           # outlined oval
            _ellipse(b, cx, cy, rx + 1, ry + 1, D_LINE)
            _ellipse(b, cx, cy, rx, ry, v)

        if mood == "sleep":
            _rope(b, [(12, 39), (8, 43), (12, 46), (20, 46)], 3, D_LINE)
            _rope(b, [(12, 39), (8, 43), (12, 46), (20, 46)], 2, D_FUR)
            blob(28, 40, 19, 7, D_FUR)
            _ellipse(b, 28, 43, 15, 3, D_SHADE)
            blob(46, 38, 9, 7, D_FUR)
            _tri(b, (40, 33), (35, 30), (44, 31), D_LINE)
            _tri(b, (40, 33), (37, 31), (43, 32), D_SHADE)
            blob(53, 41, 4, 3, D_CREAM)
            b[56, 39] = b[57, 39] = D_EYE
            bitmaptools.draw_line(b, 44, 37, 48, 37, D_LINE)          # closed eye
            blob(50, 46, 5, 2, D_CREAM)                               # paws under the chin
            return
        down = mood in ("sad", "worried")
        # tail: curled over the back and wagging, or tucked low when sad
        if down:
            tail = [(16, 37), (11, 41), (9, 44), (13, 46), (18, 46)]
        elif wag:
            tail = [(16, 31), (11, 28), (8, 23), (9, 18), (13, 15), (16, 17)]
        else:
            tail = [(16, 31), (10, 30), (6, 26), (5, 21), (7, 17), (11, 16)]
        _rope(b, tail, 3, D_LINE)
        _rope(b, tail, 2, D_FUR)
        _circle(b, tail[-1][0], tail[-1][1], 2, D_CREAM)
        # haunch, body, legs, chest
        blob(21, 38, 10, 9, D_SHADE)
        blob(28, 33, 9, 12, D_FUR)
        _ellipse(b, 21, 38, 8, 7, D_FUR)
        for x in (29, 35):                                  # front legs and paws
            bitmaptools.fill_region(b, x - 1, 33, x + 6, 46, D_LINE)
            bitmaptools.fill_region(b, x, 33, x + 5, 45, D_FUR)
            blob(x + 3, 46, 3, 2, D_CREAM)
        blob(22, 46, 5, 2, D_CREAM)
        _ellipse(b, 34, 31, 5, 8, D_CREAM)
        # ears: pointy and up, or folded back
        if down:
            ears = (((29, 12), (21, 7), (32, 7)), ((37, 9), (31, 3), (42, 6)))
        else:
            ears = (((28, 12), (30, 0), (35, 8)), ((38, 8), (43, 0), (46, 9)))
        for p1, p2, p3 in ears:
            _tri(b, (p1[0] - 1, p1[1] + 1), (p2[0], p2[1] - 1), (p3[0] + 1, p3[1]), D_LINE)
            _tri(b, p1, p2, p3, D_FUR)
            if not down:
                cx, cy = (p1[0] + p2[0] + p3[0]) // 3, (p1[1] + p2[1] + p3[1]) // 3
                _tri(b, (cx - 1, cy + 2), (p2[0], p2[1] + 3), (cx + 2, cy + 1), D_PINK)
        # head, muzzle, nose
        blob(38, 17, 10, 8, D_FUR)
        blob(47, 21, 7, 4, D_CREAM)                          # a proper long desi snout
        bitmaptools.fill_region(b, 52, 18, 56, 21, D_EYE)
        b[53, 18] = D_SHINE
        # eyes
        for ex in (35, 41):
            ey = 15
            if blink:
                bitmaptools.draw_line(b, ex - 1, ey, ex + 1, ey, D_EYE)
            elif mood in ("ecstatic", "happy", "eat"):
                b[ex - 1, ey] = b[ex, ey - 1] = b[ex + 1, ey] = D_EYE      # happy ^ ^
            else:
                bitmaptools.fill_region(b, ex - 1, ey - 1, ex + 1, ey + 2, D_EYE)
                b[ex - 1, ey - 1] = D_SHINE
                if mood in ("worried", "sad", "hungry"):                 # puppy-dog brows
                    d = 1 if ex < 38 else -1
                    bitmaptools.draw_line(b, ex - 2, ey - 3 - d, ex + 1, ey - 3 + d, D_LINE)
        # mouth and tongue
        if mood == "eat" and mouth_open:
            _ellipse(b, 49, 25, 3, 2, D_LINE)
            _ellipse(b, 49, 25, 2, 1, D_TONGUE)
        else:
            if mood in ("ecstatic", "happy"):
                bitmaptools.fill_region(b, 47, 24, 51, 30, D_LINE)
                bitmaptools.fill_region(b, 48, 24, 50, 29, D_TONGUE)
            if down:
                bitmaptools.draw_line(b, 45, 25, 50, 24, D_LINE)
            else:
                bitmaptools.draw_line(b, 43, 24, 46, 25, D_LINE)
                bitmaptools.draw_line(b, 46, 25, 52, 23, D_LINE)
        if mood in ("ecstatic", "happy", "eat"):
            _ellipse(b, 33, 20, 2, 1, D_PINK)                            # blush
        # red collar with a little tag: someone's adopted indie
        for o in range(3):
            bitmaptools.draw_line(b, 30, 24 + o, 40, 26 + o, D_COLLAR)
        _circle(b, 36, 29, 1, D_TAG)
        # the steel bowl
        if mood in ("eat", "hungry"):
            _ellipse(b, 53, 46, 6, 3, D_BOWL2)
            bitmaptools.fill_region(b, 47, 43, 60, 45, D_BOWL)
            if mood == "eat":
                _ellipse(b, 53, 43, 4, 1, D_FOOD)

    def bar(self, i, frac, colour):
        b, p = self.bars[i]
        p[1] = colour
        b.fill(0)
        w = int(max(0.0, min(1.0, frac)) * b.width)
        if w:
            bitmaptools.fill_region(b, 0, 0, w, b.height, 1)

    def enter(self, now):
        self.face = None
        self.said = None

    def boot(self, now):
        if self.mood(now) != "sleep":
            self.feed(now)

    def frame(self, now):
        mood = self.mood(now)
        if now > self.next_blink:
            self.blink_until = now + 0.15
            self.next_blink = now + 2.5 + random.random() * 3
        blink = now < self.blink_until and mood != "sleep"
        mouth = mood == "eat" and int(now * 4) % 2 == 0
        speed = {"ecstatic": 0.12, "happy": 0.25, "eat": 0.2, "meh": 0.6, "hungry": 0.9}.get(mood)
        wag = bool(speed) and int(now / speed) % 2 == 0
        face = (mood, blink, mouth, wag)
        if face != self.face:
            self.face = face
            try:
                bitmaptools.blit(self.bmp, self.pose(face), 0, 0)     # one quick copy, no half-drawn frames
            except Exception as e:  # noqa: BLE001 - keep the last good picture, say why on /debug
                log_err("pet %s pose failed: %r" % (mood, e))
        # body language
        phase = now % 3.0
        y = 36
        if mood == "ecstatic" and phase < 0.35:
            y = 26                                           # a happy hop
        elif mood not in ("sleep",):
            y = 36 + (1 if int(now * 2) % 2 else 0)          # breathing
        x = 8 + (1 if mood == "hungry" and int(now * 8) % 16 == 0 else 0)
        if (self.sprite.x, self.sprite.y) != (x, y):
            self.sprite.x, self.sprite.y = x, y
        # hearts, tears, z's
        self.heart.hidden = mood != "ecstatic" and now >= self.thanks_until
        if not self.heart.hidden:
            k = (now % 1.6) / 1.6
            self.heart.x, self.heart.y = 112, int(46 - 30 * k)
        self.tear.hidden = mood not in ("sad", "worried")
        if not self.tear.hidden:
            k = (now % 1.8) / 1.8
            self.tear.x, self.tear.y = 73, int(y + 34 + 14 * k)
        if mood == "sleep":
            self.zzz.text = ("z", "z Z", "z Z z")[int(now) % 3]
        elif self.zzz.text:
            self.zzz.text = ""
        if int(now) != self.said:                            # words and bars once a second
            self.said = int(now)
            rows, _ = wrap_px(F_MED, self.words(mood, now), 168, 3)
            for i, lbl in enumerate(self.say):
                lbl.text = rows[i] if i < len(rows) else ""
            full = 1 - min(12, self.hours_hungry()) / 12 if self.born else 0
            self.bar(0, full, 0x5BD16B if full > 0.4 else 0xFFB020 if full > 0.15 else 0xE0443A)
            pct = port_day_pct
            m = 0.5 if pct is None else 0.5 + max(-3, min(3, pct)) / 6
            self.bar(1, m, 0x5BD16B if m >= 0.5 else 0xE0443A)
            if self.born and time.localtime().tm_year >= 2024:
                age = int((time.time() - self.born) // 86400)
                self.info.text = "Age %d day%s, %d meal%s" % (
                    age, "" if age == 1 else "s", self.meals, "" if self.meals == 1 else "s")
                self.hint.text = "Fed %s ago - BOOT feeds" % _ago(time.time() - self.fed)
            else:
                self.info.text = "Just adopted!"
                self.hint.text = "BOOT = first roti"


pet_screen = PetScreen()
EXTRA["pet"] = pet_screen


# ------------------------------------------------------------- to-do board
# Tasks you manage at http://<board>:8080/todo, shown on the board. Kept in NVM.
# Each task: [id, text, done, high priority, due "YYYY-MM-DD" or ""].
TODO_NVM = 3200
TODO_ROWS = 5
TODO_PAGE_SECONDS = 6


def _todo_load():
    try:
        nv = microcontroller.nvm
        n = nv[TODO_NVM] | (nv[TODO_NVM + 1] << 8)
        if 2 <= n <= len(nv) - TODO_NVM - 2:
            return [list(t) for t in json.loads(bytes(nv[TODO_NVM + 2:TODO_NVM + 2 + n]).decode())]
    except Exception as e:  # noqa: BLE001
        print("to-do list unreadable:", repr(e))
    return []


def todo_save(items):
    b = json.dumps(items).encode()
    room = len(microcontroller.nvm) - 1200 - TODO_NVM - 2      # the last 1200 bytes hold the Ask AI answer
    if len(b) > room:
        raise ValueError("the list is full (%d of %d bytes) - clear some done tasks" % (len(b), room))
    microcontroller.nvm[TODO_NVM:TODO_NVM + 2 + len(b)] = bytes([len(b) & 255, len(b) >> 8]) + b


def _days_until(due):
    """Days from today to 'YYYY-MM-DD' (negative = overdue); None if unknown."""
    try:
        y, m, d = (int(x) for x in due.split("-"))
        t = time.localtime()
        if t.tm_year < 2024:
            return None
        a = time.mktime((y, m, d, 12, 0, 0, 0, 0, -1))
        b = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 12, 0, 0, 0, 0, -1))
        return int(round((a - b) / 86400))
    except Exception:  # noqa: BLE001
        return None


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
WDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def due_label(due):
    """('Today', colour) style label for a due date."""
    if not due:
        return "", 0
    n = _days_until(due)
    if n is None:
        return due[5:], 0x8A9099
    if n < 0:
        return ("%dd late" % -n) if n < -1 else "Yesterday", 0xFF5A5A
    if n == 0:
        return "Today", 0xFFB020
    if n == 1:
        return "Tomorrow", 0xFFD27A
    if n < 7:
        y, m, d = (int(x) for x in due.split("-"))
        return WDAYS[time.localtime(time.mktime((y, m, d, 12, 0, 0, 0, 0, -1))).tm_wday], 0xB8C0C8
    return "%s %s" % (due[8:10].lstrip("0"), MONTHS[int(due[5:7]) - 1]), 0x8A9099


def _screen_text(s):
    """The screen fonts are ASCII (plus the rupee sign): replace anything else."""
    return "".join(c if 32 <= ord(c) < 127 or c == "₹" else "?" for c in s)


class TodoScreen(Screen):
    def __init__(self):
        global root
        Screen.__init__(self)
        root = self.grp
        self.sub, self.clock = _head("TO-DO", 0x8B7CF6)
        self.rows = []
        for i in range(TODO_ROWS):
            y = 29 + i * 27
            box = RoundRect(6, y + 3, 14, 14, 3, fill=None, outline=0x8B7CF6, stroke=2)
            root.append(box)
            tp = displayio.Palette(1)
            tp[0] = 0x8B7CF6
            tick = vectorio.Polygon(pixel_shader=tp, x=6, y=y + 3,
                                    points=[(2, 7), (5, 10), (12, 3), (12, 6), (5, 13), (2, 10)])
            root.append(tick)
            pp = displayio.Palette(1)
            pp[0] = 0xFF5A5A
            pri = vectorio.Rectangle(pixel_shader=pp, x=0, y=y + 2, width=3, height=16)
            root.append(pri)
            sp = displayio.Palette(1)
            sp[0] = 0x6A727B
            strike = vectorio.Rectangle(pixel_shader=sp, x=26, y=y + 10, width=1, height=1)
            root.append(strike)
            lbl = text(F_MED, "", 26, y + 1, WHITE)
            due = text(F_SMALL, "", 314, y + 5, 0xB8C0C8, right=True)
            sep = vectorio.Rectangle(pixel_shader=pal, width=288, height=1, x=26, y=y - 1,
                                     color_index=10)
            sep.hidden = True
            if i:
                root.append(sep)
            self.rows.append((box, tick, pri, strike, lbl, due, sep))
        self.empty = [text(F_MED, "", 160, 80, 0xB8C0C8, center=True),
                      text(F_SMALL, "", 160, 104, 0x8A9099, center=True)]
        self.foot = text(F_SMALL, "", 314, 158, 0x6A727B, right=True)
        self.items = _todo_load()
        self.page = 0
        self.last_page = 0.0
        self.dirty = True

    @property
    def dwell(self):
        return max(SCREEN_SECONDS, self.pages() * TODO_PAGE_SECONDS)

    def shown(self):
        """Open tasks first (in your order), then done ones."""
        return [t for t in self.items if not t[2]] + [t for t in self.items if t[2]]

    def pages(self):
        return max(1, (len(self.items) + TODO_ROWS - 1) // TODO_ROWS)

    def changed(self):
        todo_save(self.items)
        self.dirty = True

    def enter(self, now):
        self.page = 0
        self.last_page = now
        self.draw()

    def boot(self, now):
        self.page = (self.page + 1) % self.pages()
        self.last_page = now
        self.draw()

    def frame(self, now):
        if self.dirty:
            self.draw()
        if self.pages() > 1 and now - self.last_page > TODO_PAGE_SECONDS:
            self.last_page = now
            self.page = (self.page + 1) % self.pages()
            self.draw()

    def second(self, hhmm):
        Screen.second(self, hhmm)
        if hhmm.endswith(":00") and self.grp is display.root_group:
            self.dirty = True            # due labels change at midnight

    def draw(self):
        self.dirty = False
        items = self.shown()
        open_n = sum(1 for t in items if not t[2])
        self.sub.text = ("%d OPEN" % open_n if open_n else "ALL DONE") if items else ""
        self.page = min(self.page, self.pages() - 1)
        chunk = items[self.page * TODO_ROWS:(self.page + 1) * TODO_ROWS]
        for i, (box, tick, pri, strike, lbl, due, sep) in enumerate(self.rows):
            if i >= len(chunk):
                box.hidden = tick.hidden = pri.hidden = strike.hidden = sep.hidden = True
                lbl.text = due.text = ""
                continue
            _id, txt, done, high, dd = chunk[i][:5]
            box.hidden = sep.hidden = False
            tick.hidden = not done
            pri.hidden = not high or done
            d_txt, d_col = due_label(dd) if not done else ("", 0)
            due.text, due.color = d_txt, d_col
            room = 284 - (px_width(F_SMALL, d_txt) + 8 if d_txt else 0)
            t = _screen_text(txt)
            if px_width(F_MED, t) > room:
                while t and px_width(F_MED, t + "...") > room:
                    t = t[:-1]
                t = t.rstrip() + "..."
            lbl.text = t
            lbl.color = 0x6A727B if done else WHITE
            strike.hidden = not done
            if done:
                strike.width = max(1, px_width(F_MED, t))
        if not items:
            self.empty[0].text = "Nothing to do!"
            self.empty[1].text = "Add tasks at http://%s:%d/todo" % (MY_IP, LOGIN_PORT)
        else:
            self.empty[0].text = self.empty[1].text = ""
        self.foot.text = ("page %d/%d" % (self.page + 1, self.pages())) if self.pages() > 1 else ""


todo_screen = TodoScreen()
EXTRA["todo"] = todo_screen


# ------------------------------------------------------------- my stocks
# Holdings and open positions you pick at http://<board>:8080/stocks: price (LTP),
# today's move and your P&L, five to a page (more go on page 2, 3...).  The picks
# are saved as STOCK_PICKS, which can also be set in settings.toml: holdings by
# symbol, positions as SYMBOL:PRODUCT ("RELIANCE,M&M,NIFTY25NOV24000CE:NRML").
STOCK_ROWS = 5
STOCK_PAGE_SECONDS = 6
STOCK_MAX = 30


def stock_picks(text_=None):
    out = []
    for s in ((cfg("STOCK_PICKS") if text_ is None else text_) or "").upper().split(","):
        s = s.strip()
        if s and s not in out:
            out.append(s)
    return out[:STOCK_MAX]


def group_in(n):
    """1234567 -> '12,34,567' (Indian digit grouping, whole number)."""
    s = "%d" % n
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def price(v, signed=False):
    """2912.4 -> '2,912.40'.  Whole rupees from 1 lakh up (and for moves of 1,000+)."""
    sign = ("+" if v >= 0 else "-") if signed else ("-" if v < 0 else "")
    a = abs(v)
    if a >= (1000 if signed else 1e5):
        return sign + group_in(int(a + 0.5))
    paise = int(a * 100 + 0.5)
    return "%s%s.%02d" % (sign, group_in(paise // 100), paise % 100)


def _fit(font, t, room):
    """Cut `t` (adding '..') until it fits `room` pixels."""
    if px_width(font, t) <= room:
        return t
    while t and px_width(font, t + "..") > room:
        t = t[:-1]
    return t + ".."


FO_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def fo_short(sym):
    """Kite F&O symbols without the expiry, for when the full one doesn't fit:
    NIFTY25NOV24000CE / NIFTY2511824000CE -> 'NIFTY 24000 CE', BANKNIFTY25NOVFUT -> 'BANKNIFTY FUT'.
    Anything else comes back unchanged."""
    for kind in ("CE", "PE", "FUT"):
        if sym.endswith(kind):
            break
    else:
        return sym
    body = sym[:-len(kind)]
    i = 0
    while i < len(body) and not body[i].isdigit():
        i += 1
    name, rest = body[:i], body[i + 2:]          # skip the 2-digit year
    if not name or len(body) < i + 2 or not body[i:i + 2].isdigit():
        return sym
    if rest[:3] in FO_MONTHS:                    # monthly: 25NOV...
        rest = rest[3:]
    elif len(rest) >= 3 and rest[0] in "123456789OND" and rest[1:3].isdigit():
        rest = rest[3:]                          # weekly: 25 1 18 ... (year, month, day)
    else:
        return sym
    if kind == "FUT":
        return name + " FUT" if not rest else sym
    if not rest or not rest.replace(".", "").isdigit():
        return sym
    return "%s %s %s" % (name, rest, kind)


def _set(lbl, t, colour=None):
    if lbl.text != t:
        lbl.text = t
    if colour is not None and lbl.color != colour:
        lbl.color = colour


class StocksScreen(Screen):
    MID = 206                       # right edge of the price column

    def __init__(self):
        global root
        Screen.__init__(self)
        root = self.grp
        self.sub, self.clock = _head("MY STOCKS", 0x387ED1)
        self.pg = text(F_SMALL, "", 262, 8, 0x8A9099, right=True)
        self.rows = []
        for i in range(STOCK_ROWS):
            y = 29 + i * 27
            shapes = []
            for colour, pts, dy in ((GREEN, [(0, 8), (5, 0), (10, 8)], 3),     # up
                                    (RED, [(0, 0), (10, 0), (5, 8)], 3)):     # down
                p = displayio.Palette(1)
                p[0] = colour
                shapes.append(vectorio.Polygon(pixel_shader=p, x=3, y=y + dy, points=pts))
            fp = displayio.Palette(1)
            fp[0] = 0x6A727B
            shapes.append(vectorio.Rectangle(pixel_shader=fp, x=3, y=y + 6, width=10, height=3))
            for s in shapes:
                s.hidden = True
                root.append(s)
            sep = vectorio.Rectangle(pixel_shader=pal, width=296, height=1, x=18, y=y - 2,
                                     color_index=10)
            sep.hidden = True
            if i:
                root.append(sep)
            self.rows.append(shapes + [
                text(F_MED, "", 18, y - 5, WHITE),                      # symbol
                text(F_MED, "", self.MID, y - 5, WHITE, right=True),    # price
                text(F_MED, "", 314, y - 5, WHITE, right=True),         # P&L
                text(F_SMALL, "", 18, y + 13, 0x8A9099),                # qty @ avg
                text(F_SMALL, "", self.MID, y + 13, WHITE, right=True),  # today
                text(F_SMALL, "", 314, y + 13, WHITE, right=True),      # P&L %
                text(F_SMALL, "", 18, y + 13, 0xFFB020),                # MIS / NRML / CNC
                sep])
        self.empty = [text(F_MED, "", 160, 80, 0xB8C0C8, center=True),
                      text(F_SMALL, "", 160, 104, 0x8A9099, center=True)]
        # every holding and open position, or None when logged out:
        # (key, symbol, product, qty, avg, ltp, close, P&L, P&L %, today's P&L); product is "" for holdings
        self.data = None
        self.picks = stock_picks()
        self.shown = []
        self.page = 0
        self.last_page = 0.0
        self.dirty = True

    def update(self, rows):
        """Every holding and open position from Kite, or None when logged out."""
        if rows != self.data:
            self.data = rows
            self.rebuild()

    def set_picks(self, picks):
        CFG["STOCK_PICKS"] = ",".join(picks)
        self.picks = stock_picks()
        self.rebuild()

    def rebuild(self):
        by = {}
        for r in self.data or ():
            if r[0] not in by:
                by[r[0]] = r
        self.shown = [by[s] for s in self.picks if s in by]
        self.dirty = True

    @property
    def dwell(self):
        return max(SCREEN_SECONDS, self.pages() * STOCK_PAGE_SECONDS)

    def pages(self):
        return max(1, (len(self.shown) + STOCK_ROWS - 1) // STOCK_ROWS)

    def skip(self):
        return not self.shown

    def enter(self, now):
        self.page = 0
        self.last_page = now
        self.draw()

    def boot(self, now):
        self.page = (self.page + 1) % self.pages()
        self.last_page = now
        self.draw()

    def frame(self, now):
        if self.dirty:
            self.draw()
        if self.pages() > 1 and now - self.last_page > STOCK_PAGE_SECONDS:
            self.last_page = now
            self.page = (self.page + 1) % self.pages()
            self.draw()

    def draw(self):
        self.dirty = False
        rows = self.shown
        pages = self.pages()
        self.page = min(self.page, pages - 1)
        chunk = rows[self.page * STOCK_ROWS:(self.page + 1) * STOCK_ROWS]
        if rows:
            day = sum(r[9] for r in rows)
            _set(self.sub, "TODAY " + inr(day, signed=True).replace("₹", ""), GREEN if day >= 0 else RED)
        else:
            _set(self.sub, "")
        _set(self.pg, ("%d/%d" % (self.page + 1, pages)) if pages > 1 else "")
        for i, (up, dn, flat, sym_l, ltp_l, pnl_l, held_l, chg_l, pct_l, tag_l, sep) in enumerate(self.rows):
            if i >= len(chunk):
                up.hidden = dn.hidden = flat.hidden = sep.hidden = True
                for lbl in (sym_l, ltp_l, pnl_l, held_l, chg_l, pct_l, tag_l):
                    _set(lbl, "")
                continue
            _key, sym, prod, qty, avg, ltp, close, pnl, pnl_pct, _day = chunk[i]
            chg = ltp - close if close else 0.0
            c_col = GREEN if chg > 0 else (RED if chg < 0 else 0x8A9099)
            p_col = GREEN if pnl >= 0 else RED
            up.hidden = not chg > 0
            dn.hidden = not chg < 0
            flat.hidden = chg != 0
            sep.hidden = False
            _set(ltp_l, price(ltp))
            _set(chg_l, "%s %+.2f%%" % (price(chg, True), chg / close * 100 if close else 0.0), c_col)
            _set(pnl_l, inr(pnl, signed=True), p_col)
            _set(pct_l, "%+.1f%%" % pnl_pct, p_col)
            room = self.MID - px_width(F_MED, ltp_l.text) - 26
            name = _screen_text(sym)
            if px_width(F_MED, name) > room:
                name = fo_short(name)            # options/futures: drop the expiry before cutting
            _set(sym_l, _fit(F_MED, name, room))
            _set(tag_l, prod)                    # positions: the product, in amber
            hx = 18 + (px_width(F_SMALL, prod) + 5 if prod else 0)
            if held_l.anchored_position[0] != hx:
                held_l.anchored_position = (hx, held_l.anchored_position[1])
            _set(held_l, _fit(F_SMALL, "%d @ %s" % (qty, price(avg)),
                              self.MID - px_width(F_SMALL, chg_l.text) - 6 - hx))
        if rows:
            a = b = ""
        elif not self.picks:
            a, b = "No stocks picked yet", "Pick them at http://%s:%d/stocks" % (MY_IP, LOGIN_PORT)
        elif self.data is None:
            a, b = "Log in to Kite to see your stocks", "http://%s:%d" % (MY_IP, LOGIN_PORT)
        else:
            a, b = "None of your picks are held now", "Change them at http://%s:%d/stocks" % (MY_IP, LOGIN_PORT)
        _set(self.empty[0], a)
        _set(self.empty[1], b)


stocks_screen = StocksScreen()
EXTRA["stocks"] = stocks_screen


# ------------------------------------------------------------- ask AI (Gemini)
# Type a question at http://<board>:8080/ask; the answer stays on this screen until you
# ask something else (and survives restarts).  Needs GEMINI_API_KEY in settings.toml.
GEMINI_KEY = os.getenv("GEMINI_API_KEY") or ""
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
ASK_NVM = len(microcontroller.nvm) - 1200      # the last answer lives after the to-do list
ASK_CHARS = 420                                # what the screen holds in its smallest type
ASK_RULES = ("You are answering on a tiny 320x170 pixel desk display. Reply in plain text only, "
             "at most %d characters, shorter when you can. No markdown, no bullet symbols, no "
             "emojis, no line breaks, ASCII characters only. Give the answer itself, no preamble." % ASK_CHARS)


def gemini_model():
    return cfg("GEMINI_MODEL") or "gemini-flash-latest"


def ask_gemini(prompt):
    """One question to Gemini -> its answer as plain text. Raises with Google's message on errors."""
    body = json.dumps({"systemInstruction": {"parts": [{"text": ASK_RULES}]},
                       "contents": [{"role": "user", "parts": [{"text": prompt}]}]})
    with requests.post(GEMINI_URL % gemini_model(), data=body, timeout=40,
                       headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY}) as r:
        status = r.status_code
        d = r.json()
    if "error" in d:
        raise RuntimeError("Gemini: %s" % (d["error"].get("message") or "HTTP %d" % status)[:160])
    cands = d.get("candidates") or []
    parts = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
    txt = " ".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if not txt:
        why = (cands[0].get("finishReason") if cands else (d.get("promptFeedback") or {}).get("blockReason")) or "?"
        raise RuntimeError("Gemini gave no answer (%s)" % why)
    for uni, plain in (("\u2014", "-"), ("\u2013", "-"), ("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'),
                       ("\u201d", '"'), ("\u2026", "..."), ("\u00d7", "x"), ("\u2022", "-"), ("\u00b0", " deg ")):
        txt = txt.replace(uni, plain)           # the screen fonts are ASCII
    return " ".join(txt.replace("*", "").replace("`", "").split())


class AskScreen(Screen):
    TOP, BOTTOM, WIDTH = 43, 168, 308
    SIZES = ((F_NEWS, 29), (F_NEWS2, 25), (F_MED, 18), (F_SMALL, 12))   # font, line height

    def __init__(self):
        global root
        Screen.__init__(self)
        root = self.grp
        self.sub, self.clock = _head("ASK AI", 0x4C8DF6)
        self.q_lbl = text(F_SMALL, "", 6, 26, 0x7FB0FF)
        self.lines = [text(F_SMALL, "", 6, self.TOP, WHITE) for _ in range(10)]
        self.q = self.a = self.when = ""
        try:
            nv = microcontroller.nvm
            n = nv[ASK_NVM] | (nv[ASK_NVM + 1] << 8)
            if 2 <= n <= len(nv) - ASK_NVM - 2:
                d = json.loads(bytes(nv[ASK_NVM + 2:ASK_NVM + 2 + n]).decode())
                self.q, self.a, self.when = d.get("q", ""), d.get("a", ""), d.get("t", "")
        except Exception as e:  # noqa: BLE001
            print("saved answer unreadable:", repr(e))
        self.dirty = True

    def skip(self):
        return not self.a

    def set(self, q, a, keep=True):
        self.q, self.a = q, a
        t = time.localtime()
        self.when = "%d %s %02d:%02d" % (t.tm_mday, MONTHS[t.tm_mon - 1], t.tm_hour, t.tm_min)
        self.dirty = True
        if not keep:
            return
        nv = microcontroller.nvm
        n = nv[TODO_NVM] | (nv[TODO_NVM + 1] << 8)
        if ASK_NVM - TODO_NVM - 2 < n <= len(nv) - TODO_NVM - 2:
            return                              # an old, very long to-do list still sits there
        b = json.dumps({"q": q, "a": a, "t": self.when}).encode()
        if len(b) > len(nv) - ASK_NVM - 2:
            b = json.dumps({"q": q[:60], "a": a[:ASK_CHARS], "t": self.when}).encode()
        nv[ASK_NVM:ASK_NVM + 2 + len(b)] = bytes([len(b) & 255, len(b) >> 8]) + b

    def enter(self, now):
        self.draw()

    def frame(self, now):
        if self.dirty:
            self.draw()

    def draw(self):
        self.dirty = False
        _set(self.sub, self.when.upper())
        _set(self.q_lbl, _fit(F_SMALL, "> " + _screen_text(self.q), self.WIDTH) if self.q else "")
        a = _screen_text(self.a) or "Ask something at http://%s:%d/ask" % (MY_IP, LOGIN_PORT)
        room = self.BOTTOM - self.TOP
        for font, lh in self.SIZES:             # the biggest type the whole answer fits in
            rows, fits = wrap_px(font, a, self.WIDTH, room // lh)
            if fits:
                break
        if not fits and rows:                   # even the smallest is too small: end with ...
            rows[-1] = _fit(F_SMALL, rows[-1] + " ...", self.WIDTH - 12).rstrip(".") + "..."
        y0 = self.TOP + max(0, (room - len(rows) * lh) // 2) if len(rows) <= 2 else self.TOP
        for i, lbl in enumerate(self.lines):
            if i < len(rows):
                if lbl.font is not font:
                    lbl.font = font
                lbl.anchored_position = (6, y0 + i * lh)
                _set(lbl, rows[i])
            else:
                _set(lbl, "")


ask_screen = AskScreen()
EXTRA["ask"] = ask_screen


# ------------------------------------------------------------- night screensavers
# NIGHT_SCREEN = "clock" (default), "matrix", "fire", "stars" or "cycle" (changes every hour).
# They can also go in SCREEN_ORDER for the daytime rotation.
class Saver(Screen):
    def __init__(self, clock_xy, colour):
        global root
        Screen.__init__(self)
        root = self.grp
        self.build()
        root = self.grp
        self.clock = text(F_TITLE, "--:--", clock_xy[0], clock_xy[1], colour, right=True)
        self.last = 0.0

    def build(self):
        pass

    def frame(self, now):
        if now - self.last >= 0.05:              # ~20 frames a second at most
            self.last = now
            self.step()

    def step(self):
        pass


class MatrixRain(Saver):
    COLS, ROWS = 53, 14
    CHARS = "0123456789ABCDEFHKLMNPRTUVXZ$+-*=<>:#"

    def build(self):
        # glyph sheet: every character mirrored, 6x12 each, tile 0 blank
        sheet = displayio.Bitmap(6 * (len(self.CHARS) + 1), 12, 2)
        strip = render_strip(terminalio.FONT, self.CHARS, 12, 10)
        for i in range(len(self.CHARS)):
            for xx in range(6):
                for yy in range(12):
                    if strip[i * 6 + xx, yy]:
                        sheet[(i + 1) * 6 + (5 - xx), yy] = 1
        self.layers = []
        for colour in (0x0B4A1C, 0x1FBF4A, 0xC8FFD0):          # tail, body, head
            p = displayio.Palette(2)
            p[0], p[1] = 0, colour
            p.make_transparent(0)
            tg = displayio.TileGrid(sheet, pixel_shader=p, width=self.COLS, height=self.ROWS,
                                    tile_width=6, tile_height=12, default_tile=0, x=1, y=1)
            self.grp.append(tg)
            self.layers.append(tg)
        n = len(self.CHARS)
        self.rnd = lambda: random.randint(1, n)
        self.drops = [[-1.0, 0.0, 0, random.randint(0, 60)] for _ in range(self.COLS)]

    def _set(self, layer, c, r, v):
        if 0 <= r < self.ROWS:
            self.layers[layer][c, r] = v

    def step(self):
        tail, body, head = 0, 1, 2
        for c, d in enumerate(self.drops):
            pos, speed, ln, wait = d
            if speed == 0:
                if wait > 0:
                    d[3] = wait - 1
                    continue
                d[0], d[1], d[2] = -1.0, 0.3 + random.random() * 0.6, random.randint(4, 11)
                continue
            old = int(pos)
            pos += speed
            d[0] = pos
            for r in range(old + 1, int(pos) + 1):
                self._set(head, c, r, self.rnd())
                self._set(head, c, r - 1, 0)
                self._set(body, c, r - 1, self.rnd())
                self._set(body, c, r - 1 - ln, 0)
                self._set(tail, c, r - 1 - ln, self.rnd())
                self._set(tail, c, r - 4 - ln, 0)
                if r - 4 - ln >= self.ROWS:
                    d[1], d[3] = 0.0, random.randint(0, 40)
        for _ in range(4):                                     # a few glyphs flicker
            c, r = random.randint(0, self.COLS - 1), random.randint(0, self.ROWS - 1)
            if self.layers[body][c, r]:
                self.layers[body][c, r] = self.rnd()


class Fire(Saver):
    W, H = 64, 34

    def build(self):
        n = 37
        self.bmp = displayio.Bitmap(self.W, self.H, n)
        p = displayio.Palette(n)
        for i, c in enumerate(ramp((0x000000, 0x1F0707, 0x8F2707, 0xDF4F07, 0xCF7F0F,
                                    0xBFA727, 0xEFEFC7, 0xFFFFFF), n)):
            p[i] = c
        self.grp.append(displayio.Group(scale=5))
        self.grp[0].append(displayio.TileGrid(self.bmp, pixel_shader=p))
        self.buf = bytearray(self.W * self.H)
        for x in range(self.W):
            self.buf[(self.H - 1) * self.W + x] = n - 1
        self.rnd = bytes(random.randint(0, 3) for _ in range(997))
        self.ri = 0
        self.n = n

    def step(self):
        W, buf, rnd = self.W, self.buf, self.rnd
        ri = self.ri
        bottom = (self.H - 1) * W
        for x in range(W):                                     # the fuel line flickers a little
            if rnd[(ri + x) % 997] == 0:
                buf[bottom + x] = self.n - 1 - rnd[(ri + 3 * x) % 997] * 3
        for src in range(W, W * self.H):
            p = buf[src]
            if p == 0:
                buf[src - W] = 0
            else:
                r = rnd[ri]
                ri += 1
                if ri >= 997:
                    ri = 0
                dst = src - r + 1 - W
                if dst >= 0:
                    buf[dst] = p - r if p > r else 0    # cools as it rises: ~2/3 of the screen
        self.ri = ri
        bitmaptools.arrayblit(self.bmp, buf)


class Stars(Saver):
    N = 70

    def build(self):
        self.bmp = displayio.Bitmap(320, 170, 4)
        p = displayio.Palette(4)
        p[0], p[1], p[2], p[3] = 0x000000, 0x3A3F55, 0x9AA3C7, 0xFFFFFF
        self.grp.append(displayio.TileGrid(self.bmp, pixel_shader=p))
        self.stars = [self.new(True) for _ in range(self.N)]

    def new(self, anywhere=False):
        return [random.uniform(-1, 1), random.uniform(-1, 1),
                random.uniform(0.15, 1.0) if anywhere else 1.0, -1, -1, 0]

    def step(self):
        b = self.bmp
        for i, s in enumerate(self.stars):
            x, y, z, px, py, size = s
            if px >= 0:                                        # erase where it was
                b[px, py] = 0
                if size and px + 1 < 320 and py + 1 < 170:
                    b[px + 1, py] = b[px, py + 1] = b[px + 1, py + 1] = 0
            z -= 0.008
            if z > 0.02:
                sx, sy = int(160 + x / z * 130), int(85 + y / z * 70)
            if z <= 0.02 or not (0 <= sx < 319 and 0 <= sy < 169):
                self.stars[i] = self.new()
                continue
            c = 3 if z < 0.35 else 2 if z < 0.7 else 1
            big = 1 if z < 0.25 else 0
            b[sx, sy] = c
            if big:
                b[sx + 1, sy] = b[sx, sy + 1] = b[sx + 1, sy + 1] = c
            s[2], s[3], s[4], s[5] = z, sx, sy, big


EXTRA["matrix"] = MatrixRain((314, 150), 0x1A6A30)
EXTRA["fire"] = Fire((314, 4), 0x5A3A2A)
EXTRA["stars"] = Stars((314, 150), 0x4A5068)
SAVERS = ("matrix", "fire", "stars")
NIGHT_SCREEN = (cfg("NIGHT_SCREEN") or "clock").strip().lower()
EXTRA_LIST = list(EXTRA.values())


def night_name(t):
    """Which screen shows at night."""
    if NIGHT_SCREEN == "cycle":
        return (SAVERS + ("clock",))[t.tm_hour % 4]
    return NIGHT_SCREEN if NIGHT_SCREEN in EXTRA else "clock"



# ============================================================= state + helpers
# screens, in the order set by SCREEN_ORDER (comma separated names)
ALL_SCREENS = {"weather": weather_grp, "portfolio": port_grp, "markets": mkt_grp,
               "cricket": cric_grp, "news": news_grp, "clock": clock_grp}
for _n, _s in EXTRA.items():
    ALL_SCREENS[_n] = _s.grp
TICKERS = {"weather": weather_ticker, "portfolio": port_ticker, "markets": mkt_ticker,
           "cricket": cric_ticker}
DEFAULT_ORDER = "weather,ask,todo,portfolio,stocks,heatmap,markets,cricket,stat,news,trivia,net,pet"


def parse_order(text_):
    out = []
    for n in (text_ or DEFAULT_ORDER).split(","):
        n = n.strip()
        if n in ALL_SCREENS and n not in out:
            out.append(n)
    return out or ["weather"]


def parse_night(text_):
    """'23-7' -> (23, 7); '' -> None (night mode off)."""
    p = ("23-7" if text_ is None else text_).split("-")
    try:
        return (int(p[0]) % 24, int(p[1]) % 24) if len(p) == 2 and p[0].strip() else None
    except ValueError:
        return None


ORDER = parse_order(cfg("SCREEN_ORDER"))
screen = 0
display.root_group = ALL_SCREENS[ORDER[0]]

# night mode: only the dimmed dark clock between NIGHT_HOURS (e.g. "23-7"; "" = off)
NIGHT = parse_night(cfg("NIGHT_HOURS"))
DAY_BRIGHT = float(cfg("DAY_BRIGHTNESS") or "0.6")
NIGHT_BRIGHT = float(cfg("NIGHT_BRIGHTNESS") or "0.05")


def set_brightness(v):
    try:
        display.brightness = v
    except Exception:  # noqa: BLE001
        pass


set_brightness(DAY_BRIGHT)


def is_night(t):
    if not NIGHT:
        return False
    a, b = NIGHT
    h = t.tm_hour
    return (a <= h or h < b) if a > b else (a <= h < b)
weather_ticker.set("Connecting...")
port_ticker.set("Waiting for Kite login...")

utc_offset = 19800   # IST, replaced by Open-Meteo's value
counter = 0
weather_msg = ""
air_msg = ""
kite_token = None
movers_msg, movers_at = "", 0.0
kite_status = "Kite not set up - add KITE_API_KEY and KITE_API_SECRET to settings.toml"


def inr(v, signed=False):
    """Indian-style rupee text: 12,345 / 1.23L / 4.56Cr."""
    sign = ("+" if v >= 0 else "-") if signed else ("-" if v < 0 else "")
    a = abs(v)
    if a >= 1e7:
        body = "%.2fCr" % (a / 1e7)
    elif a >= 1e5:
        body = "%.2fL" % (a / 1e5)
    else:
        s = "%d" % round(a)
        if len(s) > 3:
            head, tail = s[:-3], s[-3:]
            parts = []
            while len(head) > 2:
                parts.insert(0, head[-2:])
                head = head[:-2]
            if head:
                parts.insert(0, head)
            s = ",".join(parts) + "," + tail
        body = s
    return sign + "₹" + body


def draw_graph(temps):
    vals = [t for t in temps if t is not None][-24:]
    if vals:
        lbl_range.text = "Low %.1f  High %.1f" % (min(vals), max(vals))


# ------------------------------------------------------------- watchdog
# If the loop ever hangs for 2 minutes, the chip resets itself.
WATCHDOG = (os.getenv("WATCHDOG") or "on").strip().lower() != "off"
if WATCHDOG:
    try:
        from watchdog import WatchDogMode
        try:
            microcontroller.watchdog.timeout = 120
        except ValueError:
            microcontroller.watchdog.timeout = 60
        microcontroller.watchdog.mode = WatchDogMode.RESET
    except Exception as e:  # noqa: BLE001
        print("watchdog unavailable:", repr(e))
        WATCHDOG = False


def dog():
    if WATCHDOG:
        try:
            microcontroller.watchdog.feed()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------- network
SSID = os.getenv("CIRCUITPY_WIFI_SSID")
WIFI_PW = os.getenv("CIRCUITPY_WIFI_PASSWORD")
NET_TIMEOUT = 8                  # seconds; short so an outage can't freeze the screen for long
PROBE_URL = "http://connectivitycheck.gstatic.com/generate_204"


def wifi_up():
    try:
        return bool(wifi.radio.connected and wifi.radio.ipv4_address)
    except Exception:  # noqa: BLE001
        return False


def wifi_try(timeout=8):
    dog()
    try:
        wifi.radio.connect(SSID, WIFI_PW, timeout=timeout)
    except Exception as e:  # noqa: BLE001 - router not up yet, wrong channel...
        print("wifi connect failed:", repr(e))
    dog()
    return wifi_up()


# after a power cut the board boots long before the router: wait (and say so) instead of crashing
if not wifi_up():
    wait_grp = displayio.Group()
    root = wait_grp
    text(F_TITLE, "Waiting for Wi-Fi", 160, 62, WHITE, center=True)
    wait_lbl = text(F_SMALL, SSID or "your Wi-Fi", 160, 92, GREYS[3], center=True)
    text(F_SMALL, "The dashboard starts as soon as it connects", 160, 140, GREYS[6], center=True)
    display.root_group = wait_grp
    tries = 0
    while not wifi_try(10):
        tries += 1
        wait_lbl.text = "%s  -  tried %d times" % (SSID or "your Wi-Fi", tries)
        for _ in range(10):      # ~5 s between attempts, watchdog fed
            dog()
            time.sleep(0.5)
    display.root_group = ALL_SCREENS[ORDER[0]]
MY_IP = str(wifi.radio.ipv4_address)
pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
ssl_ctx = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
requests = adafruit_requests.Session(pool, ssl_ctx)


def ntp_sync():
    addr = pool.getaddrinfo("pool.ntp.org", 123)[0][4]
    pkt = bytearray(48)
    pkt[0] = 0x1B
    with pool.socket(pool.AF_INET, pool.SOCK_DGRAM) as sock:
        sock.settimeout(5)
        sock.sendto(pkt, addr)
        sock.recv_into(pkt)
    utc = struct.unpack_from("!I", pkt, 40)[0] - 2208988800
    rtc.RTC().datetime = time.localtime(utc + utc_offset)


def get_weather():
    global utc_offset, weather_msg
    with requests.get(WEATHER_URL, timeout=NET_TIMEOUT) as r:
        d = r.json()
    utc_offset = d.get("utc_offset_seconds", utc_offset)
    cur = d["current"]
    lbl_temp.text = "%.1f" % cur["temperature_2m"]
    tile_vals[0].text = "%d" % cur["relative_humidity_2m"]
    tile_vals[1].text = "%.1f" % cur["wind_speed_10m"]
    draw_graph(d["hourly"]["temperature_2m"])
    lbl_feels.text = "FEELS %.1f C" % cur["apparent_temperature"]
    lbl_ctemp.text = "%.1f C  %s" % (cur["temperature_2m"], TOWN[:8].upper())
    lbl_cdesc.text = WMO.get(cur["weather_code"], "")[:22].upper()
    weather_msg = "%s  #Feels like %.1f C  #Pressure %d hPa" % (
        WMO.get(cur["weather_code"], "Weather"), cur["apparent_temperature"],
        cur["pressure_msl"])
    th_weather(cur, d)


def get_air():
    global air_msg
    with requests.get(AIR_URL, timeout=NET_TIMEOUT) as r:
        cur = r.json()["current"]
    tile_vals[2].text = "%d" % cur["pm2_5"]
    air_msg = "#PM2.5 %d  #PM10 %d  #AQI %d (US)" % (
        cur["pm2_5"], cur["pm10"], cur["us_aqi"])
    th_air(cur)


# ------------------------------------------------------------- Kite
def kite_headers():
    return {"X-Kite-Version": "3",
            "Authorization": "token %s:%s" % (KITE_KEY, kite_token)}


def kite_login(request_token):
    """Swap the one-time request_token for today's access_token."""
    global kite_token, kite_status
    checksum = hashlib.sha256(
        (KITE_KEY + request_token + KITE_SECRET).encode()).hexdigest()
    body = "api_key=%s&request_token=%s&checksum=%s" % (KITE_KEY, request_token, checksum)
    with requests.post(KITE_API + "/session/token", data=body, timeout=NET_TIMEOUT,
                       headers={"X-Kite-Version": "3",
                                "Content-Type": "application/x-www-form-urlencoded"}) as r:
        d = r.json()
    if d.get("status") != "success":
        raise RuntimeError(d.get("message", "login failed"))
    kite_token = d["data"]["access_token"]
    kite_status = "Logged in"
    kite_save(kite_token)


# the day's Kite login survives restarts: kept in NVM until it expires (~07:30 next morning)
KITE_NVM = 8      # nvm[8] "K", [9:13] expiry (local epoch), [13] length, [14:] token


def kite_save(tok):
    try:
        now = int(time.time())
        lt = time.localtime(now)
        exp = now - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec) + 7 * 3600 + 1800
        if now >= exp:
            exp += 86400
        b = tok.encode()[:48]
        microcontroller.nvm[KITE_NVM:KITE_NVM + 6 + len(b)] = (
            b"K" + struct.pack("<I", exp) + bytes([len(b)]) + b)
    except Exception as e:  # noqa: BLE001
        print("couldn't save Kite login:", repr(e))


def kite_forget():
    try:
        if microcontroller.nvm[KITE_NVM] == ord("K"):
            microcontroller.nvm[KITE_NVM] = 0
    except Exception:  # noqa: BLE001
        pass


def kite_load():
    try:
        nv = microcontroller.nvm
        if nv[KITE_NVM] != ord("K"):
            return None
        exp = struct.unpack("<I", bytes(nv[KITE_NVM + 1:KITE_NVM + 5]))[0]
        tok = bytes(nv[KITE_NVM + 6:KITE_NVM + 6 + nv[KITE_NVM + 5]]).decode()
        if time.localtime().tm_year >= 2024 and time.time() >= exp:   # clock is right and it's stale
            kite_forget()
            return None
        return tok
    except Exception:  # noqa: BLE001
        return None


def show_login_needed(reason):
    global kite_token, kite_status, port_day_pct, pos_cache
    kite_token = None
    kite_forget()
    port_day_pct = None
    heat_screen.update(None)
    stocks_screen.update(None)
    pos_cache = None
    kite_status = reason
    lbl_day.text = "--"
    lbl_tot.text = "--"
    lbl_day.color = lbl_tot.color = GREYS[0]
    lbl_day_pct.text = "LOG IN AT  >"
    lbl_day_pct.color = GREYS[2]
    lbl_tot_pct.text = "%s:%d" % (MY_IP, LOGIN_PORT)
    lbl_tot_pct.color = GREYS[1]
    port_ticker.set("#%s  #Open http://%s:%d on your phone to log in to Kite"
                    % (reason, MY_IP, LOGIN_PORT))
    th_port(None)


pos_cache = None            # (rows, today's P&L, open count) from the last good positions read


def get_positions():
    """Kite positions (the Positions page): rows for the open ones, today's P&L on all of them.
    P&L is worked out from the last price like Kite does, as the API's pnl field can lag."""
    with requests.get(KITE_API + "/portfolio/positions", headers=kite_headers(),
                      timeout=NET_TIMEOUT) as r:
        d = r.json()
    if d.get("status") != "success":
        raise RuntimeError(d.get("message", "positions failed"))
    rows, day = [], 0.0
    for p in (d.get("data") or {}).get("net") or ():
        qty = p.get("quantity") or 0
        last = p.get("last_price") or 0
        mult = p.get("multiplier") or 1
        now_val = qty * last * mult
        if "buy_value" in p and "sell_value" in p:
            pnl = (p["sell_value"] or 0) - (p["buy_value"] or 0) + now_val
        else:
            pnl = p.get("pnl") or 0
        if "buy_m2m" in p and "sell_m2m" in p:
            m2m = (p["sell_m2m"] or 0) - (p["buy_m2m"] or 0) + now_val
        else:
            m2m = p.get("m2m") or 0
        day += m2m              # closed trades count towards today too
        if not qty:
            continue
        sym, prod = p.get("tradingsymbol", "?"), (p.get("product") or "POS").upper()
        avg = p.get("average_price") or 0
        cost = abs(qty) * avg * mult
        rows.append((sym + ":" + prod, sym, prod, qty, avg, last, p.get("close_price") or 0,
                     pnl, pnl / cost * 100 if cost else 0.0, m2m))
    return rows, day, len(rows)


def get_portfolio():
    with requests.get(KITE_API + "/portfolio/holdings", headers=kite_headers(),
                      timeout=NET_TIMEOUT) as r:
        status = r.status_code
        d = r.json()
    if status == 403 or d.get("error_type") == "TokenException":
        show_login_needed("Kite session expired")
        return
    if d.get("status") != "success":
        raise RuntimeError(d.get("message", "holdings failed"))

    global port_day_pct
    invested = current = day = 0.0
    movers = []
    heat_rows = []
    stock_rows = []
    for h in d["data"]:
        qty = (h.get("quantity") or 0) + (h.get("t1_quantity") or 0)
        if qty <= 0:
            continue
        last = h.get("last_price") or 0
        close = h.get("close_price") or 0
        invested += (h.get("average_price") or 0) * qty
        current += last * qty
        if close:
            day += (last - close) * qty
            movers.append(((last - close) / close * 100, h.get("tradingsymbol", "?")))
        heat_rows.append((h.get("tradingsymbol", "?"), last * qty,
                          (last - close) / close * 100 if close else 0.0))
        sym, avg = h.get("tradingsymbol", "?"), h.get("average_price") or 0
        stock_rows.append((sym, sym, "", qty, avg, last, close, (last - avg) * qty,
                           (last - avg) / avg * 100 if avg else 0.0, (last - close) * qty if close else 0.0))
    d = None                    # free the holdings JSON before the next request
    total = current - invested
    base = current - day        # holdings value at yesterday's close

    # open positions (intraday, F&O, today's delivery buys) and today's trading P&L
    global pos_cache
    try:
        pos_cache = get_positions()
    except Exception as e:  # noqa: BLE001 - holdings still update
        log_err("positions failed: %r" % (e,))
        free_sockets()
    pos_rows, pos_day, pos_open = pos_cache or ([], 0.0, 0)
    day += pos_day

    lbl_day.text = inr(day, signed=True)
    lbl_day.color = GREEN if day >= 0 else RED
    day_pct = day / base * 100 if base else 0
    port_day_pct = day_pct
    heat_screen.update(heat_rows)
    stocks_screen.update(stock_rows + pos_rows)
    lbl_day_pct.text = "%+.2f%%" % day_pct
    lbl_day_pct.color = lbl_day.color
    lbl_tot.text = inr(total, signed=True)
    lbl_tot.color = GREEN if total >= 0 else RED
    lbl_tot_pct.text = "%+.2f%%" % (total / invested * 100 if invested else 0)
    lbl_tot_pct.color = lbl_tot.color
    port_tiles[0].text = inr(invested)
    port_tiles[1].text = inr(current)
    port_tiles[2].text = "%d" % len(movers)
    th_port((day, day_pct, total, total / invested * 100 if invested else 0,
             invested, current, len(movers)))

    movers.sort()
    parts = ["%s %+.1f%%" % (s, p) for p, s in reversed(movers[-3:]) if p > 0]
    parts += ["%s %+.1f%%" % (s, p) for p, s in movers[:3] if p < 0]
    if pos_cache and (pos_open or pos_day):
        parts.append("Positions %s today%s" % (inr(pos_day, signed=True).replace("₹", ""),
                                               (", %d open" % pos_open) if pos_open else ""))
    msg = "#" + "  #".join(parts or ["No movers yet"])
    global movers_msg, movers_at
    # only restart the scrolling line when movers change (or once a minute),
    # otherwise 5-second refreshes would keep resetting it
    if msg != movers_msg or time.monotonic() - movers_at > 60:
        movers_msg, movers_at = msg, time.monotonic()
        port_ticker.set(msg + stamp())


# ------------------------------------------------------------- markets
# NASDAQ / S&P 500: FMP (financialmodelingprep.com), public API, free key, 250 calls/day.
# SENSEX / NIFTY 50: read from Yahoo Finance's chart data feed (unofficial - it can
# change or start refusing requests). Nothing here uses your Kite account.
FMP_KEY = os.getenv("FMP_API_KEY") or ""
FMP_URL = "https://financialmodelingprep.com/stable/quote?symbol=%s&apikey=%s"
mkt_notes = {}                # source -> latest problem, shown on the ticker


def group_num(v):
    s = "%.2f" % abs(v)
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    return ("-" if v < 0 else "") + whole + "." + frac


def show_index(i, last, change, pct, is_open):
    mkt_val[i].text = group_num(last)
    mkt_chg[i].text = "%+.2f  %+.2f%%" % (change, pct)
    mkt_chg[i].color = GREEN if change >= 0 else RED
    mkt_state[i].text = "OPEN" if is_open else "CLOSED"
    mkt_state[i].color = GREEN if is_open else GREYS[6]
    th_index(i, last, change, pct, is_open)


def mkt_ticker_refresh():
    notes = ["#" + n for n in mkt_notes.values() if n]
    mkt_ticker.set("  ".join(notes or ["#India: Yahoo Finance  #USA: Financial Modeling Prep"]) + stamp())


def get_fmp(which):
    """which: 'in' or 'us' - one request per index (works on the free plan)."""
    if not FMP_KEY:
        mkt_notes["fmp"] = "Add FMP_API_KEY to settings.toml (free key from financialmodelingprep.com)"
        mkt_ticker_refresh()
        return
    problems = []
    is_open = market_open() if which == "in" else us_market_open()
    for i, ix in enumerate(INDICES):
        if ix["mkt"] != which:
            continue
        with requests.get(FMP_URL % (ix["fmp"].replace("^", "%5E"), FMP_KEY), timeout=NET_TIMEOUT) as r:
            d = r.json()
        q = d[0] if isinstance(d, list) and d else None
        if not q or "price" not in q:
            msg = d.get("Error Message") if isinstance(d, dict) else "no data"
            problems.append("%s: %s" % (ix["name"], (msg or "no data")[:70]))
            show_index_error(i, "no data from FMP")
            continue
        pct = q.get("changePercentage", q.get("changesPercentage", 0)) or 0
        show_index(i, q["price"], q.get("change", 0) or 0, pct, is_open)
    mkt_notes["fmp_" + which] = "  #".join(problems)
    mkt_ticker_refresh()


YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1d"
YAHOO_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
             "Accept": "application/json"}


def get_yahoo_india():
    problems = []
    is_open = market_open()
    for i, ix in enumerate(INDICES):
        if "yahoo" not in ix:
            continue
        status = None
        try:
            with requests.get(YAHOO_URL % ix["yahoo"], headers=YAHOO_HDR, timeout=NET_TIMEOUT) as r:
                status = r.status_code
                d = r.json() if status == 200 else {}
            meta = d["chart"]["result"][0]["meta"]
            last = meta["regularMarketPrice"]
            prev = meta.get("chartPreviousClose") or meta.get("previousClose") or last
        except Exception as e:  # noqa: BLE001
            if status is None and _net_error(e):
                raise                  # network trouble: keep the last values, let safe() notice
            why = ("HTTP %s" % status) if status not in (None, 200) else repr(e)[:40]
            problems.append("%s: Yahoo %s" % (ix["name"], why))
            show_index_error(i, "no data (Yahoo)")
            continue
        show_index(i, last, last - prev, (last - prev) / prev * 100 if prev else 0, is_open)
    mkt_notes["yahoo"] = "  #".join(problems)
    mkt_ticker_refresh()


def us_market_open():
    """NYSE hours, approximately (13:30-21:00 UTC covers summer and winter)."""
    t = time.localtime(time.time() - utc_offset)
    mins = t.tm_hour * 60 + t.tm_min
    return t.tm_wday < 5 and 13 * 60 + 30 <= mins <= 21 * 60


# ------------------------------------------------------------- cricket
# You can follow several matches (picked at /cricket, or CRICKET_TEAM, comma separated);
# the cricket screen cycles through the ones in the live feed, CRICKET_MATCH_SECONDS each.
CRIC_MAX = 6
CRIC_MATCH_SECONDS = max(3, int(os.getenv("CRICKET_MATCH_SECONDS") or "8"))
CRIC_GONE_SECS = 30 * 60    # a followed match out of the feed this long has finished: forget it
CRIC_CFG = "CRICKET_MATCHES" if CRIC_RSS else "CRICKET_MATCHES_" + CRIC_SOURCE.upper()   # ids differ per source
cric_ids = [i.strip() for i in (cfg(CRIC_CFG) or "").split(",") if i.strip()][:CRIC_MAX]
cric_id = cric_ids[0] if cric_ids else None     # the one on screen now
cric_items = {}         # id -> latest feed item (RSS), match (cricapi) or followed match read (Cricbuzz)
cric_details = {}       # id -> overs/batters from Cricinfo (RSS source)
cric_detail_at = {}     # id -> when those were fetched
cric_gone = {}          # id -> when a followed match was first missing from the feed
cric_dropped = set()    # matches you stopped following: CRICKET_TEAM won't add them back
cric_ended = False
cric_hits = ""


def cric_get(path):
    global cric_hits
    url = CRIC_API + path + ("&" if "?" in path else "?") + "apikey=" + CRIC_KEY
    with requests.get(url, timeout=NET_TIMEOUT) as r:
        d = r.json()
    info = d.get("info") or {}
    if "hitsToday" in info:
        cric_hits = "%s/%s" % (info.get("hitsToday"), info.get("hitsLimit", "?"))
    if d.get("status") != "success":
        raise RuntimeError(d.get("reason") or d.get("status") or "cricket API error")
    return d["data"]


def short_name(m, team):
    for ti in m.get("teamInfo") or []:
        if ti.get("name") == team and ti.get("shortname"):
            return ti["shortname"].upper()[:5]
    return team[:3].upper()


def show_match(m):
    global cric_ended
    cric_ended = bool(m.get("matchEnded"))
    started = bool(m.get("matchStarted"))
    lbl_cname.text = (m.get("name") or "")[:52]
    lbl_ctype.text = (m.get("matchType") or "").upper()
    if cric_ended:
        lbl_clive.text, lbl_clive.color = "RESULT", GREYS[5]
    elif started:
        lbl_clive.text, lbl_clive.color = "LIVE", RED
    else:
        lbl_clive.text, lbl_clive.color = "UPCOMING", GREYS[5]

    teams = (m.get("teams") or ["Team 1", "Team 2"])[:2]
    scores = m.get("score") or []
    batting = None
    for i, team in enumerate(teams):
        inns = []
        for sc in scores:
            if (sc.get("inning") or "").lower().startswith(team.lower()):
                inns.append(sc)
                batting = i if sc is scores[-1] else batting
        txt = []
        for sc in inns:
            r, w = sc.get("r", 0), sc.get("w", 0)
            txt.append("%d" % r if w >= 10 else "%d/%d" % (r, w))
        cric_team[i].text = short_name(m, team)
        cric_score[i].text = " & ".join(txt) if txt else "-"
        last = inns[-1] if inns else None
        cric_overs[i].text = ("%s ov" % last.get("o")) if last else team[:24]
    for i in range(len(teams)):
        live = (batting == i) and started and not cric_ended
        cric_team[i].color = GREYS[0] if live else GREYS[3]
        cric_score[i].color = GREYS[0] if live else GREYS[3]
        if live:
            cric_overs[i].text += "  BATTING"
        th_team(i, teams[i], live)
    cric_ticker.set("#%s  #%s  #API hits today %s" % (
        m.get("status") or "", m.get("venue") or "", cric_hits) + stamp())


cb_list_cache = [0.0, None]     # (when, matches): Cricbuzz's list page is big, keep it a while


def cric_feed():
    """Every current match: the Cricinfo live feed, Cricbuzz's live-scores page or one cricapi call."""
    if CRIC_CB:
        now = time.monotonic()
        if cb_list_cache[1] is None or now - cb_list_cache[0] > 120:
            cb_list_cache[:] = [now, cb_list()]
        return cb_list_cache[1]
    return rss_items() if CRIC_RSS else cric_get("currentMatches?offset=0")


def get_cricket():
    if CRIC_CB:                 # Cricbuzz: one followed match at a time
        mid = cb_due(time.monotonic(), True) or cric_id
        if mid:
            cb_fetch(mid)
    else:
        cric_update(cric_feed())


def cric_save():
    CFG[CRIC_CFG] = ",".join(cric_ids)
    try:
        save_cfg()
    except Exception as e:  # noqa: BLE001
        log_err("saving cricket matches failed: %r" % (e,))


def cric_shown_ids():
    """Followed matches that are in the feed, in the order you picked them."""
    return [i for i in cric_ids if i in cric_items]


def cric_any_live():
    return any(not cric_items[i].get("matchEnded") for i in cric_shown_ids())


def cric_dwell():
    """Long enough on the cricket screen to show every followed match once."""
    n = len(cric_shown_ids())
    return max(SCREEN_SECONDS, n * CRIC_MATCH_SECONDS) if n > 1 else None


def cric_title(m):
    return m.get("title") or m.get("name") or "?"


def cric_add(mid, show=False):
    global cric_id
    if mid not in cric_ids:
        if len(cric_ids) >= CRIC_MAX:
            return False
        cric_ids.append(mid)
    cric_dropped.discard(mid)
    cric_gone.pop(mid, None)
    if show or cric_id not in cric_shown_ids():
        cric_id = mid
    return True


def cric_remove(mid):
    global cric_id
    if mid in cric_ids:
        cric_ids.remove(mid)
    cric_dropped.add(mid)
    for d in (cric_details, cric_detail_at, cric_gone):
        d.pop(mid, None)
    if cric_id == mid:
        cric_id = None


def cric_update(items):
    """A fresh feed: keep it, forget followed matches that left it long ago, redraw."""
    global cric_others
    now = time.monotonic()
    if CRIC_CB:                 # the list is only for picking; scores come from cb_fetch()
        cric_render()
        return
    cric_items.clear()
    for it in items:
        if it.get("id"):
            cric_items[it["id"]] = it
    gone = False
    for mid in list(cric_ids):
        if mid in cric_items:
            cric_gone.pop(mid, None)
        elif now - cric_gone.setdefault(mid, now) > CRIC_GONE_SECS:
            cric_ids.remove(mid)
            for d in (cric_details, cric_detail_at, cric_gone):
                d.pop(mid, None)
            gone = True
    if gone:
        cric_save()
    if CRIC_RSS:
        cric_others = "  ".join(["#" + it["title"].replace(" *", "*")
                                 for it in items if it.get("id") not in cric_ids][:6])
    cric_render()


def cric_render():
    """Draw the followed match that's on screen (or the first one still in the feed)."""
    global cric_id, cric_item, cric_detail, cric_ended
    ids = cric_shown_ids()
    waiting = CRIC_CB and cric_id in cric_ids and cric_id not in cric_items and cric_id not in cric_gone
    if cric_id not in ids and not waiting:
        cric_id = ids[0] if ids else (cric_ids[0] if cric_ids else None)
    lbl_cpage.text = ("%d/%d" % (ids.index(cric_id) + 1, len(ids))) if len(ids) > 1 and cric_id in ids else ""
    if not cric_id:
        cric_item, cric_detail = None, {}
        lbl_cname.text = "No match selected"
        lbl_clive.text = ""
        cric_ticker.set("#Pick matches at http://%s:%d/cricket" % (MY_IP, LOGIN_PORT))
        return
    m = cric_items.get(cric_id)
    if m is None and CRIC_CB and cric_id not in cric_gone:
        err = cb_err.get(cric_id)
        lbl_cname.text = ("Cricbuzz: %s - retrying" % err) if err else "Loading the score from Cricbuzz..."
        if err:
            cric_ticker.set("#Couldn't read the score from Cricbuzz (%s) - retrying  #Details: http://%s:%d/cricket/debug"
                            % (err, MY_IP, LOGIN_PORT))
        return
    if m is None:                       # every followed match has left the feed
        cric_item, cric_ended = None, True
        lbl_clive.text, lbl_clive.color = "FINISHED", GREYS[5]
        cric_ticker.set("#%s left the live feed (finished?)  %s" % (
            "Your matches have" if len(cric_ids) > 1 else "This match has", cric_others))
        return
    if CRIC_CB:
        show_cb(m)
    elif CRIC_RSS:
        cric_item = m
        cric_detail = cric_details.get(cric_id) or {}
        show_rss(m)
        cric_tick()
    else:
        show_match(m)


def cric_next():
    """Next followed match (the screen does this every CRIC_MATCH_SECONDS, BOOT does it now)."""
    global cric_id
    ids = cric_shown_ids()
    if len(ids) < 2:
        return
    cric_id = ids[(ids.index(cric_id) + 1) % len(ids)] if cric_id in ids else ids[0]
    cric_render()


def auto_pick():
    """CRICKET_TEAM (one team or several, comma separated): follow their current matches."""
    teams = [t.strip() for t in CRIC_TEAM.split(",") if t.strip()]
    items = cric_feed()
    added = False
    for m in items:
        names = (m.get("title") or " ".join(m.get("teams") or [])).lower() + " " + m.get("link", "")
        mid = m.get("id")
        if (mid and mid not in cric_ids and mid not in cric_dropped and not m.get("matchEnded")
                and any(t in names for t in teams) and len(cric_ids) < CRIC_MAX):
            cric_ids.append(mid)
            added = True
    if added:
        cric_save()
    cric_update(items)


# ---- ESPNcricinfo RSS source
def _tag(chunk, name):
    a = chunk.find("<" + name)
    if a < 0:
        return ""
    a = chunk.find(">", a) + 1
    b = chunk.find("</" + name + ">", a)
    v = chunk[a:b].strip()
    if v.startswith("<![CDATA["):
        v = v[9:-3]
    for x, y in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                 ("&#39;", "'"), ("&apos;", "'")):
        v = v.replace(x, y)
    return v.strip()


def _match_id(link):
    """Numeric match id from a Cricinfo link (last run of digits)."""
    digits, best = "", ""
    for ch in link:
        if ch.isdigit():
            digits += ch
        else:
            if len(digits) >= 4:
                best = digits
            digits = ""
    if len(digits) >= 4:
        best = digits
    return best or link


def rss_items():
    hdr = {"User-Agent": "Mozilla/5.0 (T-Display-S3 desk scoreboard; RSS reader)"}
    with requests.get(RSS_URL, headers=hdr, timeout=NET_TIMEOUT) as r:
        xml = r.text
    items = []
    for chunk in xml.split("<item")[1:]:
        title = _tag(chunk, "title") or _tag(chunk, "description")
        link = _tag(chunk, "link") or _tag(chunk, "guid")
        if title:
            items.append({"id": _match_id(link), "title": title, "link": link,
                          "desc": _tag(chunk, "description")})
    return items


def abbrev(team):
    words = [w for w in team.replace("-", " ").split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words if w[0].isalpha()).upper()[:4]


def split_overs(side):
    """'India 187/5 (18.3 ov) *' -> ('India 187/5 *', '18.3 ov')"""
    a = side.find("(")
    b = side.find(")", a + 1)
    if a >= 0 and b > a and "ov" in side[a:b]:
        return side[:a] + side[b + 1:], side[a + 1:b].strip()
    return side, ""


def parse_side(side):
    """'India 187/5 *' -> ('India', '187/5', True)"""
    batting = "*" in side
    toks = side.replace("*", " ").split()
    idx = len(toks)
    for i, t in enumerate(toks):
        core = t.replace("/", "").replace("d", "").replace("&", "")
        if i > 0 and core.isdigit():
            idx = i
            break
    return " ".join(toks[:idx]), " ".join(toks[idx:]), batting


def show_rss(item):
    global cric_ended
    cric_ended = False
    title = item["title"]
    sides = None
    for sep in (" v ", " vs ", " V "):
        if sep in title:
            sides = title.split(sep, 1)
            break
    lbl_ctype.text = "CRICINFO"
    lbl_cname.text = title[:52]
    if not sides:
        for i in range(2):
            cric_team[i].text, cric_score[i].text, cric_overs[i].text = "", "", ""
        cric_team[0].text = "?"
        lbl_clive.text = ""
        th_team(0, "", False)
        th_team(1, "", False)
        return
    any_bat = False
    names = []
    for i in range(2):
        side, overs = split_overs(sides[i])
        team, score, bat = parse_side(side)
        names.append(team)
        any_bat = any_bat or bat
        cric_team[i].text = abbrev(team)
        cric_score[i].text = score or "-"
        known = cric_detail.get("info") or {}
        info = known.get(team.lower()) or known.get(abbrev(team).lower()) or overs or team[:24]
        cric_overs[i].text = info + ("  BATTING" if bat else "")
        cric_team[i].color = cric_score[i].color = GREYS[0] if bat else GREYS[3]
        th_team(i, team, bat)
    lbl_clive.text, lbl_clive.color = ("LIVE", RED) if any_bat else ("", GREYS[5])
    lbl_cname.text = cric_detail.get("batters") or (names[0] + " v " + names[1])[:52]


cric_others = ""


def cric_tick():
    t = time.localtime()
    head = ("#" + cric_detail["status"] + "  ") if cric_detail.get("status") else ""
    cric_ticker.set("%s#Updated %02d:%02d:%02d  %s  #Data: ESPNcricinfo" % (
        head, t.tm_hour, t.tm_min, t.tm_sec, cric_others))


# ---- per-match details (overs, batters) from Cricinfo's JSON pages
CI_API = "https://hs-consumer-api.espncricinfo.com/v1/pages/match/home?lang=en&matchId=%s%s"
CI_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
          "Accept": "application/json", "Origin": "https://www.espncricinfo.com",
          "Referer": "https://www.espncricinfo.com/"}
cric_item = None
cric_detail = {}          # {"info": {0: "18.3/20 ov", 1: ...}, "batters": "...", "status": "..."}
cric_debug = {}           # what the last attempt saw, for /cricket/debug


def _series_id(link):
    """.../series/some-name-1445348/... -> '1445348' (None if the link has no series)."""
    i = link.find("/series/")
    if i < 0:
        return None
    seg = link[i + 8:].split("/")[0]
    tail = seg.split("-")[-1]
    return tail if tail.isdigit() else None


def _balanced(body, key, start=0):
    """Return the JSON object/array that follows `key` in body (as text), or None."""
    i = body.find(key, start)
    if i < 0:
        return None
    j = i + len(key)
    while j < len(body) and body[j] in " :\r\n\t":
        j += 1
    if j >= len(body) or body[j] not in "{[":
        return None
    depth, in_str, esc = 0, False, False
    for k in range(j, min(len(body), j + 60000)):
        ch = body[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return body[j:k + 1]
    return None


def _string_after(body, key):
    i = body.find(key)
    if i < 0:
        return ""
    a = body.find('"', i + len(key))
    b = body.find('"', a + 1)
    return body[a + 1:b] if a >= 0 and b > a else ""


def get_cricket_detail(item):
    """Fetch overs + batters for the chosen match. Leaves cric_detail empty on failure."""
    import json
    global cric_detail
    cric_detail_at[item["id"]] = time.monotonic()      # tried now (even if it fails)
    sid = _series_id(item["link"])
    url = CI_API % (item["id"], ("&seriesId=" + sid) if sid else "")
    cric_debug.clear()
    cric_debug.update({"url": url, "rss_title": item["title"], "rss_desc": item.get("desc", ""),
                       "rss_link": item["link"]})
    body_parts, size = [], 0
    with requests.get(url, headers=CI_HDR, timeout=NET_TIMEOUT) as r:
        cric_debug["status"] = r.status_code
        if r.status_code != 200:
            return                     # keep what we had for this match
        for chunk in r.iter_content(chunk_size=4096):
            body_parts.append(chunk)
            size += len(chunk)
            if size > 700000:              # safety cap
                break
    body = _text(b"".join(body_parts))
    del body_parts
    cric_debug["bytes"] = size
    found = {}
    # team scores + overs ("scoreInfo") from the match object
    m = body.find('"match":')
    teams_txt = _balanced(body, '"teams":', m if m >= 0 else 0)
    info = {}
    if teams_txt:
        found["teams"] = teams_txt[:300]
        try:
            for t in json.loads(teams_txt)[:2]:
                si = t.get("scoreInfo") or ""
                if not si:
                    continue
                si = si if "ov" in si else si + " ov"
                tm = t.get("team") or {}
                for key in ("name", "longName", "abbreviation", "shortName"):
                    if tm.get(key):
                        info[tm[key].lower()] = si
        except Exception as e:  # noqa: BLE001
            found["teams_err"] = repr(e)
    # batters at the crease
    batters = ""
    lp = _balanced(body, '"livePerformance":')
    if lp:
        found["livePerformance"] = lp[:300]
        try:
            bats = json.loads(lp).get("batsmen") or []
            parts = []
            for b in bats[:2]:
                pl = b.get("player") or {}
                name = pl.get("name") or pl.get("longName") or "?"
                star = "*" if b.get("currentType") == 1 or b.get("isStriker") else ""
                parts.append("%s %s%s(%s)" % (name.split()[-1], b.get("runs", "?"), star,
                                               b.get("balls", "?")))
            batters = "   ".join(parts)
        except Exception as e:  # noqa: BLE001
            found["livePerformance_err"] = repr(e)
    status = _string_after(body, '"statusText":')
    cric_debug["found"] = found
    del body
    cric_details[item["id"]] = {"info": info, "batters": batters, "status": status}
    if item["id"] == cric_id:
        cric_detail = cric_details[item["id"]]
        show_rss(item)                 # redraw now with overs + batters
        cric_tick()


# ---- Cricbuzz source (CRICKET_SOURCE = "cricbuzz", the default)
# Each followed match is read from the JSON behind Cricbuzz's own match page:
# score, overs, both batters, the bowler, run rates, recent balls, status.
# The list of matches to pick from comes from the links on its live-scores page.
# match data: the newer mcenter addresses first ("hcomm" serves some leagues "comm" doesn't);
# the old commentary address now often answers with the web page instead of data
CB_MATCH_URLS = ("https://www.cricbuzz.com/api/mcenter/comm/%s",
                 "https://www.cricbuzz.com/api/mcenter/hcomm/%s",
                 "https://www.cricbuzz.com/api/cricket-match/commentary/%s")
CB_LIST_URL = "https://www.cricbuzz.com/cricket-match/live-scores"
CB_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
          "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
          "Referer": "https://www.cricbuzz.com/"}


def _cb_get(url, cap):
    """Body of a Cricbuzz page as text (at most `cap` bytes), and the HTTP status."""
    parts, size = [], 0
    with requests.get(url, headers=CB_HDR, timeout=NET_TIMEOUT) as r:
        status = r.status_code
        if status == 200:
            for chunk in r.iter_content(chunk_size=4096):
                parts.append(chunk)
                size += len(chunk)
                if size >= cap:
                    break
    body = _text(b"".join(parts))
    del parts
    return status, body


def _cb_slug_title(slug):
    """'ind-vs-aus-3rd-t20i-australia-tour-of-india-2026' -> 'IND vs AUS 3rd T20I Australia tour of India 2026'."""
    words = [w for w in slug.split("-") if w]
    out = []
    for n, w in enumerate(words):
        near_vs = "vs" in words[max(0, n - 1):n + 2] and w != "vs"
        if w == "vs" or w in ("of", "the", "and", "in"):
            out.append(w)
        elif near_vs or w in ("odi", "t20i", "t20", "t10", "wt20i", "wodi"):
            out.append(w.upper())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)[:90]


def _cb_links(buf, items, seen):
    """Pick /live-cricket-scores/<id>/<slug> links out of `buf` into `items`.
    Returns where to keep reading from (an unfinished link stays for the next chunk)."""
    key = "/live-cricket-scores/"
    i, done = 0, 0
    while len(items) < 40:
        i = buf.find(key, i)
        if i < 0:
            break
        j = i + len(key)
        gt = buf.find(">", j)
        if gt < 0:                       # the tag goes on in the next chunk
            return max(0, i - 1500)
        k = j
        while k < len(buf) and buf[k].isdigit():
            k += 1
        mid, slug = buf[j:k], ""
        if buf[k:k + 1] == "/":
            e = k + 1
            while e < gt and buf[e] not in "\"'?#< >\\":
                e += 1
            slug = buf[k + 1:e]
        i, done = gt, gt
        if not mid or mid in seen:
            continue
        seen.add(mid)
        a = buf.rfind("<a", 0, j)        # the link's title="..." if it has one
        title = ""
        if a >= 0 and gt - a < 1500:
            t = buf.find('title="', a, gt)
            if t >= 0:
                title = buf[t + 7:buf.find('"', t + 7, gt)]
        title = _tagless(title).replace(" - Live Cricket Score, Commentary", "").strip()
        items.append({"id": mid, "title": title or _cb_slug_title(slug) or ("Match " + mid),
                      "link": "https://www.cricbuzz.com/live-cricket-scores/%s/%s" % (mid, slug)})
    return max(done, len(buf) - 1600)


def cb_list():
    """Matches on Cricbuzz's live-scores page (live, recent and coming up):
    [{"id", "title", "link"}]. The page is read in small pieces, never whole."""
    items, seen, tail, size = [], set(), "", 0
    with requests.get(CB_LIST_URL, headers=CB_HDR, timeout=NET_TIMEOUT) as r:
        status = r.status_code
        cric_debug["list_status"] = status
        if status != 200:
            raise RuntimeError("Cricbuzz list HTTP %d" % status)
        t0 = time.monotonic()
        for chunk in r.iter_content(chunk_size=4096):
            dog()
            size += len(chunk)
            buf = tail + _text(chunk)
            tail = buf[_cb_links(buf, items, seen):]
            if size > 1200000 or len(items) >= 40 or time.monotonic() - t0 > 15:
                break
    cric_debug["list_bytes"] = size
    cric_debug["list_found"] = len(items)
    return items


def _cb_overs(o):
    """Cricbuzz overs 18.3 -> '18.3', 19.6 -> '20' (it uses .6 for a finished over)."""
    try:
        o = float(o)
    except (TypeError, ValueError):
        return ""
    whole = int(o)
    balls = int(round((o - whole) * 10))
    if balls >= 6:
        whole, balls = whole + 1, 0
    return ("%d.%d" % (whole, balls)) if balls else ("%d" % whole)


def _cb_bat(b):
    if not b or not b.get("batName"):
        return ""
    return "%s %s(%s)" % (b["batName"].split()[-1], b.get("batRuns", 0), b.get("batBalls", 0))


def _cb_json(url):
    """Read one Cricbuzz data address in small pieces and pull out its "matchHeader" and
    "miniscore" objects (as text), stopping as soon as both are in - the long commentary
    list that comes with them is never kept. Anything that isn't JSON isn't read at all."""
    want = {'"matchHeader":': None, '"miniscore":': None}
    buf, size, first = "", 0, ""
    t0 = time.monotonic()
    with requests.get(url, headers=CB_HDR, timeout=NET_TIMEOUT) as r:
        status = r.status_code
        ctype = (r.headers.get("content-type") or "").lower()
        if status != 200 or "json" not in ctype:
            return status, ctype, None, None, 0, ""
        for chunk in r.iter_content(chunk_size=4096):
            dog()
            size += len(chunk)
            buf += _text(chunk)
            if not first:
                first = buf[:120]
            keep = len(buf) - 40                     # a key cut in two waits for the next piece
            for key in want:
                if want[key] is not None:
                    continue
                at = buf.find(key)
                if at < 0:
                    continue
                j = at + len(key)
                while j < len(buf) and buf[j] in " \r\n\t":
                    j += 1
                if j < len(buf) and buf[j] not in "{[":
                    want[key] = "{}"                 # null: not there for this match
                    continue
                obj = _balanced(buf, key, at)
                if obj is not None:
                    want[key] = obj
                elif len(buf) - at > 150000:
                    want[key] = "{}"                 # far too big: give up on it
                else:
                    keep = min(keep, at)             # not finished yet: keep it
            if (want['"matchHeader":'] is not None and want['"miniscore":'] is not None) or \
                    size > 600000 or time.monotonic() - t0 > 12:
                break                                # got both, or too big / too slow: stop here
            buf = buf[max(0, keep):]
    return status, ctype, want['"matchHeader":'], want['"miniscore":'], size, first


def cb_parse(mid, head_txt, mini_txt):
    """The bits of Cricbuzz's match data the screen needs."""
    import json
    head = json.loads(head_txt or "{}") or {}
    mini = json.loads(mini_txt or "{}") or {}
    teams = []
    for k in ("team1", "team2"):
        t = head.get(k) or {}
        teams.append((t.get("id"), t.get("name") or "?", (t.get("shortName") or t.get("name") or "?")[:5].upper()))
    state = head.get("state") or (mini.get("matchScoreDetails") or {}).get("state") or ""
    inns = []
    for s in (mini.get("matchScoreDetails") or {}).get("inningsScoreList") or []:
        w = s.get("wickets", 0) or 0
        txt = ("%s" % s.get("score", 0)) if w >= 10 else "%s/%s%s" % (s.get("score", 0), w,
                                                                     "d" if s.get("isDeclared") else "")
        inns.append((s.get("inningsId", 0), s.get("batTeamId"), txt, _cb_overs(s.get("overs"))))
    inns.sort(key=lambda x: x[0] or 0)
    bat = (mini.get("batTeam") or {}).get("teamId")
    if not inns and bat is not None and (mini.get("batTeam") or {}).get("teamScore") is not None:
        bt = mini["batTeam"]
        w = bt.get("teamWkts", 0) or 0
        inns.append((mini.get("inningsId", 1), bat, ("%s" % bt["teamScore"]) if w >= 10 else
                     "%s/%s" % (bt["teamScore"], w), _cb_overs(mini.get("overs"))))
    striker = _cb_bat(mini.get("batsmanStriker"))
    other = _cb_bat(mini.get("batsmanNonStriker"))
    batters = "   ".join([p for p in (striker.replace("(", "*(", 1) if striker else "", other) if p])
    b = mini.get("bowlerStriker") or {}
    bowler = ("%s %s-%s-%s-%s" % (b["bowlName"].split()[-1], _cb_overs(b.get("bowlOvs")), b.get("bowlMaidens", 0),
                                  b.get("bowlRuns", 0), b.get("bowlWkts", 0))) if b.get("bowlName") else ""
    rates = []
    if mini.get("currentRunRate"):
        rates.append("CRR %.2f" % float(mini["currentRunRate"]))
    if mini.get("requiredRunRate"):
        rates.append("RRR %.2f" % float(mini["requiredRunRate"]))
    st = state.lower()
    return {"id": mid, "state": state, "matchEnded": st in ("complete", "abandon", "abandoned", "no result"),
            "started": st not in ("preview", "upcoming", "toss", ""),
            "title": "%s v %s, %s" % (teams[0][1], teams[1][1], head.get("matchDescription") or ""),
            "format": (head.get("matchFormat") or "").upper(), "status": head.get("status") or mini.get("status") or "",
            "teams": teams, "inns": inns, "bat": bat, "batters": batters, "bowler": bowler,
            "rates": "  ".join(rates), "recent": (mini.get("recentOvsStats") or "").strip(),
            "last": mini.get("lastWicket") or ""}


cb_err = {}             # id -> why the last Cricbuzz read failed
cb_src = {}             # id -> which of CB_MATCH_URLS last had its data


def cb_fetch(mid):
    """Read one followed match from Cricbuzz and redraw."""
    now = time.monotonic()
    cric_detail_at[mid] = now                      # tried now, even if it fails
    order = list(range(len(CB_MATCH_URLS)))
    if mid in cb_src:                              # the address that worked last time first
        order.remove(cb_src[mid])
        order.insert(0, cb_src[mid])
    tried, d, why = [], None, ""
    for k in order:
        url = CB_MATCH_URLS[k] % mid
        status, ctype, head_t, mini_t, size, first = _cb_json(url)
        note = {"url": url, "status": status, "type": ctype, "bytes": size, "start": first,
                "matchHeader": bool(head_t and head_t != "{}"), "miniscore": bool(mini_t and mini_t != "{}")}
        tried.append(note)
        if head_t and head_t != "{}":
            try:
                d = cb_parse(mid, head_t, mini_t)
            except Exception as e:  # noqa: BLE001
                note["parse_error"] = repr(e)
            if d:
                cb_src[mid] = k
                break
        why = ("HTTP %d" % status) if status != 200 else ("a web page, not data" if "json" not in ctype
                                                           else "no score in the reply")
    cric_debug.clear()
    cric_debug["tried"] = tried
    cb_err.pop(mid, None)
    if d:
        cric_items[mid] = d
        cric_debug["parsed"] = d
        if d["matchEnded"]:
            cric_gone.setdefault(mid, now)
        else:
            cric_gone.pop(mid, None)
    else:                       # blocked, down or changed: keep the match, say why, retry
        cb_err[mid] = why or "no answer"
    if now - cric_gone.get(mid, now) > CRIC_GONE_SECS and mid in cric_ids:
        cric_ids.remove(mid)
        for dct in (cric_details, cric_detail_at, cric_gone, cric_items):
            dct.pop(mid, None)
        cric_save()
    cric_render()
    if not d:
        raise RuntimeError("Cricbuzz match %s: %s" % (mid, cb_err[mid]))


def cb_due(now, on_screen):
    """The followed match most in need of a refresh (None if none is due).
    The one on screen goes first when it has never been read."""
    if cric_id in cric_ids and cric_id not in cric_detail_at:
        return cric_id
    best, best_age = None, 0.0
    for mid in cric_ids:
        d = cric_items.get(mid)
        age = now - cric_detail_at.get(mid, -1e9)
        if mid in cb_err:
            need = 45
        elif d and d["matchEnded"]:
            need = 600
        elif d and not d["started"]:
            need = 300
        elif on_screen:
            need = 20 if mid == cric_id else 30
        else:
            need = CRIC_EVERY * 4
        if age > need and age > best_age:
            best, best_age = mid, age
    return best


def show_cb(d):
    """Draw a Cricbuzz match on the cricket screen (both looks)."""
    global cric_ended
    cric_ended = d["matchEnded"]
    st = d["state"].lower()
    lbl_ctype.text = d["format"] or "CRICBUZZ"
    if cric_ended:
        lbl_clive.text, lbl_clive.color = "RESULT", GREYS[5]
    elif st == "in progress":
        lbl_clive.text, lbl_clive.color = "LIVE", RED
    elif d["started"]:
        lbl_clive.text, lbl_clive.color = d["state"].upper()[:9], GREYS[5]   # STUMPS, TEA, INNINGS...
    else:
        lbl_clive.text, lbl_clive.color = "UPCOMING", GREYS[5]
    for i, (tid, name, short) in enumerate(d["teams"]):
        mine = [x for x in d["inns"] if x[1] == tid]
        batting = tid is not None and tid == d["bat"] and not cric_ended and d["started"]
        cric_team[i].text = short
        cric_score[i].text = " & ".join(x[2] for x in mine) or "-"
        cric_overs[i].text = (("%s ov" % mine[-1][3]) if mine and mine[-1][3] else name[:24]) + \
            ("  BATTING" if batting else "")
        cric_team[i].color = cric_score[i].color = GREYS[0] if batting else GREYS[3]
        th_team(i, name, batting)
    lbl_cname.text = (d["batters"] or d["title"])[:52]
    parts = [d["status"], d["rates"], ("Bowler " + d["bowler"]) if d["bowler"] else "",
             ("Recent " + d["recent"]) if d["recent"] else "", ("Last wkt " + d["last"]) if d["last"] else ""]
    t = time.localtime()
    cric_ticker.set("#" + "  #".join(p for p in parts if p) +
                    "  #Updated %02d:%02d:%02d  #Data: Cricbuzz" % (t.tm_hour, t.tm_min, t.tm_sec))



# ------------------------------------------------------------- news
NEWS_URL = os.getenv("NEWS_FEED") or "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
NEWS_EVERY = 15 * 60
news_items = []           # [(headline, source)]
news_page = 0
news_at = ""
news_from = "Google News"
news_msg = "Loading headlines..."
NEWS_SECONDS = max(2, int(cfg("NEWS_SECONDS") or "6"))
NEWS_PER_VISIT = max(1, int(cfg("NEWS_PER_VISIT") or "10"))
_ASCII = (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'), ("–", "-"),
          ("—", "-"), ("…", "..."), ("₹", "Rs "), (" ", " "), ("&#39;", "'"),
          ("&quot;", '"'), ("&amp;", "&"))


def plain(t):
    for a, b in _ASCII:
        t = t.replace(a, b)
    return "".join(ch for ch in t if 32 <= ord(ch) < 127)


def wrap2(t, width=48):
    """Split a headline into at most two lines of `width` characters."""
    if len(t) <= width:
        return t, ""
    cut = t.rfind(" ", 0, width + 1)
    cut = cut if cut > 10 else width
    first, rest = t[:cut], t[cut:].strip()
    if len(rest) > width:
        rest = rest[:width - 3].rstrip() + "..."
    return first, rest


NEWS_FALLBACKS = (
    "https://www.thehindu.com/news/national/feeder/default.rss",
    "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
)


def _text(bs):
    """Decode bytes as UTF-8 without ever raising."""
    try:
        return bs.decode("utf-8")
    except Exception:  # noqa: BLE001 - fall back to plain ASCII
        return "".join(chr(c) if c < 128 else " " for c in bs)


def _read_items(url, limit=20):
    """Stream an RSS feed in small chunks and stop after `limit` items,
    so a big feed never has to fit in memory at once."""
    hdr = {"User-Agent": "Mozilla/5.0 (T-Display-S3 desk dashboard; RSS reader)",
           "Accept": "application/rss+xml, application/xml, text/xml"}
    items, buf = [], b""
    with requests.get(url, headers=hdr, timeout=NET_TIMEOUT) as r:
        if r.status_code != 200:
            raise RuntimeError("HTTP %d" % r.status_code)
        for chunk in r.iter_content(chunk_size=2048):
            buf += chunk if isinstance(chunk, bytes) else chunk.encode()
            while True:
                a = buf.find(b"<item")
                b = buf.find(b"</item>", a + 1) if a >= 0 else -1
                if b < 0:
                    if a > 0:
                        buf = buf[a:]          # drop everything before the next item
                    elif a < 0 and len(buf) > 4096:
                        buf = buf[-200:]       # channel header etc.
                    break
                part, buf = _text(buf[a:b]), buf[b + 7:]
                title = plain(_tag(part, "title"))
                src = plain(_tag(part, "source"))
                if src and title.endswith(" - " + src):
                    title = title[:-(len(src) + 3)]
                elif not src and " - " in title and "google" in url:
                    title, src = title.rsplit(" - ", 1)
                if not src:
                    src = "The Hindu" if "thehindu" in url else (
                        "Times of India" if "indiatimes" in url else "")
                if title:
                    items.append((title.strip(), src.strip()))
            if len(items) >= limit:
                break
    return items


def get_news():
    global news_items, news_at, news_page, news_from, news_msg
    errors = []
    net_err = None
    for url in (NEWS_URL,) + NEWS_FALLBACKS:
        try:
            items = _read_items(url, NEWS_COUNT)[:NEWS_COUNT]
        except Exception as e:  # noqa: BLE001
            if _net_error(e):
                net_err = e
            errors.append("%s: %s" % (url.split("/")[2], repr(e)[:40]))
            print("news failed:", errors[-1])
            free_sockets()
            continue
        if items:
            news_items, news_page = items, 0
            news_from = ("Google News" if "google" in url else
                         "The Hindu" if "thehindu" in url else
                         "Times of India" if "indiatimes" in url else url.split("/")[2])
            t = time.localtime()
            news_at = "%02d:%02d" % (t.tm_hour, t.tm_min)
            show_news()
            return
        errors.append("%s: no headlines" % url.split("/")[2])
    if not news_items:
        news_msg = ("News failed: " + errors[0])[:60] if errors else "No headlines right now"
        show_news()
    print("news errors:", errors)
    if net_err is not None:
        raise net_err                  # every source failed and the network looks down


def _put_lines(labels, font, rows, pitch):
    top = NEWS_TOP + (NEWS_BOT - NEWS_TOP - pitch * len(rows)) // 2
    for i, lbl in enumerate(labels):
        lbl.text = rows[i] if i < len(rows) else ""
        lbl.anchored_position = (NEWS_X, top + i * pitch)


def show_news():
    """One big headline at a time, with a progress bar of all of them."""
    n = len(news_items)
    k = news_page % n if n else 0
    for i, seg in enumerate(news_seg):
        seg.color_index = SEG_COLS[0] if (n and i == k) else (SEG_COLS[1] if i < n else SEG_COLS[2])
    if not n:
        lbl_ncount.text = ""
        _put_lines(news_med, F_NEWS2, [], 22)
        _put_lines(news_big, F_NEWS, wrap_px(F_NEWS, news_msg, NEWS_W, 4)[0], 27)
        lbl_nsrc.text = lbl_nfoot.text = ""
        return
    title, src = news_items[k]
    rows, fits = wrap_px(F_NEWS, title, NEWS_W, 4)
    if fits:
        _put_lines(news_med, F_NEWS2, [], 22)
        _put_lines(news_big, F_NEWS, rows, 27)
    else:
        rows, _ = wrap_px(F_NEWS2, title, NEWS_W, 5)
        _put_lines(news_big, F_NEWS, [], 27)
        _put_lines(news_med, F_NEWS2, rows, 22)
    lbl_ncount.text = "%d/%d" % (k + 1, n)
    lbl_nsrc.text = src[:28].upper()
    lbl_nfoot.text = "%s, updated %s" % (news_from, news_at)


def market_open():
    t = time.localtime()
    mins = t.tm_hour * 60 + t.tm_min
    return t.tm_wday < 5 and 9 * 60 + 10 <= mins <= 15 * 60 + 35


def free_sockets():
    """Close finished HTTPS connections so the login page has sockets/RAM."""
    try:
        adafruit_connection_manager.connection_manager_close_all(pool)
    except Exception:  # noqa: BLE001
        pass


net_state = "ok"           # "ok", "nowifi" (Wi-Fi lost) or "noinet" (Wi-Fi fine, internet down)
fail_streak = 0
need_probe = False
refresh_all = False


def _net_error(e):
    """True for errors that smell like 'no network' rather than a bad reply."""
    if isinstance(e, (OSError, getattr(adafruit_requests, "OutOfRetries", OSError))):
        return True
    n = type(e).__name__.lower()
    return "timeout" in n or "connection" in n or "gaierror" in n


ERRLOG = []                 # recent problems, shown on http://<board>:8080/debug


def log_err(msg):
    t = time.localtime()
    line = "%02d:%02d:%02d %s" % (t.tm_hour, t.tm_min, t.tm_sec, msg)
    print(line)
    ERRLOG.append(line[:300])
    del ERRLOG[:-30]


def safe(fn, name, free=True):
    global fail_streak, need_probe
    if net_state != "ok":       # offline: skip instead of freezing on a doomed request
        return False
    dog()
    try:
        fn()
        fail_streak = 0
        return True
    except Exception as e:  # noqa: BLE001 - keep the dashboard running
        log_err("%s failed: %r" % (name, e))
        free_sockets()          # a broken connection: start fresh next time
        if _net_error(e):
            fail_streak += 1
            if fail_streak >= 2:
                need_probe = True   # two network errors in a row: is the internet down?
        return False
    finally:
        dog()
        if free:
            free_sockets()


def internet_ok():
    dog()
    try:
        with requests.get(PROBE_URL, timeout=5) as r:
            return r.status_code in (200, 204)
    except Exception as e:  # noqa: BLE001
        print("internet check failed:", repr(e))
        return False
    finally:
        free_sockets()
        dog()


# offline badge, one per screen (bottom-left; on the clock screen under the day bar)
net_badges = []
for _name, _grp in ALL_SCREENS.items():
    _bx, _by = (182, 153) if _name == "clock" else (6, 148)
    _g = displayio.Group()
    _g.append(RoundRect(_bx, _by, 62, 16, 4, fill=0xC62828))
    _l = Label(terminalio.FONT, text="OFFLINE", color=0xFFFFFF, anchor_point=(0.5, 0.5),
               anchored_position=(_bx + 31, _by + 8))
    _g.append(_l)
    _g.hidden = True
    _grp.append(_g)
    net_badges.append((_g, _l))


def show_badge(msg):
    for g, lbl in net_badges:
        lbl.text = msg or "OFFLINE"
        g.hidden = not msg


offline_since = 0.0
last_reconnect = last_probe = 0.0
reconnect_wait = 10


def set_offline(state, now_m):
    global net_state, offline_since, reconnect_wait
    if net_state == "ok":
        offline_since = now_m
    net_state = state
    reconnect_wait = 10
    show_badge("NO WI-FI" if state == "nowifi" else "OFFLINE")
    net_note("down")
    print("network:", state)


def back_online():
    """Wi-Fi/internet is back: restart the web page if needed and refresh everything."""
    global net_state, fail_streak, refresh_all, MY_IP
    ip = str(wifi.radio.ipv4_address)
    try:                        # the old listening socket died with the Wi-Fi link
        server.stop()
    except Exception:  # noqa: BLE001
        pass
    try:
        server.start(ip, port=LOGIN_PORT)
    except Exception as e:  # noqa: BLE001
        print("web page restart failed:", repr(e))
    if ip != MY_IP:
        print("new IP address:", ip)
        MY_IP = ip
    free_sockets()
    net_state = "ok"
    fail_streak = 0
    refresh_all = True
    show_badge(None)
    net_note("up")
    print("network: back online at", ip)


def net_tick(now_m):
    """Every few seconds: notice outages, reconnect Wi-Fi, check the internet."""
    global need_probe, last_probe, last_reconnect, reconnect_wait, fail_streak
    if not wifi_up():
        if net_state != "nowifi":
            set_offline("nowifi", now_m)
        if now_m - last_reconnect > reconnect_wait:
            last_reconnect = now_m
            reconnect_wait = min(60, reconnect_wait * 2)    # 10 s, 20 s, 40 s, then every minute
            if wifi_try(8):
                back_online()
                return
        if now_m - offline_since > 20 * 60:     # Wi-Fi stack stuck? a clean restart fixes it
            print("no Wi-Fi for 20 min - restarting")
            microcontroller.reset()
        return
    if net_state == "nowifi":                   # Wi-Fi came back by itself
        back_online()
        return
    if need_probe or (net_state == "noinet" and now_m - last_probe > 30):
        need_probe = False
        last_probe = now_m
        if internet_ok():
            fail_streak = 0
            if net_state != "ok":
                back_online()
        elif net_state != "noinet":
            set_offline("noinet", now_m)


# ------------------------------------------------------------- login web page
# Fix for adafruit_httpserver: if a browser opens a connection and closes it
# without sending anything (Chrome "preconnects" do this), recv returns 0 bytes
# and the library loops forever, freezing the whole board. Stop on 0 bytes.
def _recv_headers(self, sock):
    got = b""
    while b"\r\n\r\n" not in got and len(got) < 8192:
        try:
            n = sock.recv_into(self._buffer, len(self._buffer))
        except Exception:  # noqa: BLE001 - timeout or reset
            break
        if not n:
            break
        got += self._buffer[:n]
    return got


def _recv_body(self, sock, got, length):
    while len(got) < length:
        try:
            n = sock.recv_into(self._buffer, len(self._buffer))
        except Exception:  # noqa: BLE001
            break
        if not n:
            break
        got += self._buffer[:n]
    return got[:length]


Server._receive_header_bytes = _recv_headers
Server._receive_body_bytes = _recv_body

server = Server(pool, debug=False)

PAGE = """<!doctype html><html><head><meta name=viewport content="width=device-width">
<title>T-Display</title><style>body{font-family:sans-serif;background:#111;color:#ddd;
padding:24px}a{display:inline-block;background:#387ed1;color:#fff;padding:14px 22px;
border-radius:8px;text-decoration:none;font-size:18px}</style></head><body>
<h2>Zerodha login</h2><p>%s</p>%s</body></html>"""


def unquote(s):
    """Decode %xx escapes and '+' from a URL query value."""
    b = s.replace("+", " ").encode()
    out = bytearray()
    i = 0
    while i < len(b):
        if b[i] == 37 and i + 2 < len(b):
            try:
                out.append(int(b[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out.append(b[i])
        i += 1
    return out.decode()


def find_token(url):
    """Pull request_token out of a pasted Kite redirect address."""
    key = "request_token="
    i = url.find(key)
    if i < 0:
        return None
    tok = url[i + len(key):].split("&")[0].split("#")[0].strip()
    return tok or None


@server.route("/")
def home(request: Request):
    if not KITE_KEY or not KITE_SECRET:
        body = PAGE % ("Add KITE_API_KEY and KITE_API_SECRET to settings.toml first.", "")
    else:
        # Kite hands redirect_params back to the redirect page, which uses
        # "board" to send the login straight back to this board.
        link = ('<a href="https://kite.zerodha.com/connect/login?v=3&api_key=%s'
                '&redirect_params=board%%3D%s%%3A%d">Log in to Kite</a>'
                % (KITE_KEY, MY_IP, LOGIN_PORT))
        form = ('<p style="margin-top:32px">Redirect page didn\'t bring you back? '
                'Copy the full address from the page Kite sent you to and paste it here:</p>'
                '<form action="/kite"><input name=url style="width:100%%;padding:10px">'
                '<p><button style="padding:10px 18px">Send to board</button></p></form>')
        body = PAGE % ("Status: " + kite_status, link + form)
    body = body.replace("</body>", '<p style="margin-top:32px"><a href="/todo">To-do list</a> '
                        '<a href="/stocks">My stocks</a> <a href="/ask">Ask AI</a> <a href="/settings">Settings</a></p>'
                        '<p style="margin-top:16px"><a href="/cricket" '
                        'style="background:#444">Cricket matches</a></p>'
                        '<p style="margin-top:16px"><a href="/rotate?on=%d" style="background:#444">'
                        'Auto-rotate screens: %s (tap to turn %s)</a></p>'
                        '<p style="margin-top:16px"><a href="/theme" style="background:#444">'
                        'Look: %s (change)</a></p>'
                        '<p style="margin-top:16px"><a href="/pet" style="background:#444">Pet</a> '
                        '<a href="/stat/debug" style="background:#444">Stat feed</a> '
                        '<a href="/debug" style="background:#444">Debug</a></p></body>'
                        % (0 if auto_rotate else 1, "ON" if auto_rotate else "OFF",
                           "off" if auto_rotate else "on", THEME.upper()))
    return Response(request, body, content_type="text/html")


@server.route("/rotate")
def rotate_page(request: Request):
    global auto_rotate, last_switch
    on = request.query_params.get("on", safe=False)
    if on in ("0", "1"):
        CFG["AUTO_ROTATE"] = "on" if on == "1" else "off"
        try:
            save_cfg()
        except Exception:  # noqa: BLE001
            pass
        auto_rotate = on == "1" and SCREEN_SECONDS > 0
        last_switch = time.monotonic()
    msg = ("Auto-rotate is ON: screens change every %d s (the KEY button still works)." % SCREEN_SECONDS
           if auto_rotate else
           "Auto-rotate is OFF: screens change only when you press the KEY button.")
    link = '<a href="/rotate?on=%d">Turn %s</a> &nbsp; <a href="/" style="background:#444">Back</a>' % (
        0 if auto_rotate else 1, "off" if auto_rotate else "on")
    return Response(request, PAGE.replace("Zerodha login", "Screens") % (msg, link),
                    content_type="text/html")


@server.route("/theme")
def theme_page(request: Request):
    global reboot_at
    name = request.query_params.get("name", safe=False)
    if name in ("aura", "classic", "default"):
        try:
            microcontroller.nvm[0] = {"aura": 1, "classic": 2, "default": 0}[name]
            reboot_at = time.monotonic() + 2
            msg = ("Switching to %s. The board restarts in a few seconds."
                   % ("the THEME in settings.toml" if name == "default" else name.upper()))
        except Exception as e:  # noqa: BLE001
            msg = "Couldn't save the choice: %s" % e
    else:
        msg = "Current look: %s%s" % (THEME.upper(), " (chosen here)" if THEME_FROM_WEB
                                      else " (from settings.toml)")
    links = ('<a href="/theme?name=aura">Aura</a> &nbsp; <a href="/theme?name=classic">Classic</a>'
             ' &nbsp; <a href="/theme?name=default" style="background:#444">Use settings.toml</a>'
             ' &nbsp; <a href="/" style="background:#444">Back</a>')
    return Response(request, PAGE.replace("Zerodha login", "Look") % (msg, links),
                    content_type="text/html")


@server.route("/pet")
def pet_page(request: Request):
    if request.query_params.get("feed", safe=False) == "1":
        pet_screen.feed(time.monotonic())
        msg = "Fed %s. Yum!" % PET_NAME
    else:
        h = pet_screen.hours_hungry()
        msg = ("%s hasn't been fed yet." % PET_NAME if not pet_screen.born else
               "%s was fed %s ago (%d meals so far)." % (PET_NAME, _ago(h * 3600), pet_screen.meals))
    return Response(request, PAGE.replace("Zerodha login", PET_NAME) %
                    (msg, '<a href="/pet?feed=1">Feed %s</a> &nbsp; <a href="/" '
                          'style="background:#444">Back</a>' % PET_NAME),
                    content_type="text/html")


@server.route("/debug")
def debug_page(request: Request):
    import gc
    gc.collect()
    try:
        rssi = wifi.radio.ap_info.rssi
    except Exception:  # noqa: BLE001
        rssi = "?"
    info = [
        "Board: %s:%d, Wi-Fi %s dBm, network %s, up %s, free memory %d KB" % (
            MY_IP, LOGIN_PORT, rssi, net_state, _ago(time.monotonic()),
            getattr(gc, "mem_free", lambda: 0)() // 1024),
        "Speed test: " + net_screen.speed_log,
        "Router uptime: " + net_screen.upnp_log,
        "Stat of the day: " + stat_screen.debug.replace("\n", " | ")[:400],
        "",
        "Recent problems (newest last):",
    ] + (ERRLOG or ["none"])
    return Response(request, PAGE.replace("Zerodha login", "Debug") %
                    ("Send a screenshot of this page if something isn't working.",
                     "<pre style='white-space:pre-wrap;font-size:12px'>%s</pre>"
                     '<p><a href="/debug">Refresh</a> &nbsp; <a href="/" style="background:#444">Back</a></p>'
                     % esc("\n".join(info))),
                    content_type="text/html")


@server.route("/stat/debug")
def stat_debug(request: Request):
    p = stat_screen.player()
    return Response(request, PAGE.replace("Zerodha login", "Stat of the day") %
                    ("Player: %s" % (esc(p[1]) if p else "none set"),
                     "<pre style='white-space:pre-wrap'>%s</pre>" % esc(stat_screen.debug)),
                    content_type="text/html")


# ------------------------------------------------------------- settings page
SCREEN_LABELS = {"weather": "Weather", "portfolio": "Portfolio", "heatmap": "Holdings heatmap",
                 "markets": "Markets", "cricket": "Cricket", "stat": "Stat of the day",
                 "news": "News", "trivia": "Trivia", "net": "Internet", "pet": "Pet", "todo": "To-do", "stocks": "My stocks", "ask": "Ask AI",
                 "clock": "Big clock", "matrix": "Matrix rain", "fire": "Fire", "stars": "Starfield"}
RESTART_KEYS = ("WEATHER_TOWN", "WEATHER_LAT", "WEATHER_LON", "TRIVIA_SOURCE", "PET_NAME", "NEWS_COUNT")
force_show = None            # the loop switches to this screen on its next pass


def _num(v, lo, hi, default, is_float=False):
    try:
        x = float(v) if is_float else int(float(v))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, x))


def set_order(names):
    """Use a new screen order straight away (and move off a screen that was turned off)."""
    global ORDER, screen, force_show
    cur = ORDER[screen] if 0 <= screen < len(ORDER) else None
    ORDER = parse_order(",".join(names))
    if cur in ORDER:
        screen = ORDER.index(cur)
    else:
        screen = 0
        force_show = ORDER[0]


def apply_cfg():
    """Apply everything that can change without a restart."""
    global SCREEN_SECONDS, auto_rotate, NIGHT, DAY_BRIGHT, NIGHT_BRIGHT, NIGHT_SCREEN, \
        NEWS_SECONDS, NEWS_PER_VISIT, TRIVIA_SECONDS, CRIC_TEAM, STAT_PLAYERS, STAT_CLASS, PING_HOST
    SCREEN_SECONDS = _num(cfg("SCREEN_SECONDS") or "15", 3, 3600, 15)
    auto_rotate = (cfg("AUTO_ROTATE") or "on").strip().lower() not in ("off", "0", "no", "false")
    NIGHT = parse_night(cfg("NIGHT_HOURS"))
    DAY_BRIGHT = _num(cfg("DAY_BRIGHTNESS") or "0.6", 0.02, 1.0, 0.6, True)
    NIGHT_BRIGHT = _num(cfg("NIGHT_BRIGHTNESS") or "0.05", 0.01, 1.0, 0.05, True)
    set_brightness(NIGHT_BRIGHT if night_now else DAY_BRIGHT)
    NIGHT_SCREEN = (cfg("NIGHT_SCREEN") or "clock").strip().lower()
    NEWS_SECONDS = _num(cfg("NEWS_SECONDS") or "6", 2, 120, 6)
    NEWS_PER_VISIT = _num(cfg("NEWS_PER_VISIT") or "10", 1, 50, 10)
    TRIVIA_SECONDS = _num(cfg("TRIVIA_SECONDS") or "30", 5, 300, 30)
    TriviaScreen.dwell = TRIVIA_SECONDS + TRIVIA_REVEAL + 1
    CRIC_TEAM = (cfg("CRICKET_TEAM") or "").lower()
    STAT_PLAYERS = parse_players(cfg("STAT_PLAYERS"))
    STAT_CLASS = cfg("STAT_CLASS") or "11"
    stat_screen.refresh()
    PING_HOST = cfg("PING_HOST") or "1.1.1.1"
    net_screen.ping_lbl.text = "PING " + PING_HOST
    set_order(parse_order(cfg("SCREEN_ORDER")))


SET_PAGE = """<!doctype html><html><head><meta name=viewport content="width=device-width">
<title>Dashboard settings</title><style>
body{font-family:sans-serif;background:#111;color:#ddd;padding:16px;max-width:560px;margin:auto}
h2{margin:4px 0 12px}h3{margin:22px 0 8px;color:#8ab4f8;font-size:15px;text-transform:uppercase}
a{color:#8ab4f8}.row{display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid #222}
.row .name{flex:1}.pill{padding:4px 10px;border-radius:12px;text-decoration:none;font-size:13px;color:#fff}
.on{background:#1e9e50}.off{background:#555}.arr{text-decoration:none;font-size:18px;padding:0 6px}
.show{font-size:13px}label{display:block;margin:10px 0}
input,select{background:#222;color:#eee;border:1px solid #444;border-radius:6px;padding:8px;font-size:15px}
input[type=number]{width:90px}input[type=text]{width:100%%;box-sizing:border-box}
input[type=checkbox]{transform:scale(1.4);margin-right:10px}
button{background:#387ed1;color:#fff;border:0;border-radius:8px;padding:12px 18px;font-size:16px;margin:16px 8px 0 0}
.note{background:#2a2a14;border-left:4px solid #e0b020;padding:10px;margin:10px 0}
small{color:#888}</style></head><body><h2>Dashboard settings</h2>%s</body></html>"""


def _opt(options, cur):
    return "".join('<option value="%s"%s>%s</option>' % (v, " selected" if str(v) == str(cur) else "", t)
                   for v, t in options)


def settings_html(msg=""):
    out = ['<div class=note>%s</div>' % msg] if msg else []
    out.append('<p><a href="/">&larr; Back</a> &nbsp; <a href="/stocks">Pick My stocks</a> &nbsp; '
               '<a href="/todo">To-do list</a></p><h3>Screens</h3>'
               '<small>Tap ON/OFF to include a screen, arrows to reorder, "show" to jump to it.</small>')
    for i, n in enumerate(ORDER):
        out.append('<div class=row><a class="pill on" href="/settings/screen?n=%s&op=off">ON</a>'
                   '<span class=name>%d. %s</span>'
                   '<a class=arr href="/settings/screen?n=%s&op=up">&#9650;</a>'
                   '<a class=arr href="/settings/screen?n=%s&op=down">&#9660;</a>'
                   '<a class=show href="/settings/screen?n=%s&op=show">show</a></div>'
                   % (n, i + 1, SCREEN_LABELS.get(n, n), n, n, n))
    for n in ALL_SCREENS:
        if n not in ORDER:
            out.append('<div class=row><a class="pill off" href="/settings/screen?n=%s&op=on">OFF</a>'
                       '<span class=name>%s</span></div>' % (n, SCREEN_LABELS.get(n, n)))
    hours = [(h, "%02d:00" % h) for h in range(24)]
    nf, nt = NIGHT if NIGHT else (23, 7)
    v = lambda k, d="": esc(str(cfg(k) if cfg(k) is not None else d))  # noqa: E731
    out.append('<form action="/settings/save">')
    out.append('<h3>Rotation</h3>'
               '<label><input type=checkbox name=AUTO_ROTATE value=on%s>Change screens automatically</label>'
               '<label>Seconds per screen <input type=number name=SCREEN_SECONDS min=3 max=3600 value=%d></label>'
               % (" checked" if auto_rotate else "", SCREEN_SECONDS))
    out.append('<h3>Night mode</h3>'
               '<label><input type=checkbox name=NIGHT_ON value=1%s>Dim night screen</label>'
               '<label>From <select name=NIGHT_FROM>%s</select> to <select name=NIGHT_TO>%s</select></label>'
               '<label>Night screen <select name=NIGHT_SCREEN>%s</select></label>'
               '<label>Night brightness <input type=number step=0.01 min=0.01 max=1 name=NIGHT_BRIGHTNESS value=%s></label>'
               '<small>KEY still wakes the other screens for a minute at night.</small>'
               % (" checked" if NIGHT else "", _opt(hours, nf), _opt(hours, nt),
                  _opt((("clock", "Analog clock"), ("matrix", "Matrix rain"), ("fire", "Fire"),
                        ("stars", "Starfield"), ("cycle", "A different one each hour")), NIGHT_SCREEN),
                  NIGHT_BRIGHT))
    out.append('<h3>Look</h3>'
               '<label>Theme <select name=THEME>%s</select> <small>(restarts the board)</small></label>'
               '<label>Day brightness <input type=number step=0.05 min=0.05 max=1 name=DAY_BRIGHTNESS value=%s></label>'
               % (_opt((("aura", "Aura"), ("classic", "Classic")), THEME), DAY_BRIGHT))
    out.append('<h3>News</h3>'
               '<label>Seconds per headline <input type=number name=NEWS_SECONDS min=2 max=120 value=%d></label>'
               '<label>Headlines per visit <input type=number name=NEWS_PER_VISIT min=1 max=50 value=%d></label>'
               '<label>Headlines to cycle through <input type=number name=NEWS_COUNT min=1 max=15 value=%d>'
               ' <small>(restart)</small></label>' % (NEWS_SECONDS, NEWS_PER_VISIT, NEWS_COUNT))
    out.append('<h3>Trivia</h3>'
               '<label>Seconds to answer <input type=number name=TRIVIA_SECONDS min=5 max=300 value=%d></label>'
               '<label>Questions <select name=TRIVIA_SOURCE>%s</select> <small>(restart)</small></label>'
               % (TRIVIA_SECONDS, _opt((("india", "India (trivia_india.txt)"), ("world", "World (Open Trivia DB)"),
                                       ("mix", "Mix of both")), TRIVIA_SOURCE)))
    out.append('<h3>Cricket</h3>'
               '<label>Follow these teams automatically <input type=text name=CRICKET_TEAM value="%s"'
               ' placeholder="e.g. India, Mumbai Indians"></label>'
               '<small>Comma separated. Pick any other matches at <a href="/cricket">/cricket</a>.</small>'
               '<label>Stat of the day players <input type=text name=STAT_PLAYERS value="%s"></label>'
               '<small>Cricinfo id:Name, add :bowl for bowlers, comma separated.</small>'
               '<label>Stats from <select name=STAT_CLASS>%s</select></label>'
               % (v("CRICKET_TEAM"), v("STAT_PLAYERS", STAT_DEFAULT),
                  _opt((("11", "All internationals"), ("1", "Tests"), ("2", "ODIs"), ("3", "T20Is")),
                       STAT_CLASS)))
    out.append('<h3>Weather</h3>'
               '<label>Town <input type=text name=WEATHER_TOWN value="%s"></label>'
               '<label>Latitude <input type=text name=WEATHER_LAT value="%s" style="width:120px">'
               ' Longitude <input type=text name=WEATHER_LON value="%s" style="width:120px"></label>'
               '<small>Change the town and leave the numbers alone to look them up. Needs a restart.</small>'
               % (esc(TOWN), esc(LAT), esc(LON)))
    out.append('<h3>Other</h3>'
               '<label>Pet name <input type=text name=PET_NAME value="%s" maxlength=10> <small>(restart)</small></label>'
               '<label>Internet screen pings <input type=text name=PING_HOST value="%s" style="width:140px"></label>'
               % (esc(PET_NAME), esc(PING_HOST)))
    out.append('<button name=go value=save>Save</button><button name=go value=restart>Save and restart</button>'
               '</form><h3>Reset</h3><p><a href="/settings/reset">Forget everything set here and use '
               'settings.toml again</a></p><p><a href="/debug">Debug info (recent errors)</a></p>')
    return SET_PAGE % "".join(out)


def _page(request, html):
    return Response(request, html, content_type="text/html")


def _back(request, msg=""):
    return _page(request, '<!doctype html><meta http-equiv="refresh" content="0;url=/settings">%s' % esc(msg))


@server.route("/settings")
def settings_route(request: Request):
    return _page(request, settings_html())


@server.route("/settings/screen")
def settings_screen(request: Request):
    global force_show
    n = request.query_params.get("n", safe=False)
    op = request.query_params.get("op", safe=False)
    order = list(ORDER)
    if n in ALL_SCREENS:
        if op == "on" and n not in order:
            order.append(n)
        elif op == "off" and n in order and len(order) > 1:
            order.remove(n)
        elif op in ("up", "down") and n in order:
            i = order.index(n)
            j = i - 1 if op == "up" else i + 1
            if 0 <= j < len(order):
                order[i], order[j] = order[j], order[i]
        elif op == "show" and n in order:
            force_show = n
            return _back(request)
        CFG["SCREEN_ORDER"] = ",".join(order)
        save_cfg()
        set_order(order)
    return _back(request)


def geocode(town):
    """Town name -> (lat, lon) via Open-Meteo's free geocoder."""
    q = "".join(c if c.isalpha() or c.isdigit() else "%%%02X" % ord(c) for c in town)
    with requests.get("https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&name=" + q,
                      timeout=NET_TIMEOUT) as r:
        res = (r.json().get("results") or [None])[0]
    free_sockets()
    if not res:
        raise ValueError("no place called '%s'" % town)
    return "%.4f" % res["latitude"], "%.4f" % res["longitude"]


@server.route("/settings/save")
def settings_save(request: Request):
    global reboot_at
    q = request.query_params

    def g(k):
        val = q.get(k, safe=False)
        return None if val is None else unquote(val).strip()

    notes, restart = [], []
    CFG["AUTO_ROTATE"] = "on" if g("AUTO_ROTATE") else "off"
    CFG["SCREEN_SECONDS"] = str(_num(g("SCREEN_SECONDS"), 3, 3600, SCREEN_SECONDS))
    CFG["NIGHT_HOURS"] = ("%d-%d" % (_num(g("NIGHT_FROM"), 0, 23, 23), _num(g("NIGHT_TO"), 0, 23, 7))
                          if g("NIGHT_ON") else "")
    if g("NIGHT_SCREEN") in ("clock", "matrix", "fire", "stars", "cycle"):
        CFG["NIGHT_SCREEN"] = g("NIGHT_SCREEN")
    CFG["NIGHT_BRIGHTNESS"] = "%.2f" % _num(g("NIGHT_BRIGHTNESS"), 0.01, 1, NIGHT_BRIGHT, True)
    CFG["DAY_BRIGHTNESS"] = "%.2f" % _num(g("DAY_BRIGHTNESS"), 0.02, 1, DAY_BRIGHT, True)
    CFG["NEWS_SECONDS"] = str(_num(g("NEWS_SECONDS"), 2, 120, NEWS_SECONDS))
    CFG["NEWS_PER_VISIT"] = str(_num(g("NEWS_PER_VISIT"), 1, 50, NEWS_PER_VISIT))
    CFG["NEWS_COUNT"] = str(_num(g("NEWS_COUNT"), 1, 15, NEWS_COUNT))
    CFG["TRIVIA_SECONDS"] = str(_num(g("TRIVIA_SECONDS"), 5, 300, TRIVIA_SECONDS))
    if g("TRIVIA_SOURCE") in ("india", "world", "mix"):
        CFG["TRIVIA_SOURCE"] = g("TRIVIA_SOURCE")
    if g("STAT_CLASS") in ("1", "2", "3", "11"):
        CFG["STAT_CLASS"] = g("STAT_CLASS")
    for k in ("CRICKET_TEAM", "STAT_PLAYERS", "PING_HOST"):
        if g(k) is not None:
            CFG[k] = g(k)
    if g("PET_NAME"):
        CFG["PET_NAME"] = g("PET_NAME")[:10]
    town, lat, lon = g("WEATHER_TOWN") or TOWN, g("WEATHER_LAT") or "", g("WEATHER_LON") or ""
    if town != TOWN and (lat, lon) in ((LAT, LON), ("", "")):
        try:
            lat, lon = geocode(town)
            notes.append("Found %s at %s, %s." % (esc(town), lat, lon))
        except Exception as e:  # noqa: BLE001
            notes.append("Couldn't look up %s (%s) - enter its latitude and longitude." % (esc(town), esc(repr(e))))
            lat, lon = LAT, LON
    CFG["WEATHER_TOWN"], CFG["WEATHER_LAT"], CFG["WEATHER_LON"] = town, lat or LAT, lon or LON
    # what only takes effect after a restart
    now_vals = {"WEATHER_TOWN": TOWN, "WEATHER_LAT": LAT, "WEATHER_LON": LON, "TRIVIA_SOURCE": TRIVIA_SOURCE,
                "PET_NAME": PET_NAME, "NEWS_COUNT": str(NEWS_COUNT)}
    restart = [k for k in RESTART_KEYS if str(CFG.get(k, now_vals[k])) != str(now_vals[k])]
    theme = g("THEME")
    if theme in THEMES and theme != THEME:
        try:
            microcontroller.nvm[0] = THEMES.index(theme) + 1
            restart.append("THEME")
        except Exception as e:  # noqa: BLE001
            notes.append("Couldn't save the theme: %s" % esc(repr(e)))
    try:
        save_cfg()
    except Exception as e:  # noqa: BLE001
        return _page(request, settings_html("Couldn't save: %s" % esc(repr(e))))
    apply_cfg()
    if g("go") == "restart":
        reboot_at = time.monotonic() + 2
        notes.append("Saved. The board restarts in a few seconds - reload this page in about 20 seconds.")
    elif restart:
        notes.append("Saved. These take effect after a restart: %s. "
                     '<a href="/settings/restart">Restart now</a>' % ", ".join(
                         k.replace("_", " ").lower() for k in restart))
    else:
        notes.append("Saved - already applied.")
    return _page(request, settings_html(" ".join(notes)))


@server.route("/settings/restart")
def settings_restart(request: Request):
    global reboot_at
    reboot_at = time.monotonic() + 2
    return _page(request, SET_PAGE % "<p>Restarting... reload in about 20 seconds.</p>"
                 '<p><a href="/settings">Back to settings</a></p>')


@server.route("/settings/reset")
def settings_reset(request: Request):
    global reboot_at, CFG
    if request.query_params.get("sure", safe=False) != "1":
        return _page(request, SET_PAGE % ('<p>This forgets every setting changed on this page (and the theme '
                                          'choice) and goes back to settings.toml. The board restarts.</p>'
                                          '<p><a href="/settings/reset?sure=1">Yes, reset</a> &nbsp; '
                                          '<a href="/settings">Cancel</a></p>'))
    CFG = {k: v for k, v in CFG.items() if k == "STOCK_PICKS"}     # picks live on /stocks
    try:
        save_cfg()
        microcontroller.nvm[0] = 0
    except Exception as e:  # noqa: BLE001
        return _page(request, settings_html("Couldn't reset: %s" % esc(repr(e))))
    reboot_at = time.monotonic() + 2
    return _page(request, SET_PAGE % "<p>Reset. Restarting... reload in about 20 seconds.</p>")



# ------------------------------------------------------------- to-do page
def esc_attr(t):
    return esc(t).replace('"', "&quot;")


def _todo_find(i):
    for k, t in enumerate(todo_screen.items):
        if t[0] == i:
            return k
    return -1


def todo_html(msg="", edit=None):
    items = todo_screen.shown()
    out = ['<div class=note>%s</div>' % msg] if msg else []
    out.append('<p><a href="/">&larr; Back</a> &nbsp; <a href="/todo/do?op=show">Show on the board</a></p>'
               '<form action="/todo/add" class=add>'
               '<input type=text name=t maxlength=80 placeholder="Add a task..." autofocus required>'
               '<div class=opts><select name=p><option value=0>Normal</option><option value=1>High priority'
               '</option></select> <input type=date name=d> <button>Add</button></div></form>')
    open_n = sum(1 for t in items if not t[2])
    out.append('<h3>%s</h3>' % ("%d to do" % open_n if open_n else ("All done!" if items else "No tasks yet")))
    for t in items:
        i, txt, done, high, due = t[:5]
        if edit == i:
            out.append('<form action="/todo/do" class="row edit"><input type=hidden name=op value=save>'
                       '<input type=hidden name=id value=%d><input type=text name=t maxlength=80 value="%s">'
                       '<div class=opts><select name=p>%s</select> <input type=date name=d value="%s"> '
                       '<button>Save</button> <a href="/todo">Cancel</a></div></form>'
                       % (i, esc_attr(txt), _opt(((0, "Normal"), (1, "High priority")), 1 if high else 0),
                          esc_attr(due)))
            continue
        d_txt, d_col = due_label(due) if not done else ("", 0)
        out.append(
            '<div class=row><a class="chk%s" href="/todo/do?op=toggle&id=%d">%s</a>'
            '<span class="name%s">%s%s</span>%s'
            '<a class=arr href="/todo/do?op=up&id=%d">&#9650;</a>'
            '<a class=arr href="/todo/do?op=down&id=%d">&#9660;</a>'
            '<a class=arr href="/todo?edit=%d">&#9998;</a>'
            '<a class="arr del" href="/todo/do?op=del&id=%d">&#10005;</a></div>'
            % (" done" if done else "", i, "&#10003;" if done else "",
               " done" if done else "", '<b class=hi>!</b> ' if high and not done else "", esc(txt),
               ('<span class=due style="color:#%06x">%s</span>' % (d_col or 0x8A9099, d_txt)) if d_txt else "",
               i, i, i, i))
    if any(t[2] for t in items) or open_n > 1:
        out.append('<p class=tools>')
        if open_n > 1:
            out.append('<a href="/todo/do?op=sort">Sort by priority and due date</a> &nbsp; ')
        if any(t[2] for t in items):
            out.append('<a href="/todo/do?op=clear">Clear done tasks</a>')
        out.append('</p>')
    out.append('<p><small>Tip: phone shortcuts can add tasks with http://%s:%d/todo/add?t=Buy+milk'
               '</small></p>' % (MY_IP, LOGIN_PORT))
    page = SET_PAGE.replace("Dashboard settings</title>", "To-do</title>").replace(
        "<h2>Dashboard settings</h2>", "<h2>To-do</h2>").replace("</style>", TODO_CSS + "</style>")
    return page % "".join(out)


TODO_CSS = (".add input[type=text]{font-size:17px;padding:10px}.opts{margin-top:8px;display:flex;gap:8px;"
            "flex-wrap:wrap;align-items:center}.opts button{margin:0}"
            ".chk{width:24px;height:24px;border:2px solid #8b7cf6;border-radius:6px;display:inline-flex;"
            "align-items:center;justify-content:center;text-decoration:none;color:#fff;flex:none}"
            ".chk.done{background:#8b7cf6}.name.done{color:#777;text-decoration:line-through}"
            ".hi{color:#ff5a5a}.due{font-size:13px;white-space:nowrap}.del{color:#e57373}"
            ".row.edit{display:block}.tools a{font-size:14px}")


@server.route("/todo")
def todo_page(request: Request):
    e = request.query_params.get("edit", safe=False)
    return _page(request, todo_html(edit=int(e) if e and e.isdigit() else None))


@server.route("/todo.json")
def todo_json(request: Request):
    items = todo_screen.shown()
    return Response(request, json.dumps([{"id": t[0], "text": t[1], "done": bool(t[2]), "high": bool(t[3]),
                                          "due": t[4]} for t in items]), content_type="application/json")


def _todo_fields(q):
    def g(k):
        v = q.get(k, safe=False)
        return "" if v is None else unquote(v).strip()
    due = g("d")
    if due and not (len(due) == 10 and due[4] == "-" and due[7] == "-" and
                    due.replace("-", "").isdigit()):
        due = ""
    return g("t")[:80], 1 if g("p") == "1" else 0, due


@server.route("/todo/add")
def todo_add(request: Request):
    txt, high, due = _todo_fields(request.query_params)
    msg = ""
    if txt:
        items = todo_screen.items
        new_id = max([t[0] for t in items] or [0]) + 1
        items.append([new_id, txt, 0, high, due])
        try:
            todo_screen.changed()
            msg = "Added."
        except Exception as e:  # noqa: BLE001
            items.pop()
            msg = "Couldn't add: %s" % esc(str(e))
    return _page(request, todo_html(msg))


@server.route("/todo/do")
def todo_do(request: Request):
    global force_show
    q = request.query_params
    op = q.get("op", safe=False)
    sid = q.get("id", safe=False)
    i = _todo_find(int(sid)) if sid and sid.isdigit() else -1
    items = todo_screen.items
    if op == "show":
        force_show = "todo"
        return _page(request, '<!doctype html><meta http-equiv="refresh" content="0;url=/todo">')
    if op == "toggle" and i >= 0:
        items[i][2] = 0 if items[i][2] else 1
    elif op == "del" and i >= 0:
        items.pop(i)
    elif op in ("up", "down") and i >= 0:
        same = [k for k, t in enumerate(items) if t[2] == items[i][2]]   # move among open (or done) tasks
        pos = same.index(i) + (-1 if op == "up" else 1)
        if 0 <= pos < len(same):
            j = same[pos]
            items[i], items[j] = items[j], items[i]
    elif op == "save" and i >= 0:
        txt, high, due = _todo_fields(q)
        if txt:
            items[i][1], items[i][3], items[i][4] = txt, high, due
    elif op == "clear":
        items[:] = [t for t in items if not t[2]]
    elif op == "sort":
        items.sort(key=lambda t: (t[2], 0 if t[3] else 1, t[4] or "9999-99-99"))
    try:
        todo_screen.changed()
    except Exception as e:  # noqa: BLE001
        return _page(request, todo_html("Couldn't save: %s" % esc(str(e))))
    return _page(request, '<!doctype html><meta http-equiv="refresh" content="0;url=/todo">')


# ------------------------------------------------------------- Ask AI page
ASK_CSS = ("textarea{width:100%%;box-sizing:border-box;font-size:17px;padding:10px;background:#1c1c1c;"
           "color:#eee;border:1px solid #444;border-radius:8px;font-family:inherit}"
           ".q{color:#8ab4f8;margin:14px 0 4px}.a{font-size:17px;line-height:1.45;white-space:pre-wrap}")


def ask_html(msg=""):
    out = ['<div class=note>%s</div>' % msg] if msg else []
    out.append('<p><a href="/">&larr; Back</a> &nbsp; <a href="/ask/do?op=show">Show on the board</a></p>')
    if not GEMINI_KEY:
        out.append('<div class=note>Add <b>GEMINI_API_KEY = "your key"</b> to settings.toml on the board, '
                   'then restart it. The key is never shown on these pages.</div>')
    out.append('<form action="/ask/go"><textarea name=q rows=3 maxlength=300 placeholder="Ask anything - '
               'the answer stays on the board until you ask again" autofocus></textarea>'
               '<p><button>Ask</button> <small>Answers are kept short to fit the screen. '
               'Takes a few seconds.</small></p></form>')
    if ask_screen.a:
        out.append('<h3>On the board now</h3><div class=q>&gt; %s</div><div class=a>%s</div>'
                   '<p><small>%s &middot; %s &middot; <a href="/ask/do?op=clear">clear</a></small></p>'
                   % (esc(ask_screen.q), esc(ask_screen.a), esc(ask_screen.when), esc(gemini_model())))
    page = SET_PAGE.replace("Dashboard settings</title>", "Ask AI</title>").replace(
        "<h2>Dashboard settings</h2>", "<h2>Ask AI</h2>").replace("</style>", ASK_CSS + "</style>")
    return page % "".join(out)


@server.route("/ask")
def ask_page(request: Request):
    return _page(request, ask_html())


@server.route("/ask/go")
def ask_go(request: Request):
    global force_show
    q = request.query_params.get("q", safe=False)
    q = " ".join(unquote(q).split())[:300] if q else ""
    if not q:
        return _page(request, ask_html())
    if not GEMINI_KEY:
        return _page(request, ask_html("No Gemini key on the board yet."))
    a = None
    try:
        for attempt in (1, 2):
            dog()
            free_sockets()          # the secure connection to Google needs the memory that
            gc.collect()            # connections kept open to other sites are holding
            try:
                a = ask_gemini(q)
                break
            except OSError as e:    # e.g. MBEDTLS_ERR_X509_FATAL_ERROR: try once more, clean
                if attempt == 2:
                    raise
                log_err("ask: %r, free %d - retrying" % (e, getattr(gc, "mem_free", lambda: 0)()))
    except Exception as e:  # noqa: BLE001
        log_err("ask failed: %r" % (e,))
        free_sockets()
        return _page(request, ask_html("That didn't work: %s<br>The board still shows the last answer."
                                       % esc(str(e))))
    try:
        ask_screen.set(q, a)
    except Exception as e:  # noqa: BLE001 - shown anyway, just not kept over a restart
        log_err("saving the answer failed: %r" % (e,))
    if _screen_on("ask", "weather"):
        try:
            save_cfg()
        except Exception:  # noqa: BLE001
            pass
    force_show = "ask"
    return _page(request, ask_html())


@server.route("/ask/do")
def ask_do(request: Request):
    global force_show
    op = request.query_params.get("op", safe=False)
    if op == "show" and ask_screen.a:
        _screen_on("ask", "weather")
        force_show = "ask"
    elif op == "clear":
        ask_screen.set("", "")
    return _page(request, '<!doctype html><meta http-equiv="refresh" content="0;url=/ask">')


# ------------------------------------------------------------- My stocks page
def urlq(s):
    """Percent-encode a link value (M&M -> M%26M)."""
    out = []
    for c in s:
        if "A" <= c <= "Z" or "a" <= c <= "z" or "0" <= c <= "9" or c in "-_.":
            out.append(c)
        else:
            out.append("".join("%%%02X" % b for b in c.encode()))
    return "".join(out)


def _stock_line(r):
    """'20 @ 2,450.00 · LTP 2,912.40 · ▲ +32.30 (+1.12%) today · P&L +₹9,248 (+18.9%)'."""
    _key, sym, prod, qty, avg, ltp, close, pnl, pnl_pct, _day = r
    chg = ltp - close if close else 0.0
    pct = chg / close * 100 if close else 0.0
    cls = "up" if chg > 0 else ("dn" if chg < 0 else "flat")
    arrow = "&#9650;" if chg > 0 else ("&#9660;" if chg < 0 else "&ndash;")
    return ('%d @ %s &middot; LTP <b>%s</b> &middot; <span class=%s>%s %s (%+.2f%%) today</span> '
            '&middot; P&amp;L <span class=%s>%s (%+.1f%%)</span>'
            % (qty, price(avg), price(ltp), cls, arrow, price(chg, True), pct,
               "up" if pnl >= 0 else "dn", inr(pnl, signed=True), pnl_pct))


def _stock_name(key):
    """'NIFTY25NOV24000CE:NRML' -> 'NIFTY25NOV24000CE <tag>NRML</tag>'; holdings stay as they are."""
    sym, _, prod = key.partition(":")
    return "<b>%s</b>%s" % (esc(sym), (" <span class=tag>%s</span>" % esc(prod)) if prod else "")


STOCK_MSGS = {"on": "Turned on the My stocks screen (after Portfolio) - move it in Settings.",
              "full": "The board keeps up to %d stocks." % STOCK_MAX,
              "none": "Pick a stock first - the screen only shows stocks you picked.",
              "err": "Couldn't save - try again."}

STOCK_CSS = (".up{color:#4cd964}.dn{color:#ff5a5a}.flat{color:#999}.del{color:#e57373}"
             ".name small{display:block;margin-top:3px;line-height:1.5}"
             ".pg{color:#8ab4f8;font-size:12px;margin:14px 0 0;text-transform:uppercase}"
             ".tools a{font-size:14px}.add{min-width:56px;text-align:center}"
             ".tag{background:#4a3a10;color:#ffb020;font-size:11px;padding:1px 6px;border-radius:8px;"
             "vertical-align:2px;font-weight:normal}")


def stocks_html(msg=""):
    scr = stocks_screen
    picks = scr.picks
    by = {}
    for r in scr.data or ():
        if r[0] not in by:
            by[r[0]] = r
    out = ['<div class=note>%s</div>' % msg] if msg else []
    out.append('<p><a href="/">&larr; Back</a> &nbsp; <a href="/stocks/do?op=show">Show on the board</a>'
               ' &nbsp; <a href="/settings">Settings</a></p>')
    if scr.data is None:
        out.append('<div class=note>Log in to Kite on the <a href="/">home page</a> to see your '
                   'holdings and positions. The ones you already picked are kept.</div>')
    out.append('<h3>On the board (%d)</h3><small>%d per page; the board flips pages every %d s '
               '(BOOT button: next page).</small>' % (len(picks), STOCK_ROWS, STOCK_PAGE_SECONDS))
    stale = 0
    for k, key in enumerate(picks):
        if len(picks) > STOCK_ROWS and k % STOCK_ROWS == 0:
            out.append('<div class=pg>Page %d</div>' % (k // STOCK_ROWS + 1))
        r = by.get(key)
        if r:
            info = _stock_line(r)
        elif scr.data is None:
            info = ""
        elif ":" in key and pos_cache is None:
            info = "positions not loaded yet"        # Kite's positions call failed: don't call it closed
        else:
            stale += 1
            info = "position closed" if ":" in key else "not in your holdings any more"
        q = urlq(key)
        out.append('<div class=row><span class=name>%s<small>%s</small></span>'
                   '<a class=arr href="/stocks/do?op=up&s=%s">&#9650;</a>'
                   '<a class=arr href="/stocks/do?op=down&s=%s">&#9660;</a>'
                   '<a class="arr del" href="/stocks/do?op=del&s=%s">&#10005;</a></div>'
                   % (_stock_name(key), info, q, q, q))
    if not picks:
        out.append('<p><small>Nothing picked yet - add from your holdings and positions below.</small></p>')
    full = len(picks) >= STOCK_MAX
    rest = [k for k in by if k not in picks]
    if scr.data is not None:
        pos_note = ("Couldn't load positions from Kite - retrying." if pos_cache is None else
                    "None open right now. Intraday, F&amp;O and today's delivery buys show up here.")
        for title, is_pos, none, all_in in (
                ("Your holdings", False, "No holdings.", "All your holdings are on the board."),
                ("Open positions", True, pos_note, "All your open positions are on the board.")):
            keys = sorted(k for k in rest if (":" in k) == is_pos)
            out.append('<h3>%s (%d more)</h3>' % (title, len(keys)))
            for key in keys:
                add = ('<a class="pill on add" href="/stocks/do?op=add&s=%s">+ Add</a>' % urlq(key)) if not full else ""
                out.append('<div class=row>%s<span class=name>%s<small>%s</small></span></div>'
                           % (add, _stock_name(key), _stock_line(by[key])))
            if not keys:
                out.append('<p><small>%s</small></p>'
                           % (all_in if any((":" in k) == is_pos for k in by) else none))
    tools = []
    if rest and not full:
        tools.append('<a href="/stocks/do?op=all">Add all</a>')
    if len(picks) > 1:
        tools.append('<a href="/stocks/do?op=sort">Sort A-Z</a>')
    if stale:
        tools.append('<a href="/stocks/do?op=stale">Remove closed (%d)</a>' % stale)
    if picks:
        tools.append('<a href="/stocks/do?op=clear">Remove all</a>')
    if tools:
        out.append('<p class=tools>%s</p>' % " &nbsp; ".join(tools))
    page = SET_PAGE.replace("Dashboard settings</title>", "My stocks</title>").replace(
        "<h2>Dashboard settings</h2>", "<h2>My stocks</h2>").replace("</style>", STOCK_CSS + "</style>")
    return page % "".join(out)


@server.route("/stocks")
def stocks_page(request: Request):
    m = request.query_params.get("m", safe=False)
    return _page(request, stocks_html(STOCK_MSGS.get(m, "")))


def _stocks_on():
    """Put My stocks in the rotation (after Portfolio) if it isn't there yet."""
    return _screen_on("stocks", "portfolio")


@server.route("/stocks/do")
def stocks_do(request: Request):
    global force_show
    q = request.query_params
    op = q.get("op", safe=False)
    s = q.get("s", safe=False)
    s = unquote(s).strip().upper() if s else ""
    picks = list(stocks_screen.picks)
    keys = [r[0] for r in stocks_screen.data or ()]
    held = sorted(k for k in keys if ":" not in k) + sorted(k for k in keys if ":" in k)
    m = ""
    if op == "show":
        if not picks:
            m = "none"
        else:
            if _stocks_on():
                m = "on"
                try:
                    save_cfg()
                except Exception:  # noqa: BLE001
                    m = "err"
            force_show = "stocks"
        return _page(request, '<!doctype html><meta http-equiv="refresh" content="0;url=/stocks%s">'
                     % ("?m=" + m if m else ""))
    if op == "add" and s in held and s not in picks:
        if len(picks) >= STOCK_MAX:
            m = "full"
        else:
            picks.append(s)
    elif op == "all":
        picks += [h for h in held if h not in picks]
        if len(picks) > STOCK_MAX:
            picks, m = picks[:STOCK_MAX], "full"
    elif op == "del" and s in picks:
        picks.remove(s)
    elif op in ("up", "down") and s in picks:
        i = picks.index(s)
        j = i - 1 if op == "up" else i + 1
        if 0 <= j < len(picks):
            picks[i], picks[j] = picks[j], picks[i]
    elif op == "sort":
        picks.sort()
    elif op == "stale" and stocks_screen.data is not None:
        picks = [k for k in picks if k in keys or (":" in k and pos_cache is None)]
    elif op == "clear":
        picks = []
    if picks != stocks_screen.picks:
        old = stocks_screen.picks
        stocks_screen.set_picks(picks)
        if picks and not old and _stocks_on():
            m = m or "on"
        try:
            save_cfg()
        except Exception:  # noqa: BLE001
            stocks_screen.set_picks(old)
            m = "err"
    return _page(request, '<!doctype html><meta http-equiv="refresh" content="0;url=/stocks%s">'
                 % ("?m=" + m if m else ""))


@server.route("/kite")
def kite_redirect(request: Request):
    q = request.query_params
    tok = q.get("request_token", safe=False)
    if not tok and q.get("url", safe=False):
        tok = find_token(unquote(q.get("url", safe=False)))
    if not tok or q.get("status", safe=False) not in (None, "success"):
        return Response(request, PAGE % ("No login token found - try again.", ""),
                        content_type="text/html")
    try:
        kite_login(tok)
        safe(get_portfolio, "kite")
        msg = "Logged in. The board will show your portfolio until tomorrow morning."
    except Exception as e:  # noqa: BLE001
        msg = "Login failed: %s" % e
    return Response(request, PAGE % (msg, ""), content_type="text/html")


def esc(t):
    return (t or "").replace("&", "&amp;").replace("<", "&lt;")


@server.route("/cricket/debug")
def cricket_debug(request: Request):
    rows = ["<p><b>%s</b><br><code style='word-break:break-all'>%s</code></p>" % (esc(str(k)), esc(str(v)))
            for k, v in cric_debug.items()]
    rows.append("<p><b>shown</b><br><code>%s</code></p>" % esc(str(cric_detail)))
    return Response(request, PAGE.replace("Zerodha login", "Cricket debug") %
                    ("What the board last got for the selected match:",
                     "".join(rows) or "Nothing fetched yet - pick a live match first."),
                    content_type="text/html")


def _screen_on(name, after):
    """Put a screen in the rotation (after `after`) if it isn't there; True if it was added."""
    if name in ORDER:
        return False
    order = list(ORDER)
    order.insert(order.index(after) + 1 if after in order else len(order), name)
    CFG["SCREEN_ORDER"] = ",".join(order)
    set_order(order)
    return True


def _cric_state(m):
    if CRIC_RSS:
        return "live" if "*" in m.get("title", "") else ""
    if CRIC_CB:
        return esc(" - ".join(x for x in (m.get("state"), m.get("status")) if x))
    state = "ended" if m.get("matchEnded") else ("live" if m.get("matchStarted") else "upcoming")
    return "%s - %s" % (state, esc(m.get("status") or ""))


@server.route("/cricket")
def cricket_page(request: Request):
    global cric_id, last_cric, last_cdetail, force_show
    if not CRIC_ON:
        return Response(request, PAGE % ("Add CRICKET_API_KEY to settings.toml first "
                                         "(free key from cricketdata.org).", ""),
                        content_type="text/html")
    q = request.query_params

    def arg(k):
        v = q.get(k, safe=False)
        return unquote(v).strip() if v else ""
    add, rem, show = arg("id"), arg("del"), arg("show")
    try:
        items = cric_feed()
    except Exception as e:  # noqa: BLE001
        return _page(request, SET_PAGE % ('<p><a href="/">&larr; Back</a></p><div class=note>Could not load '
                                          'the matches: %s</div>' % esc(repr(e))))
    feed = {}
    for m in items:
        if m.get("id"):
            feed[m["id"]] = m
    if not CRIC_CB:             # (Cricbuzz keeps its per-match reads in cric_items)
        cric_items.clear()
        cric_items.update(feed)

    def info(mid):              # what we know about a match: its latest read, else its list entry
        return cric_items.get(mid) or feed.get(mid)

    def name(mid):
        m = info(mid)
        return esc(cric_title(m)) if m else "that match"
    msg = ""
    if add == "off":
        for mid in list(cric_ids):
            cric_remove(mid)
        msg = "Not following any match now."
    elif add:
        if add not in feed:
            msg = "That match isn't in the feed any more."
        elif cric_add(add, show=True):
            msg = "Following " + name(add)
            if _screen_on("cricket", "markets"):
                msg += " - and turned the cricket screen on."
        else:
            msg = "The board follows up to %d matches - stop one first." % CRIC_MAX
    elif rem:
        cric_remove(rem)
        msg = "Stopped following " + name(rem)
    elif show and show in cric_ids:
        cric_id = show
        _screen_on("cricket", "markets")
        force_show = "cricket"
        msg = "Showing " + name(show)
    if add or rem or show:
        cric_save()
        last_cric = 0.0 if CRIC_CB else time.monotonic()    # Cricbuzz: read the new match now
        last_cdetail = 0.0             # overs/batters for a new match right away
        if CRIC_CB and add in cric_ids:
            cric_detail_at.pop(add, None)
    cric_update(items)                 # and redraw the board with what we just fetched

    out = ['<div class=note>%s</div>' % msg] if msg else []
    out.append('<p><a href="/">&larr; Back</a> &nbsp; <a href="/settings">Settings</a></p>'
               '<small>Follow up to %d matches. The cricket screen shows each one for %d s '
               '(BOOT: next match) and stays up long enough to show them all.</small>'
               % (CRIC_MAX, CRIC_MATCH_SECONDS))
    out.append('<h3>Following (%d)</h3>' % len(cric_ids))
    for mid in cric_ids:
        m = info(mid)
        state = ("on the board now &middot; " if mid == cric_id and m else "") + (
            _cric_state(m) if m else ("waiting for its first read" if CRIC_CB and mid not in cric_gone else
                                      "left the live feed (finished?) - forgotten after 30 min"))
        out.append('<div class=row><span class=name><b>%s</b><small>%s</small></span>%s'
                   '<a class="arr del" href="/cricket?del=%s">&#10005;</a></div>'
                   % (name(mid) if m else "Match %s" % esc(mid), state,
                      ('<a class=show href="/cricket?show=%s">show</a>' % urlq(mid)) if m else "",
                      urlq(mid)))
    if not cric_ids:
        out.append('<p><small>Not following any match - pick some below.</small></p>')
    rest = [m for m in items if m.get("id") and m["id"] not in cric_ids]
    out.append('<h3>%s (%d)</h3>' % ("Live on Cricinfo" if CRIC_RSS else (
        "On Cricbuzz now (live, recent and next)" if CRIC_CB else "Current matches"), len(rest)))
    full = len(cric_ids) >= CRIC_MAX
    for m in rest:
        out.append('<div class=row>%s<span class=name><b>%s</b><small>%s</small></span></div>'
                   % ('' if full else '<a class="pill on add" href="/cricket?id=%s">+ Follow</a>' % urlq(m["id"]),
                      esc(cric_title(m)), _cric_state(m)))
    if not items:
        out.append('<p><small>No matches in the feed right now.</small></p>')
    if cric_ids:
        out.append('<p class=tools><a href="/cricket?id=off">Stop following all</a></p>')
    if CRIC_TEAM:
        out.append('<p><small>Also following %s automatically (Settings &rarr; Cricket).</small></p>'
                   % esc(CRIC_TEAM.title()))
    if not CRIC_RSS and not CRIC_CB:
        out.append('<p><small>API hits today: %s</small></p>' % esc(cric_hits))
    out.append('<p><small>Scores from %s. <a href="/cricket/debug">What the board last got</a></small></p>'
               % ("Cricbuzz" if CRIC_CB else "ESPNcricinfo" if CRIC_RSS else "CricketData.org"))
    page = SET_PAGE.replace("Dashboard settings</title>", "Cricket</title>").replace(
        "<h2>Dashboard settings</h2>", "<h2>Cricket matches</h2>").replace("</style>", STOCK_CSS + "</style>")
    return _page(request, page % "".join(out))


server.socket_timeout = 1   # don't let idle browser "preconnects" stall the loop
server.start(MY_IP, port=LOGIN_PORT)
print("Kite login page: http://%s:%d" % (MY_IP, LOGIN_PORT))

# ------------------------------------------------------------- buttons
button = digitalio.DigitalInOut(microcontroller.pin.GPIO14)   # the KEY button
button.switch_to_input(pull=digitalio.Pull.UP)
try:                                    # BOOT button: next headline on the news screen
    boot = digitalio.DigitalInOut(microcontroller.pin.GPIO0)
    boot.switch_to_input(pull=digitalio.Pull.UP)
except Exception as e:  # noqa: BLE001 - pin busy on some builds
    print("BOOT button unavailable:", repr(e))
    boot = None
boot_was = True

# ------------------------------------------------------------- start-up
if ORDER[0] in EXTRA:            # draw the first screen now, so it isn't blank while data loads
    try:
        EXTRA[ORDER[0]].enter(time.monotonic())
    except Exception as e:  # noqa: BLE001
        log_err("first screen: %r" % (e,))
if not internet_ok():            # Wi-Fi up but no internet: don't stall on every start-up fetch
    set_offline("noinet", time.monotonic())
weather_ticker.set("Fetching weather for " + TOWN + "...")
safe(get_weather, "weather")
safe(ntp_sync, "ntp")
safe(get_air, "air")
weather_ticker.set("#" + weather_msg + "  " + air_msg + stamp())
if KITE_KEY and KITE_SECRET:
    kite_token = kite_load()
    if kite_token:               # still today's login, kept from before the restart
        kite_status = "Logged in (kept across restart)"
        port_ticker.set("#Restoring today's Kite login...")
        if not safe(get_portfolio, "kite") and kite_token:
            port_ticker.set("#Kite login kept - waiting for the network")
    else:
        show_login_needed("Kite login needed")
else:
    port_ticker.set("#" + kite_status)
if CRIC_TEAM and CRIC_ON and not CRIC_CB:                  # (Cricbuzz: the main loop looks, 10 min in)
    safe(auto_pick, "cricket")
if cric_ids and CRIC_ON and not CRIC_CB and not CRIC_TEAM:    # matches followed before the restart
    safe(get_cricket, "cricket")                              # (Cricbuzz ones are read by the main loop)
if not CRIC_ON:
    cric_ticker.set("#Add CRICKET_API_KEY to settings.toml (free key from cricketdata.org)")
elif not cric_ids:
    cric_ticker.set("#Pick matches at http://%s:%d/cricket" % (MY_IP, LOGIN_PORT))

safe(lambda: get_fmp("us"), "fmp")
safe(get_yahoo_india, "yahoo")
safe(get_news, "news")
clock_minute(time.localtime())

last_weather = last_air = last_ntp = last_kite = last_switch = time.monotonic()
last_cric = last_pick = time.monotonic()
last_cdetail = last_cmatch = 0.0
last_fmp_in = last_fmp_us = time.monotonic()
last_news = last_npage = time.monotonic()
was_showing = None
news_left = 0
reboot_at = 0.0
last_sec = last_min = -1
sec_mark = time.monotonic()
btn_was = True
night_now = False
wake_until = 0.0             # a button press at night shows other screens for a while
last_netcheck = time.monotonic()
loop_errors = []

# ------------------------------------------------------------- main loop
while True:
    try:
        now_m = time.monotonic()
        dog()
        if now_m - last_netcheck > 5:
            last_netcheck = now_m
            net_tick(now_m)
        if refresh_all:              # just back online: refresh every screen now
            refresh_all = False
            last_weather = last_air = last_ntp = last_kite = last_cric = last_pick = -1e6
            last_fmp_in = last_fmp_us = last_news = -1e6
            last_cdetail = 0.0
            for _s in EXTRA_LIST:
                _s.refresh()

        if now_m - last_weather > WEATHER_EVERY:
            last_weather = now_m
            ok = safe(get_weather, "weather")
            counter = (counter + 1) % 100
            lbl_counter.text = str(counter)
            if now_m - last_air > AIR_EVERY:
                last_air = now_m
                safe(get_air, "air")
            if now_m - last_ntp > NTP_EVERY:
                last_ntp = now_m
                safe(ntp_sync, "ntp")
            weather_ticker.set(("#" + weather_msg + "  " + air_msg) if ok
                               else "#Update failed - will retry  " + weather_msg)

        if market_open():
            every = KITE_EVERY_FAST if ORDER[screen] in ("portfolio", "stocks") else KITE_EVERY_OPEN
        else:
            every = KITE_EVERY_CLOSED
        if kite_token and now_m - last_kite > every:
            last_kite = now_m
            # keep the Kite connection open between fast refreshes
            if not safe(get_portfolio, "kite", free=(every > 30)):
                port_ticker.set("#Portfolio update failed - will retry" + stamp())

        if cric_ids and CRIC_CB:
            # Cricbuzz: one match per read; the one on screen every ~20 s, others less often
            on = ORDER[screen] == "cricket"
            if now_m - last_cric > (4 if on else 20):
                due = cb_due(now_m, on)
                if due:
                    last_cric = now_m
                    safe(lambda: cb_fetch(due), "cricket")
        elif cric_ids and CRIC_ON:
            every = CRIC_EVERY if (CRIC_RSS or cric_any_live()) else 15 * 60
            if now_m - last_cric > every:
                last_cric = now_m
                safe(get_cricket, "cricket")       # one feed read covers every followed match
            # overs + batters for the match on screen: a big page, so at most one every 20 s
            if CRIC_RSS and cric_item and now_m - last_cdetail > 20 and \
                    now_m - cric_detail_at.get(cric_id, -1e9) > (60 if ORDER[screen] == "cricket" else 180):
                last_cdetail = now_m
                safe(lambda: get_cricket_detail(cric_item), "cricket detail")
        if CRIC_TEAM and (CRIC_RSS or CRIC_CB or (CRIC_KEY and not cric_any_live())) and \
                now_m - last_pick > (5 if CRIC_RSS else 10 if CRIC_CB else 30) * 60:
            last_pick = now_m            # follow the team's new matches
            safe(auto_pick, "cricket")

        # market indices
        showing = ORDER[screen]
        # India (Yahoo): 1 min while the markets screen is up in market hours
        if market_open():
            every = 60 if showing == "markets" else 600
        else:
            every = 3600
        if now_m - last_fmp_in > every:
            last_fmp_in = now_m
            safe(get_yahoo_india, "yahoo")
        # FMP free plan = 250 calls/day: 12 min while the US market is open, hourly otherwise
        if now_m - last_fmp_us > (12 * 60 if us_market_open() else 3600):
            last_fmp_us = now_m
            safe(lambda: get_fmp("us"), "fmp")

        # news: refresh every 15 min (headline flipping happens next to the screen switching)
        if now_m - last_news > (NEWS_EVERY if news_items else 120):
            last_news = now_m
            safe(get_news, "news")

        # the extra screens refresh their own data (stats, trivia, pings...)
        for _s in EXTRA_LIST:
            _s.tick(now_m)

        # handle a few queued connections per pass (browsers open several at once)
        for _ in range(4):
            try:
                if server.poll() == "no_request":
                    break
            except Exception as e:  # noqa: BLE001
                print("login page error:", repr(e))
                break

        t = time.localtime()

        # night mode: dark, dim clock only (a button press wakes other screens for 60 s)
        night = is_night(t)
        if night != night_now:
            night_now = night
            clock_theme(night)
            set_brightness(NIGHT_BRIGHT if night else DAY_BRIGHT)
            if night:
                screen = ORDER.index("clock") if "clock" in ORDER else screen
                showing = night_name(t)
                display.root_group = ALL_SCREENS[showing]
            else:                       # morning: back to the normal rotation
                display.root_group = ALL_SCREENS[ORDER[screen]]
                showing = ORDER[screen]

        # screen switching: KEY button cycles every screen in SCREEN_ORDER;
        # the automatic rotation skips screens with nothing to show
        pressed = not button.value
        switch = pressed and btn_was
        btn_was = not pressed
        if switch:
            wake_until = now_m + 60
        if force_show:                       # "show" on the Settings page, or a screen turned off
            name, force_show = force_show, None
            if name in ORDER:
                screen = ORDER.index(name)
            display.root_group = ALL_SCREENS[name]
            showing = name
            last_switch = now_m
            wake_until = now_m + 60
            was_showing = None
        boot_down = boot is not None and not boot.value
        boot_press = boot_down and boot_was
        boot_was = not boot_down
        if boot_press and showing in EXTRA:             # BOOT: the screen's own action
            EXTRA[showing].boot(now_m)
        elif boot_press and showing == "cricket":       # BOOT: next followed match
            last_cmatch = now_m
            cric_next()
        # news: next headline every NEWS_SECONDS (or on the BOOT button); with auto-rotate on,
        # the news screen moves on after NEWS_PER_VISIT headlines instead of SCREEN_SECONDS
        news_done = False
        if showing == "news":
            skip = boot_press
            if skip or now_m - last_npage > NEWS_SECONDS:
                last_npage = now_m
                news_page += 1
                news_left -= 1
                if auto_rotate and news_left <= 0 and not skip:
                    news_done = True              # leave; the next visit starts at this headline
                else:
                    show_news()
        if showing == "news":
            auto = auto_rotate and news_done
        else:
            dwell = EXTRA[showing].dwell if showing in EXTRA else (
                cric_dwell() if showing == "cricket" else None)
            auto = auto_rotate and now_m - last_switch > (dwell or SCREEN_SECONDS)
        if night_now and not switch:
            auto = False
            if now_m > wake_until:            # not woken by the button: the night screen
                nname = night_name(t)
                if display.root_group is not ALL_SCREENS[nname]:
                    display.root_group = ALL_SCREENS[nname]
                showing = nname
        if switch or auto:
            last_switch = now_m
            was_showing = None            # (re)entering a screen restarts its news count
            for _ in range(len(ORDER)):
                screen = (screen + 1) % len(ORDER)
                name = ORDER[screen]
                if switch:
                    break
                if name == "cricket" and not cric_ids:
                    continue
                if name == "markets" and not FMP_KEY:
                    continue
                if name in EXTRA and EXTRA[name].skip():
                    continue
                break
            display.root_group = ALL_SCREENS[ORDER[screen]]
            showing = ORDER[screen]
        if showing == "news" and was_showing != "news":
            news_left = min(NEWS_PER_VISIT, max(1, len(news_items)))
            last_npage = now_m
            show_news()
        if showing in EXTRA and was_showing != showing:
            EXTRA[showing].enter(now_m)
        if showing == "cricket":                         # several matches: take turns
            if was_showing != "cricket":
                last_cmatch = now_m
            elif now_m - last_cmatch > CRIC_MATCH_SECONDS:
                last_cmatch = now_m
                cric_next()
        was_showing = showing

        if t.tm_sec != last_sec:
            last_sec = t.tm_sec
            sec_mark = now_m
            hhmm = "%02d:%02d" % (t.tm_hour, t.tm_min)
            lbl_pclock.text = hhmm
            lbl_cclock.text = hhmm
            lbl_mclock.text = hhmm
            lbl_nclock.text = hhmm
            th_second()
            for _s in EXTRA_LIST:
                _s.second(hhmm)
            if t.tm_min != last_min:
                last_min = t.tm_min
                clock_minute(t)

        frac = min(0.99, time.monotonic() - sec_mark)
        if showing == "weather":
            wx_clock.update(t.tm_hour, t.tm_min, t.tm_sec, frac)
        elif showing == "clock":
            big_clock.update(t.tm_hour, t.tm_min, t.tm_sec, frac)
        tk = TICKERS.get(showing)
        if tk:
            tk.step()
        th_frame(showing)
        if showing in EXTRA:
            EXTRA[showing].frame(now_m)
        if reboot_at and now_m > reboot_at:          # theme changed on the web page
            microcontroller.reset()
        time.sleep(0.03)
    except MemoryError as e:
        print("out of memory:", repr(e))
        free_sockets()
        microcontroller.reset()
    except Exception as e:  # noqa: BLE001 - one bad update must not kill the dashboard
        t_err = time.monotonic()
        log_err("loop error: %r" % e)
        loop_errors = [x for x in loop_errors if t_err - x < 60] + [t_err]
        if len(loop_errors) > 10:            # failing over and over: start clean
            print("too many errors - restarting")
            microcontroller.reset()
        time.sleep(0.5)
