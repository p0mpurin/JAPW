// The bar under the top bar: each view puts its own controls here (title, mode switch,
// artist chips, back button…); the right side shows progress and the active colour filter.
import { $, el } from "../core/dom.js";
import { icon } from "../core/icons.js";

const main = $("viewbar-main");
const progress = $("viewbar-progress");

export function setViewbar(...nodes) {
  main.replaceChildren(...nodes.filter(Boolean));
}

export function setProgress(text) {
  progress.textContent = text || "";
  progress.classList.toggle("hidden", !text);
}

export const vbTitle = (text, sub) => el("div", { className: "vb-heading" },
  el("span", { className: "vb-title" }, text),
  sub ? el("span", { className: "vb-sub" }, ` ${sub}`) : null);

export const vbBack = (label, onClick) => el("button", {
  type: "button",
  className: "vb-back",
  html: icon("chevronLeft", 15),
  onclick: onClick,
}, label);

export function vbButton(label, iconName, onClick, title = "") {
  const b = el("button", { type: "button", className: "vb-btn", title, html: icon(iconName, 14), onclick: onClick });
  b.append(label);
  return b;
}

/** Segmented control: options = [{ id, label }]. Returns { node, set(id) }. */
export function segmented(options, active, onChange) {
  const node = el("div", { className: "seg", attrs: { role: "tablist" } });
  const set = (id) => {
    for (const b of node.children) b.classList.toggle("active", b.dataset.id === id);
  };
  for (const o of options) {
    node.append(el("button", {
      type: "button",
      className: "seg-btn",
      attrs: { "data-id": o.id, role: "tab" },
      html: o.icon ? icon(o.icon, 13) : "",
      onclick: () => {
        set(o.id);
        onChange(o.id);
      },
    }, o.label));
  }
  set(active);
  return { node, set };
}
