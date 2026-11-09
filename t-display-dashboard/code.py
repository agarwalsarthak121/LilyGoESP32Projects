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
#   CRICKET_TEAM="India"  (optional: auto-pick this team's live match)
#   CRICKET_EVERY="300"   (seconds between score updates while a match is live)
#
#   FMP_API_KEY="..."     (free key from financialmodelingprep.com, for the MARKETS screen)
#   SCREEN_ORDER="weather,portfolio,markets,cricket,news"   (add "clock" for the big clock by day)
#   NEWS_FEED="..."       (any RSS feed; default: Google News India top stories)
#   NEWS_COUNT="10"       (how many top headlines to cycle through)
#   NEWS_SECONDS="6"      (how long each headline stays up)
#   NEWS_PER_VISIT="10"   (headlines shown before auto-rotate moves on; "2" = short visits)
#   NIGHT_HOURS="23-7"    (dark, dim clock only at night; "" turns night mode off)
#   DAY_BRIGHTNESS="0.6"  NIGHT_BRIGHTNESS="0.05"
#
# Kite needs a login once a day: open http://<board-ip>:8080 on your phone.
# Pick a cricket match at http://<board-ip>:8080/cricket

import os
import time
import struct
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

try:
    import hashlib
    hashlib.sha256(b"x")
except Exception:  # noqa: BLE001 - fall back to the pure-Python version
    import adafruit_hashlib as hashlib

# ------------------------------------------------------------- settings
TOWN = os.getenv("WEATHER_TOWN") or "Delhi"
LAT = os.getenv("WEATHER_LAT") or "28.61"
LON = os.getenv("WEATHER_LON") or "77.21"
KITE_KEY = os.getenv("KITE_API_KEY") or ""
KITE_SECRET = os.getenv("KITE_API_SECRET") or ""
SCREEN_SECONDS = int(os.getenv("SCREEN_SECONDS") or "15")
auto_rotate = (os.getenv("AUTO_ROTATE") or "on").strip().lower() not in ("off", "0", "no", "false") \
    and SCREEN_SECONDS > 0
CRIC_KEY = os.getenv("CRICKET_API_KEY") or ""
CRIC_TEAM = (os.getenv("CRICKET_TEAM") or "").lower()
# cricket source: "rss" = ESPNcricinfo live-scores feed (free, no key, ~30 s refresh)
#                 "cricapi" = CricketData.org (needs key, 100 hits/day)
CRIC_SOURCE = (os.getenv("CRICKET_SOURCE") or "rss").lower()
CRIC_RSS = CRIC_SOURCE == "rss"
CRIC_EVERY = int(os.getenv("CRICKET_EVERY") or ("30" if CRIC_RSS else "300"))
CRIC_API = "https://api.cricapi.com/v1/"
RSS_URL = "https://static.cricinfo.com/rss/livescores.xml"
LOGIN_PORT = 8080

WEATHER_EVERY = 10 * 60
AIR_EVERY = 30 * 60
NTP_EVERY = 6 * 60 * 60
KITE_EVERY_FAST = int(os.getenv("KITE_EVERY") or "5")   # market hours, portfolio on screen
KITE_EVERY_OPEN = 60          # market hours, other screens showing
KITE_EVERY_CLOSED = 15 * 60   # outside market hours

WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude=" + LAT + "&longitude=" + LON
    + "&current=temperature_2m,relative_humidity_2m,pressure_msl,wind_speed_10m,"
    "weather_code,apparent_temperature"
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

    def __init__(self, x, y, w=166):
        self.W = w
        rrect(x - 4, y - 2, w + 8, 18, 3, 10)
        self.bmp = displayio.Bitmap(self.W, self.H, 2)
        p = displayio.Palette(2)
        p[0] = GREYS[10]
        p[1] = GREYS[1]
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
        half = int((r * r - yy * yy) ** 0.5 + 0.5)
        bitmaptools.fill_region(bmp, cx - half, cy + yy, cx + half + 1, cy + yy + 1, v)


