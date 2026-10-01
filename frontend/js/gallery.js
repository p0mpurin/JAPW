// The masonry grid: shortest-column placement with aspect-ratio boxes tinted by each pin's
// dominant colour (so nothing jumps while images load), lazy images sized to the column,
// colour filter / sort, resolution filter, select mode and grid zoom.
import { $, el } from "./core/dom.js";
import { icon } from "./core/icons.js";
import { api } from "./core/api.js";
import { state } from "./core/state.js";
import { store } from "./core/store.js";
import { emit, on } from "./core/bus.js";
import { canonicalKey, toPost, sizedUrl, estimateSizeFromUrl, urlFormatHint, isGifUrl } from "./core/pins.js";
import { colorBucket, colorSortKey } from "./core/colors.js";
import { actions } from "./actions.js";

const gallery = $("gallery");
const sentinel = $("infinite-sentinel");
const GAP_BY_COLS = { 6: 12, 7: 10, 8: 8 };

let columns = [];
let heights = [];
/** Every post loaded into the current view (including ones hidden by a filter), in load order. */
let posts = [];
let keys = new Set();
let shown = 0;

export const getPosts = () => posts;
export const postCount = () => posts.length;
export const visibleCount = () => shown;
export const findPost = (key) => posts.find((p) => p.key === key) || null;
export const itemEl = (key) => gallery.querySelector(`.gallery-item[data-post-key="${CSS.escape(key)}"]`);

// ─── Image sizing ───
function columnWidth() {
  const gap = GAP_BY_COLS[state.colCount] || 16;
  const pad = state.colCount >= 6 ? 32 : 48;
  return Math.max(120, (gallery.clientWidth - pad - gap * (state.colCount - 1)) / state.colCount);
}

/** Smallest CDN rendition that still looks sharp at the current column width. */
export function thumbnailUrl(url) {
  const px = columnWidth() * (window.devicePixelRatio || 1);
  return sizedUrl(url, Math.min(px * 1.05, 736));
}

const lazyObserver = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    const img = entry.target.querySelector("img[data-lazy-src]");
    if (img) {
      img.src = img.dataset.lazySrc;
      img.removeAttribute("data-lazy-src");
    }
    lazyObserver.unobserve(entry.target);
  }
}, { rootMargin: "0px 0px 2500px 0px" });

// ─── Filters ───
export function passesResolutionFilter(w, h) {
  const f = state.resFilter;
  if (!f.enabled || !w || !h) return true;
  if (f.mode === "exact") {
    const tol = Math.max(8, Math.round(Math.max(f.w, f.h) * 0.02));
    return Math.abs(w - f.w) <= tol && Math.abs(h - f.h) <= tol;
  }
  return w >= f.w && h >= f.h;
}

function isVisible(post) {
  if (state.resFilter.enabled) {
    const size = post.width && post.height ? { w: post.width, h: post.height } : estimateSizeFromUrl(post.urls[0]);
    if (size && !passesResolutionFilter(size.w, size.h)) return false;
  }
  if (state.colorFilter && !state.serverColor) return (post.bucket || colorBucket(post.color)) === state.colorFilter;
  return true;
}

// ─── Layout ───
function initColumns() {
  for (const c of columns) c.remove();
  gallery.className = gallery.className.replace(/\bcols-\d+\b/g, "").trim();
  if (state.colCount >= 6) gallery.classList.add(`cols-${state.colCount}`);
  columns = [];
  heights = [];
  for (let i = 0; i < state.colCount; i++) {
    const col = el("div", { className: "gallery-col" });
    gallery.insertBefore(col, sentinel);
    columns.push(col);
    heights.push(0);
  }
}

function place(node, post) {
  let best = 0;
  for (let i = 1; i < heights.length; i++) if (heights[i] < heights[best] - 0.01) best = i;
  const ratio = post.width && post.height ? post.height / post.width : 1.3;
  heights[best] += Math.min(Math.max(ratio, 0.35), 3) + 0.08;
  columns[best].append(node);
}

function sortedForDisplay(list) {
  if (!state.colorSort) return list;
  return list.slice().sort((a, b) => {
    const ka = colorSortKey(a.color);
    const kb = colorSortKey(b.color);
    return ka[0] - kb[0] || ka[1] - kb[1];
  });
}

