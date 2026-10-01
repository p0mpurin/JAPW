// Search tab. While you type, the server is told to start fetching the query (and Pinterest's
// suggestions are shown), so by the time you press Enter the results are usually already there.
import { $, el } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { api } from "../core/api.js";
import { state } from "../core/state.js";
import { store } from "../core/store.js";
import { registerTab, setTab } from "../tabs.js";
import { createPagedFeed } from "./paged.js";
import { showEmpty } from "../ui/feedback.js";
import { setViewbar, vbTitle } from "../ui/viewbar.js";

const HISTORY_KEY = "JAPW_search_history";
const input = $("search-input");
const dropdown = $("search-history-dropdown");

let query = "";
let source = "session";

const feed = createPagedFeed({
  tab: "search",
  colorAware: true,
  pageUrl: (offset) => `/api/search?q=${encodeURIComponent(query)}&offset=${offset}&limit=50`,
  onLoaded(res) {
    source = (res && res.data.source) || "session";
  },
  onEmpty() {
    showEmpty(state.colorFilter ? "No results in this colour" : "No results found",
      state.colorFilter ? "Try another colour or a broader search." : "Try a different search term.");
  },
  onError(_res, message) {
    showEmpty("Search failed", message);
  },
});

// ─── History ───
export const searchHistory = () => store.getJSON(HISTORY_KEY, []).filter((q) => typeof q === "string");

function saveHistory(q) {
  store.setJSON(HISTORY_KEY, [q, ...searchHistory().filter((h) => h !== q)].slice(0, 12));
}

function removeHistory(q) {
  store.setJSON(HISTORY_KEY, searchHistory().filter((h) => h !== q));
}

// ─── Run ───
export function runSearch(raw) {
  const q = (raw ?? input.value).trim();
  if (!q) return;
  input.value = q;
  query = q;
  hideDropdown();
  input.blur();
  saveHistory(q);
  feed.started = false;
  if (state.tab !== "search") setTab("search");
  else enterSearch();
}

function enterSearch() {
  if (!query) {
    setViewbar(vbTitle("Search"));
    showEmpty("Search Pinterest", "Start typing above — results load while you type, so Enter is usually instant.");
    searchHistory().slice(0, 3).forEach(prefetch);
    return;
  }
  setViewbar(vbTitle(`“${query}”`));
  if (feed.started) feed.show();
  else feed.start();
}

// ─── Typeahead + prefetch ───
let suggestTimer = null;
let prefetchTimer = null;
let suggestReq = 0;
let highlighted = -1;
const prefetched = new Set();

function prefetch(q) {
  q = q.trim();
  if (q.length < 2 || prefetched.has(q.toLowerCase())) return;
  prefetched.add(q.toLowerCase());
  api.post("/api/search/prefetch", { q }).catch(() => {});
}

function dropdownItems() {
  return [...dropdown.querySelectorAll(".search-history-item")];
}

function setHighlight(i) {
  const items = dropdownItems();
  highlighted = items.length ? (i + items.length) % items.length : -1;
  items.forEach((it, idx) => it.classList.toggle("is-active", idx === highlighted));
  if (highlighted >= 0) prefetch(items[highlighted].dataset.query);
}

function row(q, kind) {
  const item = el("div", {
    className: `search-history-item search-item--${kind}`,
    html: icon(kind === "history" ? "refresh" : "search", 12),
    attrs: { "data-query": q },
  }, el("span", { className: "search-history-item-text" }, q));
  if (kind === "history") {
    item.append(el("button", {
      className: "search-history-clear",
      title: "Remove from history",
      textContent: "×",
      onmousedown: (e) => e.preventDefault(),
      onclick: (e) => {
        e.stopPropagation();
        removeHistory(q);
        renderDropdown(input.value.trim(), lastSuggestions);
      },
    }));
  }
  item.addEventListener("mousedown", (e) => e.preventDefault());
  item.addEventListener("mouseenter", () => prefetch(q));
  item.addEventListener("click", () => runSearch(q));
  return item;
}

let lastSuggestions = [];

function renderDropdown(typed, suggestions) {
  const t = typed.toLowerCase();
  const history = searchHistory().filter((h) => !t || h.toLowerCase().includes(t)).slice(0, t ? 4 : 8);
  const seen = new Set(history.map((h) => h.toLowerCase()));
  const extra = suggestions.filter((s) => !seen.has(s.toLowerCase())).slice(0, 8 - Math.min(history.length, 3));
  const label = (text) => el("div", { className: "search-dropdown-label" }, text);
  dropdown.replaceChildren(
    ...(history.length ? [label(t ? "Recent" : "Recent searches"), ...history.map((h) => row(h, "history"))] : []),
    ...(extra.length ? [label("Suggestions"), ...extra.map((s) => row(s, "suggestion"))] : []),
  );
  highlighted = -1;
  dropdown.classList.toggle("hidden", !dropdown.children.length || document.activeElement !== input);
}

function hideDropdown() {
  dropdown.classList.add("hidden");
  highlighted = -1;
}

input.addEventListener("input", () => {
  const typed = input.value.trim();
  clearTimeout(suggestTimer);
  clearTimeout(prefetchTimer);
  renderDropdown(typed, typed ? lastSuggestions.filter((s) => s.toLowerCase().includes(typed.toLowerCase())) : []);
  if (typed.length < 2) return;
  suggestTimer = setTimeout(async () => {
    const req = ++suggestReq;
    const res = await api.get(`/api/search/suggest?q=${encodeURIComponent(typed)}`).catch(() => null);
    if (req !== suggestReq || input.value.trim() !== typed) return;
    lastSuggestions = (res && res.data.suggestions) || [];
    renderDropdown(typed, lastSuggestions);
  }, 120);
  // A short pause in typing usually means this is the query — start fetching it now.
  prefetchTimer = setTimeout(() => prefetch(typed), 200);
});

input.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    if (dropdown.classList.contains("hidden")) renderDropdown(input.value.trim(), lastSuggestions);
    e.preventDefault();
    setHighlight(highlighted + (e.key === "ArrowDown" ? 1 : -1));
  } else if (e.key === "Enter") {
    const items = dropdownItems();
    runSearch(highlighted >= 0 && items[highlighted] ? items[highlighted].dataset.query : undefined);
  }
});
input.addEventListener("focus", () => renderDropdown(input.value.trim(), lastSuggestions));
input.addEventListener("blur", () => setTimeout(hideDropdown, 120));

registerTab("search", {
  enter: enterSearch,
  leave() {
    input.value = "";
  },
  loadMore: () => source === "session" && feed.more(),
  refresh() {
    if (query) runSearch(query);
  },
});

export function focusSearch() {
  input.focus();
  input.select();
}
