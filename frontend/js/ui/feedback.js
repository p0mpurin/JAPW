// Empty state, the centre spinner and the infinite-scroll sentinel.
import { $, el } from "../core/dom.js";

const emptyState = $("empty-state");
const emptyTitle = $("empty-title");
const emptySub = $("empty-sub");
const loading = $("loading");
const sentinel = $("infinite-sentinel");
const sentinelHint = $("infinite-hint");

/** action = { label, onClick } renders a button under the message. */
export function showEmpty(title, subtitle = "", action = null) {
  emptyTitle.textContent = title;
  emptySub.textContent = subtitle;
  emptyState.querySelectorAll(".empty-sync-btn").forEach((b) => b.remove());
  if (action) {
    const btn = el("button", { className: "btn btn-primary btn-sm empty-sync-btn", textContent: action.label });
    btn.addEventListener("click", () => action.onClick(btn));
    emptyState.append(btn);
  }
  emptyState.classList.remove("hidden");
  setSentinelVisible(false);
}

export const hideEmpty = () => emptyState.classList.add("hidden");

export const setLoading = (on) => loading.classList.toggle("hidden", !on);

export function setSentinelVisible(show) {
  sentinel.classList.toggle("hidden", !show);
  sentinel.setAttribute("aria-hidden", show ? "false" : "true");
}

export function setInfiniteLoading(on) {
  sentinel.classList.toggle("is-loading", on);
  sentinelHint.textContent = on ? "Loading more…" : "";
}

// ─── Splash ───
const splash = $("splash");
const splashStartedAt = Date.now();
let splashPending = true;

(function cycleSplashLabel() {
  const label = $("splash-label");
  const msgs = ["Loading your feed", "Warming up pins", "Almost there"];
  let i = 0;
  const t = setInterval(() => {
    if (!splashPending) return clearInterval(t);
    i = (i + 1) % msgs.length;
    label.style.opacity = "0";
    setTimeout(() => {
      if (!splashPending) return;
      label.textContent = msgs[i];
      label.style.opacity = "";
    }, 300);
  }, 2800);
})();

export function finishSplash() {
  if (!splashPending) return;
  splashPending = false;
  const wait = Math.max(0, 650 - (Date.now() - splashStartedAt));
  setTimeout(() => {
    splash.classList.add("splash-fade-out");
    splash.setAttribute("aria-hidden", "true");
    splash.setAttribute("aria-busy", "false");
    document.body.classList.remove("splash-active");
    setTimeout(() => splash.classList.add("hidden"), 950);
  }, wait);
}
