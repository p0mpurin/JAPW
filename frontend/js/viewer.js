// Full-size viewer: the image on the left (slides, zoom/pan, swipe) and a side panel with
// actions, details, the pin's colour and "More like this".
import { $, el } from "./core/dom.js";
import { api } from "./core/api.js";
import { state } from "./core/state.js";
import { on, emit } from "./core/bus.js";
import { canonicalKey, toPost, sizedUrl } from "./core/pins.js";
import { colorBucket, SWATCHES } from "./core/colors.js";
import { actions } from "./actions.js";
import { downloadMany } from "./downloads.js";
import { setColorFilter } from "./gallery.js";

const modal = $("modal");
const img = $("modal-img");
const video = $("modal-video");
const stage = modal.querySelector(".viewer-stage");
const panelScroll = $("viewer-panel-scroll");
const prevBtn = $("modal-prev");
const nextBtn = $("modal-next");
const counter = $("modal-slide-counter");
const dots = $("modal-dots");
const hint = $("modal-slideshow-hint");
const related = $("modal-related");
const downloadAllBtn = $("modal-download-all");
const likeBtn = $("viewer-like");
const titleEl = $("viewer-title");
const sizeEl = $("viewer-size");
const sourceEl = $("viewer-source");
const colorRow = $("viewer-color-row");
const colorBtn = $("viewer-color");
const openBtn = $("viewer-open");

const v = {
  post: null,
  slides: [],
  index: 0,
  relatedReq: 0,
  zoom: 1,
  panX: 0,
  panY: 0,
  drag: null, // { mode: "pan" | "swipe", x, y, panX, panY }
  scrollToRelatedWhenReady: false,
};

export const viewerOpen = () => modal.classList.contains("active");

/** What shortcuts / context menu act on while the viewer is open. */
export function viewerTarget() {
  if (!viewerOpen() || !v.post) return null;
  return { post: v.post, url: v.slides[v.index] || v.post.urls[0] };
}

// ─── Open / close ───
export function openViewer(rawPost, startSlide = 0) {
  if (!rawPost || !rawPost.urls || !rawPost.urls.length) return;
  v.post = toPost(rawPost);
  v.slides = v.post.urls.slice();
  v.index = startSlide > 0 && startSlide < v.slides.length ? startSlide : 0;
  resetZoom();
  showMedia();
  fillPanel();
  panelScroll.scrollTop = 0;
  modal.classList.add("active");
  document.body.style.overflow = "hidden";
  syncNav();
  loadRelated();
  actions.signal("view", v.post);
}

export function closeViewer() {
  v.relatedReq++;
  v.scrollToRelatedWhenReady = false;
  related.classList.add("hidden");
  related.replaceChildren();
  resetZoom();
  v.drag = null;
  modal.classList.remove("active");
  document.body.style.overflow = "";
  setTimeout(() => {
    if (viewerOpen()) return;
    img.removeAttribute("src");
    video.removeAttribute("src");
    video.style.display = "none";
    img.style.display = "";
    v.post = null;
    v.slides = [];
    v.index = 0;
  }, 250);
}

// ─── Side panel ───
function syncLike() {
  const liked = !!v.post && state.likedKeys.has(canonicalKey(v.post.urls[0]));
  likeBtn.classList.toggle("is-liked", liked);
  likeBtn.querySelector("span").textContent = liked ? "Liked" : "Like";
}

function fillPanel() {
  const p = v.post;
  const isX = p.source === "x";
  const isPin = (p.pin_url || "").includes("pinterest.com/pin/");
  sourceEl.textContent = isX ? `X · @${p.artist || ""}` : isPin ? "Pinterest" : "Image";
  titleEl.textContent = p.title || "";
  sizeEl.textContent = p.width && p.height ? `${p.width} × ${p.height}` : "—";
  openBtn.querySelector("span").textContent = isX ? "Open on X" : isPin ? "Open on Pinterest" : "Open in browser";
  downloadAllBtn.classList.toggle("hidden", v.slides.length < 2);
  downloadAllBtn.textContent = `Download all ${v.slides.length} images`;
  syncLike();
  syncColor();
}

function syncColor() {
  const bucket = v.post.bucket || colorBucket(v.post.color);
  const swatch = SWATCHES.find((s) => s.id === bucket);
  colorRow.classList.toggle("hidden", !swatch);
  if (!swatch) return;
  colorBtn.style.setProperty("--swatch", v.post.color || swatch.hex);
  colorBtn.querySelector(".color-pill-label").textContent = `More ${swatch.label.toLowerCase()}`;
  colorBtn.dataset.bucket = bucket;
}

