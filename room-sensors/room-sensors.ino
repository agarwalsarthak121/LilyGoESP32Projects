// Room sensor board (ESP32): DHT22 temperature/humidity, LDR light sensor, TTP223 touch pad.
// Serves a live page at http://<this board>/ and JSON at /data for the LilyGO dashboard.
// The touch pad recognises single tap, double tap and long press, and sends each one to the
// LilyGO the moment it happens (http://192.168.1.10:8080/room/tap?g=single&n=<number>).
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <HTTPClient.h>
#include <DHT.h>

// ---- Change these ----
const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* LILYGO_TAP_URL = "http://192.168.1.10:8080/room/tap";   // where taps are sent

#define DHT_PIN        4
#define DHT_TYPE       DHT22
#define TOUCH_PIN      27
#define LDR_PIN        35   // LDR module DO pin (LOW = bright, HIGH = dark)
#define LED_PIN        2    // onboard blue LED

// GPIOs used as 3.3V power for sensors (board has only one 3V3 pin)
#define TOUCH_PWR_PIN  25
#define LDR_PWR_PIN    26

// ---- Touch gesture timing (milliseconds) ----
const unsigned long DEBOUNCE_MS   = 30;   // ignore flickers shorter than this
const unsigned long LONG_MS       = 700;  // hold this long = long press
const unsigned long DOUBLE_GAP_MS = 350;  // second tap must start within this after the first ends

DHT dht(DHT_PIN, DHT_TYPE);
WebServer server(80);

float temperature = NAN;
float humidity = NAN;
bool isDark = false;
bool ledOn = false;
unsigned long lastRead = 0;

// touch state
bool rawTouch = false;          // what the pin says right now
bool touched = false;           // after debouncing
unsigned long rawChangedAt = 0;
unsigned long pressStart = 0;
bool longFired = false;
bool secondPress = false;       // this press is the second tap of a double tap
bool waitingSecond = false;     // a tap just ended; waiting to see if a second one follows
unsigned long firstReleaseAt = 0;

// counters
unsigned long touchCount = 0;   // every press of the pad
unsigned long singles = 0, doubles = 0, longs = 0;
unsigned long gestureSeq = 0;   // goes up by one for every gesture (the LilyGO uses it to spot missed ones)
const char* lastGesture = "none";
unsigned long lastGestureAt = 0;
int lastSendCode = 0;           // HTTP result of the last message to the LilyGO