function layout(list, animate) {
  let n = 0;
  for (const post of sortedForDisplay(list)) {
    if (!isVisible(post)) continue;
    place(createItem(post, animate ? n : 0), post);
    n++;
  }
  shown += n;
  return n;
}

export function clearGallery() {
  posts = [];
  keys = new Set();
  shown = 0;
  for (const c of columns) c.remove();
  columns = [];
  heights = [];
}

/** Lay the current posts out again (zoom, filter or sort changed). */
export function relayout() {
  shown = 0;
  initColumns();
  layout(posts, false);
  emit("gallery:changed");
}

/** Replace the grid contents. */
export function renderPosts(rawPosts) {
  clearGallery();
  initColumns();
  appendPosts(rawPosts);
}

/** Add posts to the end of the grid, skipping duplicates. Returns how many new posts arrived. */
export function appendPosts(rawPosts) {
  if (!columns.length) initColumns();
  const fresh = [];
  for (const raw of rawPosts) {
    const post = toPost(raw);
    if (!post.urls.length) continue;
    post.key = canonicalKey(post.urls[0]);
    if (!post.key || keys.has(post.key)) continue;
    keys.add(post.key);
    posts.push(post);
    fresh.push(post);
  }
  layout(fresh, true);
  if (needsColors()) fetchMissingColors(fresh);
  emit("gallery:changed");
  return fresh.length;
}

export function removePost(key) {
  keys.delete(key);
  posts = posts.filter((p) => p.key !== key);
  const node = itemEl(key);
  if (node) {
    node.remove();
    shown--;
  }
  emit("gallery:changed");
}

export function reapplyResolutionFilter() {
  relayout();
}

// ─── Skeleton while the first page loads ───
export function showSkeleton(count = 18) {
  clearGallery();
  initColumns();
  for (let i = 0; i < count; i++) {
    const ratio = [1.25, 1.5, 0.8, 1.1, 1.4, 0.95][i % 6];
    const node = el("div", { className: "skeleton-card", style: { aspectRatio: `1 / ${ratio}`, animationDelay: `${i * 40}ms` } });
    place(node, { width: 1, height: ratio });
  }
}

// ─── Colour filter / sort ───
const needsColors = () => !!((state.colorFilter && !state.serverColor) || state.colorSort);
let colorRelayoutTimer = null;

/** Pins from Pinterest carry a colour; X media and old likes need it measured by the backend. */
async function fetchMissingColors(list = posts) {
  const missing = list.filter((p) => !p.color && !p.colorPending);
  if (!missing.length) return;
  for (const p of missing) p.colorPending = true;
  for (let i = 0; i < missing.length; i += 60) {
    const batch = missing.slice(i, i + 60);
    const res = await api.post("/api/colors", { urls: batch.map((p) => p.urls[0]) }).catch(() => null);
    const found = (res && res.data.colors) || {};
    for (const p of batch) {
      p.color = found[p.urls[0]] || p.color;
      p.colorPending = false;
    }
    clearTimeout(colorRelayoutTimer);
    colorRelayoutTimer = setTimeout(() => needsColors() && relayout(), 150);
  }
}

export function setColorFilter(bucket) {
  state.colorFilter = bucket || null;
  emit("color:changed", state.colorFilter);
  // Server-filtered feeds restart themselves on "color:changed"; local views filter here.
  if (state.serverColor) return;
  relayout();
  if (needsColors()) fetchMissingColors();
}

export function setColorSort(on) {
  state.colorSort = !!on;
  relayout();
  if (needsColors()) fetchMissingColors();
}

// ─── Cards ───
function navButton(dir, onClick) {
  return el("button", {
    type: "button",
    className: `card-nav-btn card-nav-${dir}`,
    attrs: { "aria-label": dir === "prev" ? "Previous image" : "Next image" },
    html: icon(dir === "prev" ? "chevronLeft" : "chevronRight", 12, 2.5),
    onclick: (e) => {
      e.stopPropagation();
      onClick();
    },
  });
}