// Pins without a colour (X, older likes) get one measured on demand.
async function ensureColor() {
  if (!v.post || v.post.color) return;
  const post = v.post;
  const res = await api.post("/api/colors", { urls: [post.urls[0]] }).catch(() => null);
  const c = res && res.data.colors && res.data.colors[post.urls[0]];
  if (c && v.post === post) {
    post.color = c;
    syncColor();
  }
}

on("like:changed", ({ key }) => {
  if (v.post && canonicalKey(v.post.urls[0]) === key) syncLike();
});

// ─── Media ───
/** A mid-size rendition to show instantly (gifs keep their animated original). */
const quickUrl = (url) => (/\.gif(\?|$)/i.test(url) ? url : sizedUrl(url, 736));

/**
 * Show a slide instantly from the 736px rendition (usually already cached by hover / the grid),
 * then swap in the full-resolution original once it has downloaded.
 */
function showSlide(index) {
  const full = v.slides[index];
  const quick = quickUrl(full);
  img.src = quick;
  if (quick !== full) {
    const hi = new Image();
    hi.onload = () => {
      if (v.slides[v.index] === full && viewerOpen()) img.src = full;
    };
    hi.src = full;
  }
  for (const n of [index + 1, index - 1]) {
    if (v.slides[n]) new Image().src = quickUrl(v.slides[n]);
  }
}

function showMedia() {
  if (v.post.gif_video_url) {
    img.style.display = "none";
    video.style.display = "";
    video.src = v.post.gif_video_url;
  } else {
    video.style.display = "none";
    video.removeAttribute("src");
    img.style.display = "";
    img.style.opacity = "1";
    showSlide(v.index);
  }
  ensureColor();
}

// ─── Slides ───
export function stepSlide(dir) {
  goToSlide(v.index + dir);
}

function goToSlide(index) {
  if (index < 0 || index >= v.slides.length || index === v.index) return;
  v.index = index;
  resetZoom();
  img.style.opacity = "0";
  setTimeout(() => {
    img.onload = () => {
      img.style.opacity = "1";
    };
    showSlide(v.index);
  }, 120);
  syncNav();
}

function syncNav() {
  const n = v.slides.length;
  prevBtn.style.display = n < 2 || v.index <= 0 ? "none" : "";
  nextBtn.style.display = n < 2 || v.index >= n - 1 ? "none" : "";
  counter.classList.toggle("hidden", n < 2);
  counter.textContent = `${v.index + 1} / ${n}`;
  dots.replaceChildren();
  dots.classList.toggle("hidden", n < 2 || n > 20);
  for (let i = 0; i < Math.min(n, 20); i++) {
    dots.append(el("button", {
      type: "button",
      className: `modal-dot${i === v.index ? " active" : ""}`,
      attrs: { "aria-label": `Image ${i + 1}` },
      onclick: () => goToSlide(i),
    }));
  }
  hint.classList.toggle("hidden", n <= 20);
  hint.textContent = n > 20 ? `${n} images — use ← →` : "";
}

// ─── Zoom / pan ───
function applyZoom() {
  img.style.transform = `scale(${v.zoom}) translate(${v.panX / v.zoom}px, ${v.panY / v.zoom}px)`;
  img.classList.toggle("is-zoomed", v.zoom > 1);
  img.classList.add("zoomable");
}

function resetZoom() {
  v.zoom = 1;
  v.panX = 0;
  v.panY = 0;
  img.style.transform = "";
  img.classList.remove("is-zoomed", "is-dragging");
  img.classList.add("zoomable");
}

stage.addEventListener("wheel", (e) => {
  if (!viewerOpen()) return;
  e.preventDefault();
  v.zoom = Math.max(1, Math.min(5, v.zoom + (e.deltaY < 0 ? 0.2 : -0.2)));
  if (v.zoom === 1) {
    v.panX = 0;
    v.panY = 0;
  }
  applyZoom();
}, { passive: false });

stage.addEventListener("dblclick", (e) => {
  if (e.target !== img) return;
  if (v.zoom > 1) resetZoom();
  else {
    v.zoom = 2.5;
    applyZoom();
  }
});

stage.addEventListener("mousedown", (e) => {
  if (e.button !== 0 || (e.target !== img && e.target !== video)) return;
  e.preventDefault();
  v.drag = { mode: v.zoom > 1 ? "pan" : "swipe", x: e.clientX, y: e.clientY, panX: v.panX, panY: v.panY };
  if (v.drag.mode === "pan") img.classList.add("is-dragging");
});

document.addEventListener("mousemove", (e) => {
  if (!v.drag || v.drag.mode !== "pan") return;
  v.panX = v.drag.panX + e.clientX - v.drag.x;
  v.panY = v.drag.panY + e.clientY - v.drag.y;
  applyZoom();
});

