import { emit } from "./bus.js";

/**
 * Thin JSON client for the local Flask API.
 * Resolves to { ok, status, data } and never throws for HTTP errors —
 * only for network failures. A 401 with code=session_expired fires "session:expired".
 */
async function request(method, path, body) {
  const init = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (res.status === 401 && data && data.code === "session_expired") emit("session:expired");
  return { ok: res.ok && !(data && data.error), status: res.status, data: data || {} };
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body = {}) => request("POST", path, body),
  patch: (path, body = {}) => request("PATCH", path, body),
  del: (path, body) => request("DELETE", path, body),
};

export function errorMessage(res, fallback) {
  return (res && res.data && res.data.error) || fallback;
}
