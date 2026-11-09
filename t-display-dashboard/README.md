# T-Display-S3 desk dashboard

A Wi-Fi desk dashboard for the **LilyGO T-Display-S3** (ESP32-S3, 1.9" 320×170 screen), written in **CircuitPython 10**. It rotates through weather, your Zerodha portfolio, market indices, live cricket and top news, and turns into a dim analog clock at night.

| | |
|---|---|
| ![Weather](docs/aura-weather.png) | ![Portfolio](docs/aura-portfolio.png) |
| ![Markets](docs/aura-markets.png) | ![Cricket](docs/aura-cricket.png) |
| ![News](docs/aura-news.png) | ![Night clock](docs/aura-night.png) |

*(The default **aura** look. Previews are from the desktop simulator with sample data. The original grey look is still available as [`THEME = "classic"`](#looks-themes).)*

## Screens

| Screen | What it shows | Data source |
|---|---|---|
| **Weather** | Temperature, feels-like, low/high, humidity, wind, PM2.5, and an analog clock with smooth hands, the date and how much of the day has gone | [Open-Meteo](https://open-meteo.com) forecast + air quality (no key) |
| **Portfolio** | Today's P&L and total P&L, invested and current value, stock count, and a ticker of the biggest movers | [Kite Connect](https://kite.trade) Personal API (free) |
| **Markets** | SENSEX, NIFTY 50, NASDAQ, S&P 500 with change and open/closed state | Yahoo Finance chart feed (India), [FMP](https://financialmodelingprep.com) free API (US) |
| **Cricket** | Live score for a match you pick: teams, score, overs, current batters | ESPNcricinfo live-scores RSS (every 30 s) + match details |
| **News** | Top 10 India headlines, one at a time in large text, with source and a progress bar | Google News India RSS (falls back to The Hindu, then Times of India) |
| **Night clock** | Large dim analog clock, date, temperature (23:00–07:00 by default) | — |

## Looks (themes)

`THEME` in `settings.toml` picks the look; the board's web page (`/theme`) can switch it too, without editing files.

### `aura` (default)

Each screen borrows a different, well-known visual language, so you can tell them apart from across the room:

| Screen | Idea | Details |
|---|---|---|
| Weather | **Living sky**, after weather apps like CARROT where the background *is* the forecast | The gradient follows time of day (dawn, day, dusk, night) and conditions (cloud, fog, rain, storm, snow). Frosted-glass cards, a drawn weather symbol, and a Swiss station clock. PM2.5 is coloured by air-quality band. |
| Portfolio | **Mood dial** | A red-to-green dial (a preview of the servo P&L gauge project) whose needle eases to today's % move; the whole backdrop glows green or red with the day. |
| Markets | **Trading terminal**, after the Bloomberg Terminal's amber-on-black | One row per index: open/closed dot, value, % change, absolute change and a centred change bar (full bar = 2 %). |
| Cricket | **Broadcast scorebug** | Team-colour blocks (countries and IPL sides), a big score, a red dot for the batting side and a LIVE pill, on a mown-pitch backdrop. |
| News | **TV lower third** | Red TOP STORY tag, big white headline with a red rule, source and progress dots. |
| Clock | **Station clock** | White Swiss-railway face with the red "lollipop" seconds hand by day; dim warm amber at night so the room isn't lit blue. |

| | |
|---|---|
| ![Weather at dusk](docs/aura-weather-dusk.png) | ![Station clock](docs/aura-clock.png) |

### `classic`

The original grey look:

| | |
|---|---|
| ![Weather](docs/classic-weather.png) | ![Portfolio](docs/classic-port.png) |
| ![Markets](docs/classic-markets.png) | ![Cricket](docs/classic-cric.png) |
| ![News](docs/classic-news.png) | ![Night clock](docs/classic-night.png) |

## Buttons

- **KEY** (GPIO14): next screen. At night it wakes the other screens for 60 seconds.
- **BOOT** (GPIO0): next headline while the News screen is showing.

## Install

1. Flash **CircuitPython 10.x** for the LilyGO T-Display-S3 (from [circuitpython.org](https://circuitpython.org/board/lilygo_tdisplay_s3/)).
2. Copy `code.py`, `fonts/` and `lib/` from this folder to the `CIRCUITPY` drive (or upload them through the web workflow at `http://<board-ip>/code/`).
3. Copy `settings.toml.example` to the board as `settings.toml` and fill in your Wi-Fi, town and API keys.
4. The board restarts and the screens appear. Its IP address is printed on the serial console.

## Board web page (port 8080)

Open `http://<board-ip>:8080` on a phone or laptop on the same Wi-Fi:

| Page | Use |
|---|---|
| `/` | Kite login link, paste-the-redirect-URL form, auto-rotate toggle |
| `/kite` | Where the Kite login lands (via the https redirect page) |
| `/cricket` | Pick which live match to follow, or turn cricket off |
| `/cricket/debug` | Raw details of the cricket feed, for troubleshooting |
| `/rotate?on=0` / `?on=1` | Turn auto-rotate off / on |
| `/theme` | Switch between **aura** and **classic** (saved on the board, restarts it); "Use settings.toml" goes back to the `THEME` setting |

### Daily Kite login

Kite access tokens expire every morning (around 07:30 IST). Kite only accepts an **https** redirect URL, so the login goes through a tiny GitHub Pages page ([kite-redirect](https://github.com/agarwalsarthak121/kite-redirect)) that forwards the `request_token` to the board:

1. In your Kite developer app, set the redirect URL to the GitHub Pages URL.
2. Each morning open `http://<board-ip>:8080`, tap **Login with Kite**, and sign in.
3. If the forward fails, copy the URL you land on and paste it into the form on the board's page.

## Settings

Everything is configured in `settings.toml`; see [`settings.toml.example`](settings.toml.example) for every key and its default. The most useful ones:

| Key | Default | Meaning |
|---|---|---|
| `THEME` | `aura` | `aura` (a different style per screen) or `classic` (the original grey look) |
| `SCREEN_ORDER` | `weather,portfolio,markets,cricket,news` | Which screens rotate, in order (add `clock` for the big clock by day) |
| `SCREEN_SECONDS` | `15` | Seconds per screen |
| `AUTO_ROTATE` | on | `off` = change screens only with the KEY button |
| `NEWS_SECONDS` / `NEWS_PER_VISIT` | `6` / `10` | Seconds per headline / headlines per visit |
| `NIGHT_HOURS` | `23-7` | Night clock hours (`""` turns it off) |
| `DAY_BRIGHTNESS` / `NIGHT_BRIGHTNESS` | `0.6` / `0.05` | Backlight levels |

## How it works

- One main loop does everything: fetches data on timers, serves the web page, reads the buttons, and animates the clock hands and tickers. Nothing may block for long, so network calls have short timeouts and finished sockets are freed straight away.
- `adafruit_httpserver` is patched in `code.py` so a browser's empty "preconnect" socket can't freeze the board (the stock library loops forever on a 0-byte read).
- Fonts are Inter, converted to bitmap PCF fonts with [`tools/mkfont.py`](../tools/mkfont.py).
- The aura backgrounds are one 320×170 bitmap per screen with a 32-colour palette (16 gradient shades plus 16 darker "glass" shades for the cards), ordered-dithered so there's no banding. Changing the sky or the P&L mood only rewrites the palette, which is instant.
- Refresh rates are tuned to the free API limits: weather every 10 min, Kite every 5 s on screen in market hours, cricket every 30 s, Indian indices every 60 s on screen, US indices every 12 min (FMP allows 250 calls a day), news every 15 min.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Portfolio shows `--` | Do the daily Kite login at `http://<board-ip>:8080` |
| Page at port 8080 won't open | Make sure your phone is on the same Wi-Fi; wait a few seconds and retry |
| `no module named ...` on the serial console | Copy the whole `lib/` folder again |
| News says "News failed" | The error names the feed and HTTP status; it retries every 2 minutes |
| Cricket score but no overs/batters | Check `/cricket/debug` |

## Credits

- Weather layout inspired by [VolosR/tDisplayS3WeatherStation](https://github.com/VolosR/tDisplayS3WeatherStation).
- Libraries in `lib/` are from [Adafruit](https://github.com/adafruit) (MIT licence).
- Fonts generated from [Inter](https://rsms.me/inter/) (SIL Open Font Licence).
