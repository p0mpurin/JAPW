# JAPW: Just A Pinterest Wrapper

JAPW is a small **desktop app** for browsing Pinterest (and a little bit of X) in its own window. You get your **home feed**, **search**, **boards**, **similar pins**, **likes**, **collections**, and **downloads** without juggling a million browser tabs. Under the hood it’s a tiny **Flask** server plus static pages, wrapped in **pywebview** on Windows so it feels like a normal app.


This project isn’t affiliated with Pinterest or X. Use it in a way that respects their rules and whatever applies where you live.

---

## What you can do with it

### Pinterest

- **Home → For you:** JAPW learns your taste locally from what you open, like, download, copy and collect, and builds a feed of "more like this" around your strongest picks (mixed with your Pinterest feed). Nothing is sent to Pinterest; reset it any time in Settings.
- **Home → Pinterest:** Your real personalized Pinterest feed. It starts loading the moment the app opens and always fetches the next page before you scroll to it. Refresh (or press **R**) to pull a fresh slice from the top.
- **Search:** With a synced session, search goes through Pinterest as you. Suggestions appear as you type, and the query starts loading in the background while you type, so pressing Enter is usually instant. Re-running a recent search is instant too. When you’re not logged in (or you turn on “use pinscrape for search while logged in”), search uses **pinscrape**, which doesn’t need your cookies.
- **Boards:** Your own boards, straight from your account. Pick one and scroll its pins.
- **Opening a pin:** Big preview (a sharp version shows instantly, then the full original swaps in), carousels, zoom/pan, and **More like this**.
- **Colour:** Show only pins of one colour (red, blue, black, …) or sort the grid by colour, from the palette button, a pin's right-click menu, or the colour pill in the viewer. On Home and Search the filtering happens on the server, which also runs colour-targeted searches in parallel, so a colour fills the screen in a couple of seconds.
- **Ads:** “Hide promoted” filters sponsored pins using the flags Pinterest sends with each pin.
- **AI labels:** Optional filter for pins Pinterest marks as AI-generated or AI-modified.

### Your library (all local)

- **Liked:** Heart things and they land in `likes.json`.
- **Collections:** Make folders of posts in `collections.json`.
- **Downloads:** Pick a folder and save images; each download offers **Show in folder**, and pins you’ve already saved get a small check mark. An optional **resolution filter** favours real wallpaper-sized images.

### Artists (X)

Sync X from your browser like Pinterest, add **@handles** (or paste a profile link), and browse their media on the Artists tab — one artist or everyone interleaved. Media comes straight from x.com's own API with your cookies, a page in about a second, no browser involved.

### Getting around

- **Right-click any pin** (in the grid, the viewer, or More like this) for every action: open, like, add to collection, download, **copy image**, copy link, open on Pinterest/X, filter by its colour.
- **Drag an image** out of the grid into Explorer, Discord or an editor.
- **Keyboard:** `/` or `Ctrl+K` search · `1`–`6` tabs · `R` refresh · `-` / `=` image size · `S` select · `,` settings · `?` all shortcuts. With an image hovered or open: `L` like · `D` download · `C` collect · `O` open · `Y` copy link · `←`/`→` slides.
- The window remembers its size and position, and the app reopens on the tab you last used.

---

## How Pinterest login works

JAPW never sees your password. Log in on Chrome, Edge, Firefox, Zen or whatever you use, then hit **Settings** and **Sync from browser**. The app copies your Pinterest cookies into a local session file and calls the same JSON endpoints pinterest.com uses, directly over HTTPS — no hidden browser. If Pinterest stops accepting the session, a banner asks you to sync again.

---

## Tech stack

| Layer | What we use |
|--------|-------------|
| Window | pywebview |
| Server | Flask (JSON API on `127.0.0.1`, fixed port), split into blueprints in `japw/routes/` |
| UI | Plain HTML, CSS and ES-module JavaScript (`frontend/js/`) |
| Pinterest | Direct calls to Pinterest’s resource API with `requests` (`japw/pinterest/`) |
| X / Twitter | Direct calls to x.com's GraphQL API with `requests` (`japw/x.py`) |
| Search without login | pinscrape |
| Cookie import | browser-cookie3 |
| Images (clipboard, colours) | Pillow |
| Tests | pytest |

