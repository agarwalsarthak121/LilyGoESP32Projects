# LilyGO ESP32 Projects

Hobby builds on the **LilyGO T-Display-S3** (ESP32-S3, 16 MB flash, 8 MB PSRAM, 1.9" 320×170 screen).

## Projects

| Project | Status | What it is |
|---|---|---|
| [**T-Display desk dashboard**](t-display-dashboard/) | Working | Rotating Wi-Fi dashboard in CircuitPython: weather with an analog clock, Zerodha P&L, SENSEX/NIFTY/NASDAQ/S&P 500, live cricket, top India news, and a night clock |
| "Hey Jarvis" voice assistant | Planned | Wake word on the ESP32-S3 (INMP441 mic, MAX98357A amp), with speech-to-text → Claude → text-to-speech through a small relay server |
| Analog P&L gauge | Planned | A servo needle on a printed dial showing today's portfolio P&L |
| Cricket alerts | Planned | Sounds for wickets, fours and sixes through the I2S amp |
| Presence-aware screen | Planned | LD2410C mmWave sensor wakes the screen when someone is at the desk |

![Dashboard screens](t-display-dashboard/docs/news.png)

## Repository layout

```
t-display-dashboard/      the dashboard: code.py, fonts/, lib/, settings.toml.example
  docs/                   screen previews
tools/
  mkfont.py               TTF/OTF -> BDF bitmap font generator (then bdftopcf -> .pcf)
  simulator/              run code.py on a desktop with fake hardware and sample data
```

The Kite login redirect page lives in its own repo: [kite-redirect](https://github.com/agarwalsarthak121/kite-redirect) (GitHub Pages).

## Secrets

Wi-Fi passwords and API keys go only in `settings.toml` on the board. That file is git-ignored; use [`settings.toml.example`](t-display-dashboard/settings.toml.example) as the template.

## Desktop simulator

Preview screens and test the code without the board:

```bash
pip install adafruit-blinka-displayio blinka-displayio-pygamedisplay pygame
SHOW=news OUT=news.png python tools/simulator/harness.py      # render one screen to a PNG
python tools/simulator/dryrun.py                              # real web server on 127.0.0.1:8080
```

Useful variables for `harness.py`: `SHOW` (weather, port, markets, cric, news, clock), `FAKE_HOUR` (e.g. 23 for night mode), `LOGIN=1` (fake Kite login), `STEPS`, `OUT`.

## Making fonts

```bash
python tools/mkfont.py Inter-Bold.otf 24 all news24.bdf && bdftopcf -o news24.pcf news24.bdf
```

Modes: `digits`, `money` (digits plus ₹ and signs), `all` (printable ASCII plus ° and ₹).