function createItem(post, batchIndex) {
  const { urls, key } = post;
  const url = urls[0];
  const gifVideo = post.gif_video_url;
  let isGif = !!gifVideo || isGifUrl(url);
  let slide = 0;

  const item = el("div", {
    className: "gallery-item"
      + (state.likedKeys.has(key) ? " is-liked" : "")
      + (state.downloadedKeys.has(key) ? " is-downloaded" : "")
      + (state.selectedKeys.has(key) ? " is-selected" : ""),
    attrs: { "data-post-key": key },
    style: { animationDelay: `${Math.min(batchIndex * 0.03, 0.25)}s` },
  });
  item.japwPost = post;

  const media = el("div", { className: "card-media" });
  if (post.width && post.height) media.style.aspectRatio = `${post.width} / ${post.height}`;
  else media.classList.add("no-ratio");
  if (post.color) media.style.backgroundColor = post.color;

  const meta = el("div", { className: "gallery-item-meta" },
    isGif ? "GIF" : post.width && post.height ? `${post.width} × ${post.height}` : urlFormatHint(url));

  if (gifVideo) {
    // X animated GIF — silent looping video.
    const vid = el("video", { autoplay: true, loop: true, muted: true, src: gifVideo });
    vid.setAttribute("playsinline", "");
    vid.onloadeddata = () => media.classList.add("loaded", "has-ratio");
    vid.onerror = () => removePost(key);
    media.append(vid);
  } else {
    const img = el("img", { alt: post.title || "", decoding: "async", draggable: true });
    img.onload = () => {
      media.classList.add("loaded");
      if (!post.width || !post.height) {
        meta.textContent = `${img.naturalWidth} × ${img.naturalHeight}`;
      }
    };
    img.onerror = () => {
      if (isGif) {
        isGif = false;
        img.src = thumbnailUrl(url);
      } else {
        removePost(key);
      }
    };
    // Drag the image out of the app (to Explorer, Discord, an editor…) as a real file.
    img.addEventListener("dragstart", (e) => {
      const name = (urls[slide].split("/").pop() || "image.jpg").split("?")[0];
      e.dataTransfer.setData("DownloadURL", `image/${name.endsWith(".png") ? "png" : "jpeg"}:${name}:${urls[slide]}`);
      e.dataTransfer.setData("text/uri-list", urls[slide]);
    });
    const src = isGif ? url : thumbnailUrl(url);
    if (batchIndex < 12 && posts.length <= 60) {
      img.fetchPriority = "high";
      img.src = src;
    } else {
      img.dataset.lazySrc = src;
      lazyObserver.observe(item);
    }
    media.append(img);
    post.setSlide = (i) => {
      slide = i;
      img.src = thumbnailUrl(urls[i]);
    };
  }
  item.append(media);

  item.append(
    el("div", { className: "select-check", html: icon("check", 11, 3) }),
    el("button", {
      className: "like-btn" + (state.likedKeys.has(key) ? " liked" : ""),
      title: "Like (L)",
      attrs: { "aria-label": "Like" },
      html: icon("heart", 15),
      onclick: (e) => {
        e.stopPropagation();
        actions.toggleLike(post);
      },
    }),
    el("span", { className: "downloaded-badge", title: "Already downloaded", html: icon("check", 11, 3) }),
    meta,
  );
  if (isGif) item.append(el("span", { className: "gif-badge" }, "GIF"));

  if (urls.length > 1) {
    item.append(el("span", {
      className: "gallery-item-badge",
      title: `${urls.length} images in this pin`,
    }, el("span", { className: "gallery-badge-stack" }), String(urls.length)));
  }

  // Step through a multi-image pin without opening it.
  if (urls.length > 1 && !gifVideo) {
    const dots = el("div", { className: "card-dots" });
    for (let d = 0; d < Math.min(urls.length, 15); d++) dots.append(el("span", { className: "card-dot" }));
    const sync = () => {
      prev.classList.toggle("is-hidden", slide <= 0);
      next.classList.toggle("is-hidden", slide >= urls.length - 1);
      dots.querySelectorAll(".card-dot").forEach((d, i) => d.classList.toggle("active", i === slide));
    };
    const go = (dir) => {
      const n = slide + dir;
      if (n < 0 || n >= urls.length) return;
      post.setSlide(n);
      sync();
    };
    const prev = navButton("prev", () => go(-1));
    const next = navButton("next", () => go(1));
    item.append(dots, prev, next);
    sync();
  }

  item.addEventListener("click", () => {
    if (state.selectMode) toggleSelected(key);
    else emit("viewer:open", { post, slide });
  });
  return item;
}

