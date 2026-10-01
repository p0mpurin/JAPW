// Boards tab: your Pinterest boards, and the pins inside one.
import { $, el } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { api, errorMessage } from "../core/api.js";
import { state } from "../core/state.js";
import { pinimgSize } from "../core/pins.js";
import { registerTab } from "../tabs.js";
import { createPagedFeed } from "./paged.js";
import { showEmpty, setLoading } from "../ui/feedback.js";
import { setViewbar, vbBack, vbButton, vbTitle } from "../ui/viewbar.js";

const gallery = $("gallery");
const view = $("collections-view");

let openBoard = null;
let boardsCache = [];

const feed = createPagedFeed({
  tab: "boards",
  pageUrl: (offset) => `/api/boards/${openBoard.id}/pins?offset=${offset}&limit=50&url=${encodeURIComponent(openBoard.url)}`,
  onEmpty: () => showEmpty("This board is empty"),
  onError: (_res, message) => showEmpty("Could not load board", message),
});
feed.isCurrent = () => !!openBoard;

function boardTile(board, i) {
  const cover = board.cover
    ? el("img", { className: "tile-cover", src: pinimgSize(board.cover, "474x"), alt: "", loading: "lazy" })
    : el("div", { className: "tile-cover-empty", html: icon("grid", 26, 1.5) });
  return el("div", {
    className: "tile",
    style: { animationDelay: `${i * 30}ms` },
    onclick: () => openBoardView(board),
  },
  cover,
  el("div", { className: "tile-info" },
    el("div", { className: "tile-name" }, board.name, board.secret ? " \u{1F512}" : ""),
    el("div", { className: "tile-count" }, `${board.count} ${board.count === 1 ? "pin" : "pins"}`),
  ));
}

function listBar() {
  setViewbar(vbTitle("Your boards", boardsCache.length ? `${boardsCache.length}` : ""),
    vbButton("Refresh", "refresh", () => loadBoards(true)));
}

async function loadBoards(force = false) {
  openBoard = null;
  gallery.classList.add("hidden");
  view.classList.remove("hidden");
  view.replaceChildren();
  listBar();
  setLoading(true);
  const res = await api.get(`/api/boards${force ? "?refresh=1" : ""}`).catch(() => null);
  setLoading(false);
  if (state.tab !== "boards" || openBoard) return;
  if (!res || !res.ok) {
    view.classList.add("hidden");
    gallery.classList.remove("hidden");
    const notConnected = res && res.status === 401;
    showEmpty(notConnected ? "Connect Pinterest" : "Could not load boards",
      notConnected ? "Sync your Pinterest session in Settings to see your boards." : errorMessage(res, "Try again."));
    return;
  }
  boardsCache = res.data.boards || [];
  listBar();
  if (!boardsCache.length) {
    view.append(el("div", { className: "tiles-message" }, "You don't have any boards yet."));
    return;
  }
  boardsCache.forEach((b, i) => view.append(boardTile(b, i)));
}

function openBoardView(board) {
  openBoard = board;
  view.classList.add("hidden");
  gallery.classList.remove("hidden");
  setViewbar(vbBack("Boards", () => loadBoards(false)), vbTitle(board.name, `${board.count} pins`));
  feed.start();
}

registerTab("boards", {
  enter: () => loadBoards(false),
  leave() {
    openBoard = null;
    view.classList.add("hidden");
  },
  loadMore: () => openBoard && feed.more(),
  refresh() {
    if (openBoard) openBoardView(openBoard);
    else loadBoards(true);
  },
});