class AnalogClock:
    """Clock face in a bitmap + hour/minute/second hands as vectorio polygons.
    The second hand sweeps smoothly (it's redrawn every frame)."""

    def __init__(self, group, cx, cy, r, numbers=False):
        self.cx, self.cy, self.r = cx, cy, r
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
        self._last = [None, None, None]

    def _hand(self, i, poly, angle, length, width, tail):
        dx, dy = math.sin(angle), -math.cos(angle)
        px, py = -dy, dx                              # perpendicular
        hw, tw = width / 2, max(0.6, width / 5)
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
        self._hand(2, self.second, sec * math.pi / 30, r * 0.88, 2 if r < 60 else 3, r * 0.2)

    def colours(self, face, rim, minor, major, hour, minute, second, numbers=None):
        for i, col in enumerate((face, rim, minor, major)):
            self.fpal[i + 1] = col
        for i, col in enumerate((hour, minute, second, second)):
            self.hpal[i] = col
        for n in self.nums:
            n.color = numbers if numbers is not None else major


# ============================================================= WEATHER SCREEN
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

# ============================================================= PORTFOLIO SCREEN
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

# ============================================================= CRICKET SCREEN
cric_grp = displayio.Group()
root = cric_grp

text(F_TITLE, "CRICKET", 5, 4, GREYS[1])
lbl_ctype = text(F_SMALL, "", 82, 4, GREYS[5])
lbl_clive = text(F_SMALL, "", 82, 15, GREYS[5])
lbl_cclock = text(F_TITLE, "--:--", 315, 4, GREYS[4], right=True)
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

# ============================================================= MARKETS SCREEN
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

# ============================================================= NEWS SCREEN
news_grp = displayio.Group()
root = news_grp

text(F_TITLE, "NEWS", 5, 4, GREYS[1])
lbl_ncount = text(F_TITLE, "", 62, 4, GREYS[5])           # "3/10"
lbl_nclock = text(F_TITLE, "--:--", 315, 4, GREYS[4], right=True)
# progress bar: one segment per headline, the current one lit
NEWS_COUNT = max(1, min(15, int(os.getenv("NEWS_COUNT") or "10")))
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

# ============================================================= ANALOG CLOCK SCREEN
# Big analog clock; also used (dark and dimmed) as the night screen.
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
    if int(72 * frac):
        bitmaptools.fill_region(wx_daybar, 0, 0, int(72 * frac), 3, 1)


clock_theme(False)

# ============================================================= state + helpers
# screens, in the order set by SCREEN_ORDER (comma separated names)
ALL_SCREENS = {"weather": weather_grp, "portfolio": port_grp, "markets": mkt_grp,
               "cricket": cric_grp, "news": news_grp, "clock": clock_grp}
TICKERS = {"weather": weather_ticker, "portfolio": port_ticker, "markets": mkt_ticker,
           "cricket": cric_ticker}
ORDER = [n.strip() for n in (os.getenv("SCREEN_ORDER") or
                             "weather,portfolio,markets,cricket,news").split(",")
         if n.strip() in ALL_SCREENS] or ["weather"]
screen = 0
display.root_group = ALL_SCREENS[ORDER[0]]

# night mode: only the dimmed dark clock between NIGHT_HOURS (e.g. "23-7"; "" = off)
_nh = (os.getenv("NIGHT_HOURS") if os.getenv("NIGHT_HOURS") is not None else "23-7").split("-")
NIGHT = (int(_nh[0]), int(_nh[1])) if len(_nh) == 2 and _nh[0].strip() else None
DAY_BRIGHT = float(os.getenv("DAY_BRIGHTNESS") or "0.6")
NIGHT_BRIGHT = float(os.getenv("NIGHT_BRIGHTNESS") or "0.05")


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


# ------------------------------------------------------------- network
if not wifi.radio.connected:
    wifi.radio.connect(os.getenv("CIRCUITPY_WIFI_SSID"),
                       os.getenv("CIRCUITPY_WIFI_PASSWORD"))
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
    with requests.get(WEATHER_URL, timeout=15) as r:
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


def get_air():
    global air_msg
    with requests.get(AIR_URL, timeout=15) as r:
        cur = r.json()["current"]
    tile_vals[2].text = "%d" % cur["pm2_5"]
    air_msg = "#PM2.5 %d  #PM10 %d  #AQI %d (US)" % (
        cur["pm2_5"], cur["pm10"], cur["us_aqi"])


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
    with requests.post(KITE_API + "/session/token", data=body, timeout=15,
                       headers={"X-Kite-Version": "3",
                                "Content-Type": "application/x-www-form-urlencoded"}) as r:
        d = r.json()
    if d.get("status") != "success":
        raise RuntimeError(d.get("message", "login failed"))
    kite_token = d["data"]["access_token"]
    kite_status = "Logged in"


