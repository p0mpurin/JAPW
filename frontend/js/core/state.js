// Shared, mutable UI state. Modules read and write it directly; changes that other
// modules must react to go through the event bus.
import { store } from "./store.js";

export const state = {
  tab: "home",
  /** Bumped whenever the gallery is replaced; async callbacks compare against it. */
  feedEpoch: 0,

  likedKeys: new Set(),
  downloadedKeys: new Set(),

  colCount: Math.max(2, Math.min(8, parseInt(store.get("gridZoom", "4"), 10) || 4)),

  selectMode: false,
  selectedKeys: new Set(),

  resFilter: { enabled: false, w: 1920, h: 1080, mode: "min" },

  /** Colour bucket id (see core/colors.js) to show exclusively, or null. */
  colorFilter: null,
  colorSort: false,
  /** True while the active feed is already filtered by colour on the server. */
  serverColor: false,

  /** True once the home feed loaded with a session at least once (distinguishes "expired" from "never connected"). */
  hadSession: false,
};
