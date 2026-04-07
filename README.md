# JAPW — Just A Pinterest Wrapper

JAPW is a **desktop app** for browsing Pinterest (and a bit of X) in a focused window: your **home feed**, **search**, **boards**, **related pins**, **likes**, **collections**, and **downloads** without living inside a full browser tab. The UI is a local web app (**Flask** serves static files; **pywebview** wraps it in a native window on Windows).

A full, file-by-file style **feature inventory** is in **[FEATURES.md](FEATURES.md)**.

This project is **not** affiliated with Pinterest or X. Use it in line with those services’ terms and your local laws.

---

## What it does

### Pinterest (main)

- **Home** — Personalized feed using the same **`UserHomefeedResource`** JSON API Pinterest uses when you are logged in. Posts are buffered in the background for quick paging. Optional **refresh** fetches a new slice from the top.
- **Search** — With a saved session, search goes through Pinterest’s authenticated APIs. If you are **not** logged in, or you enable the setting **“use pinscrape for search while logged in”**, search can use the **pinscrape** library (public, no cookies). Home always stays account-based when connected.
- **Boards** — After you set your **boards listing URL** in Settings (profile or “all boards” page, not a single board), JAPW can list boards and open pins from a chosen board with infinite scroll.
- **Pin detail** — Open a pin, view carousels, jump to **similar / related** pins (session required).
- **Promoted / sponsored pins** — When **filter promoted content** is on, home and other API-backed flows drop pins marked as promoted (for example `is_promoted` in the homefeed payload). Additional heuristics exist for scrape-based code paths.
- **AI-labeled content** — Optional filter (off by default) for pins Pinterest marks as AI-related, where the data exposes it.

### Library features

- **Liked** — Local list of favorited posts (stored in `likes.json`).
- **Collections** — User-defined groups of posts (stored in `collections.json`).
- **Download** — Save the current image to a folder you choose; optional **minimum resolution** filter so tiny thumbnails are not treated as the “best” copy when multiple sizes exist.

### Artists (X / Twitter)

- Separate **session sync** from your browser (see X panel in the app).
- Add **@handles** and browse aggregated **media** from those accounts in the Artists tab (filter by artist, refresh, manage list).

---

## How login works (Pinterest)

JAPW does not store your password. You log in with a normal browser, then use **Settings → Sync from browser**. The app pulls cookies into a **Playwright storage state** file and reuses that session for API calls inside a headless Chromium instance. If the session expires, sync again.

---

## Tech stack

| Layer | Technology |
|--------|------------|
| Desktop shell | pywebview |
| Backend | Flask (JSON API, `127.0.0.1` + fixed port) |
| Frontend | Static HTML / CSS / JavaScript |
| Pinterest automation | Playwright (Chromium), in-process API fetches |
| Public search fallback | pinscrape |
| Cookie import | browser-cookie3 (sync path) |
| Tests | pytest |

---

## Requirements

- **Python 3.12+** (as used in this repo; slightly older 3.x may work).
- **Windows** is the primary target (paths and `build.bat` assume it).
- **Playwright browsers** after install:

```bash
playwright install chromium
```

---

## Run from source

```bash
cd JAPW
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python main.py
```

The window loads the UI from the embedded Flask server (default port **52741**).

### Tests

```bash
python -m pytest tests/ -q
```

Some tests hit the real network; narrow with `-k` if needed.

---

## Configuration and data files

| Mode | Config & state location |
|------|-------------------------|
| **Development** (`python main.py`) | Project directory: `config.json`, `likes.json`, `collections.json`, Pinterest session file, X session data, etc. |
| **Frozen exe** (PyInstaller) | `%APPDATA%\JAPW\` for persistence |

Important **settings** (see also `japw_config.py`):

- `download_folder` — Where saves go.
- `pinterest_boards_page_url` — Profile or boards index URL for the Boards feature.
- `search_use_pinscrape_when_logged_in` — Force public pinscrape for search only.
- `filter_promoted` / `filter_ai_content` — Content filters.
- Resolution filter toggles and target size / mode (`min` or `exact`).

---

## Building a Windows executable

```bat
build.bat
```

Uses **`JAPW.spec`** (PyInstaller one-file, windowed): bundles **`frontend/`**, **`collect_all("playwright")`**, and hidden imports such as **`japw_config`**, **`api`**, **`pinterest_session`**, **`x_session`**. Output: **`dist\JAPW.exe`**. Frozen runs set **`PLAYWRIGHT_BROWSERS_PATH=0`** in `main.py` so Chromium ships with the exe.

---

## Tools

- **`tools/dump_homefeed_json.py`** — Dumps raw **`UserHomefeedResource`** JSON using your saved Pinterest session (useful for debugging feed shape, promoted flags, etc.):

  ```bash
  python tools/dump_homefeed_json.py -o homefeed.json
  ```

---

## API surface (overview)

The frontend talks to Flask routes such as:

- `/api/home`, `/api/home/more` — Feed.
- `/api/search`, `/api/search/more` — Search.
- `/api/boards`, `/api/board_pins`, `/api/board_pins/more` — Boards.
- `/api/pin/related`, `/api/pin/resolve` — Related pins and cover → pin URL.
- `/api/auth/*` — Session status, sync, logout.
- `/api/settings` — GET/POST configuration.
- `/api/download`, `/api/likes`, `/api/collections` — Downloads and local library.
- `/x/*` — X session and Artists media.

All of this is **local-only**; no separate cloud backend ships with the app.

---

## Troubleshooting (short)

- **“Not connected to Pinterest”** — Run sync from Settings with Pinterest open and logged in in a supported browser.
- **Playwright errors** — Run `playwright install chromium` and ensure antivirus is not blocking the browser binary.
- **Empty or wrong boards** — Boards URL must be your **profile** or **all boards** page, not one board deep link.
- **Search vs home behave differently** — By design if **pinscrape** is enabled for search while logged in; home still uses your account.

---

## License / contributing

Add your preferred **LICENSE** if you publish the repo; this README does not impose one. Contributions and forks are welcome if you document your own terms.
