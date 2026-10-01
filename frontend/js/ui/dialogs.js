import { $, el } from "../core/dom.js";
import { api } from "../core/api.js";
import { showToast } from "./toast.js";
import { emit } from "../core/bus.js";

// ─── Confirm ───
const confirmDialog = $("confirm-dialog");
let confirmResolve = null;

export function showConfirmDialog(title, message, confirmLabel = "Remove") {
  return new Promise((resolve) => {
    confirmResolve = resolve;
    $("confirm-dialog-title").textContent = title || "Are you sure?";
    $("confirm-dialog-message").textContent = message || "";
    $("confirm-dialog-confirm").textContent = confirmLabel;
    confirmDialog.classList.remove("hidden");
  });
}

function closeConfirm(result) {
  confirmDialog.classList.add("hidden");
  if (confirmResolve) {
    confirmResolve(result);
    confirmResolve = null;
  }
}

$("confirm-dialog-confirm").addEventListener("click", () => closeConfirm(true));
$("confirm-dialog-cancel").addEventListener("click", () => closeConfirm(false));
confirmDialog.querySelector(".prompt-dialog-backdrop").addEventListener("click", () => closeConfirm(false));

// ─── Prompt ───
const promptDialog = $("prompt-dialog");
const promptInput = $("prompt-dialog-input");
let promptResolve = null;

export function showPromptDialog(title, placeholder, confirmLabel, initialValue = "") {
  return new Promise((resolve) => {
    promptResolve = resolve;
    $("prompt-dialog-title").textContent = title || "Enter name";
    promptInput.placeholder = placeholder || "";
    promptInput.value = initialValue;
    if (confirmLabel) $("prompt-dialog-confirm").textContent = confirmLabel;
    promptDialog.classList.remove("hidden");
    requestAnimationFrame(() => {
      promptInput.focus();
      promptInput.select();
    });
  });
}

function closePrompt(value) {
  promptDialog.classList.add("hidden");
  promptInput.value = "";
  if (promptResolve) {
    promptResolve(value || null);
    promptResolve = null;
  }
}

$("prompt-dialog-confirm").addEventListener("click", () => closePrompt(promptInput.value.trim()));
$("prompt-dialog-cancel").addEventListener("click", () => closePrompt(null));
$("prompt-dialog-close").addEventListener("click", () => closePrompt(null));
promptDialog.querySelector(".prompt-dialog-backdrop").addEventListener("click", () => closePrompt(null));
promptInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") closePrompt(promptInput.value.trim());
  if (e.key === "Escape") closePrompt(null);
});

// ─── Add to collection ───
const colDialog = $("col-dialog");
const colList = $("col-dialog-list");
const colInput = $("col-dialog-input");
let colDialogPost = null;

export function showAddToCollectionDialog(post) {
  colDialogPost = post;
  colDialog.classList.remove("hidden");
  colInput.value = "";
  renderCollectionChoices();
}

export function closeCollectionDialog() {
  colDialog.classList.add("hidden");
  colDialogPost = null;
}

function addPostTo(colId, name) {
  if (!colDialogPost) return Promise.resolve();
  const post = colDialogPost;
  return api.post(`/api/collections/${colId}/posts`, { urls: post.urls, color: post.color || null })
    .then(() => {
      showToast(`✓ Added to “${name}”`);
      emit("collection:added", post);
      closeCollectionDialog();
    });
}

async function renderCollectionChoices() {
  colList.replaceChildren();
  const res = await api.get("/api/collections");
  const cols = res.data.collections || [];
  if (!cols.length) {
    colList.append(el("div", { className: "col-dialog-empty" }, "No collections yet — create one below."));
    return;
  }
  for (const col of cols) {
    colList.append(
      el("div", { className: "col-dialog-item", onclick: () => addPostTo(col.id, col.name) },
        el("span", { className: "col-dialog-item-name" }, col.name),
        el("span", { className: "col-dialog-item-count" }, `${col.count} ${col.count === 1 ? "pin" : "pins"}`),
      ),
    );
  }
}

async function createAndAdd() {
  const name = colInput.value.trim();
  if (!name) {
    colInput.focus();
    return;
  }
  const res = await api.post("/api/collections", { name });
  if (res.data.collection) await addPostTo(res.data.collection.id, name);
}

$("col-dialog-close").addEventListener("click", closeCollectionDialog);
colDialog.querySelector(".col-dialog-backdrop").addEventListener("click", closeCollectionDialog);
$("col-dialog-create-btn").addEventListener("click", createAndAdd);
colInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") createAndAdd();
});

// ─── Shortcuts help ───
const shortcutsDialog = $("shortcuts-dialog");
export const openShortcuts = () => shortcutsDialog.classList.remove("hidden");
export const closeShortcuts = () => shortcutsDialog.classList.add("hidden");
$("shortcuts-close").addEventListener("click", closeShortcuts);
shortcutsDialog.querySelector(".prompt-dialog-backdrop").addEventListener("click", closeShortcuts);

/** Close the top-most open dialog. Returns true if something was closed. */
export function closeTopDialog() {
  if (!shortcutsDialog.classList.contains("hidden")) closeShortcuts();
  else if (!colDialog.classList.contains("hidden")) closeCollectionDialog();
  else if (!confirmDialog.classList.contains("hidden")) closeConfirm(false);
  else if (!promptDialog.classList.contains("hidden")) closePrompt(null);
  else return false;
  return true;
}

export function anyDialogOpen() {
  return [promptDialog, confirmDialog, colDialog, shortcutsDialog].some((d) => !d.classList.contains("hidden"));
}
