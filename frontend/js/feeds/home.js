// Home: "For you" (built from what you open / like / download / copy) or your Pinterest feed.
import { state } from "../core/state.js";
import { store } from "../core/store.js";
import { emit } from "../core/bus.js";
import { registerTab } from "../tabs.js";
import { createPagedFeed } from "./paged.js";
import { showEmpty, finishSplash } from "../ui/feedback.js";
import { showToast } from "../ui/toast.js";
import { setViewbar, segmented, vbButton } from "../ui/viewbar.js";

const MODE_KEY = "JAPW_home_mode";
let mode = store.get(MODE_KEY, "foryou") === "pinterest" ? "pinterest" : "foryou";
let refreshNext = false;
let personalised = true;

const sync = { label: "Sync now", onClick: (btn) => { btn.remove(); emit("auth:sync"); } };

function makeFeed(kind) {
  const path = kind === "foryou" ? "/api/foryou" : "/api/home";
  return createPagedFeed({
    tab: "home",
    colorAware: true,
    pageUrl: (offset) => {
      const refresh = refreshNext && offset === 0;
      refreshNext = false;
      return `${path}?offset=${offset}&limit=50${refresh ? "&refresh=1" : ""}`;
    },
    onLoaded(res) {
      finishSplash();
      refreshBtn.classList.remove("is-busy");
      if (res && res.ok) state.hadSession = true;
      if (kind === "foryou" && res && res.ok) {
        personalised = res.data.personalised !== false;
        renderBar();
      }
    },
    onEmpty() {
      showEmpty(state.colorFilter ? "No pins in this colour yet" : "Nothing here yet",
        state.colorFilter ? "Try another colour, or refresh." : "Try refreshing in a moment.");
    },
    onError(res, message) {
      if (res && res.status === 401) {
        if (state.hadSession || res.data.code === "session_expired") {
          showEmpty("Session expired", "Your Pinterest session has expired. Sync again to restore your feed.", sync);
        } else {
          showEmpty("Connect Pinterest", "Sync your browser session to load your feed. Works with Chrome, Edge, Firefox, Zen and others.", sync);
        }
        return;
      }
      showEmpty("Could not load your feed", message);
    },
  });
}

const feeds = { foryou: makeFeed("foryou"), pinterest: makeFeed("pinterest") };
const current = () => feeds[mode];
feeds.foryou.isCurrent = () => mode === "foryou";
feeds.pinterest.isCurrent = () => mode === "pinterest";

const refreshBtn = vbButton("Refresh", "refresh", () => refresh(), "Refresh (R)");
const modeSwitch = segmented(
  [{ id: "foryou", label: "For you", icon: "sparkles" }, { id: "pinterest", label: "Pinterest", icon: "grid" }],
  mode,
  (id) => {
    if (id === mode) return;
    mode = id;
    store.set(MODE_KEY, id);
    renderBar();
    show();
  },
);

function renderBar() {
  const hint = mode === "foryou" && !personalised
    ? Object.assign(document.createElement("span"), {
      className: "vb-sub",
      textContent: "Open, like and download pins to teach it your taste",
    })
    : null;
  setViewbar(modeSwitch.node, hint, refreshBtn);
}

function show() {
  const feed = current();
  if (feed.started && (feed.posts.length || feed.loading)) feed.show();
  else feed.start();
}

function refresh() {
  refreshBtn.classList.add("is-busy");
  showToast(mode === "foryou" ? "Refreshing For you…" : "Refreshing home…");
  refreshNext = true;
  current().start();
}

registerTab("home", {
  enter() {
    modeSwitch.set(mode);
    renderBar();
    show();
  },
  leave() {
    refreshBtn.classList.remove("is-busy");
  },
  loadMore: () => current().more(),
  refresh,
});

export function reloadHome() {
  for (const f of Object.values(feeds)) {
    f.started = false;
    f.posts = [];
  }
  if (state.tab === "home") show();
}
