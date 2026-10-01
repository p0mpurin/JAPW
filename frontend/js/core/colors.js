// Colour buckets for filtering / sorting pins by their dominant colour.

export const SWATCHES = [
  { id: "red", label: "Red", hex: "#e5484d" },
  { id: "orange", label: "Orange", hex: "#f76b15" },
  { id: "yellow", label: "Yellow", hex: "#ffd60a" },
  { id: "green", label: "Green", hex: "#30a46c" },
  { id: "teal", label: "Teal", hex: "#12a594" },
  { id: "blue", label: "Blue", hex: "#3e63dd" },
  { id: "purple", label: "Purple", hex: "#8e4ec6" },
  { id: "pink", label: "Pink", hex: "#d6409f" },
  { id: "brown", label: "Brown", hex: "#8a5a3c" },
  { id: "black", label: "Black", hex: "#111111" },
  { id: "gray", label: "Gray", hex: "#8b8d98" },
  { id: "white", label: "White", hex: "#f4f4f4" },
];

const ORDER = SWATCHES.map((s) => s.id);

export function hexToHsl(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return null;
  const n = parseInt(m[1], 16);
  const r = ((n >> 16) & 255) / 255;
  const g = ((n >> 8) & 255) / 255;
  const b = (n & 255) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return { h: 0, s: 0, l };
  const s = d / (1 - Math.abs(2 * l - 1));
  let h;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return { h: (h * 60 + 360) % 360, s, l };
}

/** Which swatch a colour belongs to (null when unknown). */
export function colorBucket(hex) {
  const c = hexToHsl(hex);
  if (!c) return null;
  const { h, s, l } = c;
  if (l < 0.14) return "black";
  if (l > 0.88 && s < 0.5) return "white";
  if (s < 0.14 || (s < 0.22 && (l < 0.25 || l > 0.75))) return l < 0.22 ? "black" : l > 0.82 ? "white" : "gray";
  if (h >= 12 && h < 48 && l < 0.42) return "brown";
  if (h < 12 || h >= 345) return "red";
  if (h < 40) return "orange";
  if (h < 68) return "yellow";
  if (h < 160) return "green";
  if (h < 195) return "teal";
  if (h < 255) return "blue";
  if (h < 295) return "purple";
  return "pink";
}

/** Sort key: bucket order, then lightness (light → dark) inside a bucket. */
export function colorSortKey(hex) {
  const bucket = colorBucket(hex);
  const c = hexToHsl(hex);
  if (!bucket || !c) return [ORDER.length, 0];
  return [ORDER.indexOf(bucket), -c.l];
}