def show_login_needed(reason):
    global kite_token, kite_status
    kite_token = None
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


def get_portfolio():
    with requests.get(KITE_API + "/portfolio/holdings", headers=kite_headers(),
                      timeout=20) as r:
        status = r.status_code
        d = r.json()
    if status == 403 or d.get("error_type") == "TokenException":
        show_login_needed("Kite session expired")
        return
    if d.get("status") != "success":
        raise RuntimeError(d.get("message", "holdings failed"))

    invested = current = day = 0.0
    movers = []
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
    total = current - invested

    lbl_day.text = inr(day, signed=True)
    lbl_day.color = GREEN if day >= 0 else RED
    base = current - day
    lbl_day_pct.text = "%+.2f%%" % (day / base * 100 if base else 0)
    lbl_day_pct.color = lbl_day.color
    lbl_tot.text = inr(total, signed=True)
    lbl_tot.color = GREEN if total >= 0 else RED
    lbl_tot_pct.text = "%+.2f%%" % (total / invested * 100 if invested else 0)
    lbl_tot_pct.color = lbl_tot.color
    port_tiles[0].text = inr(invested)
    port_tiles[1].text = inr(current)
    port_tiles[2].text = "%d" % len(movers)

    movers.sort()
    parts = ["%s %+.1f%%" % (s, p) for p, s in reversed(movers[-3:]) if p > 0]
    parts += ["%s %+.1f%%" % (s, p) for p, s in movers[:3] if p < 0]
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
        with requests.get(FMP_URL % (ix["fmp"].replace("^", "%5E"), FMP_KEY), timeout=20) as r:
            d = r.json()
        q = d[0] if isinstance(d, list) and d else None
        if not q or "price" not in q:
            msg = d.get("Error Message") if isinstance(d, dict) else "no data"
            problems.append("%s: %s" % (ix["name"], (msg or "no data")[:70]))
            mkt_chg[i].text = "no data from FMP"
            mkt_chg[i].color = GREYS[6]
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
            with requests.get(YAHOO_URL % ix["yahoo"], headers=YAHOO_HDR, timeout=20) as r:
                status = r.status_code
                d = r.json() if status == 200 else {}
            meta = d["chart"]["result"][0]["meta"]
            last = meta["regularMarketPrice"]
            prev = meta.get("chartPreviousClose") or meta.get("previousClose") or last
        except Exception as e:  # noqa: BLE001
            why = ("HTTP %s" % status) if status not in (None, 200) else repr(e)[:40]
            problems.append("%s: Yahoo %s" % (ix["name"], why))
            mkt_chg[i].text = "no data (Yahoo)"
            mkt_chg[i].color = GREYS[6]
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
cric_id = None          # match being shown
cric_ended = False
cric_hits = ""


def cric_get(path):
    global cric_hits
    url = CRIC_API + path + ("&" if "?" in path else "?") + "apikey=" + CRIC_KEY
    with requests.get(url, timeout=20) as r:
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
    cric_ticker.set("#%s  #%s  #API hits today %s" % (
        m.get("status") or "", m.get("venue") or "", cric_hits) + stamp())


def get_cricket():
    if cric_id and CRIC_RSS:
        get_cricket_rss()
    elif cric_id:
        show_match(cric_get("match_info?id=" + cric_id))


def auto_pick():
    """If CRICKET_TEAM is set, pick that team's current match."""
    global cric_id
    if CRIC_RSS:
        items = rss_items()
        for it in items:
            if CRIC_TEAM in it["title"].lower():
                cric_id = it["id"]
                get_cricket_rss(items)
                return
        return
    for m in cric_get("currentMatches?offset=0"):
        names = " ".join(m.get("teams") or []).lower()
        if CRIC_TEAM in names and not m.get("matchEnded"):
            cric_id = m["id"]
            show_match(m)
            return


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
    with requests.get(RSS_URL, headers=hdr, timeout=15) as r:
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
    lbl_clive.text, lbl_clive.color = ("LIVE", RED) if any_bat else ("", GREYS[5])
    lbl_cname.text = cric_detail.get("batters") or (names[0] + " v " + names[1])[:52]


cric_others = ""


