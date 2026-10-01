// Right-click menu for any pin: grid cards, the open viewer, and "More like this" thumbnails.
import { el } from "./core/dom.js";
import { icon } from "./core/icons.js";
import { state } from "./core/state.js";
import { on } from "./core/bus.js";
import { canonicalKey, toPost } from "./core/pins.js";
import { colorBucket, SWATCHES } from "./core/colors.js";
import { actions } from "./actions.js";
import { findPost, setColorFilter, selectAllVisible, toggleSelectMode } from "./gallery.js";
import { viewerOpen, viewerTarget, openViewer, scrollToRelated, closeViewer } from "./viewer.js";
import { searchByPost } from "./feeds/visual.js";
import { currentCollection, removeFromCurrentCollection } from "./feeds/library.js";
import { downloadMany } from "./downloads.js";
import { syncColorButton } from "./colorbar.js";

let menu = null;

export const contextMenuOpen = () => !!menu;

export function closeContextMenu() {
  if (!menu) return;
  menu.remove();
  menu = null;
}

function item(label, iconName, onClick, { hint = "", danger = false } = {}) {
  const btn = el("button", {
    type: "button",
    className: `ctx-item${danger ? " ctx-danger" : ""}`,
    attrs: { role: "menuitem" },
    html: `${icon(iconName, 14)}<span class="ctx-label"></span>${hint ? `<kbd>${hint}</kbd>` : ""}`,
    onclick: () => {
      closeContextMenu();
      onClick();
    },
  });
  btn.querySelector(".ctx-label").textContent = label;
  return btn;
}

const sep = () => el("div", { className: "ctx-sep", attrs: { role: "separator" } });

function buildItems(post, url, where) {
  const liked = state.likedKeys.has(canonicalKey(post.urls[0]));
  const isPin = (post.pin_url || "").includes("pinterest.com/pin/");
  const isX = post.source === "x";
  const out = [];

  if (where !== "viewer") out.push(item("Open", "image", () => openViewer(post)));
  if (isPin) {
    out.push(item("More like this", "sparkles", () => {
      if (where !== "viewer") openViewer(post);
      scrollToRelated();
    }));
  }
  out.push(item("Find similar images", "search", () => {
    if (where === "viewer") closeViewer();
    searchByPost(post, url);
  }));
  out.push(sep());
  out.push(item(liked ? "Unlike" : "Like", "heart", () => actions.toggleLike(post), { hint: "L" }));
  out.push(item("Add to collection…", "folderPlus", () => actions.addToCollection(post), { hint: "C" }));
  const col = currentCollection();
  if (col && where === "grid") {
    out.push(item(`Remove from “${col.name}”`, "trash", () => removeFromCurrentCollection(post), { danger: true }));
  }
  out.push(sep());
  out.push(item("Download", "download", () => actions.download(post, post.gif_video_url || url), { hint: "D" }));
  if (post.urls.length > 1) {
    const key = canonicalKey(post.urls[0]);
    out.push(item(`Download all ${post.urls.length} images`, "download",
      () => downloadMany(post.urls.map((u) => ({ url: u, key })))));
  }
  if (!post.gif_video_url) out.push(item("Copy image", "copy", () => actions.copyImage(url, post)));
  out.push(item("Copy image link", "link", () => actions.copyLink(url, post), { hint: "Y" }));
  out.push(item(isX ? "Open on X" : isPin ? "Open on Pinterest" : "Open in browser", "external",
    () => actions.openExternal(post, url), { hint: "O" }));

  const bucket = colorBucket(post.color);
  if (bucket && where === "grid") {
    const swatch = SWATCHES.find((s) => s.id === bucket);
    out.push(sep());
    out.push(item(`Show only ${swatch.label.toLowerCase()} pins`, "palette", () => {
      setColorFilter(bucket);
      syncColorButton();
    }));
  }
  if (where === "grid") {
    out.push(item(state.selectMode ? "Select all visible" : "Select…", "check", () => {
      if (state.selectMode) selectAllVisible();
      else toggleSelectMode();
    }, { hint: "S" }));
  }
  // Tidy separators (no leading / trailing / doubled).
  return out.filter((n, i, arr) => !(n.classList.contains("ctx-sep")
    && (i === 0 || i === arr.length - 1 || arr[i - 1].classList.contains("ctx-sep"))));
}

export function openContextMenu(x, y, post, url, where) {
  closeContextMenu();
  menu = el("div", { className: "ctx-menu", attrs: { role: "menu" } }, ...buildItems(post, url, where));
  document.body.append(menu);
  const { width, height } = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - width - 8))}px`;
  menu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - height - 8))}px`;
  menu.querySelector(".ctx-item")?.focus();
}

/** Work out which post a right-click landed on. */
function resolve(target) {
  const node = target.closest("[data-post-key]");
  if (node && node.japwPost) {
    const where = node.classList.contains("gallery-item") ? "grid" : "related";
    const post = node.japwPost;
    const img = node.querySelector("img");
    const shownUrl = img && (img.dataset.lazySrc || img.currentSrc || img.src);
    const slide = shownUrl ? Math.max(0, post.urls.findIndex((u) => canonicalKey(u) === canonicalKey(shownUrl))) : 0;
    return { post, url: post.urls[slide] || post.urls[0], where };
  }
  if (node) {
    const post = findPost(node.dataset.postKey);
    if (post) return { post, url: post.urls[0], where: "grid" };
  }
  if (viewerOpen() && target.closest(".modal-stage")) {
    const t = viewerTarget();
    if (t) return { post: t.post, url: t.url, where: "viewer" };
  }
  return null;
}

export function initContextMenu() {
  on("viewer:menu", ({ x, y }) => {
    const t = viewerTarget();
    if (t) openContextMenu(x, y, toPost(t.post), t.url, "viewer");
  });
  document.addEventListener("contextmenu", (e) => {
    if (e.target.closest("input, textarea")) return;
    const hit = resolve(e.target);
    if (!hit) {
      closeContextMenu();
      return;
    }
    e.preventDefault();
    openContextMenu(e.clientX, e.clientY, toPost(hit.post), hit.url, hit.where);
  });
  document.addEventListener("mousedown", (e) => {
    if (menu && !menu.contains(e.target)) closeContextMenu();
  }, true);
  window.addEventListener("blur", closeContextMenu);
  window.addEventListener("scroll", closeContextMenu, { passive: true });
  document.addEventListener("keydown", (e) => {
    if (!menu) return;
    const items = [...menu.querySelectorAll(".ctx-item")];
    const i = items.indexOf(document.activeElement);
    if (e.key === "Escape") {
      e.stopImmediatePropagation();
      closeContextMenu();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      e.stopImmediatePropagation();
      const n = (i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items[n].focus();
    } else {
      // Keep global shortcuts quiet while the menu is open (Enter / Space still click natively).
      e.stopImmediatePropagation();
    }
  }, true);
}
