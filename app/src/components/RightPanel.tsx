import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import type { Clip, Meta, QueueItem } from "../api";
import { Alert, Check, CheckSquare, Download, Film, Folder, Link, Play, Refresh, Square, Trash, User, X } from "../icons";
import { secondsToTimestamp, toSeconds } from "../time";
import { IconButton, ProgressBar } from "./ui";

/** YouTube ids are 11 chars of [A-Za-z0-9_-]; for those the thumbnail is derivable. */
function thumbFor(clip: Clip): string | null {
  if (clip.thumbnail) return clip.thumbnail;
  if (/^[A-Za-z0-9_-]{11}$/.test(clip.id)) return `https://i.ytimg.com/vi/${clip.id}/mqdefault.jpg`;
  return null;
}

/** A thumbnail that falls back to a placeholder when the URL is missing, 404s, or
 *  comes back as a stub image (YouTube serves a tiny grey frame for gone videos). */
function Thumb({ src, className, iconSize, children }: {
  src: string | null | undefined; className: string; iconSize: number; children?: ReactNode;
}) {
  const [broken, setBroken] = useState<string | null>(null);
  const ok = Boolean(src) && broken !== src;
  return (
    <div className={`${className} ${ok ? "" : "is-empty"}`}>
      {ok ? (
        <img
          src={src!}
          alt=""
          loading="lazy"
          onError={() => setBroken(src!)}
          onLoad={(e) => { if (e.currentTarget.naturalWidth < 150) setBroken(src!); }}
        />
      ) : (
        <span className="thumb-placeholder"><Film size={iconSize} /><span>No thumbnail</span></span>
      )}
      {ok && children}
    </div>
  );
}

