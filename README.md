# JAPW: Just A Pinterest Wrapper

JAPW is a small **desktop app** for browsing Pinterest (and a little bit of X) in its own window. You get your **home feed**, **search**, **boards**, **similar pins**, **likes**, **collections**, and **downloads** without juggling a million browser tabs. Under the hood it’s a tiny **Flask** server plus static pages, wrapped in **pywebview** on Windows so it feels like a normal app.

If you want the full checklist of what every part does, see **[FEATURES.md](FEATURES.md)**.

This project isn’t affiliated with Pinterest or X. Use it in a way that respects their rules and whatever applies where you live.

---

## What you can do with it

### Pinterest

- **Home:** Your real personalized feed, same kind of data Pinterest uses when you’re logged in. It preloads posts in the background so paging feels snappy, and you can refresh to pull a fresh slice from the top.
- **Search:** With a synced session, search goes through Pinterest while logged in as you. If you’re not logged in (or you turn on “use pinscrape for search while logged in”), search can use **pinscrape** instead, which doesn’t need your cookies. Home still uses your account when you’re connected.
- **Boards:** Paste your **profile or “all boards”** URL in Settings (not a single board link). Then you can pick a board and scroll its pins forever.
- **Opening a pin:** Big preview, carousels, and a strip of **similar pins** when you’re signed in.
- **Ads:** Turn on “hide promoted” and sponsored-style pins get filtered out where the API gives us a clear signal (like `is_promoted` on the home feed). Other code paths use extra heuristics when scraping.
- **AI labels:** Optional filter for stuff Pinterest marks as AI-related, when that shows up in the data.

### Your library (all local)

- **Liked:** Heart things and they land in `likes.json`.
- **Collections:** Make folders of posts in `collections.json`.
- **Downloads:** Pick a folder and save images. There’s an optional **resolution filter** so you can favor real wallpaper-sized images over tiny thumbnails when Pinterest offers several sizes.

### Artists (X)

Sync X from your browser like Pinterest, add **@handles**, and browse their media on the Artists tab (filters, refresh, manage list).

---

## How Pinterest login works

JAPW never sees your password. Log in on Chrome, Edge, Firefox, or whatever you use, then hit **Settings** and **Sync from browser**. The app copies cookies into a **Playwright** storage file and uses them inside a headless Chromium for API calls. If things stop working, sync again.

---

## Tech stack

| Layer | What we use |
|--------|-------------|
| Window | pywebview |
| Server | Flask (JSON API on `127.0.0.1`, fixed port) |
| UI | Plain HTML, CSS, JavaScript |
| Pinterest | Playwright (Chromium), fetch from the page context |
| Search without login | pinscrape |
| Cookie import | browser-cookie3 |
| Tests | pytest |

---

## What you need

- **Python 3.12+** is what this repo is tested with; older 3.x might still work.
- **Windows** is what `build.bat` and paths assume.
- After `pip install`, install the browser Playwright needs:

```bash
playwright install chromium
```

---

## Run it from source

```bash
cd JAPW
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python main.py
```

The UI opens against the local Flask app (default port **52741**).

### Tests

```bash
python -m pytest tests/ -q
```

A few tests touch the real network; use `-k` to skip them if your machine is offline or flaky.

---

## Where your files live

| How you run it | Where config and data go |
|----------------|---------------------------|
| `python main.py` from the repo | Next to the project: `config.json`, `likes.json`, `collections.json`, session files, etc. |
| The built **JAPW.exe** | `%APPDATA%\JAPW\` |

Handy **config keys** (defaults and merge logic are in `japw_config.py`):

- `download_folder`: where downloads land.
- `pinterest_boards_page_url`: your boards listing page for the Boards feature.
- `search_use_pinscrape_when_logged_in`: public pinscrape for search only, even when logged in.
- `filter_promoted` / `filter_ai_content`: content filters.
- Resolution filter on/off, target size, and `min` vs `exact` mode.

---

## Build a Windows .exe

```bat
build.bat
```

That runs **PyInstaller** with **`JAPW.spec`**: one file, no console window, bundles **`frontend/`**, Playwright via **`collect_all("playwright")`**, and imports like **`japw_config`**, **`api`**, **`pinterest_session`**, **`x_session`**. You get **`dist\JAPW.exe`**. Frozen builds set **`PLAYWRIGHT_BROWSERS_PATH=0`** in `main.py` so Chromium rides along inside the exe.

---

## Small tools

**`tools/dump_homefeed_json.py`** saves a raw **`UserHomefeedResource`** response while you’re logged in (handy for debugging feeds or promoted flags):

```bash
python tools/dump_homefeed_json.py -o homefeed.json
```

---

## API in one glance

The UI talks to local Flask routes only, for example:

- `/api/home`, `/api/home/more` for the feed.
- `/api/search`, `/api/search/more` for search.
- `/api/boards`, `/api/board_pins`, `/api/board_pins/more` for boards.
- `/api/pin/related`, `/api/pin/resolve` for similar pins and mapping a cover image to a pin URL.
- `/api/auth/*` for session status, sync, logout.
- `/api/settings` to read or update config.
- `/api/download`, `/api/likes`, `/api/collections` for saves and your library.
- `/x/*` for X session and Artists media.

Nothing here phones home to a separate JAPW cloud; it’s all on your machine.

---

## If something goes wrong

- **“Not connected to Pinterest”:** Open Pinterest in a normal browser, log in, then run sync from Settings with that browser closed if the cookie file is locked.
- **Playwright weirdness:** Run `playwright install chromium` again and check that security software isn’t blocking the browser binary.
- **Boards look wrong:** The URL must be your **profile** or **all boards** page, not `…/board/some-name/` by itself.
- **Search and home don’t match:** That’s expected if you enabled pinscrape for search while logged in; home still follows your account.

---

## License and contributions

There’s no license baked into this README. Add a **LICENSE** file if you publish the fork. PRs and forks are welcome; just be clear about your own terms if you redistribute.