def cric_tick():
    t = time.localtime()
    head = ("#" + cric_detail["status"] + "  ") if cric_detail.get("status") else ""
    cric_ticker.set("%s#Updated %02d:%02d:%02d  %s  #Data: ESPNcricinfo" % (
        head, t.tm_hour, t.tm_min, t.tm_sec, cric_others))


def get_cricket_rss(items=None):
    global cric_ended, cric_item, cric_others
    items = items or rss_items()
    mine = [it for it in items if it["id"] == cric_id]
    others = ["#" + it["title"].replace(" *", "*") for it in items if it["id"] != cric_id][:6]
    if mine:
        cric_item = mine[0]
        show_rss(mine[0])
        cric_others = "  ".join(others)
        cric_tick()
    else:
        cric_ended = True
        lbl_clive.text, lbl_clive.color = "FINISHED", GREYS[5]
        cric_ticker.set("#This match has left the live feed (finished?)  " + "  ".join(others))


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
    sid = _series_id(item["link"])
    url = CI_API % (item["id"], ("&seriesId=" + sid) if sid else "")
    cric_debug.clear()
    cric_debug.update({"url": url, "rss_title": item["title"], "rss_desc": item.get("desc", ""),
                       "rss_link": item["link"]})
    body_parts, size = [], 0
    with requests.get(url, headers=CI_HDR, timeout=20) as r:
        cric_debug["status"] = r.status_code
        if r.status_code != 200:
            cric_detail = {}
            return
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
    cric_detail = {"info": info, "batters": batters, "status": status}
    show_rss(item)                 # redraw now with overs + batters
    cric_tick()


# ------------------------------------------------------------- news
NEWS_URL = os.getenv("NEWS_FEED") or "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
NEWS_EVERY = 15 * 60
news_items = []           # [(headline, source)]
news_page = 0
news_at = ""
news_from = "Google News"
news_msg = "Loading headlines..."
NEWS_SECONDS = max(2, int(os.getenv("NEWS_SECONDS") or "6"))
NEWS_PER_VISIT = max(1, int(os.getenv("NEWS_PER_VISIT") or "10"))
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
    with requests.get(url, headers=hdr, timeout=20) as r:
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
    for url in (NEWS_URL,) + NEWS_FALLBACKS:
        try:
            items = _read_items(url, NEWS_COUNT)[:NEWS_COUNT]
        except Exception as e:  # noqa: BLE001
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


def _put_lines(labels, font, rows, pitch):
    top = NEWS_TOP + (NEWS_BOT - NEWS_TOP - pitch * len(rows)) // 2
    for i, lbl in enumerate(labels):
        lbl.text = rows[i] if i < len(rows) else ""
        lbl.anchored_position = (5, top + i * pitch)


def show_news():
    """One big headline at a time, with a progress bar of all of them."""
    n = len(news_items)
    k = news_page % n if n else 0
    for i, seg in enumerate(news_seg):
        seg.color_index = 1 if (n and i == k) else (7 if i < n else 10)
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


def safe(fn, name, free=True):
    try:
        fn()
        return True
    except Exception as e:  # noqa: BLE001 - keep the dashboard running
        print(name, "failed:", repr(e))
        free_sockets()          # a broken connection: start fresh next time
        return False
    finally:
        if free:
            free_sockets()


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
    body = body.replace("</body>", '<p style="margin-top:32px"><a href="/cricket" '
                        'style="background:#444">Pick cricket match</a></p>'
                        '<p style="margin-top:16px"><a href="/rotate?on=%d" style="background:#444">'
                        'Auto-rotate screens: %s (tap to turn %s)</a></p></body>'
                        % (0 if auto_rotate else 1, "ON" if auto_rotate else "OFF",
                           "off" if auto_rotate else "on"))
    return Response(request, body, content_type="text/html")


@server.route("/rotate")
def rotate_page(request: Request):
    global auto_rotate, last_switch
    on = request.query_params.get("on", safe=False)
    if on in ("0", "1"):
        auto_rotate = on == "1" and SCREEN_SECONDS > 0
        last_switch = time.monotonic()
    msg = ("Auto-rotate is ON: screens change every %d s (the KEY button still works)." % SCREEN_SECONDS
           if auto_rotate else
           "Auto-rotate is OFF: screens change only when you press the KEY button.")
    link = '<a href="/rotate?on=%d">Turn %s</a> &nbsp; <a href="/" style="background:#444">Back</a>' % (
        0 if auto_rotate else 1, "off" if auto_rotate else "on")
    return Response(request, PAGE.replace("Zerodha login", "Screens") % (msg, link),
                    content_type="text/html")


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


