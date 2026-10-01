// Colour control: the palette popover in the top bar and the "● Blue ×" chip in the view bar.
import { $, el } from "./core/dom.js";
import { state } from "./core/state.js";
import { on } from "./core/bus.js";
import { SWATCHES } from "./core/colors.js";
import { setColorFilter, setColorSort } from "./gallery.js";

const button = $("color-btn");
const popover = $("color-popover");
const swatchRow = $("color-swatches");
const sortToggle = $("color-sort");
const chip = $("color-chip");

export function syncColorButton() {
  const swatch = SWATCHES.find((s) => s.id === state.colorFilter);
  button.classList.toggle("active", !!(swatch || state.colorSort));
  button.style.setProperty("--swatch", swatch ? swatch.hex : "var(--accent)");
  button.title = swatch ? `Showing ${swatch.label.toLowerCase()} pins` : state.colorSort ? "Sorted by colour" : "Filter by colour";
  for (const b of swatchRow.children) b.classList.toggle("active", b.dataset.color === state.colorFilter);
  sortToggle.checked = !!state.colorSort;

  chip.classList.toggle("hidden", !swatch);
  if (swatch) {
    chip.style.setProperty("--swatch", swatch.hex);
    chip.querySelector(".chip-label").textContent = swatch.label;
  }
}

export const colorPopoverOpen = () => !popover.classList.contains("hidden");

export function closeColorPopover() {
  popover.classList.add("hidden");
  button.setAttribute("aria-expanded", "false");
}

function openColorPopover() {
  popover.classList.remove("hidden");
  button.setAttribute("aria-expanded", "true");
}

swatchRow.append(...SWATCHES.map((s) => el("button", {
  type: "button",
  className: "color-swatch",
  title: s.label,
  attrs: { "data-color": s.id, "aria-label": s.label },
  style: { "--swatch": s.hex },
  onclick: () => {
    setColorFilter(state.colorFilter === s.id ? null : s.id);
    syncColorButton();
    closeColorPopover();
  },
})));

button.addEventListener("click", (e) => {
  e.stopPropagation();
  if (colorPopoverOpen()) closeColorPopover();
  else openColorPopover();
});

sortToggle.addEventListener("change", () => {
  setColorSort(sortToggle.checked);
  syncColorButton();
});

$("color-clear").addEventListener("click", () => {
  if (state.colorFilter) setColorFilter(null);
  if (state.colorSort) setColorSort(false);
  syncColorButton();
  closeColorPopover();
});

chip.addEventListener("click", () => {
  setColorFilter(null);
  syncColorButton();
});

document.addEventListener("mousedown", (e) => {
  if (colorPopoverOpen() && !popover.contains(e.target) && !button.contains(e.target)) closeColorPopover();
});

on("color:changed", syncColorButton);
on("color:ui", syncColorButton);
syncColorButton();
