// Search by image: drop a file or image link anywhere, paste one (Ctrl+V), pick one with the
// camera button, or right-click a pin → "Find similar images".
import { $, el } from "../core/dom.js";
import { api } from "../core/api.js";
import { state } from "../core/state.js";
import { registerTab, setTab } from "../tabs.js";
import { createPagedFeed } from "./paged.js";
import { showEmpty } from "../ui/feedback.js";
import { showToast } from "../ui/toast.js";
import { setViewbar, vbTitle, vbButton } from "../ui/viewbar.js";
import { showSkeleton, renderPosts } from "../gallery.js";
import { sizedUrl } from "../core/pins.js";

const overlay = $("drop-overlay");
const fileInput = $("visual-file-input");

let searchId = null;
let preview = null; // object URL or image URL shown in the view bar
let busy = false;

const feed = createPagedFeed({
  tab: "visual",
  pageUrl: (offset) => `/api/visual/${searchId}?offset=${offset}&limit=50`,
  onEmpty: () => showEmpty("Nothing similar found", "Try a different crop or image."),
  onError: (_res, message) => showEmpty("Image search failed", message),
});

function renderBar(status) {
  const thumb = preview ? el("img", { className: "vb-thumb", src: preview, alt: "" }) : null;
  setViewbar(
    thumb,
    vbTitle("Similar images", status || ""),
    vbButton("New image", "image", () => fileInput.click(), "Search with another image"),
  );
}

async function run(request, previewUrl) {
  if (busy) return;
  busy = true;
  if (preview && preview.startsWith("blob:")) URL.revokeObjectURL(preview);
  preview = previewUrl;
  searchId = null;
  if (state.tab !== "visual") setTab("visual");
  renderBar("searching…");
  showSkeleton();
  try {
    const res = await request();
    if (state.tab !== "visual") return;
    if (!res.ok) {
      renderPosts([]);
      renderBar();
      showEmpty("Image search failed", res.data.error || "Try another image.");
      return;
    }
    searchId = res.data.id;
    renderBar();
    feed.start();
  } catch {
    renderPosts([]);
    showEmpty("Image search failed", "Check your connection and try again.");
  } finally {
    busy = false;
  }
}

export function searchByFile(file) {
  if (!file || !file.type.startsWith("image/")) {
    showToast("✗ That isn't an image");
    return;
  }
  const form = new FormData();
  form.append("image", file);
  run(async () => {
    const r = await fetch("/api/visual", { method: "POST", body: form });
    return { ok: r.ok, data: await r.json().catch(() => ({})) };
  }, URL.createObjectURL(file));
}

export function searchByUrl(url) {
  run(() => api.post("/api/visual", { url }), url);
}

/** Right-click → Find similar images (uses a mid-size rendition: plenty for matching). */
export function searchByPost(post, url) {
  searchByUrl(sizedUrl(url || post.urls[0], 736));
}

registerTab("visual", {
  enter() {
    if (searchId && feed.started) {
      renderBar();
      feed.show();
    } else if (!busy) {
      renderBar();
      showEmpty("Search by image", "Drop an image anywhere, paste one with Ctrl+V, or pick a file.",
        { label: "Choose an image", onClick: () => fileInput.click() });
    }
  },
  loadMore: () => searchId && feed.more(),
  refresh: () => searchId && feed.start(),
});

// ─── Entry points ───
$("visual-btn").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  const file = fileInput.files && fileInput.files[0];
  fileInput.value = "";
  if (file) searchByFile(file);
});

// Drags that start on our own cards are image exports, not searches.
let internalDrag = false;
document.addEventListener("dragstart", () => {
  internalDrag = true;
});
document.addEventListener("dragend", () => {
  internalDrag = false;
});

const isImageDrag = (e) => !internalDrag && [...(e.dataTransfer?.types || [])]
  .some((t) => t === "Files" || t === "text/uri-list");

let dragDepth = 0;
document.addEventListener("dragenter", (e) => {
  if (!isImageDrag(e)) return;
  dragDepth++;
  overlay.classList.remove("hidden");
});
document.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) overlay.classList.add("hidden");
});
document.addEventListener("dragover", (e) => {
  if (isImageDrag(e)) e.preventDefault();
});
document.addEventListener("drop", (e) => {
  dragDepth = 0;
  overlay.classList.add("hidden");
  if (internalDrag) return;
  const file = [...(e.dataTransfer?.files || [])].find((f) => f.type.startsWith("image/"));
  const url = (e.dataTransfer?.getData("text/uri-list") || "").split("\n").find((u) => u.startsWith("http"));
  if (!file && !url) return;
  e.preventDefault();
  if (file) searchByFile(file);
  else searchByUrl(url.trim());
});

document.addEventListener("paste", (e) => {
  const file = [...(e.clipboardData?.files || [])].find((f) => f.type.startsWith("image/"));
  if (!file) return;
  e.preventDefault();
  searchByFile(file);
});