function fmtSize(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(0)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

function fmtWhen(t: number): string {
  const d = new Date(t * 1000);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return sameDay ? time : `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}

/** "1:30 · 30s" for a section, "Entire video · 10:35" for a whole one. */
function clipLabel(clip: Clip): string {
  const len = clip.duration != null
    ? fmtLength(clip.duration)
    : clip.section ? fmtLength(toSeconds(clip.section.end) - toSeconds(clip.section.start)) : null;
  const what = clip.kind === "full"
    ? "Entire video"
    : clip.section ? `from ${clip.section.start.replace(/^00:/, "")}` : clip.number != null ? `Clip ${clip.number}` : "Clip";
  return len ? `${what} · ${len}` : what;
}

/** Short lengths as "15s" / "90s", longer ones as m:ss. */
function fmtLength(seconds: number): string {
  const s = Math.round(seconds);
  return s < 120 ? `${s}s` : secondsToTimestamp(s).replace(/^0/, "");
}

/** The download queue, shown above the clips while it has anything in it. */
export function QueuePanel({ items, onRemove, onClear }: {
  items: QueueItem[]; onRemove: (id: string) => void; onClear: () => void;
}) {
  if (items.length === 0) return null;
  const active = items.filter((i) => i.status === "queued" || i.status === "running").length;
  const finished = items.length - active;
  return (
    <div className="queue">
      <header className="panel-head">
        <h2>Queue</h2>
        <span className="panel-count">{active ? `${active} left` : "all done"}</span>
        <span className="log-spacer" />
        {finished > 0 && <button type="button" className="link-btn" onClick={onClear}>Clear finished</button>}
      </header>
      <div className="queue-list">
        {items.map((item) => {
          const range = item.start && item.end
            ? `${item.start.replace(/^00:/, "")}–${item.end.replace(/^00:/, "")}`
            : "Entire video";
          const running = item.status === "running";
          return (
            <div key={item.id} className={`queue-item is-${item.status}`}>
              <Thumb src={item.thumbnail} className="queue-thumb" iconSize={16} />
              <div className="queue-text">
                <div className="queue-title" title={item.url}>{item.title || item.url}</div>
                <div className="queue-meta">
                  <span>{range}</span>
                  <span className="queue-step">{item.step}</span>
                </div>
                {running && <ProgressBar fraction={item.fraction} />}
              </div>
              <IconButton
                label={running ? "Stop this download" : item.status === "queued" ? "Remove from the queue" : "Remove from the list"}
                onClick={() => onRemove(item.id)}
              >
                {running ? <Square size={16} /> : <X size={16} />}
              </IconButton>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Slides its content open and shut, and follows its content's height as it
 * changes, so what sits below moves smoothly instead of jumping. The last
 * content stays on screen while it closes.
 */
function Reveal({ show, children }: { show: boolean; children: ReactNode }) {
  const inner = useRef<HTMLDivElement>(null);
  const kept = useRef<ReactNode>(children);
  if (show) kept.current = children;
  const [mounted, setMounted] = useState(show);
  const [height, setHeight] = useState(0);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (show) setMounted(true);
  }, [show]);

  // Track the content's natural height while shown.
  useLayoutEffect(() => {
    const el = inner.current;
    if (!mounted || !el) return;
    const measure = () => setHeight(el.offsetHeight);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [mounted]);

  // Open on the frame after mounting, so the height animates from zero.
  useEffect(() => {
    if (!mounted) return;
    if (!show) {
      // Never got open (hidden within two frames): no transition will end.
      if (!open || height === 0) setMounted(false);
      else setOpen(false);
      return;
    }
    // Two frames: the first gets the closed state painted, so the browser
    // has a height to animate from.
    let id = requestAnimationFrame(() => {
      id = requestAnimationFrame(() => setOpen(true));
    });
    return () => cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted, show]);

  if (!mounted) return null;
  return (
    <div
      className={`reveal ${open ? "is-open" : ""}`}
      style={{ height: open ? height : 0 }}
      onTransitionEnd={(e) => {
        if (e.target === e.currentTarget && e.propertyName === "height" && !show) setMounted(false);
      }}
    >
      <div ref={inner} className="reveal-inner">{show ? children : kept.current}</div>
    </div>
  );
}

export function PreviewCard({ meta, loading, url, onClear }: {
  meta: Meta | null; loading: boolean; url: string; onClear: () => void;
}) {
  return (
    <Reveal show={Boolean(url.trim())}>
      <PreviewBody meta={meta} loading={loading} onClear={onClear} />
    </Reveal>
  );
}

function PreviewBody({ meta, loading, onClear }: {
  meta: Meta | null; loading: boolean; onClear: () => void;
}) {
  const thumb = meta?.thumbnail;
  const ready = Boolean(meta && !meta.age_restricted && (meta.title || meta.heights.length));
  return (
    <div className="preview">
      <Thumb src={thumb} className="preview-thumb" iconSize={22}>
        {meta?.duration != null && <span className="thumb-duration">{secondsToTimestamp(meta.duration)}</span>}
      </Thumb>
      <div className="preview-text">
        <div className="preview-title">{meta?.title || (loading ? "Looking it up…" : meta ? "Unknown title" : "…")}</div>
        <div className="preview-channel"><User size={14} />{meta?.channel || (loading ? "" : meta ? "Unknown channel" : "")}</div>
        {meta && meta.heights.length > 0 && (
          <div className="preview-formats">{meta.heights.slice(0, 5).map((h) => `${h}p`).join(" · ")}</div>
        )}
        {meta?.age_restricted && (
          <div className="preview-warn"><Alert size={14} /> Age restricted — YouTube needs a signed-in session, so this can't be downloaded.</div>
        )}
      </div>
      <div className="preview-side">
        {ready && <span className="ready"><Check size={14} /> Ready</span>}
        {loading && <span className="ready is-loading">Checking…</span>}
        <IconButton label="Clear link" className="icon-btn-sm" onClick={onClear}><X size={16} /></IconButton>
      </div>
    </div>
  );
}

export function History({ clips, loading, busy, queueActive = false, canInsert, onInsert, onPlay, onOpen, onDelete, onRefresh, onOpenRoot }: {
  clips: Clip[] | null;
  loading: boolean;
  busy: boolean;
  /** Queued downloads are running (the engine refuses deletes then). */
  queueActive?: boolean;
  canInsert: boolean;
  /** Inserts the given clips, in order, as one job. */
  onInsert: (clips: Clip[]) => void;
  onPlay: (clip: Clip) => void;
  onOpen: (clip: Clip) => void;
  /** Deletes the given clips, in order. */
  onDelete: (clips: Clip[]) => void;
  onRefresh: () => void;
  onOpenRoot: () => void;
}) {
  // "Copied" shown briefly on whatever was clicked (title, channel, link).
  const [copied, setCopied] = useState<string | null>(null);
  const copy = async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      window.setTimeout(() => setCopied((c) => (c === key ? null : c)), 1100);
    } catch { /* clipboard blocked; nothing sensible to do */ }
  };

  // Selection mode: the insert or trash icon in the header turns rows into
  // checkboxes; a bar at the bottom acts on the ticked ones in one go.
  // Deleting takes two steps — Delete, then Confirm — no dialog.
  const [mode, setMode] = useState<"insert" | "delete" | null>(null);
  const selecting = mode !== null;
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [armed, setArmed] = useState(false);
  const toggle = (path: string) =>
    setSelected((s) => { const n = new Set(s); if (n.has(path)) n.delete(path); else n.add(path); return n; });
  const leave = () => { setMode(null); setSelected(new Set()); setArmed(false); };
  const enter = (m: "insert" | "delete") => { if (mode === m) leave(); else { setMode(m); setSelected(new Set()); setArmed(false); } };
  const chosen = () => picked;
  const all = clips ?? [];
  // Only clips still in the list count: one can vanish while it's ticked.
  const picked = all.filter((c) => selected.has(c.path));
  const allSelected = all.length > 0 && picked.length === all.length;

  return (
    <div className={`history ${selecting ? "is-selecting" : ""}`}>
      <header className="panel-head">
        <h2>Clips</h2>
        <span className="panel-count">{clips ? clips.length : ""}</span>
        <span className="log-spacer" />
        <IconButton
          label={mode === "insert" ? "Done selecting" : "Select clips to YEET into the timeline"}
          className={mode === "insert" ? "is-active" : ""}
          disabled={!clips || clips.length === 0 || !canInsert}
          onClick={() => enter("insert")}
        >
          <Download size={18} />
        </IconButton>
        <IconButton
          label={mode === "delete" ? "Done selecting" : "Select clips to delete"}
          className={mode === "delete" ? "is-active" : ""}
          disabled={!clips || clips.length === 0}
          onClick={() => enter("delete")}
        >
          <Trash size={18} />
        </IconButton>
        <IconButton label="Open clips folder" onClick={onOpenRoot}><Folder size={18} /></IconButton>
        <IconButton label="Refresh" onClick={onRefresh} className={loading ? "is-spinning" : ""}><Refresh size={18} /></IconButton>
      </header>

      {clips && clips.length === 0 && (
        <div className="empty">
          <Film size={28} />
          <p>Your downloaded clips will appear here.</p>
        </div>
      )}

      <div className="history-list">
        {clips?.map((clip) => {
          const thumb = thumbFor(clip);
          const isSelected = selected.has(clip.path);
          return (
            <div
              key={clip.path}
              className={`clip ${isSelected ? "is-selected" : ""}`}
              onClick={selecting ? () => toggle(clip.path) : undefined}
              {...(selecting ? {
                role: "checkbox", "aria-checked": isSelected, tabIndex: 0,
                onKeyDown: (e: KeyboardEvent) => {
                  if (e.key === " " || e.key === "Enter") { e.preventDefault(); toggle(clip.path); }
                },
              } : {})}
            >
              <Thumb src={thumb} className="clip-thumb" iconSize={18} />
              <div className="clip-text">
                <button
                  type="button"
                  className={`clip-title copyable ${copied === clip.path + ":t" ? "is-copied" : ""}`}
                  title="Click to copy the title"
                  disabled={selecting}
                  onClick={(e) => { e.stopPropagation(); copy(clip.path + ":t", clip.title || clip.name); }}
                >
                  {clip.title || clip.name}
                </button>
                <div className="clip-meta">
                  {clip.channel && (
                    <button
                      type="button"
                      className={`copyable ${copied === clip.path + ":c" ? "is-copied" : ""}`}
                      title="Click to copy the channel"
                      disabled={selecting}
                      onClick={(e) => { e.stopPropagation(); copy(clip.path + ":c", clip.channel); }}
                    >
                      {clip.channel}
                    </button>
                  )}
                  <span className="clip-len">{clipLabel(clip)}</span>
                  <span>{fmtSize(clip.size)}</span>
                  <span>{fmtWhen(clip.mtime)}</span>
                </div>
              </div>
              {!selecting && (
                <div className="clip-actions">
                  <IconButton label="YEET into the timeline" className="clip-yeet" disabled={busy || !canInsert} onClick={() => onInsert([clip])}>
                    <Download size={18} />
                  </IconButton>
                  <IconButton label="Play in your video player" onClick={() => onPlay(clip)}><Play size={18} /></IconButton>
                  <IconButton
                    label={clip.source ? "Copy the video's link" : "Source link unknown for this clip"}
                    className={copied === clip.path + ":u" ? "is-copied" : ""}
                    disabled={!clip.source}
                    onClick={() => clip.source && copy(clip.path + ":u", clip.source)}
                  >
                    {copied === clip.path + ":u" ? <Check size={18} /> : <Link size={18} />}
                  </IconButton>
                  <IconButton label="Open folder" onClick={() => onOpen(clip)}><Folder size={18} /></IconButton>
                </div>
              )}
              {selecting && (
                <span className={`clip-check ${isSelected ? "on" : ""}`}>
                  {isSelected ? <CheckSquare size={22} /> : <Square size={22} />}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {selecting && (
        <footer className="select-bar">
          <button type="button" className="link-btn" onClick={() => setSelected(allSelected ? new Set() : new Set(all.map((c) => c.path)))}>
            {allSelected ? "Select none" : "Select all"}
          </button>
          <span className="select-count">{picked.length} selected</span>
          <span className="log-spacer" />
          {mode === "insert" ? (
            <>
              <button type="button" className="btn btn-primary btn-sm" disabled={picked.length === 0 || busy || !canInsert}
                onClick={() => { onInsert(chosen()); leave(); }}>
                <Download size={16} /> YEET {picked.length || ""}
              </button>
              <button type="button" className="btn btn-sm" onClick={leave}>Cancel</button>
            </>
          ) : armed ? (
            <>
              <span className="select-count bad">Delete {picked.length} clip{picked.length === 1 ? "" : "s"} from disk?</span>
              <button type="button" className="btn btn-danger btn-sm" disabled={busy || queueActive}
                onClick={() => { onDelete(chosen()); leave(); }}>
                Delete
              </button>
              <button type="button" className="btn btn-sm" onClick={() => setArmed(false)}>Keep</button>
            </>
          ) : (
            <>
              <button type="button" className="btn btn-danger btn-sm" disabled={picked.length === 0 || busy || queueActive} onClick={() => setArmed(true)}
                title={queueActive ? "Wait for the queue to finish downloading" : undefined}>
                <Trash size={16} /> Delete
              </button>
              <button type="button" className="btn btn-sm" onClick={leave}>Cancel</button>
            </>
          )}
        </footer>
      )}
    </div>
  );
}
