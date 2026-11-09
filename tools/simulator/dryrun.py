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
    for path in ["/", "/cricket/debug", "/cricket?id=off", "/kite?status=success&request_token=abc"]:
        try:
            r = urllib.request.urlopen("http://127.0.0.1:8080" + path, timeout=4)
            print(f"GET {path} -> {r.status}, {len(r.read())} bytes")
        except Exception as e:
            print(f"GET {path} -> FAILED: {e!r}")
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