def cricket_page_rss(request):
    global cric_id, last_cric, cric_detail, last_cdetail
    pick = request.query_params.get("id", safe=False)
    if pick == "off":
        cric_id = None
        lbl_cname.text = "No match selected"
        return Response(request, PAGE % ("Cricket screen turned off.", ""),
                        content_type="text/html")
    try:
        items = rss_items()
    except Exception as e:  # noqa: BLE001
        return Response(request, PAGE % ("Could not load the Cricinfo feed: %r" % e, ""),
                        content_type="text/html")
    if pick:
        cric_id = pick
        cric_detail = {}
        last_cric = time.monotonic()
        last_cdetail = 0.0             # fetch overs/batters for the new match right away
        get_cricket_rss(items)
        name = [it["title"] for it in items if it["id"] == pick]
        return Response(request, PAGE % ("Showing: " + esc(name[0] if name else pick), ""),
                        content_type="text/html")
    rows = []
    for it in items:
        mark = " &#10003;" if it["id"] == cric_id else ""
        rows.append('<p><a style="display:block;font-size:15px" href="/cricket?id=%s">%s%s</a></p>'
                    % (it["id"], esc(it["title"]), mark))
    rows.append('<p><a href="/cricket?id=off" style="background:#444">Turn cricket screen off</a></p>')
    return Response(request, PAGE.replace("Zerodha login", "Pick a match") %
                    ("Live matches from ESPNcricinfo (%d)" % len(items),
                     "".join(rows) if items else "No live matches right now."),
                    content_type="text/html")


@server.route("/cricket/debug")
def cricket_debug(request: Request):
    rows = ["<p><b>%s</b><br><code style='word-break:break-all'>%s</code></p>" % (esc(str(k)), esc(str(v)))
            for k, v in cric_debug.items()]
    rows.append("<p><b>shown</b><br><code>%s</code></p>" % esc(str(cric_detail)))
    return Response(request, PAGE.replace("Zerodha login", "Cricket debug") %
                    ("What the board got from Cricinfo for the selected match:",
                     "".join(rows) or "Nothing fetched yet - pick a live match first."),
                    content_type="text/html")


@server.route("/cricket")
def cricket_page(request: Request):
    global cric_id, last_cric
    if CRIC_RSS:
        return cricket_page_rss(request)
    if not CRIC_KEY:
        return Response(request, PAGE % ("Add CRICKET_API_KEY to settings.toml first "
                                         "(free key from cricketdata.org).", ""),
                        content_type="text/html")
    pick = request.query_params.get("id", safe=False)
    if pick == "off":
        cric_id = None
        lbl_cname.text = "No match selected"
        return Response(request, PAGE % ("Cricket screen turned off.", ""),
                        content_type="text/html")
    try:
        matches = cric_get("currentMatches?offset=0")
    except Exception as e:  # noqa: BLE001
        return Response(request, PAGE % ("Could not load matches: %s" % e, ""),
                        content_type="text/html")
    if pick:
        for m in matches:
            if m.get("id") == pick:
                cric_id = pick
                last_cric = time.monotonic()
                show_match(m)
                return Response(request, PAGE % ("Showing: " + esc(m.get("name")), ""),
                                content_type="text/html")
    rows = []
    for m in matches:
        state = "ended" if m.get("matchEnded") else ("live" if m.get("matchStarted") else "upcoming")
        mark = " &#10003;" if m.get("id") == cric_id else ""
        rows.append('<p><a style="display:block;font-size:15px" href="/cricket?id=%s">%s%s</a>'
                    '<small>%s - %s</small></p>' % (m.get("id"), esc(m.get("name")), mark,
                                                    state, esc(m.get("status"))))
    rows.append('<p><a href="/cricket?id=off" style="background:#444">Turn cricket screen off</a></p>')
    return Response(request, PAGE.replace("Zerodha login", "Pick a match") %
                    ("API hits today: " + cric_hits, "".join(rows) or "No current matches."),
                    content_type="text/html")


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
weather_ticker.set("Fetching weather for " + TOWN + "...")
safe(get_weather, "weather")
safe(ntp_sync, "ntp")
safe(get_air, "air")
weather_ticker.set("#" + weather_msg + "  " + air_msg + stamp())
if KITE_KEY and KITE_SECRET:
    show_login_needed("Kite login needed")
