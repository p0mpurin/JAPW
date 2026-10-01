import { $, el } from "../core/dom.js";

const toast = $("toast");
let hideTimer = null;
let removeTimer = null;

/** opts.action = { label, onClick } adds a button; opts.duration overrides the default. */
export function showToast(message, opts = {}) {
  clearTimeout(hideTimer);
  clearTimeout(removeTimer);
  toast.replaceChildren(el("span", {}, message));
  toast.classList.toggle("has-action", !!opts.action);
  if (opts.action) {
    toast.append(
      el("button", {
        type: "button",
        className: "toast-action",
        textContent: opts.action.label,
        onclick: () => {
          hideToast();
          opts.action.onClick();
        },
      }),
    );
  }
  toast.classList.remove("hidden");
  requestAnimationFrame(() => toast.classList.add("visible"));
  hideTimer = setTimeout(hideToast, opts.duration || (opts.action ? 5000 : 2500));
}

export function hideToast() {
  clearTimeout(hideTimer);
  toast.classList.remove("visible");
  removeTimer = setTimeout(() => toast.classList.add("hidden"), 400);
}