// ─── Reactions to app events ───
on("like:changed", ({ key, liked }) => {
  const node = itemEl(key);
  if (!node) return;
  node.classList.toggle("is-liked", liked);
  node.querySelector(".like-btn")?.classList.toggle("liked", liked);
});

on("download:done", (key) => itemEl(key)?.classList.add("is-downloaded"));

on("downloads:loaded", () => {
  for (const node of gallery.querySelectorAll(".gallery-item")) {
    if (state.downloadedKeys.has(node.dataset.postKey)) node.classList.add("is-downloaded");
  }
});

// ─── Grid zoom ───
const zoomOut = $("grid-zoom-out");
const zoomIn = $("grid-zoom-in");

function syncZoomButtons() {
  zoomOut.disabled = state.colCount >= 8;
  zoomIn.disabled = state.colCount <= 2;
}

export function setColCount(n) {
  const next = Math.max(2, Math.min(8, n));
  if (next === state.colCount) return;
  state.colCount = next;
  store.set("gridZoom", String(next));
  syncZoomButtons();
  if (columns.length) relayout();
}

zoomOut.addEventListener("click", () => setColCount(state.colCount + 1));
zoomIn.addEventListener("click", () => setColCount(state.colCount - 1));
syncZoomButtons();

// Re-flow when the window width changes the number of usable pixels per column.
let resizeTimer = null;
let lastWidth = gallery.clientWidth;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (Math.abs(gallery.clientWidth - lastWidth) > 40 && columns.length) {
      lastWidth = gallery.clientWidth;
      relayout();
    }
  }, 200);
}, { passive: true });

// ─── Select mode ───
const bulkBar = $("bulk-bar");
const bulkToggle = $("bulk-toggle-btn");

function updateBulkBar() {
  const n = state.selectedKeys.size;
  $("bulk-count-label").textContent = `${n} selected`;
  if (n > 0 && state.selectMode) {
    bulkBar.classList.remove("hidden");
    requestAnimationFrame(() => bulkBar.classList.add("visible"));
  } else {
    bulkBar.classList.remove("visible");
    setTimeout(() => {
      if (!bulkBar.classList.contains("visible")) bulkBar.classList.add("hidden");
    }, 350);
  }
}

function clearSelection() {
  state.selectedKeys.clear();
  gallery.querySelectorAll(".gallery-item.is-selected").forEach((n) => n.classList.remove("is-selected"));
  updateBulkBar();
}

export function toggleSelectMode() {
  state.selectMode = !state.selectMode;
  bulkToggle.classList.toggle("active", state.selectMode);
  gallery.classList.toggle("select-mode", state.selectMode);
  if (!state.selectMode) clearSelection();
  updateBulkBar();
}

export function toggleSelected(key) {
  const selected = !state.selectedKeys.has(key);
  if (selected) state.selectedKeys.add(key);
  else state.selectedKeys.delete(key);
  itemEl(key)?.classList.toggle("is-selected", selected);
  updateBulkBar();
}

export function selectAllVisible() {
  if (!state.selectMode) toggleSelectMode();
  for (const node of gallery.querySelectorAll(".gallery-item")) {
    state.selectedKeys.add(node.dataset.postKey);
    node.classList.add("is-selected");
  }
  updateBulkBar();
}

bulkToggle.addEventListener("click", toggleSelectMode);
$("bulk-clear-btn").addEventListener("click", clearSelection);
$("bulk-download-btn").addEventListener("click", () => {
  actions.downloadMany(posts.filter((p) => state.selectedKeys.has(p.key)));
});

// ─── Hover: shortcut target + warm the viewer's image ───
let hovered = null;
let preloadTimer = null;
gallery.addEventListener("mouseover", (e) => {
  const node = e.target.closest(".gallery-item");
  if (node === hovered) return;
  hovered = node;
  clearTimeout(preloadTimer);
  if (!node || !node.japwPost) return;
  preloadTimer = setTimeout(() => {
    const p = node.japwPost;
    if (!p.gif_video_url) new Image().src = sizedUrl(p.urls[0], 736);
  }, 220);
});
gallery.addEventListener("mouseleave", () => {
  hovered = null;
  clearTimeout(preloadTimer);
});

export function hoveredPost() {
  return hovered && hovered.isConnected ? hovered.japwPost || null : null;
}