const char PAGE[] = R"rawliteral(
<!DOCTYPE html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ESP32 sensors</title>
<style>
body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0;padding:20px;max-width:480px}
h1{font-size:20px;font-weight:500;margin:0 0 16px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.card{background:#1e1e1e;border-radius:12px;padding:16px}
.label{font-size:13px;color:#999}
.val{font-size:26px;margin-top:6px}
.sub{font-size:13px;color:#999;margin-top:4px}
button{margin-top:16px;width:100%;padding:14px;font-size:16px;border:0;border-radius:10px;background:#2d6cdf;color:#fff}
.foot{margin-top:12px;font-size:12px;color:#777}
</style></head><body>
<h1>ESP32 sensors</h1>
<div class="grid">
  <div class="card"><div class="label">Temperature</div><div class="val" id="t">--</div></div>
  <div class="card"><div class="label">Humidity</div><div class="val" id="h">--</div></div>
  <div class="card"><div class="label">Light</div><div class="val" id="l">--</div></div>
  <div class="card"><div class="label">Touch</div><div class="val" id="tc">--</div><div class="sub" id="g">--</div></div>
</div>
<button id="btn" onclick="toggleLed()">Toggle LED</button>
<div class="foot" id="f">Connecting...</div>
<script>
const $ = id => document.getElementById(id);
const names = {single: 'Single tap', double: 'Double tap', long: 'Long press', none: 'No gesture yet'};
async function load() {
  try {
    const d = await (await fetch('/data')).json();
    $('t').textContent  = d.temp === null ? 'Error' : d.temp.toFixed(1) + ' °C';
    $('h').textContent  = d.hum  === null ? 'Error' : d.hum.toFixed(1) + ' %';
    $('l').textContent  = d.dark ? 'Dark' : 'Bright';
    $('tc').textContent = (d.touched ? 'Touching' : 'Idle') + ' · ' + d.taps;
    $('g').textContent  = names[d.gesture] + (d.gesture === 'none' ? '' : ' · ' + d.gesture_age + ' s ago') +
                          ' (1x ' + d.singles + ', 2x ' + d.doubles + ', hold ' + d.longs + ')';
    $('btn').textContent = d.led ? 'Turn LED off' : 'Turn LED on';
    $('f').textContent = 'Updated ' + new Date().toLocaleTimeString() +
                         ' · up ' + d.uptime + 's · WiFi ' + d.rssi + ' dBm · LilyGO ' +
                         (d.sent === 200 ? 'OK' : d.sent === 0 ? '-' : 'error ' + d.sent);
  } catch (e) {
    $('f').textContent = 'Lost connection, retrying...';
  }
}
async function toggleLed() {
  await fetch('/toggle', { method: 'POST' });
  load();
}
load();
setInterval(load, 1000);
</script>
</body></html>
)rawliteral";

void setLed(bool on) {
  ledOn = on;
  digitalWrite(LED_PIN, ledOn ? HIGH : LOW);
}

void handleRoot() {
  server.send(200, "text/html; charset=utf-8", PAGE);
}

void handleData() {
  char tBuf[10], hBuf[10];
  if (isnan(temperature)) strcpy(tBuf, "null");
  else snprintf(tBuf, sizeof(tBuf), "%.1f", temperature);
  if (isnan(humidity)) strcpy(hBuf, "null");
  else snprintf(hBuf, sizeof(hBuf), "%.1f", humidity);

  char json[400];
  snprintf(json, sizeof(json),
    "{\"temp\":%s,\"hum\":%s,\"dark\":%s,\"touched\":%s,\"taps\":%lu,"
    "\"gesture\":\"%s\",\"seq\":%lu,\"gesture_age\":%lu,"
    "\"singles\":%lu,\"doubles\":%lu,\"longs\":%lu,"
    "\"led\":%s,\"uptime\":%lu,\"rssi\":%d,\"sent\":%d}",
    tBuf, hBuf,
    isDark ? "true" : "false",
    touched ? "true" : "false",
    touchCount,
    lastGesture, gestureSeq,
    gestureSeq ? (millis() - lastGestureAt) / 1000 : 0,
    singles, doubles, longs,
    ledOn ? "true" : "false",
    millis() / 1000,
    (int)WiFi.RSSI(),
    lastSendCode);
  server.send(200, "application/json", json);
}

void handleToggle() {
  setLed(!ledOn);
  server.send(200, "text/plain", "ok");
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to WiFi");
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Connected! Open http://");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("WiFi failed. Check name/password (ESP32 needs 2.4 GHz WiFi).");
  }
}

void readSensors() {
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (!isnan(t) && !isnan(h)) {
    temperature = t;
    humidity = h;
  } else {
    Serial.println("DHT22 read failed");
  }
  isDark = digitalRead(LDR_PIN) == HIGH;

  Serial.printf("Temp: %.1f C | Humidity: %.1f %% | Light: %s | Taps: %lu\n",
                temperature, humidity, isDark ? "DARK" : "BRIGHT", touchCount);
}

// Tell the LilyGO about a gesture straight away. Short timeouts, so a LilyGO that's busy or
// off never holds this board up for long; the LilyGO also catches gestures through /data.
void sendGesture(const char* g) {
  if (WiFi.status() != WL_CONNECTED) {
    lastSendCode = -1;
    return;
  }
  char url[192];
  snprintf(url, sizeof(url), "%s?g=%s&n=%lu", LILYGO_TAP_URL, g, gestureSeq);
  HTTPClient http;
  http.setConnectTimeout(800);
  http.setTimeout(1500);
  if (http.begin(url)) {
    lastSendCode = http.GET();
    http.end();
  } else {
    lastSendCode = -2;
  }
  Serial.printf("Gesture %s #%lu -> LilyGO %d\n", g, gestureSeq, lastSendCode);
}

void onGesture(const char* g) {
  gestureSeq++;
  lastGesture = g;
  lastGestureAt = millis();
  if (strcmp(g, "single") == 0) {
    singles++;
    setLed(!ledOn);                 // a single tap still toggles the onboard LED, as before
  } else if (strcmp(g, "double") == 0) {
    doubles++;
  } else {
    longs++;
  }
  sendGesture(g);
}

// Turns presses of the pad into single tap / double tap / long press.
void updateTouch() {
  unsigned long now = millis();
  bool raw = digitalRead(TOUCH_PIN) == HIGH;
  if (raw != rawTouch) {
    rawTouch = raw;
    rawChangedAt = now;
  }
  if (now - rawChangedAt >= DEBOUNCE_MS && raw != touched) {
    touched = raw;
    if (touched) {                                            // finger down
      touchCount++;
      pressStart = now;
      longFired = false;
      secondPress = waitingSecond && (now - firstReleaseAt <= DOUBLE_GAP_MS);
      waitingSecond = false;
    } else if (!longFired) {                                  // finger up after a short press
      if (secondPress) {
        secondPress = false;
        onGesture("double");
      } else {
        waitingSecond = true;
        firstReleaseAt = now;
      }
    }
  }
  if (touched && !longFired && now - pressStart >= LONG_MS) {  // held long enough: fire while still held
    longFired = true;
    secondPress = false;
    onGesture("long");
  }
  if (waitingSecond && !touched && now - firstReleaseAt > DOUBLE_GAP_MS) {
    waitingSecond = false;                                    // no second tap came: it was a single
    onGesture("single");
  }
}

void setup() {
  Serial.begin(115200);

  // Power up the touch and LDR sensors from GPIO pins
  pinMode(TOUCH_PWR_PIN, OUTPUT);
  pinMode(LDR_PWR_PIN, OUTPUT);
  digitalWrite(TOUCH_PWR_PIN, HIGH);
  digitalWrite(LDR_PWR_PIN, HIGH);
  delay(500);  // let sensors settle (don't touch the pad during this)

  pinMode(TOUCH_PIN, INPUT);
  pinMode(LDR_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);
  setLed(false);
  dht.begin();

  connectWiFi();

  if (MDNS.begin("esp32-sensors")) {
    MDNS.addService("http", "tcp", 80);
    Serial.println("Also try: http://esp32-sensors.local");
  }

  server.on("/", handleRoot);
  server.on("/data", handleData);
  server.on("/toggle", HTTP_POST, handleToggle);
  server.begin();
  Serial.println("Web server started");
}

void loop() {
  server.handleClient();
  updateTouch();

  // DHT22 can only be read every ~2 seconds
  if (millis() - lastRead >= 2000) {
    lastRead = millis();
    readSensors();
  }

  delay(5);
}
