// Artists tab: media from X creators, fetched directly from X and paged like Pinterest feeds.
import { $, el } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { api } from "../core/api.js";
import { state } from "../core/state.js";
import { registerTab } from "../tabs.js";
import { createPagedFeed } from "./paged.js";
import { showEmpty } from "../ui/feedback.js";
import { showToast } from "../ui/toast.js";
import { showConfirmDialog } from "../ui/dialogs.js";
import { setViewbar, vbButton } from "../ui/viewbar.js";

const panel = $("x-panel");
const panelBackdrop = $("x-panel-backdrop");
const addInput = $("x-add-input");
const addBtn = $("x-add-btn");
const artistsList = $("x-artists-list");
const sessionStatus = $("x-session-status");
const syncBtn = $("x-sync-btn");
const disconnectBtn = $("x-disconnect-btn");

let artists = [];
let active = null; // username, or null for everyone
let refreshNext = false;
let panelOpen = false;

const syncAction = {
  label: "Sync X login",
  onClick: async (btn) => {
    btn.disabled = true;
    btn.textContent = "Syncing…";
    if (await syncSession()) enter();
    else {
      btn.disabled = false;
      btn.textContent = "Sync X login";
    }
  },
};

const feed = createPagedFeed({
  tab: "artists",
  pageUrl: (offset) => {
    const params = new URLSearchParams({ offset, limit: 40 });
    if (active) params.set("username", active);
    if (refreshNext && offset === 0) params.set("refresh", "1");
    refreshNext = false;
    return `/x/media?${params}`;
  },
  onEmpty() {
    showEmpty("No images yet", active ? `@${active} hasn't posted any images (or the account is private).` : "These artists haven't posted any images yet.");
  },
  onError(res, message) {
    if (res && res.status === 401) {
      showEmpty("Connect X", "Log in to x.com in your browser, then sync your login here.", syncAction);
      return;
    }
    showEmpty("Could not load artists", message);
  },
});

// ─── View bar ───
function avatarImg(a) {
  if (!a.avatar_url) return null;
  const img = el("img", { src: a.avatar_url, alt: "" });
  img.onerror = () => img.remove();
  return img;
}

function renderBar() {
  const chip = (label, value, a) => el("button", {
    type: "button",
    className: `chip${active === value ? " active" : ""}`,
    title: a ? a.display_name || a.username : "Everyone",
    onclick: () => {
      if (active === value) return;
      active = value;
      renderBar();
      feed.start();
    },
  }, a ? avatarImg(a) : null, label);
  const chips = el("div", { className: "chips" },
    chip("All", null), ...artists.map((a) => chip(a.display_name || `@${a.username}`, a.username, a)));
  setViewbar(chips, vbButton("Refresh", "refresh", refresh, "Refresh (R)"), vbButton("Manage", "plus", openArtistsPanel));
}

// ─── Panel ───
export function openArtistsPanel() {
  panelOpen = true;
  panel.classList.add("open");
  panelBackdrop.classList.add("open");
  renderArtistsList();
  refreshSessionStatus();
  setTimeout(() => addInput.focus(), 150);
}

export function closeArtistsPanel() {
  panelOpen = false;
  panel.classList.remove("open");
  panelBackdrop.classList.remove("open");
}

export const artistsPanelOpen = () => panelOpen;

async function refreshSessionStatus() {
  const res = await api.get("/x/auth/status").catch(() => null);
  if (!res) return;
  const connected = !!res.data.connected;
  sessionStatus.classList.toggle("is-ok", connected);
  sessionStatus.querySelector(".status-text").textContent = connected ? "Connected" : "Not connected";
  syncBtn.textContent = connected ? "Re-sync" : "Sync from browser";
  disconnectBtn.classList.toggle("hidden", !connected);
}

async function syncSession() {
  const res = await api.post("/x/auth/sync").catch(() => null);
  if (!res || !res.ok) {
    showToast(`✗ ${(res && res.data.error) || "Sync failed"}`);
    return false;
  }
  showToast("✓ X login synced");
  refreshSessionStatus();
  return true;
}

