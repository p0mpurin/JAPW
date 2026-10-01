// Settings panel, Pinterest session (sync / status / expiry banner) and backup.
import { $, el } from "./core/dom.js";
import { SWATCHES } from "./core/colors.js";
import { showConfirmDialog } from "./ui/dialogs.js";
import { api } from "./core/api.js";
import { state } from "./core/state.js";
import { on, emit } from "./core/bus.js";
import { showToast } from "./ui/toast.js";
import { reapplyResolutionFilter } from "./gallery.js";

const panel = $("settings-panel");
const backdrop = $("settings-backdrop");
const authDot = $("auth-dot");
const status = $("pinterest-status");
const connectBtn = $("pinterest-connect-btn");
const openBrowserBtn = $("pinterest-open-browser-btn");
const disconnectBtn = $("pinterest-disconnect-btn");
const folderInput = $("download-folder");
const resEnabled = $("resolution-filter-enabled");
const resWidth = $("resolution-width");
const resHeight = $("resolution-height");
const resMode = $("resolution-match-mode");
const filterPromoted = $("filter-promoted");
const filterAi = $("filter-ai-content");
const banner = $("session-banner");
const bannerSync = $("session-banner-sync");

// ─── Panel ───
export function openSettings() {
  panel.classList.add("visible");
  backdrop.classList.add("visible");
  loadSettings();
  refreshAuthStatus();
  loadTaste();
}

export function closeSettings() {
  panel.classList.remove("visible");
  backdrop.classList.remove("visible");
}

export const settingsOpen = () => panel.classList.contains("visible");

$("settings-btn").addEventListener("click", openSettings);
$("settings-close").addEventListener("click", closeSettings);
backdrop.addEventListener("click", closeSettings);

// ─── Settings values ───
export function applyResolutionConfig(data) {
  Object.assign(state.resFilter, {
    enabled: !!data.resolution_filter_enabled,
    w: Math.max(1, parseInt(data.resolution_target_width, 10) || 1920),
    h: Math.max(1, parseInt(data.resolution_target_height, 10) || 1080),
    mode: data.resolution_match_mode === "exact" ? "exact" : "min",
  });
}

function fillForm(data) {
  folderInput.value = data.download_folder || "";
  resEnabled.checked = !!data.resolution_filter_enabled;
  resWidth.value = String(data.resolution_target_width || 1920);
  resHeight.value = String(data.resolution_target_height || 1080);
  resMode.value = data.resolution_match_mode === "exact" ? "exact" : "min";
  filterPromoted.checked = data.filter_promoted !== false;
  filterAi.checked = !!data.filter_ai_content;
  applyResolutionConfig(data);
}

export async function loadSettings() {
  const res = await api.get("/api/settings").catch(() => null);
  if (res && res.ok) fillForm(res.data);
  return res ? res.data : {};
}

async function saveSettings(patch) {
  const res = await api.post("/api/settings", patch).catch(() => null);
  return !!(res && res.ok);
}

$("resolution-filter-save-btn").addEventListener("click", async () => {
  const ok = await saveSettings({
    resolution_filter_enabled: resEnabled.checked,
    resolution_target_width: parseInt(resWidth.value, 10) || 1920,
    resolution_target_height: parseInt(resHeight.value, 10) || 1080,
    resolution_match_mode: resMode.value || "min",
  });
  if (!ok) {
    showToast("✗ Could not save filter");
    return;
  }
  await loadSettings();
  reapplyResolutionFilter();
  showToast("✓ Resolution filter saved");
});

for (const [box, key] of [[filterPromoted, "filter_promoted"], [filterAi, "filter_ai_content"]]) {
  box.addEventListener("change", async () => {
    const ok = await saveSettings({ [key]: box.checked });
    showToast(ok ? (box.checked ? "✓ Filter enabled" : "✓ Filter disabled") : "✗ Could not save setting");
  });
}

$("folder-picker-btn").addEventListener("click", async () => {
  if (!window.pywebview) return;
  const folder = await window.pywebview.api.pick_folder();
  if (!folder) return;
  folderInput.value = folder;
  saveSettings({ download_folder: folder });
});

// ─── Pinterest session ───
function applyAuthStatus(data) {
  const connected = !!data.connected;
  const busy = !!data.login_in_progress;
  const label = busy ? "Syncing…" : connected ? "Connected" : "Not connected";
  authDot.className = `status-dot${busy ? " is-busy" : connected ? " is-ok" : ""}`;
  authDot.title = `Pinterest: ${label.toLowerCase()}`;
  status.classList.toggle("is-ok", connected && !busy);
  status.classList.toggle("is-busy", busy);
  status.querySelector(".status-text").textContent = busy
    ? "Reading your login from installed browsers…"
    : connected ? "Connected — Home, For you, boards and search use your account." : "Not connected";
  disconnectBtn.classList.toggle("hidden", !connected || busy);
  connectBtn.disabled = busy;
  openBrowserBtn.disabled = busy;
}

export async function refreshAuthStatus() {
  const res = await api.get("/api/auth/status").catch(() => null);
  if (res) applyAuthStatus(res.data);
}

let pollTimer = null;

