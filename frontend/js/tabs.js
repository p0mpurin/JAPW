// Tab registry: each view registers { enter, leave?, loadMore?, refresh? }.
// setTab() swaps views; infinite scroll and shortcuts dispatch to the active handler.
import { $ } from "./core/dom.js";
import { state } from "./core/state.js";
import { store } from "./core/store.js";
import { emit } from "./core/bus.js";
import { finishSplash, hideEmpty, setSentinelVisible } from "./ui/feedback.js";
import { setViewbar, setProgress } from "./ui/viewbar.js";
import { clearGallery } from "./gallery.js";

/** Tabs reachable with the number keys (search has no tab button — the search box is always there). */
export const TAB_ORDER = ["home", "boards", "liked", "collections", "artists"];
const LAST_TAB_KEY = "JAPW_last_tab";
const handlers = {};

export function registerTab(name, handler) {
  handlers[name] = handler;
}

export const activeHandler = () => handlers[state.tab] || {};

export function setTab(name) {
  if (!handlers[name]) name = "home";
  const prev = handlers[state.tab];
  if (prev && prev.leave) prev.leave(name);

  state.tab = name;
  state.feedEpoch++;
  state.serverColor = false;
  store.set(LAST_TAB_KEY, name);
  if (name !== "home") finishSplash();

  for (const btn of document.querySelectorAll(".tab-btn")) {
    const on = btn.dataset.tab === name;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", String(on));
  }
  $("search-row").classList.toggle("is-active", name === "search");
  $("collections-view").classList.add("hidden");
  $("gallery").classList.remove("hidden");
  window.scrollTo(0, 0);
  clearGallery();
  hideEmpty();
  setViewbar();
  setProgress(null);
  setSentinelVisible(false);
  emit("tab:changed", name);
  handlers[name].enter();
}

export function refreshCurrent() {
  const h = activeHandler();
  if (h.refresh) h.refresh();
}

export function loadMoreCurrent() {
  const h = activeHandler();
  if (h.loadMore) h.loadMore();
}

export function lastTab() {
  const t = store.get(LAST_TAB_KEY, "home");
  return handlers[t] ? t : "home";
}

for (const btn of document.querySelectorAll(".tab-btn")) {
  btn.addEventListener("click", () => {
    if (btn.dataset.tab === state.tab) refreshCurrent();
    else setTab(btn.dataset.tab);
  });
}
