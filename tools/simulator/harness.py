import os, sys, types, time, math
os.environ["SDL_VIDEODRIVER"] = "dummy"
HERE = os.path.dirname(os.path.abspath(__file__))
BOARD = os.path.join(HERE, "..", "..", "t-display-dashboard")
sys.path.insert(0, os.path.join(BOARD, "lib"))


from blinka_displayio_pygamedisplay import PyGameDisplay
import pygame

disp = PyGameDisplay(width=320, height=170, auto_refresh=False)
board = types.ModuleType("board"); board.DISPLAY = disp
sys.modules["board"] = board

wifi = types.ModuleType("wifi")
class Radio:
    connected = True
    ipv4_address = "192.168.1.42"
wifi.radio = Radio()
sys.modules["wifi"] = wifi

rtcm = types.ModuleType("rtc")
class RTC:
    datetime = None
rtcm.RTC = RTC
sys.modules["rtc"] = rtcm

FAIL = os.environ.get("FAIL") == "1"
class Resp:
    def __init__(self, d, raw=None): self.d = d; self.raw = raw; self.status_code = 200
    def iter_content(self, chunk_size=1024):
        for i in range(0, len(self.raw), chunk_size):
            yield self.raw[i:i + chunk_size]
    def json(self): return self.d
    def __enter__(self): return self
    def __exit__(self, *a): pass
