// Helpers for Pinterest / X post objects and pinimg CDN URLs.

/** Must match japw.pinterest._pinimg_canonical_key / api._pin_key (dedupe + likes/downloads keys). */
export function canonicalKey(url) {
  const u = String(url || "").split("?")[0].trim().toLowerCase();
  if (!u.includes("i.pinimg.com")) {
    const d = u.lastIndexOf(".");
    return d === -1 ? u : u.slice(0, d);
  }
  const m = u.match(/^https?:\/\/i\.pinimg\.com\/[^/]+\/(.+)$/i);
  if (!m) return u;
  const path = m[1];
  const dot = path.lastIndexOf(".");
  return dot === -1 ? path : path.slice(0, dot);
}

export const postKey = (post) => canonicalKey((post && post.urls && post.urls[0]) || "");

/** Normalised post shape used everywhere in the UI. */
export function toPost(raw) {
  return {
    urls: (raw.urls || []).slice(),
    pin_url: raw.pin_url || null,
    source: raw.source || null,
    gif_video_url: raw.gif_video_url || null,
    width: raw.width || 0,
    height: raw.height || 0,
    color: raw.color || raw.dominant_color || null,
    bucket: raw.bucket || null,
    title: raw.title || "",
    artist: raw.artist || null,
  };
}

/** Swap a pinimg URL onto a given size bucket ("236x", "474x", "736x", "originals"). */
export function pinimgSize(url, bucket) {
  return String(url || "").replace(
    /i\.pinimg\.com\/(?:originals|\d+x(?:\d+)?)\//i,
    `i.pinimg.com/${bucket}/`,
  );
}

/**
 * A rendition of `url` at least `px` wide: pinimg size buckets, or X's name=small/medium/large.
 * Anything else is returned unchanged.
 */
export function sizedUrl(url, px) {
  const u = String(url || "");
  if (/i\.pinimg\.com\//i.test(u)) {
    return pinimgSize(u, px <= 236 ? "236x" : px <= 474 ? "474x" : px <= 736 ? "736x" : "originals");
  }
  if (/pbs\.twimg\.com\/media\//i.test(u)) {
    const name = px <= 680 ? "small" : px <= 1200 ? "medium" : "large";
    return u.includes("name=") ? u.replace(/name=\w+/, `name=${name}`) : `${u}${u.includes("?") ? "&" : "?"}name=${name}`;
  }
  return u;
}

/**
 * Estimate pixel size from the CDN path so the resolution filter can work without
 * loading the full image. ≥736 px buckets may hide much larger originals → unknown (null).
 */
export function estimateSizeFromUrl(url) {
  const u = String(url || "").toLowerCase();
  if (u.includes("/originals/")) return { w: 9999, h: 9999 };
  const m = u.match(/pinimg\.com\/(\d+)x(?:(\d+))?\//);
  if (!m) return null;
  const w = parseInt(m[1], 10);
  if (w >= 736) return null;
  const h = m[2] ? parseInt(m[2], 10) : Math.round(w * 1.33);
  return { w, h };
}

export function urlFormatHint(url) {
  const u = String(url || "").toLowerCase();
  const parts = [];
  const m = u.match(/pinimg\.com\/(\d+)x(?:\d+)?\//);
  if (m) parts.push(`CDN ${m[1]}px`);
  else if (u.includes("/originals/")) parts.push("originals");
  if (u.includes(".webp")) parts.push("WebP");
  else if (u.includes(".gif")) parts.push("GIF");
  else if (u.includes(".png")) parts.push("PNG");
  else if (u.includes(".jpg") || u.includes(".jpeg")) parts.push("JPEG");
  return parts.join(" · ");
}

export const isGifUrl = (url) => String(url || "").toLowerCase().includes(".gif");
