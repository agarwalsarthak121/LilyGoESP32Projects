import os, sys, types, time, math
os.environ["SDL_VIDEODRIVER"] = "dummy"
HERE = os.path.dirname(os.path.abspath(__file__))
BOARD = os.path.join(HERE, "..", "..", "t-display-dashboard")
sys.path.insert(0, os.path.join(BOARD, "lib"))

os.environ.setdefault("TRIVIA_FILE", BOARD + "/trivia_india.txt")

from blinka_displayio_pygamedisplay import PyGameDisplay
import pygame

disp = PyGameDisplay(width=320, height=170, auto_refresh=False)
board = types.ModuleType("board"); board.DISPLAY = disp
sys.modules["board"] = board

STEP = {"n": 0}                                    # loop steps (fake sleeps), shared below
def _window(name):
    w = os.environ.get(name)
    if not w: return False
    a, b = (int(x) for x in w.split("-"))
    return a <= STEP["n"] < b
wifi = types.ModuleType("wifi")
class Radio:
    def __init__(self):
        self.attempts = 0
        self.up = int(os.environ.get("WIFI_BOOT_FAILS", "0")) == 0
        self.ip = "192.168.1.42"
        self.was_down = False
    @property
    def connected(self):
        if _window("WIFI_DOWN"):
            self.up = False; self.was_down = True
        return self.up
    @property
    def ipv4_address(self):
        return self.ip if self.connected else None
    ipv4_gateway = "192.168.1.1"
    ap_info = types.SimpleNamespace(rssi=-58)
    def ping(self, ip, timeout=None):
        if not self.connected: return None
        if _window("NET_DOWN") and str(ip) != "192.168.1.1": return None
        import random as _r
        return (3 if str(ip) == "192.168.1.1" else 18 + _r.random() * 40 + (90 if _r.random() < 0.08 else 0)) / 1000
    def connect(self, ssid, pw, timeout=None):
        self.attempts += 1
        print("WIFI connect attempt %d (step %d)" % (self.attempts, STEP["n"]))
        if self.attempts <= int(os.environ.get("WIFI_BOOT_FAILS", "0")) or _window("WIFI_DOWN"):
            raise ConnectionError("No network with that ssid")
        if self.was_down and os.environ.get("NEWIP"):
            self.ip = "192.168.1.77"
        self.up = True
wifi.radio = Radio()
sys.modules["wifi"] = wifi

rtcm = types.ModuleType("rtc")
class RTC:
    datetime = None
rtcm.RTC = RTC
sys.modules["rtc"] = rtcm