function artistRow(artist) {
  const avatar = el("div", { className: "artist-avatar" }, (artist.username[0] || "?").toUpperCase());
  if (artist.avatar_url) {
    const img = el("img", { src: artist.avatar_url, alt: "" });
    img.onload = () => avatar.replaceChildren(img);
  }
  return el("div", { className: "artist-row" },
    avatar,
    el("div", { className: "artist-info" },
      el("div", { className: "artist-name" }, artist.display_name || artist.username),
      el("div", { className: "artist-handle" }, `@${artist.username}`),
    ),
    el("button", {
      type: "button",
      className: "icon-btn icon-btn-sm",
      title: `Remove @${artist.username}`,
      attrs: { "aria-label": `Remove @${artist.username}` },
      html: icon("trash", 14),
      onclick: async () => {
        const ok = await showConfirmDialog("Remove artist", `Stop following @${artist.username} in JAPW?`, "Remove");
        if (ok) removeArtist(artist.username);
      },
    }),
  );
}

function renderArtistsList() {
  artistsList.replaceChildren(...(artists.length
    ? artists.map(artistRow)
    : [el("p", { className: "artist-empty" }, "No artists yet — add one above.")]));
}

async function addArtist(raw) {
  const username = raw.trim();
  if (!username) return;
  addBtn.disabled = true;
  addBtn.textContent = "Adding…";
  try {
    const res = await api.post("/x/artists", { username });
    if (res.status === 409) {
      showToast(`${username} is already in your list`);
      return;
    }
    if (!res.ok) {
      showToast(`✗ ${res.data.error || "Could not add artist"}`);
      return;
    }
    artists.push(res.data);
    addInput.value = "";
    renderArtistsList();
    showToast(`Added @${res.data.username}`);
    if (state.tab === "artists") {
      active = res.data.username;
      renderBar();
      feed.start();
    }
  } catch {
    showToast("✗ Could not add artist");
  } finally {
    addBtn.disabled = false;
    addBtn.textContent = "Add";
  }
}

async function removeArtist(username) {
  const res = await api.del(`/x/artists/${encodeURIComponent(username)}`).catch(() => null);
  if (!res) {
    showToast("✗ Could not remove artist");
    return;
  }
  artists = artists.filter((a) => a.username !== username);
  if (active === username) active = null;
  renderArtistsList();
  showToast(`Removed @${username}`);
  if (state.tab === "artists") enter();
}

// ─── Tab ───
async function enter() {
  const res = await api.get("/x/artists").catch(() => null);
  if (state.tab !== "artists") return;
  artists = res && Array.isArray(res.data) ? res.data : [];
  if (active && !artists.some((a) => a.username === active)) active = null;
  renderBar();
  if (!artists.length) {
    showEmpty("Follow some artists", "Add X creators and browse all their art in one place.",
      { label: "Add an artist", onClick: openArtistsPanel });
    return;
  }
  if (feed.started && feed.posts.length) feed.show();
  else feed.start();
}

function refresh() {
  showToast("Refreshing artists…");
  refreshNext = true;
  feed.start();
}

registerTab("artists", {
  enter,
  loadMore: () => feed.more(),
  refresh,
});

$("x-panel-close").addEventListener("click", closeArtistsPanel);
panelBackdrop.addEventListener("click", closeArtistsPanel);
addBtn.addEventListener("click", () => addArtist(addInput.value));
addInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") addArtist(addInput.value);
});
syncBtn.addEventListener("click", async () => {
  syncBtn.disabled = true;
  syncBtn.textContent = "Syncing…";
  await syncSession();
  syncBtn.disabled = false;
  refreshSessionStatus();
});
disconnectBtn.addEventListener("click", async () => {
  await api.post("/x/auth/logout");
  showToast("X login removed");
  refreshSessionStatus();
});
