# Room sensor board (ESP32, Arduino)

A classic ESP32 DevKit (38-pin) with:

| Part | Pin |
|---|---|
| DHT22 module DATA | GPIO 4 |
| TTP223 touch SIG | GPIO 27 (powered from GPIO 25) |
| LDR module DO | GPIO 35 (powered from GPIO 26) |
| Onboard LED | GPIO 2 |

- `http://<board>/` — live page (refreshes every second).
- `http://<board>/data` — JSON: `temp`, `hum`, `dark`, `touched`, `taps`, `gesture`, `seq`, `gesture_age`, `singles`, `doubles`, `longs`, `led`, `uptime`, `rssi`, `sent`.
- **Touch gestures:** single tap, double tap (second tap within 350 ms) and long press (held 700 ms, fires while still held).
  Each one is sent at once to the LilyGO dashboard: `GET http://192.168.1.10:8080/room/tap?g=single|double|long&n=<seq>`.
  The LilyGO also reads `/data` every 5 s and catches any gesture whose message got lost (`seq` tells it which ones it has seen).
- A single tap still toggles the onboard LED.

Set `WIFI_SSID`, `WIFI_PASS` and `LILYGO_TAP_URL` at the top of `room-sensors.ino`, then upload with the Arduino IDE
(board: "ESP32 Dev Module"; library: "DHT sensor library" by Adafruit).