FAIL = os.environ.get("FAIL") == "1"
class Resp:
    def __init__(self, d, raw=None, headers=None): self.d = d; self.raw = raw; self.status_code = 200; self.headers = headers or {}
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
 {"tradingsymbol":"M&M","quantity":15,"t1_quantity":0,"average_price":2650.0,"last_price":3120.5,"close_price":3098.0},
 {"tradingsymbol":"MRF","quantity":1,"t1_quantity":0,"average_price":118500.0,"last_price":131250.0,"close_price":132480.0},
 {"tradingsymbol":"BAJAJ-AUTO","quantity":4,"t1_quantity":0,"average_price":9100.0,"last_price":8875.0,"close_price":8875.0},
 {"tradingsymbol":"ICICIPRULI","quantity":120,"t1_quantity":0,"average_price":560.0,"last_price":612.35,"close_price":604.1},
]
POS = [   # net positions: an overnight option, an intraday short, today's delivery buy, a closed scalp
 {"tradingsymbol":"NIFTY25NOV24000CE","product":"NRML","quantity":75,"multiplier":1,"average_price":182.5,"last_price":214.35,"close_price":196.1,
  "buy_value":13687.5,"sell_value":0,"buy_m2m":14707.5,"sell_m2m":0,"pnl":0,"m2m":0},
 {"tradingsymbol":"TATAMOTORS","product":"MIS","quantity":-50,"multiplier":1,"average_price":725.0,"last_price":712.3,"close_price":728.9,
  "buy_value":0,"sell_value":36250,"buy_m2m":0,"sell_m2m":36250},
 {"tradingsymbol":"ITC","product":"CNC","quantity":100,"multiplier":1,"average_price":412.0,"last_price":409.15,"close_price":405.2,
  "buy_value":41200,"sell_value":0,"buy_m2m":41200,"sell_m2m":0},
 {"tradingsymbol":"SBIN","product":"MIS","quantity":0,"multiplier":1,"average_price":0,"last_price":801.2,"close_price":795.0,
  "buy_value":80000,"sell_value":80650,"buy_m2m":80000,"sell_m2m":80650},
]
KITE_EXPIRED = os.environ.get("KITE_EXPIRED") == "1"
class Session:
    def __init__(self, *a): pass
    def post(self, url, data=None, timeout=None, headers=None):
        if "generativelanguage" in url:
            import json as _j
            q = _j.loads(data)["contents"][0]["parts"][0]["text"]
            print("GEMINI", url.split("/models/")[1], "| key header:", "x-goog-api-key" in (headers or {}), "|", q[:50])
            if os.environ.get("ASK_FAIL"):
                r = Resp({"error": {"code": 401, "message": "API key not valid. Please pass a valid API key.", "status": "UNAUTHENTICATED"}}); r.status_code = 401; return r
            ans = {"short": "Paris.", "long": ("A UPS keeps devices running through a power cut by switching to its battery within milliseconds. " * 5).strip()}.get(q,
                   "Sachin Tendulkar scored 100 international centuries: 51 in Tests and 49 in ODIs, the most by any batter. \u2014 **Legend**")
            return Resp({"candidates": [{"content": {"parts": [{"text": "plan", "thought": True}, {"text": ans}], "role": "model"}, "finishReason": "STOP"}]})
        print("POST", url, data[:60])
        return Resp({"status":"success","data":{"access_token":"tok123"}})
    def get(self, url, timeout=None, headers=None):
        if FAIL: raise OSError("no network")
        if _window("NET_DOWN") or not wifi.radio.up:
            print("REQ-FAIL step %d %s" % (STEP["n"], url.split("/")[2]))
            raise OSError(113, "EHOSTUNREACH")
        print("REQ step %d %s" % (STEP["n"], url.split("/")[2]))
        if "generate_204" in url:
            r = Resp({}); r.status_code = 204; return r
        if "geocoding-api.open-meteo.com" in url:
            return Resp({"results": [{"name": "Bijnor", "latitude": 29.3724, "longitude": 78.1358}]})
        if "api_token.php" in url:
            return Resp({"response_code": 0, "token": "tkn"})
        if "opentdb.com/api.php" in url:
            from urllib.parse import quote
            Q = [("What is the capital of Japan?", "Tokyo", ["Kyoto", "Osaka", "Nagoya"], "Geography"),
                 ("Which element has the chemical symbol 'Fe'?", "Iron", ["Lead", "Fluorine", "Francium"], "Science & Nature"),
                 ("In computing, what does the acronym 'RAM' stand for in a typical desktop or laptop specification sheet?", "Random Access Memory", ["Read Access Memory", "Rapid Allocation Module", "Runtime Application Manager"], "Science: Computers")]
            return Resp({"response_code": 0, "results": [
                {"category": quote(c), "difficulty": "easy", "question": quote(q),
                 "correct_answer": quote(a), "incorrect_answers": [quote(x) for x in w]} for q, a, w, c in Q]})
        if "stats.espncricinfo.com" in url:
            if os.environ.get("STAT_FAIL"):
                r = Resp({}, b"<html>blocked</html>"); r.status_code = 403; return r
            bowl = "type=bowling" in url
            head = ("<th></th><th>Span</th><th>Mat</th><th>Inns</th><th>Overs</th><th>Mdns</th><th>Runs</th>"
                    "<th>Wkts</th><th>BBI</th><th>Ave</th><th>Econ</th><th>SR</th><th>4</th><th>5</th>") if bowl else (
                    "<th></th><th>Span</th><th>Mat</th><th>Inns</th><th>NO</th><th>Runs</th><th>HS</th><th>Ave</th>"
                    "<th>BF</th><th>SR</th><th>100</th><th>50</th><th>0</th><th>4s</th><th>6s</th>")
            yr = time.localtime().tm_year
            def row(label, vals):
                return '<tr class="data1"><td class="left" nowrap="nowrap"><b>%s</b></td>%s</tr>' % (
                    label, "".join('<td>%s</td>' % v for v in vals))
            if bowl:
                car = ["2016-%d" % yr, "200", "390", "1580.2", "160", "4400", "445", "6/19", "19.80", "2.78", "21.3", "15", "17"]
                cur = ["%d-%d" % (yr, yr), "22", "36", "301.4", "28", "1012", "61", "5/27", "16.59", "3.35", "29.6", "3", "2"]
            else:
                car = ["2008-%d" % yr, "560", "620", "90", "27599", "254*", "52.07", "29000", "92.1", "82", "143", "38", "2700", "300"]
                cur = ["%d-%d" % (yr, yr), "24", "28", "4", "1187", "135", "49.45", "1290", "92.01", "4", "6", "1", "120", "18"]
            html = ("<html><body>" + "<p>junk</p>" * 300 +
                    '<table class="engineTable"><thead><tr class="headlinks">' + head + "</tr></thead><tbody>" +
                    row("unfiltered", car) + "</tbody></table>" +
                    '<table class="engineTable"><thead><tr class="headlinks">' + head + "</tr></thead><tbody>" +
                    row("year %d" % (yr - 1), car) + row("year %d" % yr, cur) + "</tbody></table></body></html>")
            return Resp({}, html.encode())
        if "speed.cloudflare.com" in url or "cachefly" in url or "tele2" in url:
            fail = os.environ.get("SPEED_FAIL", "")
            if fail == "all" or (fail and fail in url):
                raise OSError(-2, "Name or service not known" if "cachefly" in url else "SSL handshake failed")
            return Resp({}, b"x" * 1000000)
        if "kite.trade" in url:
            print("GET", url, headers["Authorization"])
            if KITE_EXPIRED:
                r = Resp({"status":"error","error_type":"TokenException","message":"expired"}); r.status_code=403; return r
            if "positions" in url:
                if os.environ.get("POS_FAIL") == "1":
                    raise OSError(104, "ECONNRESET")
                r = Resp({"status":"success","data":{"net":POS if os.environ.get("NO_POS") != "1" else [],"day":[]}}); r.status_code=200; return r
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
        if "cricbuzz.com" in url:
            import json as _j
            print("CB GET", url.split("cricbuzz.com")[1][:60])
            if os.environ.get("CB_FAIL"):
                r = Resp(None, b""); r.status_code = 403; return r
            if "live-scores" in url:
                pad = "<div class='x'>" + "filler " * 3000 + "</div>"
                html = ("<html><head><title>Live Cricket Scores</title></head><body>" + pad +
                        '<a href="/live-cricket-scores/171301/ind-vs-sa-2nd-test-south-africa-tour-of-india-2026" '
                        'title="India vs South Africa, 2nd Test - Live Cricket Score, Commentary" class="cb-lv-scrs-well">IND 312/5</a>' + pad +
                        '<a class="text-hvr-underline" title="Mumbai vs Delhi, Elite Group A" href="/live-cricket-scores/171450/mum-vs-del-elite-group-a-ranji-trophy-2026-27">MUM vs DEL</a>' + pad +
                        '<a href="/live-cricket-scores/171520/aus-vs-eng-1st-odi-england-tour-of-australia-2026">AUS vs ENG</a>' +
                        '<a href="/live-cricket-scores/171301/ind-vs-sa-2nd-test">again</a></body></html>')
                return Resp(None, html.encode())
            mid = url.rstrip("/").split("/")[-1]
            if "/api/cricket-match/commentary/" in url:     # like now: the web page, not data
                return Resp(None, (b"<!DOCTYPE html><html>" + b"x" * 401000), {"content-type": "text/html; charset=utf-8"})
            if "/mcenter/comm/" in url and mid == "171450":   # served by hcomm only (like The Hundred)
                return Resp(None, b'{"matchHeader":null,"miniscore":null,"commentaryList":[]}', {"content-type": "application/json"})
            def team(i, n, s): return {"id": i, "name": n, "shortName": s}
            if mid == "171301":
                head = {"matchId": 171301, "matchDescription": "2nd Test", "matchFormat": "TEST", "state": "In Progress",
                        "status": "India lead by 27 runs", "team1": team(2, "India", "IND"), "team2": team(11, "South Africa", "SA"),
                        "seriesName": "South Africa tour of India, 2026"}
                mini = {"inningsId": 2, "overs": 88.3, "currentRunRate": 3.53, "requiredRunRate": 0, "status": "",
                        "batTeam": {"teamId": 2, "teamScore": 312, "teamWkts": 5},
                        "batsmanStriker": {"batName": "Shubman Gill", "batRuns": 112, "batBalls": 198},
                        "batsmanNonStriker": {"batName": "Rishabh Pant", "batRuns": 44, "batBalls": 61},
                        "bowlerStriker": {"bowlName": "Kagiso Rabada", "bowlOvs": 21.3, "bowlMaidens": 4, "bowlRuns": 71, "bowlWkts": 2},
                        "recentOvsStats": "... 0 1 4 0 0 1 | 0 0 1 4 ", "lastWicket": "KL Rahul c Verreynne b Rabada 38(77) - 214/4 in 61.2 ov.",
                        "matchScoreDetails": {"state": "In Progress", "inningsScoreList": [
                            {"inningsId": 2, "batTeamId": 2, "batTeamName": "IND", "score": 312, "wickets": 5, "overs": 88.3, "isDeclared": False},
                            {"inningsId": 1, "batTeamId": 11, "batTeamName": "SA", "score": 285, "wickets": 10, "overs": 92.6, "isDeclared": False}]}}
            elif mid == "171450":
                head = {"matchId": 171450, "matchDescription": "Elite Group A", "matchFormat": "TEST", "state": "Stumps",
                        "status": "Day 1: Stumps - Mumbai 248/4", "team1": team(54, "Mumbai", "MUM"), "team2": team(57, "Delhi", "DEL")}
                mini = {"batTeam": {"teamId": 54}, "batsmanStriker": {"batName": "Sarfaraz Khan", "batRuns": 87, "batBalls": 140},
                        "batsmanNonStriker": {"batName": "Shardul Thakur", "batRuns": 12, "batBalls": 30},
                        "matchScoreDetails": {"inningsScoreList": [{"inningsId": 1, "batTeamId": 54, "score": 248, "wickets": 4, "overs": 90.0}]}}
            elif mid == "171520":
                head = {"matchId": 171520, "matchDescription": "1st ODI", "matchFormat": "ODI", "state": "Preview",
                        "status": "Match starts at Nov 13, 03:30 GMT", "team1": team(4, "Australia", "AUS"), "team2": team(9, "England", "ENG")}
                mini = None
            else:
                r = Resp(None, b""); r.status_code = 204; return r
            body = {"commentaryList": [{"commText": "filler ball %d " % k + "x" * 300, "ballNbr": k} for k in range(900)],
                    "matchHeader": head, "page": "commentary"}
            body["miniscore"] = mini
            return Resp(None, _j.dumps(body).encode(), {"content-type": "application/json; charset=utf-8"})
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
                                 "weather_code": int(os.environ.get("WCODE", "45")), "apparent_temperature": 25.1, "is_day": int(os.environ.get("ISDAY", "1"))},
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
    def stop(self): print("server stopped")
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
mc.nvm = bytearray(b"\xff" * 8192)
NVMFILE = os.environ.get("NVMFILE")
if NVMFILE and os.path.exists(NVMFILE):
    mc.nvm = bytearray(open(NVMFILE, "rb").read())
import atexit
if NVMFILE:
    atexit.register(lambda: open(NVMFILE, "wb").write(bytes(mc.nvm)))
class _WD:
    timeout = None; mode = None; feeds = 0
    def feed(self): _WD.feeds += 1
mc.watchdog = _WD()
wdm = types.ModuleType("watchdog"); wdm.WatchDogMode = types.SimpleNamespace(RESET="RESET", RAISE="RAISE")
sys.modules["watchdog"] = wdm
sup = types.ModuleType("supervisor")
def _sncf(f, **k): print("set_next_code_file", f, k)
sup.set_next_code_file = _sncf
sys.modules["supervisor"] = sup
def _reset():
    print("RESET requested"); raise SystemExit
mc.reset = _reset
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
    STEP["n"] = calls["n"]
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
    if calls["n"] == 9 and os.environ.get("EVAL"):
        exec(os.environ["EVAL"], NS)
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
if os.environ.get("FASTCLOCK"):          # each loop step = FASTCLOCK seconds of board time
    _mono = time.monotonic; _k = float(os.environ["FASTCLOCK"])
    time.monotonic = lambda: _mono() + calls["n"] * _k

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
