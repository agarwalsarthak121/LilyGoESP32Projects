"""Dry run code.py with the REAL adafruit_httpserver over real sockets on localhost."""
import os, sys, types, time, threading, socket, urllib.request
os.environ["SDL_VIDEODRIVER"] = "dummy"
sys.argv = ["x"]
# reuse the fake hardware/network from harness, but keep the real http server
src_h = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py")).read()
src_h = src_h.split("from adafruit_bitmap_font import bitmap_font")[0]
src_h = src_h.replace('sys.modules["adafruit_httpserver"] = hs', '')
exec(src_h)
Radio.ipv4_address = "127.0.0.1"

class Pool:
    def __getattr__(self, n): return getattr(socket, n)
    def getaddrinfo(self, host, port, *a):
        if host == "pool.ntp.org": raise OSError("no ntp in dry run")
        return socket.getaddrinfo(host, port, *a)
cm.get_radio_socketpool = lambda r: Pool()

from adafruit_bitmap_font import bitmap_font
_orig = bitmap_font.load_font
bitmap_font.load_font = lambda p, *a, **k: _orig((BOARD + p) if p.startswith("/fonts") else p, *a, **k)

RUN = float(os.environ.get("RUN", "10"))
loops = {"n": 0}
t0 = time.monotonic()
_sleep = time.sleep
MAIN = threading.current_thread()
def fake_sleep(s):
    if threading.current_thread() is MAIN:
        loops["n"] += 1
        if loops["n"] == 5 and os.environ.get("FORCE_MARKET"):
            NS["market_open"] = lambda: True
            NS["screen"] = 1; NS["display"].root_group = NS["port_grp"]
        if time.monotonic() - t0 > RUN:
            raise SystemExit
    _sleep(s)
time.sleep = fake_sleep

def client():
    _sleep(3)
    print(f"[t+3s] main-loop passes so far: {loops['n']}")
    s = socket.create_connection(("127.0.0.1", 8080)); s.close()     # browser preconnect, then gives up
    print("[t+3s] opened+closed an empty connection (like a Chrome preconnect)")
    _sleep(2)
    print(f"[t+5s] main-loop passes: {loops['n']}")
    for path in ["/", "/cricket/debug", "/cricket?id=off", "/kite?status=success&request_token=abc", "/theme"]:
        try:
            r = urllib.request.urlopen("http://127.0.0.1:8080" + path, timeout=4)
            print(f"GET {path} -> {r.status}, {len(r.read())} bytes")
        except Exception as e:
            print(f"GET {path} -> FAILED: {e!r}")
    # SETTINGS TEST: the page, a form save with real URL encoding, screen on/off/reorder
    r = urllib.request.urlopen("http://127.0.0.1:8080/settings", timeout=4).read().decode()
    print("settings page:", len(r), "bytes,", r.count("class=row"), "screen rows")
    from urllib.parse import urlencode as _enc
    form = {"AUTO_ROTATE": "on", "SCREEN_SECONDS": "20", "NIGHT_ON": "1", "NIGHT_FROM": "22", "NIGHT_TO": "6",
            "NIGHT_SCREEN": "fire", "NIGHT_BRIGHTNESS": "0.08", "DAY_BRIGHTNESS": "0.7", "NEWS_SECONDS": "8",
            "NEWS_PER_VISIT": "4", "NEWS_COUNT": "10", "TRIVIA_SECONDS": "25", "TRIVIA_SOURCE": "india",
            "CRICKET_TEAM": "India", "STAT_PLAYERS": "253802:Virat Kohli,625383:Jasprit Bumrah:bowl",
            "STAT_CLASS": "2", "WEATHER_TOWN": "Delhi", "WEATHER_LAT": "28.61", "WEATHER_LON": "77.21",
            "PET_NAME": "Moong", "PING_HOST": "8.8.8.8", "THEME": "aura", "go": "save"}
    r = urllib.request.urlopen("http://127.0.0.1:8080/settings/save?" + _enc(form), timeout=4).read().decode()
    print("save note:", r.split("<div class=note>")[1].split("</div>")[0][:80] if "class=note" in r else "?")
    print("applied:", NS["SCREEN_SECONDS"], NS["NIGHT"], NS["NIGHT_SCREEN"], NS["NEWS_SECONDS"], NS["TRIVIA_SECONDS"],
          NS["STAT_CLASS"], NS["PING_HOST"], [p[1] for p in NS["STAT_PLAYERS"]], NS["DAY_BRIGHT"])
    for q in ("n=pet&op=off", "n=trivia&op=up", "n=matrix&op=on", "n=news&op=show"):
        urllib.request.urlopen("http://127.0.0.1:8080/settings/screen?" + q, timeout=4).read()
    print("order now:", NS["ORDER"])
    print("stored:", sorted(NS["CFG"].items())[:4], "...")
    r = urllib.request.urlopen("http://127.0.0.1:8080/settings/save?" + _enc(
        dict(form, WEATHER_TOWN="Bijnor")), timeout=4).read().decode()
    print("town change:", r.split("<div class=note>")[1].split("</div>")[0][:120])
    # TODO TEST: add with real form encoding, odd characters, then the page and the screen text
    for t in ("Mom's birthday gift <surprise> & cake", "दूध लेना", "Fix 🔥 bug"):
        urllib.request.urlopen("http://127.0.0.1:8080/todo/add?" + _enc({"t": t, "p": "1", "d": "2026-11-12"}), timeout=4).read()
    r = urllib.request.urlopen("http://127.0.0.1:8080/todo", timeout=4).read().decode()
    print("todo items:", [x[1] for x in NS["todo_screen"].items])
    print("page escaped:", "&lt;surprise>" in r and "<surprise>" not in r, "| hindi kept on page:", "दूध" in r)
    NS["todo_screen"].draw()
    print("screen text:", [row[4].text for row in NS["todo_screen"].rows if row[4].text])
    # THEME TEST: choosing a look saves it to NVM and asks for a restart
    r = urllib.request.urlopen("http://127.0.0.1:8080/theme?name=classic", timeout=4).read().decode()
    print("theme page:", r.split("<p>")[1][:60] if "<p>" in r else r[:80], "| nvm[0] =", NS["microcontroller"].nvm[0] if "microcontroller" in NS else "?")
    # ROTATE TEST
    a = NS["screen"]; _sleep(2.5); b = NS["screen"]
    print("rotation on : screen changed", a, "->", b)
    r = urllib.request.urlopen("http://127.0.0.1:8080/rotate?on=0", timeout=4)
    print("GET /rotate?on=0 ->", r.status, "| auto_rotate =", NS["auto_rotate"])
    a = NS["screen"]; _sleep(3); b = NS["screen"]
    print("rotation off: screen", a, "->", b, "(unchanged)" if a == b else "(CHANGED!)")
    r = urllib.request.urlopen("http://127.0.0.1:8080/", timeout=4).read().decode()
    print("home page shows:", "Auto-rotate screens: OFF" in r)
    s2 = socket.create_connection(("127.0.0.1", 8080)); s2.sendall(b"GET / HT"); _sleep(0.2); s2.close()
    print("sent a half request and closed")
    _sleep(2)
    print(f"[end] main-loop passes: {loops['n']}")
threading.Thread(target=client, daemon=True).start()

NS = {"__name__": "__main__"}
try:
    exec(compile(open(BOARD + "/code.py").read(), "code.py", "exec"), NS)
except SystemExit:
    pass
print("finished; total passes", loops["n"])
