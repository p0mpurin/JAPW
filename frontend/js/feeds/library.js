// Local library: Liked and Collections tabs.
import { $, el } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { api } from "../core/api.js";
import { state } from "../core/state.js";
import { on } from "../core/bus.js";
import { canonicalKey, pinimgSize } from "../core/pins.js";
import { registerTab } from "../tabs.js";
import { renderPosts, removePost, postCount, showSkeleton } from "../gallery.js";
import { showEmpty, hideEmpty } from "../ui/feedback.js";
import { showConfirmDialog, showPromptDialog } from "../ui/dialogs.js";
import { showToast } from "../ui/toast.js";
import { setViewbar, vbBack, vbButton, vbTitle } from "../ui/viewbar.js";

const gallery = $("gallery");
const tiles = $("collections-view");

const toPosts = (list) => (list || [])
  .map((p) => ({ urls: p.urls || [], color: p.color || null, pin_url: p.pin_url || null }))
  .filter((p) => p.urls.length);

const countLabel = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Fetch a list endpoint and render it into the grid, guarding against tab switches. */
async function loadIntoGrid(path, emptyTitle, emptySub) {
  const epoch = ++state.feedEpoch;
  hideEmpty();
  showSkeleton(12);
  const res = await api.get(path).catch(() => null);
  if (epoch !== state.feedEpoch) return null;
  if (!res || !res.ok) {
    renderPosts([]);
    showEmpty("Could not load", "Try again.");
    return null;
  }
  const posts = toPosts(res.data.posts);
  renderPosts(posts);
  if (!posts.length) showEmpty(emptyTitle, emptySub);
  return { ...res.data, count: posts.length };
}

// ─── Liked ───
export async function loadLikedKeys() {
  const res = await api.get("/api/likes").catch(() => null);
  if (res && res.ok) state.likedKeys = new Set((res.data.posts || []).map((p) => p.key).filter(Boolean));
}

async function loadLiked() {
  setViewbar(vbTitle("Liked"));
  const data = await loadIntoGrid("/api/likes", "No liked pins yet", "Press the heart (or L) on any image to keep it here.");
  if (data && state.tab === "liked") setViewbar(vbTitle("Liked", countLabel(data.count, "pin")));
}

registerTab("liked", { enter: loadLiked, refresh: loadLiked });

on("like:changed", ({ key, liked }) => {
  if (state.tab !== "liked" || liked) return;
  removePost(key);
  setViewbar(vbTitle("Liked", countLabel(postCount(), "pin")));
  if (!postCount()) showEmpty("No liked pins yet", "Press the heart (or L) on any image to keep it here.");
});

// ─── Collections ───
let openCollectionId = null;
let collectionsCache = [];

/** The collection currently open in the grid (for "Remove from collection"), or null. */
export function currentCollection() {
  if (state.tab !== "collections" || !openCollectionId) return null;
  return collectionsCache.find((c) => c.id === openCollectionId) || { id: openCollectionId, name: "collection" };
}

export async function removeFromCurrentCollection(post) {
  const col = currentCollection();
  if (!col) return;
  const key = canonicalKey(post.urls[0]);
  const res = await api.del(`/api/collections/${col.id}/posts`, { key }).catch(() => null);
  if (!res || !res.ok) {
    showToast("✗ Could not remove");
    return;
  }
  removePost(key);
  showToast(`Removed from “${col.name}”`);
  if (!postCount()) showEmpty("Empty collection", "Right-click any image and choose “Add to collection”.");
}

async function createCollection() {
  const name = await showPromptDialog("New collection", "Collection name…", "Create");
  if (!name) return;
  const res = await api.post("/api/collections", { name });
  if (res.data.collection) loadCollectionsGrid();
}

function collectionTile(col, index) {
  const cover = col.cover
    ? el("img", { className: "tile-cover", src: pinimgSize(col.cover, "474x"), alt: "", loading: "lazy" })
    : el("div", { className: "tile-cover-empty", html: icon("folder", 26, 1.5) });
  return el("div", {
    className: "tile",
    style: { animationDelay: `${index * 30}ms` },
    onclick: () => openCollection(col),
  },
  cover,
  el("div", { className: "tile-info" },
    el("div", { className: "tile-name" }, col.name),
    el("div", { className: "tile-count" }, countLabel(col.count, "pin")),
  ),
  el("button", {
    className: "tile-del",
    title: "Delete collection",
    attrs: { "aria-label": "Delete collection" },
    html: icon("trash", 13),
    onclick: async (e) => {
      e.stopPropagation();
      const ok = await showConfirmDialog("Delete collection", `Delete “${col.name}”? The pins stay on Pinterest; only this list is removed.`, "Delete");
      if (!ok) return;
      await api.del(`/api/collections/${col.id}`);
      loadCollectionsGrid();
    },
  }));
}

async function loadCollectionsGrid() {
  openCollectionId = null;
  gallery.classList.add("hidden");
  tiles.classList.remove("hidden");
  tiles.replaceChildren();
  setViewbar(vbTitle("Collections"), vbButton("New collection", "plus", createCollection));
  const res = await api.get("/api/collections").catch(() => null);
  if (state.tab !== "collections" || openCollectionId) return;
  if (!res || !res.ok) {
    tiles.append(el("div", { className: "tiles-message" }, "Could not load collections."));
    return;
  }
  collectionsCache = res.data.collections || [];
  setViewbar(vbTitle("Collections", collectionsCache.length ? String(collectionsCache.length) : ""),
    vbButton("New collection", "plus", createCollection));
  collectionsCache.forEach((col, i) => tiles.append(collectionTile(col, i)));
  tiles.append(el("button", {
    type: "button",
    className: "tile tile-new",
    html: `${icon("plus", 22)}<span>New collection</span>`,
    onclick: createCollection,
  }));
}

async function renameCollection(col) {
  const name = await showPromptDialog("Rename collection", "Collection name…", "Rename", col.name);
  if (!name || name === col.name) return;
  const res = await api.patch(`/api/collections/${col.id}`, { name }).catch(() => null);
  if (!res || !res.ok) {
    showToast("✗ Could not rename");
    return;
  }
  col.name = name;
  collectionBar(col, postCount());
}

function collectionBar(col, count) {
  setViewbar(
    vbBack("Collections", loadCollectionsGrid),
    vbTitle(col.name, count == null ? "" : countLabel(count, "pin")),
    vbButton("Rename", "folder", () => renameCollection(col)),
  );
}

async function openCollection(col) {
  openCollectionId = col.id;
  tiles.classList.add("hidden");
  gallery.classList.remove("hidden");
  collectionBar(col);
  const data = await loadIntoGrid(`/api/collections/${col.id}/posts`, "Empty collection",
    "Right-click any image and choose “Add to collection”.");
  if (data && openCollectionId === col.id) collectionBar(col, data.count);
}

registerTab("collections", {
  enter: loadCollectionsGrid,
  leave() {
    openCollectionId = null;
    tiles.classList.add("hidden");
  },
  refresh() {
    const col = collectionsCache.find((c) => c.id === openCollectionId);
    if (col) openCollection(col);
    else loadCollectionsGrid();
  },
});
