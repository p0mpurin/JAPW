// Infinite scroll: ask the active tab for more posts well before the user reaches the bottom.
import { $, rafTwice } from "./core/dom.js";
import { on } from "./core/bus.js";
import { loadMoreCurrent } from "./tabs.js";

const sentinel = $("infinite-sentinel");
let scrollRaf = null;
let observer = null;
let resizeTimer = null;

/** How far above the bottom we start loading (viewport-aware so tall screens prefetch earlier). */
const thresholdPx = () => Math.max(8800, Math.round((window.innerHeight || 900) * 3.15));

function distanceToBottom() {
  const docEl = document.documentElement;
  const total = Math.max(document.body.scrollHeight, docEl.scrollHeight, 0);
  return total - (window.scrollY || docEl.scrollTop) - window.innerHeight;
}

export function scheduleScrollCheck() {
  if (scrollRaf !== null) return;
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = null;
    if (distanceToBottom() <= thresholdPx()) loadMoreCurrent();
  });
}

/** If the page is still short, queue another page so users rarely scroll into a gap. */
export function ensureBuffer() {
  rafTwice(() => {
    const total = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, 0);
    if (total < (window.innerHeight || 900) * 2.65) loadMoreCurrent();
  });
}

function setupObserver() {
  if (typeof IntersectionObserver === "undefined") return;
  if (observer) observer.disconnect();
  const margin = Math.max(6800, Math.round((window.innerHeight || 900) * 2.85));
  observer = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) loadMoreCurrent();
  }, { rootMargin: `0px 0px ${margin}px 0px` });
  observer.observe(sentinel);
}

export function initInfiniteScroll() {
  window.addEventListener("scroll", scheduleScrollCheck, { passive: true });
  window.addEventListener("resize", () => {
    scheduleScrollCheck();
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(setupObserver, 250);
  }, { passive: true });
  on("gallery:changed", scheduleScrollCheck);
  setupObserver();
}
