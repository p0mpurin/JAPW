// Global keyboard shortcuts (see the "?" help dialog in index.html).
import { isTypingTarget } from "./core/dom.js";
import { state } from "./core/state.js";
import { setTab, refreshCurrent, TAB_ORDER } from "./tabs.js";
import { hoveredPost, setColCount, toggleSelectMode } from "./gallery.js";
import { viewerOpen, viewerTarget, closeViewer, stepSlide } from "./viewer.js";
import { actions } from "./actions.js";
import { focusSearch } from "./feeds/search.js";
import { artistsPanelOpen, closeArtistsPanel } from "./feeds/artists.js";
import { openSettings, closeSettings, settingsOpen } from "./settings.js";
import { anyDialogOpen, closeTopDialog, openShortcuts } from "./ui/dialogs.js";
import { showToast } from "./ui/toast.js";
import { colorPopoverOpen, closeColorPopover } from "./colorbar.js";

/** The post a shortcut acts on: the open viewer's pin, else the hovered card. */
function target() {
  const t = viewerTarget();
  if (t) return t;
  const post = hoveredPost();
  return post ? { post, url: post.urls[0] } : null;
}

const POST_KEYS = {
  async l({ post }) {
    const liked = await actions.toggleLike(post);
    if (liked !== null) showToast(liked ? "♥ Liked" : "Removed from liked");
  },
  d: ({ post, url }) => actions.download(post, post.gif_video_url || url),
  c: ({ post }) => actions.addToCollection(post),
  o: ({ post, url }) => actions.openExternal(post, url),
  y: ({ post, url }) => actions.copyLink(url, post),
};

const GLOBAL_KEYS = {
  r: refreshCurrent,
  "-": () => setColCount(state.colCount + 1),
  "=": () => setColCount(state.colCount - 1),
  "+": () => setColCount(state.colCount - 1),
  s: toggleSelectMode,
  ",": openSettings,
  "?": openShortcuts,
};

function onEscape() {
  if (colorPopoverOpen()) {
    closeColorPopover();
    return;
  }
  if (closeTopDialog()) return;
  if (settingsOpen()) closeSettings();
  else if (artistsPanelOpen()) closeArtistsPanel();
  else if (viewerOpen()) closeViewer();
  else if (document.activeElement && isTypingTarget(document.activeElement)) document.activeElement.blur();
}

export function initShortcuts() {
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      onEscape();
      return;
    }
    const ctrlK = (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k";
    if (!ctrlK && (e.ctrlKey || e.metaKey || e.altKey)) return;
    if (isTypingTarget(e.target) || anyDialogOpen() || settingsOpen() || artistsPanelOpen()) return;

    if (ctrlK || e.key === "/") {
      e.preventDefault();
      if (viewerOpen()) closeViewer();
      focusSearch();
      return;
    }

    if (viewerOpen() && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
      stepSlide(e.key === "ArrowLeft" ? -1 : 1);
      return;
    }

    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (POST_KEYS[k]) {
      const t = target();
      if (t) {
        e.preventDefault();
        POST_KEYS[k](t);
        return;
      }
    }
    if (viewerOpen()) return;

    if (k >= "1" && k <= String(TAB_ORDER.length)) {
      const tab = TAB_ORDER[Number(k) - 1];
      if (tab !== state.tab) setTab(tab);
    } else if (GLOBAL_KEYS[k]) {
      GLOBAL_KEYS[k]();
    } else {
      return;
    }
    e.preventDefault();
  });
}
