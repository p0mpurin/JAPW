export const $ = (id) => document.getElementById(id);

/**
 * el("button", { className: "x", onclick: fn, attrs: { "aria-label": "Close" } }, child, "text")
 * `html` sets innerHTML (only for trusted, static markup such as icons).
 */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null) continue;
    if (k === "attrs") {
      for (const [a, av] of Object.entries(v)) node.setAttribute(a, av);
    } else if (k === "style" && typeof v === "object") {
      // Custom properties ("--swatch") need setProperty; plain assignment silently drops them.
      for (const [prop, pv] of Object.entries(v)) {
        if (prop.startsWith("--")) node.style.setProperty(prop, pv);
        else node.style[prop] = pv;
      }
    } else if (k === "html") {
      node.innerHTML = v;
    } else if (k.startsWith("on") && typeof v === "function") {
      node.addEventListener(k.slice(2), v);
    } else {
      node[k] = v;
    }
  }
  for (const c of children) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : String(c));
  }
  return node;
}

export function rafTwice(fn) {
  requestAnimationFrame(() => requestAnimationFrame(fn));
}

export function isTypingTarget(node) {
  if (!node) return false;
  const tag = node.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || node.isContentEditable;
}