else:
    port_ticker.set("#" + kite_status)
if CRIC_TEAM and (CRIC_RSS or CRIC_KEY):
    safe(auto_pick, "cricket")
if not CRIC_RSS and not CRIC_KEY:
    cric_ticker.set("#Add CRICKET_API_KEY to settings.toml (free key from cricketdata.org)")
elif not cric_id:
    cric_ticker.set("#Pick a match at http://%s:%d/cricket" % (MY_IP, LOGIN_PORT))

safe(lambda: get_fmp("us"), "fmp")
safe(get_yahoo_india, "yahoo")
safe(get_news, "news")
clock_minute(time.localtime())

last_weather = last_air = last_ntp = last_kite = last_switch = time.monotonic()
last_cric = last_pick = time.monotonic()
last_cdetail = 0.0
last_fmp_in = last_fmp_us = time.monotonic()
last_news = last_npage = time.monotonic()
was_showing = None
news_left = 0
last_sec = last_min = -1
sec_mark = time.monotonic()
btn_was = True
night_now = False
wake_until = 0.0             # a button press at night shows other screens for a while

# ------------------------------------------------------------- main loop
while True:
    now_m = time.monotonic()

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
        every = KITE_EVERY_FAST if ORDER[screen] == "portfolio" else KITE_EVERY_OPEN
    else:
        every = KITE_EVERY_CLOSED
    if kite_token and now_m - last_kite > every:
        last_kite = now_m
        # keep the Kite connection open between fast refreshes
        if not safe(get_portfolio, "kite", free=(every > 30)):
            port_ticker.set("#Portfolio update failed - will retry" + stamp())

    if cric_id and not cric_ended:
        every = CRIC_EVERY if (CRIC_RSS or lbl_clive.text == "LIVE") else 15 * 60
        if now_m - last_cric > every:
            last_cric = now_m
            safe(get_cricket, "cricket")
        if CRIC_RSS and cric_item and now_m - last_cdetail > (60 if ORDER[screen] == "cricket" else 180):
            last_cdetail = now_m
            safe(lambda: get_cricket_detail(cric_item), "cricket detail")
    elif CRIC_TEAM and (CRIC_RSS or CRIC_KEY) and now_m - last_pick > (5 if CRIC_RSS else 30) * 60:
        last_pick = now_m            # look for this team's next match
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
            display.root_group = clock_grp
            showing = "clock"
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
    # news: next headline every NEWS_SECONDS (or on the BOOT button); with auto-rotate on,
    # the news screen moves on after NEWS_PER_VISIT headlines instead of SCREEN_SECONDS
    news_done = False
    if showing == "news":
        boot_down = boot is not None and not boot.value
        skip = boot_down and boot_was
        boot_was = not boot_down
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
        auto = auto_rotate and now_m - last_switch > SCREEN_SECONDS
    if night_now and not switch:
        auto = False
        if now_m > wake_until:            # not woken by the button: stay on the clock
            if display.root_group is not clock_grp:
                display.root_group = clock_grp
            showing = "clock"
    if switch or auto:
        last_switch = now_m
        was_showing = None            # (re)entering a screen restarts its news count
        for _ in range(len(ORDER)):
            screen = (screen + 1) % len(ORDER)
            name = ORDER[screen]
            if switch:
                break
            if name == "cricket" and not cric_id:
                continue
            if name == "markets" and not FMP_KEY:
                continue
            break
        display.root_group = ALL_SCREENS[ORDER[screen]]
        showing = ORDER[screen]
    if showing == "news" and was_showing != "news":
        news_left = min(NEWS_PER_VISIT, max(1, len(news_items)))
        last_npage = now_m
        show_news()
    was_showing = showing

    if t.tm_sec != last_sec:
        last_sec = t.tm_sec
        sec_mark = now_m
        hhmm = "%02d:%02d" % (t.tm_hour, t.tm_min)
        lbl_pclock.text = hhmm
        lbl_cclock.text = hhmm
        lbl_mclock.text = hhmm
        lbl_nclock.text = hhmm
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
    time.sleep(0.03)
