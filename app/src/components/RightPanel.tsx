import { useState } from "react";
import type { Clip, Meta } from "../api";
import { Alert, Check, CheckSquare, Download, Film, Folder, Link, Play, Refresh, Square, Trash, User, X } from "../icons";
import { secondsToTimestamp, toSeconds } from "../time";
import { IconButton } from "./ui";

/** YouTube ids are 11 chars of [A-Za-z0-9_-]; for those the thumbnail is derivable. */
function thumbFor(clip: Clip): string | null {
  if (clip.thumbnail) return clip.thumbnail;
  if (/^[A-Za-z0-9_-]{11}$/.test(clip.id)) return `https://i.ytimg.com/vi/${clip.id}/mqdefault.jpg`;
  return null;
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

export function PreviewCard({ meta, loading, url, onClear }: {
  meta: Meta | null; loading: boolean; url: string; onClear: () => void;
}) {
  if (!url.trim()) return null;
  const thumb = meta?.thumbnail;
  const ready = Boolean(meta && !meta.age_restricted && (meta.title || meta.heights.length));
  return (
    <div className={`preview ${ready ? "is-ready" : ""}`}>
      <div className={`preview-thumb ${thumb ? "" : "is-empty"}`}>
        {thumb ? <img src={thumb} alt="" /> : <Film size={22} />}
        {meta?.duration != null && thumb && <span className="thumb-duration">{secondsToTimestamp(meta.duration)}</span>}
      </div>
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

export function History({ clips, loading, busy, canInsert, onInsert, onPlay, onOpen, onDelete, onRefresh, onOpenRoot }: {
  clips: Clip[] | null;
  loading: boolean;
  busy: boolean;
  canInsert: boolean;
  onInsert: (clip: Clip) => void;
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

  // Selection mode: the checklist icon in the header turns rows into
  // checkboxes; a bar at the bottom deletes the ticked ones in one go
  // (two steps — Delete, then Confirm — no dialog).
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [armed, setArmed] = useState(false);
  const toggle = (path: string) =>
    setSelected((s) => { const n = new Set(s); if (n.has(path)) n.delete(path); else n.add(path); return n; });
  const leave = () => { setSelecting(false); setSelected(new Set()); setArmed(false); };
  const all = clips ?? [];
  const allSelected = all.length > 0 && selected.size === all.length;

  return (
    <div className={`history ${selecting ? "is-selecting" : ""}`}>
      <header className="panel-head">
        <h2>Clips</h2>
        <span className="panel-count">{clips ? clips.length : ""}</span>
        <span className="log-spacer" />
        <IconButton
          label={selecting ? "Done selecting" : "Select clips to delete"}
          className={selecting ? "is-active" : ""}
          disabled={!clips || clips.length === 0}
          onClick={() => (selecting ? leave() : setSelecting(true))}
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
            >
              <div className={`clip-thumb ${thumb ? "" : "is-empty"}`}>
                {thumb ? <img src={thumb} alt="" loading="lazy" /> : <Film size={18} />}
              </div>
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
                  <IconButton label="YEET into the timeline" className="clip-yeet" disabled={busy || !canInsert} onClick={() => onInsert(clip)}>
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
          <span className="select-count">{selected.size} selected</span>
          <span className="log-spacer" />
          {armed ? (
            <>
              <span className="select-count bad">Delete {selected.size} clip{selected.size === 1 ? "" : "s"} from disk?</span>
              <button type="button" className="btn btn-danger btn-sm" disabled={busy}
                onClick={() => { onDelete(all.filter((c) => selected.has(c.path))); leave(); }}>
                Delete
              </button>
              <button type="button" className="btn btn-sm" onClick={() => setArmed(false)}>Keep</button>
            </>
          ) : (
            <>
              <button type="button" className="btn btn-danger btn-sm" disabled={selected.size === 0 || busy} onClick={() => setArmed(true)}>
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
