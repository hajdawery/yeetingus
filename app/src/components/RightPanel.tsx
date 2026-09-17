import { useState } from "react";
import type { Clip, Meta } from "../api";
import { Alert, Check, Download, ExternalLink, Film, Folder, Play, Refresh, Trash, User, X } from "../icons";
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

export function History({ clips, loading, busy, canInsert, onInsert, onPlay, onSource, onOpen, onDelete, onRefresh, onOpenRoot }: {
  clips: Clip[] | null;
  loading: boolean;
  busy: boolean;
  canInsert: boolean;
  onInsert: (clip: Clip) => void;
  onPlay: (clip: Clip) => void;
  onSource: (clip: Clip) => void;
  onOpen: (clip: Clip) => void;
  onDelete: (clip: Clip) => void;
  onRefresh: () => void;
  onOpenRoot: () => void;
}) {
  // Two-step delete, inline: the first click arms the row, the second confirms.
  const [armed, setArmed] = useState<string | null>(null);
  // "Copied" shown briefly on whichever title/channel was clicked.
  const [copied, setCopied] = useState<string | null>(null);
  const copy = async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      window.setTimeout(() => setCopied((c) => (c === key ? null : c)), 1100);
    } catch { /* clipboard blocked; nothing sensible to do */ }
  };

  return (
    <div className="history">
      <header className="panel-head">
        <h2>Clips</h2>
        <span className="panel-count">{clips ? clips.length : ""}</span>
        <span className="log-spacer" />
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
          const isArmed = armed === clip.path;
          return (
            <div key={clip.path} className={`clip ${isArmed ? "is-armed" : ""}`}>
              <div className={`clip-thumb ${thumb ? "" : "is-empty"}`}>
                {thumb ? <img src={thumb} alt="" loading="lazy" /> : <Film size={18} />}
              </div>
              <div className="clip-text">
                <button
                  type="button"
                  className={`clip-title copyable ${copied === clip.path + ":t" ? "is-copied" : ""}`}
                  title="Click to copy the title"
                  onClick={() => copy(clip.path + ":t", clip.title || clip.name)}
                >
                  {clip.title || clip.name}
                </button>
                <div className="clip-meta">
                  {clip.channel && (
                    <button
                      type="button"
                      className={`copyable ${copied === clip.path + ":c" ? "is-copied" : ""}`}
                      title="Click to copy the channel"
                      onClick={() => copy(clip.path + ":c", clip.channel)}
                    >
                      {clip.channel}
                    </button>
                  )}
                  <span className="clip-len">{clipLabel(clip)}</span>
                  <span>{fmtSize(clip.size)}</span>
                  <span>{fmtWhen(clip.mtime)}</span>
                </div>
              </div>
              <div className="clip-actions">
                {isArmed ? (
                  <>
                    <button type="button" className="btn btn-danger btn-sm" onClick={() => { setArmed(null); onDelete(clip); }}>Delete</button>
                    <button type="button" className="btn btn-sm" onClick={() => setArmed(null)}>Keep</button>
                  </>
                ) : (
                  <>
                    <IconButton label="YEET into the timeline" className="clip-yeet" disabled={busy || !canInsert} onClick={() => onInsert(clip)}>
                      <Download size={18} />
                    </IconButton>
                    <IconButton label="Play in your video player" onClick={() => onPlay(clip)}><Play size={18} /></IconButton>
                    <IconButton label={clip.source ? "Open the video's page in your browser" : "Source link unknown for this clip"} disabled={!clip.source} onClick={() => onSource(clip)}>
                      <ExternalLink size={18} />
                    </IconButton>
                    <IconButton label="Open folder" onClick={() => onOpen(clip)}><Folder size={18} /></IconButton>
                    <IconButton label="Delete" disabled={busy} onClick={() => setArmed(clip.path)}><Trash size={18} /></IconButton>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