function resetBannerButton() {
  bannerSync.disabled = false;
  bannerSync.textContent = "Sync now";
}

function pollLogin() {
  clearInterval(pollTimer);
  let ticks = 0;
  pollTimer = setInterval(async () => {
    if (++ticks > 720) {
      clearInterval(pollTimer);
      showToast("✗ Sync timed out");
      resetBannerButton();
      refreshAuthStatus();
      return;
    }
    const res = await api.get("/api/auth/status").catch(() => null);
    if (!res) return;
    applyAuthStatus(res.data);
    if (res.data.login_in_progress) return;
    clearInterval(pollTimer);
    if (res.data.last_error) {
      showToast(`✗ ${res.data.last_error}`);
      resetBannerButton();
    } else if (res.data.connected) {
      hideSessionBanner();
      showToast("✓ Pinterest connected");
      emit("auth:connected");
    }
  }, 1000);
}

export async function startSync() {
  const res = await api.post("/api/auth/login").catch(() => null);
  if (!res) {
    showToast("✗ Could not start sync");
    resetBannerButton();
    return;
  }
  if (res.status === 409) {
    showToast("✗ Sync already in progress");
    return;
  }
  showToast("Syncing with your browsers…");
  pollLogin();
  refreshAuthStatus();
}

connectBtn.addEventListener("click", startSync);
on("auth:sync", startSync);

openBrowserBtn.addEventListener("click", async () => {
  const res = await api.post("/api/auth/open-browser").catch(() => null);
  showToast(res && res.ok ? "Opened Pinterest in your default browser" : "✗ Could not open browser");
});

disconnectBtn.addEventListener("click", async () => {
  const res = await api.post("/api/auth/logout").catch(() => null);
  if (!res) {
    showToast("✗ Disconnect failed");
    return;
  }
  showToast("Pinterest session cleared");
  refreshAuthStatus();
  emit("auth:disconnected");
});

// ─── Session-expired banner ───
function showSessionBanner() {
  banner.classList.remove("hidden");
}

function hideSessionBanner() {
  banner.classList.add("hidden");
  resetBannerButton();
}

on("session:expired", showSessionBanner);
bannerSync.addEventListener("click", () => {
  bannerSync.disabled = true;
  bannerSync.textContent = "Syncing…";
  startSync();
});
$("session-banner-close").addEventListener("click", hideSessionBanner);

// ─── For You taste profile ───
async function loadTaste() {
  const res = await api.get("/api/taste").catch(() => null);
  if (!res || !res.ok) return;
  const { events, counts, colors } = res.data;
  const parts = Object.entries(counts || {})
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `${n} ${{ view: "viewed", open: "opened", copy: "copied", download: "downloaded", like: "liked", collect: "collected" }[k] || k}`);
  $("taste-summary").textContent = events
    ? `Learned from ${parts.join(", ")}. Everything stays on this computer.`
    : "Open, like, download and copy pins — For You learns from it. Everything stays on this computer.";
  $("taste-colors").replaceChildren(...(colors || []).map((id) => {
    const s = SWATCHES.find((x) => x.id === id);
    return s ? el("span", { className: "chip", style: { "--swatch": s.hex } }, el("span", { className: "chip-dot" }), s.label) : null;
  }).filter(Boolean));
}

$("taste-reset").addEventListener("click", async () => {
  const ok = await showConfirmDialog("Reset For You", "Forget everything For You has learned about your taste?", "Reset");
  if (!ok) return;
  await api.post("/api/taste/reset").catch(() => null);
  showToast("For You has been reset");
  loadTaste();
});

// ─── Backup / restore ───
const exportBtn = $("export-btn");
const importBtn = $("import-btn");
const importInput = $("import-file-input");

exportBtn.addEventListener("click", async () => {
  exportBtn.disabled = true;
  try {
    const res = await fetch("/api/export");
    if (!res.ok) throw new Error("Export failed");
    const text = await res.text();
    // In pywebview <a download> clicks are silently dropped — use the native save dialog.
    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_file) {
      const path = await window.pywebview.api.save_file(text, "japw_backup.json");
      if (path) showToast("✓ Backup saved");
    } else {
      const blobUrl = URL.createObjectURL(new Blob([text], { type: "application/json" }));
      const a = Object.assign(document.createElement("a"), { href: blobUrl, download: "japw_backup.json" });
      document.body.append(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      showToast("✓ Backup exported");
    }
  } catch {
    showToast("✗ Export failed");
  } finally {
    exportBtn.disabled = false;
  }
});

importBtn.addEventListener("click", () => {
  importInput.value = "";
  importInput.click();
});

importInput.addEventListener("change", async () => {
  const file = importInput.files && importInput.files[0];
  if (!file) return;
  let data;
  try {
    data = JSON.parse(await file.text());
  } catch {
    showToast("Invalid backup file");
    return;
  }
  importBtn.disabled = true;
  try {
    const res = await api.post("/api/import", data);
    if (res.data.success) {
      showToast("Backup restored — restart to apply all changes");
      loadSettings();
    } else {
      showToast(`Import error: ${(res.data.errors || [res.data.error]).join(", ")}`);
    }
  } catch {
    showToast("Import failed");
  } finally {
    importBtn.disabled = false;
  }
});
