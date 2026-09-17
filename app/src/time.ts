/**
 * Timestamp helpers, ported from engine.py / naming.py so the form can be
 * checked and adjusted as you type. The engine re-validates on submit; this
 * is only for keeping the fields consistent with each other.
 */

const TS_RE = /^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.(\d+))?\s*$|^\s*(\d+(?:\.\d+)?)\s*$/;

/** 'SS', 'SS.ms', 'MM:SS' or 'HH:MM:SS(.ms)' -> 'HH:MM:SS(.ms)', or null. */
export function normalizeTimestamp(text: string): string | null {
  const m = TS_RE.exec(text);
  if (!m) return null;
  if (m[5] !== undefined) {
    const total = parseFloat(m[5]);
    const h = Math.floor(total / 3600);
    const rem = total - h * 3600;
    const mnt = Math.floor(rem / 60);
    const sec = rem - mnt * 60;
    const secStr = sec.toFixed(3).padStart(6, "0").replace(/0+$/, "").replace(/\.$/, "");
    return `${pad(h)}:${pad(mnt)}:${secStr}`;
  }
  const h = parseInt(m[1] ?? "0", 10);
  const base = `${pad(h)}:${pad(parseInt(m[2], 10))}:${pad(parseInt(m[3], 10))}`;
  return m[4] ? `${base}.${m[4]}` : base;
}

export function toSeconds(tsNorm: string): number {
  const parts = tsNorm.split(":").map(parseFloat);
  while (parts.length < 3) parts.unshift(0);
  const [h, m, s] = parts;
  return h * 3600 + m * 60 + s;
}

/** Seconds -> 'MM:SS', or 'HH:MM:SS' once it passes an hour. */
export function secondsToTimestamp(total: number): string {
  total = Math.floor(total);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

// YouTube's "start at" parameter, in all the shapes it appears in the wild:
//   ?t=169   &t=169s   &t=2m49s   &t=1h2m3s   ?start=169   #t=90
const T_PARAM = /[?&#](?:t|start|time_continue)=([0-9hms]+)/i;
const HMS = /(\d+)\s*([hms])/gi;

/** Seconds from a share link's timestamp, or null if it has none. */
export function startSecondsFromUrl(url: string): number | null {
  const m = T_PARAM.exec(url ?? "");
  if (!m) return null;
  const raw = m[1].toLowerCase();
  if (/^\d+$/.test(raw)) return parseInt(raw, 10);
  const scale: Record<string, number> = { h: 3600, m: 60, s: 1 };
  let total = 0;
  let found = false;
  for (const part of raw.matchAll(HMS)) {
    total += parseInt(part[1], 10) * scale[part[2].toLowerCase()];
    found = true;
  }
  return found ? total : null;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}