temps = [round(19 + 6 * math.sin((i - 8) / 24 * 2 * math.pi), 1) for i in range(24)]
HOLD = [
 {"tradingsymbol":"RELIANCE","quantity":20,"t1_quantity":0,"average_price":2450.0,"last_price":2912.4,"close_price":2880.1},
 {"tradingsymbol":"INFY","quantity":35,"t1_quantity":0,"average_price":1520.0,"last_price":1488.2,"close_price":1510.6},
 {"tradingsymbol":"HDFCBANK","quantity":40,"t1_quantity":5,"average_price":1580.0,"last_price":1742.5,"close_price":1731.0},
 {"tradingsymbol":"TATAMOTORS","quantity":60,"t1_quantity":0,"average_price":690.0,"last_price":712.3,"close_price":728.9},
 {"tradingsymbol":"NIFTYBEES","quantity":300,"t1_quantity":0,"average_price":238.0,"last_price":271.6,"close_price":270.2},
]
KITE_EXPIRED = os.environ.get("KITE_EXPIRED") == "1"
class Session:
    def __init__(self, *a): pass
    def post(self, url, data=None, timeout=None, headers=None):
        print("POST", url, data[:60])
        return Resp({"status":"success","data":{"access_token":"tok123"}})
    def get(self, url, timeout=None, headers=None):
        if FAIL: raise OSError("no network")
        if "kite.trade" in url:
            print("GET", url, headers["Authorization"])
            if KITE_EXPIRED:
                r = Resp({"status":"error","error_type":"TokenException","message":"expired"}); r.status_code=403; return r
            r = Resp({"status":"success","data":HOLD}); r.status_code=200; return r
        if "news.google.com" in url or "thehindu.com" in url or "indiatimes.com" in url:
            host = url.split("/")[2]
            print("NEWS GET", host)
            fail = os.environ.get("NEWS_FAIL", "")
            if fail == "all" or (fail == "google" and "google" in url):
                r = Resp(None, b""); r.status_code = 403; return r
            heads = [("RBI holds repo rate at 5.25%, signals \u2018patient\u2019 stance as inflation cools", "The Hindu"),
                     ("Delhi AQI slips to \u2018severe\u2019 again; GRAP Stage III curbs back in NCR", "Hindustan Times"),
                     ("India vs Australia: Kohli\u2019s 72 powers hosts to 187/5 in third T20I at Wankhede", "ESPNcricinfo"),
                     ("Govt clears \u20b912,000 crore semiconductor package for Gujarat and Assam units", "Moneycontrol"),
                     ("Sensex jumps 600 points", "Mint"),
                     ("Supreme Court asks Centre, states to file detailed replies within four weeks on petitions challenging the new data protection rules and their impact on journalists and RTI", "Indian Express")] * 4
            if "google" in url:
                items = "".join('<item><title>%s - %s</title><link>https://news.google.com/x</link><description>%s</description><source url="https://x">%s</source></item>' % (h, s_, "&lt;a href=x&gt;" + "y" * 900, s_) for h, s_ in heads)
            else:
                items = "".join('<item><title><![CDATA[%s]]></title><link>https://x</link></item>' % h for h, s_ in heads)
            raw = ('<?xml version="1.0"?><rss><channel><title>Top stories</title>' + items + '</channel></rss>').encode("utf-8")
            return Resp(None, raw)
        if "hs-consumer-api" in url:
            print("CI GET", url.split("?")[1])
            import json as _j
            body = {"appPage": {"data": {"filler": "x" * 200000, "series": {"name": "India tour"},
                    "match": {"objectId": 1456781, "statusText": "India need 46 runs in 21 balls",
                              "teams": [{"team": {"name": "Australia", "abbreviation": "AUS"}, "score": "", "scoreInfo": None},
                                        {"team": {"name": "India", "abbreviation": "IND"}, "score": "187/5", "scoreInfo": "18.3/20 ov"}]},
                    "content": {"livePerformance": {"batsmen": [
                        {"player": {"name": "Virat Kohli", "longName": "Virat Kohli"}, "runs": 72, "balls": 48, "currentType": 1},
                        {"player": {"name": "Shubman Gill", "longName": "Shubman Gill"}, "runs": 31, "balls": 22, "currentType": 2}],
                        "bowlers": []}}}}}
            raw = _j.dumps(body).encode()
            return Resp(None, raw)
        if "finance.yahoo.com" in url:
            print("YAHOO GET", url.split("/chart/")[1].split("?")[0], (headers or {}).get("User-Agent","")[:11])
            if os.environ.get("YAHOO_FAIL"):
                r = Resp({}); r.status_code = 429; return r
            sym = url.split("/chart/")[1].split("?")[0].replace("%5E", "^")
            px = {"^BSESN": (77412.84, 76957.27), "^NSEI": (24215.10, 24080.40)}[sym]
            r = Resp({"chart": {"result": [{"meta": {"symbol": sym, "currency": "INR",
                      "regularMarketPrice": px[0], "chartPreviousClose": px[1]}}], "error": None}})
            r.status_code = 200; return r
        if "financialmodelingprep" in url:
            sym = url.split("symbol=")[1].split("&")[0].replace("%5E", "^")
            if os.environ.get("FMP_NO_INDIA") and sym in ("^BSESN", "^NSEI"):
                return Resp([])
            data = {"^BSESN": (76957.27, -307.23, -0.40), "^NSEI": (24080.40, -95.25, -0.39),
                    "^IXIC": (19871.42, 182.35, 0.93), "^GSPC": (6012.18, 21.07, 0.35)}[sym]
            return Resp([{"symbol": sym, "price": data[0], "change": data[1], "changePercentage": data[2]}])
        if "cricinfo" in url:
            print("RSS GET", headers.get("User-Agent","")[:20] if headers else None)
            xml = """<?xml version="1.0"?><rss version="2.0"><channel><title>Cricinfo Live Scores</title>
<item><title>India 187/5 * v Australia</title><link>https://www.espncricinfo.com/series/india-tour-1445348/india-vs-australia-3rd-t20i-1456781/live-cricket-score</link><description>India 187/5 * v Australia</description><guid>https://www.espncricinfo.com/ci/engine/match/1456781.html</guid></item>
<item><title><![CDATA[England 325 & 180/4 * v New Zealand 412/8d]]></title><link>https://www.espncricinfo.com/ci/engine/match/1456790.html</link></item>
<item><title>Mumbai Indians 201/6 v Chennai Super Kings 145/3 *</title><link>http://www.cricinfo.com/ci/engine/match/1456800.html</link></item>
<item><title>Pakistan v South Africa</title><link>http://www.cricinfo.com/ci/engine/match/1456811.html</link></item>
</channel></rss>"""
            r = Resp({}); r.text = xml; return r
        if "cricapi" in url:
            print("CRIC GET", url.split("?")[0].split("/")[-1])
            m = {"id":"m-test","name":"India vs Australia, 3rd T20I","matchType":"t20",
                 "status":"Australia need 46 runs in 21 balls","venue":"Wankhede Stadium, Mumbai",
                 "teams":["India","Australia"],
                 "teamInfo":[{"name":"India","shortname":"IND"},{"name":"Australia","shortname":"AUS"}],
                 "score":[{"r":187,"w":5,"o":20,"inning":"India Inning 1"},{"r":142,"w":6,"o":16.3,"inning":"Australia Inning 1"}],
                 "matchStarted":True,"matchEnded":False}
            info = {"hitsToday": 7, "hitsLimit": 100}
            if "currentMatches" in url:
                m2 = dict(m, id="m-2", name="England vs Pakistan, 1st Test", teams=["England","Pakistan"], score=[], matchStarted=False, teamInfo=[])
                return Resp({"status":"success","data":[m2, m],"info":info})
            return Resp({"status":"success","data":m,"info":info})
        if "air-quality" in url:
            return Resp({"current": {"pm2_5": 187.4, "pm10": 265.0, "us_aqi": 238}})
        return Resp({"utc_offset_seconds": 19800,
                     "current": {"temperature_2m": 24.3, "relative_humidity_2m": 62,
                                 "pressure_msl": 1014.2, "wind_speed_10m": 2.4,
                                 "weather_code": 45, "apparent_temperature": 25.1},
                     "hourly": {"temperature_2m": temps}})
cm = types.ModuleType("adafruit_connection_manager")
cm.get_radio_socketpool = lambda r: types.SimpleNamespace(getaddrinfo=lambda *a: (_ for _ in ()).throw(OSError("ntp stub")))
cm.get_radio_ssl_context = lambda r: None
sys.modules["adafruit_connection_manager"] = cm
rq = types.ModuleType("adafruit_requests"); rq.Session = Session
hs = types.ModuleType("adafruit_httpserver")
class Server:
    routes = {}
    def __init__(self, *a, **k): pass
    def route(self, path, *a, **k):
        def deco(fn): Server.routes[path] = fn; return fn
        return deco
    def start(self, host, port): print("server on", host, port)
    def poll(self): pass