document.addEventListener("mouseup", (e) => {
  if (!v.drag) return;
  const dx = e.clientX - v.drag.x;
  const dy = e.clientY - v.drag.y;
  if (v.drag.mode === "swipe" && Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 50) stepSlide(dx < 0 ? 1 : -1);
  img.classList.remove("is-dragging");
  v.drag = null;
});

// Clicking the empty area around the image closes the viewer.
stage.addEventListener("click", (e) => {
  if (e.target === stage) closeViewer();
});

// ─── More like this ───
function relatedThumb(raw) {
  const post = toPost(raw);
  const ratio = post.width && post.height ? post.height / post.width : 1.25;
  const im = el("img", { alt: "", decoding: "async", loading: "lazy", src: sizedUrl(post.urls[0], 236) });
  im.onload = () => im.classList.add("loaded");
  im.onerror = () => thumb.remove();
  const thumb = el("div", {
    className: "related-thumb",
    style: { aspectRatio: `1 / ${Math.min(Math.max(ratio, 0.5), 2.2)}`, backgroundColor: post.color || "" },
    attrs: { role: "button", tabindex: "0", "aria-label": "Open similar pin", "data-post-key": canonicalKey(post.urls[0]) },
    onclick: (e) => {
      e.stopPropagation();
      openViewer(post);
    },
    onkeydown: (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openViewer(post);
      }
    },
  }, im, post.urls.length > 1 ? el("span", { className: "related-count" }, String(post.urls.length)) : null);
  thumb.japwPost = post;
  return thumb;
}

async function loadRelated() {
  const req = ++v.relatedReq;
  related.replaceChildren();
  related.classList.add("hidden");
  const pinUrl = (v.post.pin_url || "").trim();
  if (!pinUrl.includes("pinterest.com/pin/")) return;

  const skeleton = el("div", { className: "related-skeleton" },
    ...[1.3, 0.9, 1.5, 1.1, 1.2, 0.8].map((r) => el("span", { style: { aspectRatio: `1 / ${r}` } })));
  related.append(el("div", { className: "related-label" }, "More like this"), skeleton);
  related.classList.remove("hidden");

  const res = await api.post("/api/pin/related", { pin_url: pinUrl, exclude_urls: v.post.urls }).catch(() => null);
  if (req !== v.relatedReq) return;
  const posts = res && res.ok ? (res.data.posts || []).filter((p) => p.urls && p.urls.length) : [];
  if (!posts.length) {
    skeleton.replaceWith(el("p", { className: "related-message" },
      res && res.ok ? "No similar pins found." : (res && res.data.error) || "Could not load similar pins."));
    return;
  }
  skeleton.replaceWith(el("div", { className: "related-grid" }, ...posts.map(relatedThumb)));
  if (v.scrollToRelatedWhenReady) scrollToRelated();
}

/** Scroll the side panel to "More like this" (now, or as soon as it has loaded). */
export function scrollToRelated() {
  if (!related.querySelector(".related-grid")) {
    v.scrollToRelatedWhenReady = true;
    return;
  }
  v.scrollToRelatedWhenReady = false;
  requestAnimationFrame(() => panelScroll.scrollTo({ top: related.offsetTop - 12, behavior: "smooth" }));
}

// ─── Wiring ───
on("viewer:open", ({ post, slide }) => openViewer(post, slide));
$("modal-close").addEventListener("click", closeViewer);
modal.querySelector(".viewer-backdrop").addEventListener("click", closeViewer);
prevBtn.addEventListener("click", () => stepSlide(-1));
nextBtn.addEventListener("click", () => stepSlide(1));
$("modal-more").addEventListener("click", (e) => {
  e.stopPropagation();
  const r = e.currentTarget.getBoundingClientRect();
  emit("viewer:menu", { x: r.right - 230, y: r.bottom + 6 });
});
$("modal-download").addEventListener("click", () => {
  if (v.post) actions.download(v.post, v.post.gif_video_url || v.slides[v.index]);
});
likeBtn.addEventListener("click", () => v.post && actions.toggleLike(v.post));
$("viewer-copy").addEventListener("click", () => v.post && actions.copyImage(v.slides[v.index], v.post));
$("viewer-collect").addEventListener("click", () => v.post && actions.addToCollection(v.post));
openBtn.addEventListener("click", () => v.post && actions.openExternal(v.post, v.slides[v.index]));
colorBtn.addEventListener("click", () => {
  const bucket = colorBtn.dataset.bucket;
  if (!bucket) return;
  closeViewer();
  setColorFilter(bucket);
  emit("color:ui");
});
downloadAllBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  if (v.slides.length < 2) return;
  const key = canonicalKey(v.post.urls[0]);
  downloadMany(v.slides.map((url) => ({ url, key })));
  actions.signal("download", v.post);
});
