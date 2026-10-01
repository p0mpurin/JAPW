// Things you can do to a post — shared by cards, the viewer, the context menu and shortcuts.
// Meaningful ones are also reported as taste signals (stored locally) for the For You feed.
import { api } from "./core/api.js";
import { state } from "./core/state.js";
import { emit, on } from "./core/bus.js";
import { canonicalKey } from "./core/pins.js";
import { showToast } from "./ui/toast.js";
import { showAddToCollectionDialog } from "./ui/dialogs.js";
import { downloadOne, downloadMany } from "./downloads.js";

const keyOf = (post) => canonicalKey(post.urls[0]);

function signal(kind, post) {
  if (!post || !post.urls || !post.urls.length) return;
  api.post("/api/taste/signal", {
    kind,
    post: { urls: post.urls.slice(0, 1), pin_url: post.pin_url, color: post.color, source: post.source, artist: post.artist },
  }).catch(() => {});
}

on("collection:added", (post) => signal("collect", post));

export const actions = {
  signal,

  async toggleLike(post) {
    if (!post || !post.urls.length) return null;
    const res = await api.post("/api/likes/toggle", { urls: post.urls, color: post.color || null }).catch(() => null);
    if (!res || !res.ok) {
      showToast("✗ Could not update like");
      return null;
    }
    const { liked, key } = res.data;
    if (liked) {
      state.likedKeys.add(key);
      signal("like", post);
    } else {
      state.likedKeys.delete(key);
    }
    emit("like:changed", { key, liked, post });
    return liked;
  },

  /** url defaults to the post's cover (or its GIF video). */
  download(post, url) {
    signal("download", post);
    return downloadOne(url || post.gif_video_url || post.urls[0], keyOf(post));
  },

  downloadMany(posts) {
    posts.forEach((p) => signal("download", p));
    return downloadMany(posts.map((p) => ({ url: p.gif_video_url || p.urls[0], key: keyOf(p) })));
  },

  addToCollection(post) {
    showAddToCollectionDialog(post);
  },

  openExternal(post, url) {
    signal("open", post);
    api.post("/api/open-url", { url: post.pin_url || url || post.urls[0] }).catch(() => {});
  },

  async copyLink(url, post) {
    if (post) signal("copy", post);
    // Native clipboard first (always allowed in the desktop app), browser API as fallback.
    const res = await api.post("/api/clipboard", { text: url }).catch(() => null);
    if (res && res.ok) {
      showToast("✓ Link copied");
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      showToast("✓ Link copied");
    } catch {
      showToast("✗ Copy failed");
    }
  },

  /** Put the picture itself on the clipboard (paste straight into Discord, Photoshop, …). */
  async copyImage(url, post) {
    if (post) signal("copy", post);
    showToast("Copying image…", { duration: 8000 });
    const res = await api.post("/api/clipboard", { url }).catch(() => null);
    if (res && res.ok) {
      showToast("✓ Image copied — paste it anywhere");
      return;
    }
    if (res && res.status !== 501) {
      showToast(`✗ ${res.data.error || "Could not copy image"}`);
      return;
    }
    try {
      // Browser fallback: only PNG is accepted on the clipboard; the backend converts it.
      const png = fetch(`/api/image.png?url=${encodeURIComponent(url)}`).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.blob();
      });
      await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
      showToast("✓ Image copied — paste it anywhere");
    } catch {
      showToast("✗ Could not copy image");
    }
  },
};
