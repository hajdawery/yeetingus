/**
 * One hook that owns the connection to the service and mirrors the engine's
 * state into React. Components read `engine.*` and call `engine.api.*`.
 */
import { useEffect, useRef, useState } from "react";
import { Api, EngineEvent, EngineState, resolveService } from "./api";

export interface LogLine {
  seq: number;
  text: string;
  tag: string;
}

export interface Engine {
  api: Api | null;
  connected: boolean;
  error: string | null;
  state: EngineState | null;
  log: LogLine[];
  toolBusy: Record<string, boolean>;
  /** Bumps every time the engine asks for the log to be shown. */
  revealLog: number;
  /** Bumps every time the clip library changes on disk. */
  clipsVersion: number;
  clearLog: () => void;
}

const MAX_LOG = 2000;

/** The Tk app guesses a style from the text when none is given; same here. */
function guessTag(text: string): string {
  const low = text.toLowerCase();
  if (low.includes("error") || low.includes("warning") || low.includes("resolve:")) return "bad";
  if (low.includes("ready") || low.includes("done") || low.includes("inserted")) return "accent";
  return "";
}

export function useEngine(): Engine {
  const [api, setApi] = useState<Api | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<EngineState | null>(null);
  const [log, setLog] = useState<LogLine[]>([]);
  const [toolBusy, setToolBusy] = useState<Record<string, boolean>>({});
  const [revealLog, setRevealLog] = useState(0);
  const [clipsVersion, setClipsVersion] = useState(0);
  const lastSeq = useRef(0);

  useEffect(() => {
    let close: (() => void) | null = null;
    let cancelled = false;

    (async () => {
      let a: Api;
      try {
        a = new Api(await resolveService());
      } catch (e) {
        setError(`Couldn't start the service: ${String(e)}`);
        return;
      }
      if (cancelled) return;
      setApi(a);

      const onEvent = (ev: EngineEvent) => {
        if (ev.seq > lastSeq.current) lastSeq.current = ev.seq;
        switch (ev.kind) {
          case "state":
            // Snapshot after the replay — the single source of truth.
            setState(stripEvent(ev));
            setConnected(true);
            setError(null);
            break;
          case "log":
            setLog((prev) => {
              const next = [...prev, { seq: ev.seq, text: ev.text, tag: ev.tag ?? guessTag(ev.text) }];
              return next.length > MAX_LOG ? next.slice(next.length - MAX_LOG) : next;
            });
            break;
          case "progress":
            setState((s) =>
              s && {
                ...s,
                progress: {
                  fraction: ev.fraction ?? s.progress.fraction,
                  step: ev.step ?? s.progress.step,
                },
              },
            );
            break;
          case "resolve":
            setState((s) => s && { ...s, resolve: { text: ev.text, level: ev.level } });
            break;
          case "busy":
            setState((s) => s && { ...s, busy: ev.busy, booted: s.booted || !ev.busy });
            break;
          case "tools":
            setState((s) => s && { ...s, tools: stripEvent(ev) });
            break;
          case "tool_busy":
            setToolBusy((t) => ({ ...t, [ev.tool]: ev.busy }));
            break;
          case "reveal_log":
            setRevealLog((n) => n + 1);
            break;
          case "clips":
            setClipsVersion((n) => n + 1);
            break;
          case "premiere":
            setState((s) => s && { ...s, premiere: stripEvent(ev) });
            break;
          case "resolve_menu":
            setState((s) => s && { ...s, resolve_menu: stripEvent(ev) });
            break;
          case "settings": {
            const settings = stripEvent(ev);
            // A new editor means the old pill text is about the wrong app
            // until its check lands; say so instead of showing it.
            setState((s) => s && {
              ...s, settings, editor: settings.editor,
              resolve: s.editor === settings.editor ? s.resolve : { text: "checking…", level: "error" },
            });
            break;
          }
        }
      };

      const connect = () => {
        close?.();
        // Resume from the last seq we saw, so a hiccup doesn't duplicate lines.
        close = a.events(onEvent, () => {
          setConnected(false);
          setError("Lost the connection to the service; reconnecting…");
          // EventSource reconnects by itself, but with a fresh `since` we get
          // a clean state snapshot rather than a full replay.
          setTimeout(connect, 1500);
        }, lastSeq.current);
      };
      connect();
    })();

    return () => {
      cancelled = true;
      close?.();
    };
  }, []);

  return {
    api,
    connected,
    error,
    state,
    log,
    toolBusy,
    revealLog,
    clipsVersion,
    clearLog: () => setLog([]),
  };
}

/** An event with its envelope fields removed, typed as the payload. */
function stripEvent<T extends { kind: string; seq: number; t: number }>(
  ev: T,
): Omit<T, "kind" | "seq" | "t"> {
  const { kind: _k, seq: _s, t: _t, ...rest } = ev;
  return rest;
}
