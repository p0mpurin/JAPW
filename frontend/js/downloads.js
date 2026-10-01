import { api } from "./core/api.js";
import { state } from "./core/state.js";
import { emit } from "./core/bus.js";
import { showToast } from "./ui/toast.js";

export async function loadDownloadedKeys() {
  const res = await api.get("/api/downloads");
  state.downloadedKeys = new Set(res.data.keys || []);
  emit("downloads:loaded");
}

export async function revealDownload(path = "") {
  const res = await api.post("/api/reveal", { path }).catch(() => null);
  if (!res || !res.ok) showToast("✗ Could not open folder");
}

function revealAction(path) {
  return { label: "Show in folder", onClick: () => revealDownload(path) };
}

async function save(url, key) {
  const res = await api.post("/api/download", { url, key });
  if (!res.ok || !res.data.success) throw new Error(res.data.error || "Download failed");
  state.downloadedKeys.add(key);
  emit("download:done", key);
  return res.data.path;
}

export async function downloadOne(url, key) {
  const again = state.downloadedKeys.has(key);
  try {
    const path = await save(url, key);
    showToast(again ? "✓ Saved again" : "✓ Downloaded", { action: revealAction(path) });
  } catch {
    showToast("✗ Download failed");
  }
}

/** items = [{ url, key }], saved a few at a time. */
export async function downloadMany(items) {
  if (!items.length) {
    showToast("✗ No images to download");
    return;
  }
  showToast(`Downloading ${items.length} images…`);
  let ok = 0;
  let fail = 0;
  let lastPath = "";
  const queue = items.slice();
  const worker = async () => {
    while (queue.length) {
      const it = queue.shift();
      try {
        lastPath = await save(it.url, it.key);
        ok++;
      } catch {
        fail++;
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(4, items.length) }, worker));
  if (!ok) {
    showToast("✗ Download failed");
    return;
  }
  showToast(`✓ ${ok} saved${fail ? `, ${fail} failed` : ""}`, { action: revealAction(lastPath) });
}
