// Entry point: wires the modules together and restores the last session.
import { on } from "./core/bus.js";
import { setTab, lastTab } from "./tabs.js";
import { initInfiniteScroll } from "./infinite.js";
import { initShortcuts } from "./shortcuts.js";
import { initContextMenu } from "./contextmenu.js";
import { loadSettings, refreshAuthStatus } from "./settings.js";
import { loadDownloadedKeys } from "./downloads.js";
import { reloadHome } from "./feeds/home.js";
import { runSearch, searchHistory } from "./feeds/search.js";
import { loadLikedKeys } from "./feeds/library.js";
import "./feeds/artists.js";
import "./feeds/boards.js";
import "./feeds/visual.js";
import "./viewer.js";
import "./colorbar.js";

on("auth:connected", reloadHome);
on("auth:disconnected", reloadHome);

async function boot() {
  initInfiniteScroll();
  initShortcuts();
  initContextMenu();
  refreshAuthStatus();
  loadDownloadedKeys().catch(() => {});
  // Likes + resolution settings affect how the first cards render, so wait for them.
  await Promise.allSettled([loadSettings(), loadLikedKeys()]);

  const tab = lastTab();
  const recent = searchHistory()[0];
  if (tab === "search" && recent) runSearch(recent);
  else setTab(tab === "search" || tab === "visual" ? "home" : tab);
}

boot();