### Project layout

```
main.py                 window, geometry memory, clean shutdown
japw/api.py             create_app(): registers the blueprints
japw/routes/            pinterest · library (likes, collections, downloads, backup) · media · x · system
japw/feeds.py           shared paged feeds with read-ahead + parallel merged feeds
japw/pinterest/         session (cookie sync) · client (HTTP) · feeds · parse
japw/x.py               X session, GraphQL client and media parsing
japw/taste.py           local taste profile for For You
japw/colors.py          colour buckets (mirrors frontend/js/core/colors.js)
japw/media.py           image proxy, PNG conversion, dominant colours
japw/clipboard.py       native Windows clipboard
frontend/js/main.js     entry point; feeds/, ui/, core/ hold the rest
```

---

## What you need

- **Python 3.12+** is what this repo is tested with; older 3.x might still work.
- **Windows** is what `build.bat`, paths and the native clipboard assume.

---

## Run it from source

```bash
cd JAPW
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

The UI opens against the local Flask app (default port **52741**).

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

The tests are offline: Pinterest, the network and the clipboard are mocked.

---

## Where your files live

| How you run it | Where config and data go |
|----------------|---------------------------|
| `python main.py` from the repo | Next to the project: `config.json`, `likes.json`, `collections.json`, `downloads.json`, session files, `webview/` (UI storage), etc. |
| The built **JAPW.exe** | `%APPDATA%\JAPW\` |

Handy **config keys** (defaults and merge logic are in `japw/config.py`):

- `download_folder`: where downloads land.
- `search_use_pinscrape_when_logged_in`: public pinscrape for search only, even when logged in.
- `filter_promoted` / `filter_ai_content`: content filters.
- Resolution filter on/off, target size, and `min` vs `exact` mode.

---

## Build a Windows .exe

```bat
build.bat
```

That runs **PyInstaller** with **`JAPW.spec`**: one file, no console window, bundles **`frontend/`** and every `japw` module. You get **`dist\JAPW.exe`** — no bundled browser any more, so it is much smaller than before.

---

## API in one glance

The UI talks to local Flask routes only, for example:

- `/api/home`, `/api/foryou`, `/api/search?q=` — paged feeds (`offset`, `limit`, optional `color`, `refresh=1`; returns `posts`, `next_offset`, `has_more`).
- `/api/taste`, `/api/taste/signal`, `/api/taste/reset` — the local For You profile.
- `/api/search/prefetch`, `/api/search/suggest` — warm a query while typing; Pinterest suggestions.
- `/api/boards`, `/api/boards/<id>/pins` — your boards.
- `/api/pin/related` — More like this.
- `/api/auth/*` — session status, sync, logout.
- `/api/settings` — read or update config.
- `/api/download`, `/api/downloads`, `/api/reveal`, `/api/likes`, `/api/collections` — saves and your library.
- `/api/clipboard`, `/api/image.png`, `/api/colors` — copy image, PNG proxy, dominant colours.
- `/x/artists`, `/x/media?username=&offset=` — X artists and their paged media.

Nothing here phones home to a separate JAPW cloud; it’s all on your machine.

---

## If something goes wrong

- **“Not connected to Pinterest” / “session expired”:** Open Pinterest in a normal browser, log in, then sync from Settings (or the banner). Close that browser first if its cookie file is locked.
- **Artists tab says “Connect X” or fails:** log in to x.com in your browser, then **Manage → Sync from browser**. JAPW reads X's API details from x.com itself and refreshes them automatically when X changes them.
- **Search and home don’t match:** That’s expected if you enabled pinscrape for search while logged in; home still follows your account.

---

## License and contributions

There’s no license baked into this README. Add a **LICENSE** file if you publish the fork. PRs and forks are welcome; just be clear about your own terms if you redistribute.