class QP(dict):
    def get(self, k, default=None, safe=True): return dict.get(self, k, default)
class Request:
    def __init__(self, q): self.query_params = QP(q)
class Response:
    def __init__(self, req, body, content_type=None): self.body = body
hs.Server, hs.Request, hs.Response = Server, Request, Response
sys.modules["adafruit_httpserver"] = hs
mc = types.ModuleType("microcontroller"); mc.pin = types.SimpleNamespace(GPIO14="GPIO14", GPIO0="GPIO0")
sys.modules["microcontroller"] = mc
dio = types.ModuleType("digitalio")
class DIO:
    def __init__(self, p): self.value = True
    def switch_to_input(self, pull=None): pass
dio.DigitalInOut = DIO; dio.Pull = types.SimpleNamespace(UP=1)
sys.modules["digitalio"] = dio
os.environ.setdefault("SCREEN_SECONDS", "0")
sys.modules["adafruit_requests"] = rq

from adafruit_bitmap_font import bitmap_font
_orig = bitmap_font.load_font
bitmap_font.load_font = lambda p, *a, **k: _orig((BOARD + p) if p.startswith("/fonts") else p, *a, **k)

N = int(os.environ.get("STEPS", "60"))
calls = {"n": 0}
_sleep = time.sleep
T0 = time.monotonic()
import threading
MAIN = threading.current_thread()
def fake_sleep(s):
    if threading.current_thread() is not MAIN:
        return _sleep(s)
    calls["n"] += 1
    if calls["n"] == 5 and os.environ.get("LOGIN") == "1":
        r = Server.routes["/kite"](Request({"status":"success","request_token":"rt999"}))
        print("login page:", r.body.split("<p>")[1][:80])
        r = Server.routes["/kite"](Request({"url":"https%3A%2F%2Fsarthak.github.io%2Fkite-redirect%2F%3Faction%3Dlogin%26type%3Dlogin%26status%3Dsuccess%26request_token%3DPaStEd42%26board%3D192.168.1.42%253A8080"}))
        print("paste page:", r.body.split("<p>")[1][:80])
        r = Server.routes["/"](Request({}))
        import re; print("link:", re.search(r'href="([^"]+)"', r.body).group(1))
    if calls["n"] == 6 and os.environ.get("SHOW"):
        name = {"port": "portfolio", "cric": "cricket"}.get(os.environ["SHOW"], os.environ["SHOW"])
        NS["display"].root_group = NS["ALL_SCREENS"][name]; NS["screen"] = NS["ORDER"].index(name)
    if calls["n"] == 8 and os.environ.get("NPAGE"):
        NS["news_page"] = int(os.environ["NPAGE"]); NS["show_news"]()
    if calls["n"] == 7 and os.environ.get("CRICPAGE") == "1":
        r = Server.routes["/cricket"](Request({}))
        import re; print("cric page links:", re.findall(r'href="(/cricket[^"]*)"', r.body))
        pid = os.environ.get("PICK", "m-test")
        r = Server.routes["/cricket"](Request({"id": pid}))
        print("pick:", r.body.split("<p>")[1][:60])
    if os.environ.get("TRACE"):
        _sleep(0.02)
        st = (NS.get("showing"), NS.get("news_page") if NS.get("showing") == "news" else None)
        if st != calls.get("last"):
            calls["last"] = st; print("TRACE %6.2f" % (time.monotonic() - T0), st)
    if calls["n"] >= N:
        raise SystemExit
time.sleep = fake_sleep

src = open(BOARD + "/code.py").read()
NS = {"__name__": "__main__"}
if os.environ.get("FAKE_HOUR"):
    import time as _t
    _h = int(os.environ["FAKE_HOUR"])
    _real_lt = _t.localtime
    def _lt(*a):
        if a:
            return _real_lt(*a)
        x = _real_lt()
        return _t.struct_time((x.tm_year, x.tm_mon, x.tm_mday, _h, x.tm_min, x.tm_sec, x.tm_wday, x.tm_yday, -1))
    _t.localtime = _lt
t0 = time.monotonic()
try:
    exec(compile(src, "code.py", "exec"), NS)
except SystemExit:
    pass
print("ran steps:", calls["n"], "secs", round(time.monotonic() - t0, 2))
tb = NS["weather_ticker"].bmp; print("ticker px", sum(tb[x,y] for x in range(tb.width) for y in range(tb.height)))
for yy in range(tb.height):
    tb[0,yy] = tb[0,yy]
disp.refresh()
surf = disp._pygame_screen if hasattr(disp, "_pygame_screen") else pygame.display.get_surface()
out = os.environ.get("OUT", "preview.png")
pygame.image.save(surf, out)
from PIL import Image
im = Image.open(out); im.resize((im.width * 3, im.height * 3), Image.NEAREST).save(out)
print("saved", out)
