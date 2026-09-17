import { useCallback, useEffect, useRef, useState } from "react";
import type { Clip, Meta } from "./api";
import { Header } from "./components/Header";
import { LogPanel } from "./components/LogPanel";
import { Onboarding } from "./components/Onboarding";
import { History, PreviewCard } from "./components/RightPanel";
import { SettingsDialog } from "./components/SettingsDialog";
import { SourceCard, type SourceForm } from "./components/SourceCard";
import { Button, Card, ProgressBar, Segmented, Select, StepRow } from "./components/ui";
import { Download, List, Play, Square } from "./icons";
import { normalizeTimestamp, secondsToTimestamp, startSecondsFromUrl, toSeconds } from "./time";
import { useEngine } from "./useEngine";

type Theme = "dark" | "light";

function loadTheme(): Theme {
  try {
    const t = localStorage.getItem("theme");
    if (t === "light" || t === "dark") return t;
  } catch { /* private mode etc. */ }
  return "dark";
}

export default function App() {
  const engine = useEngine();
  const { api, state } = engine;

  const [theme, setTheme] = useState<Theme>(loadTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch { /* ignore */ }
  }, [theme]);

  // ---- form ------------------------------------------------------------- //
  const [form, setForm] = useState<SourceForm>({ url: "", inPoint: "00:00", outPoint: "00:30" });
  const [quality, setQuality] = useState("Best available");
  const [insertAt, setInsertAt] = useState("playhead");
  const defaultLength = state?.settings.default_length ?? 30;

  // The end point starts at the configured default once settings are known.
  const seededRef = useRef(false);
  useEffect(() => {
    if (state && !seededRef.current) {
      seededRef.current = true;
      setForm((f) => ({ ...f, outPoint: secondsToTimestamp(state.settings.default_length) }));
    }
  }, [state]);

  const log = useCallback((text: string, tag?: string) => {
    api?.log(text, tag).catch(() => undefined);
  }, [api]);

  // In point committed (blur/Enter) and changed: apply the default length,
  // unless both points are zero (whole-video mode).
  const lastIn = useRef(form.inPoint);
  const commitIn = () => {
    if (form.inPoint === lastIn.current) return;
    const start = normalizeTimestamp(form.inPoint);
    if (start === null) return;
    lastIn.current = form.inPoint;
    const endNow = normalizeTimestamp(form.outPoint);
    if (toSeconds(start) === 0 && endNow !== null && toSeconds(endNow) === 0) return;
    const newEnd = secondsToTimestamp(toSeconds(start) + defaultLength);
    setForm((f) => ({ ...f, outPoint: newEnd }));
    flashField("out");
    log(`End point set to ${newEnd} (+${defaultLength}s from the in point).`);
  };

  const setInPoint = (stamp: string) => {
    lastIn.current = stamp;
    setForm((f) => ({ ...f, inPoint: stamp }));
  };

  // A brief glow on a field the app filled in by itself, so the change is seen.
  const [flash, setFlash] = useState<{ in: boolean; out: boolean }>({ in: false, out: false });
  const flashTimers = useRef<{ in?: number; out?: number }>({});
  const flashField = (which: "in" | "out") => {
    setFlash((f) => ({ ...f, [which]: false }));
    window.clearTimeout(flashTimers.current[which]);
    // Off then on across a frame, so a second flash restarts the animation.
    requestAnimationFrame(() => {
      setFlash((f) => ({ ...f, [which]: true }));
      flashTimers.current[which] = window.setTimeout(
        () => setFlash((f) => ({ ...f, [which]: false })), 1200);
    });
  };

  const applyLinkTimestamp = (seconds: number, auto: boolean) => {
    const stamp = secondsToTimestamp(seconds);
    setInPoint(stamp);
    flashField("in");
    log(auto
      ? `Timestamp detected in the link — in point ${stamp} (t=${seconds}s).`
      : `In point set to ${stamp} (from the link's t=${seconds}s).`);
    const end = normalizeTimestamp(form.outPoint);
    if (end === null || toSeconds(end) <= seconds) {
      const newEnd = secondsToTimestamp(seconds + defaultLength);
      setForm((f) => ({ ...f, outPoint: newEnd }));
      flashField("out");
      log(`End point moved to ${newEnd} (+${defaultLength}s) to keep the range valid.`);
    }
  };

  // Auto-apply a link's ?t= once per distinct URL. Done from an effect on the
  // value rather than in the change handler, so it fires however the link got
  // there — typed, pasted, dropped, or set by the app — and can't be skipped
  // by a batched or out-of-order change event.
  const autoTsUrl = useRef<string | null>(null);
  const onUrl = (url: string) => setForm((f) => ({ ...f, url }));
  useEffect(() => {
    const trimmed = form.url.trim();
    if (!trimmed) { autoTsUrl.current = null; return; }
    if (trimmed === autoTsUrl.current) return;
    const seconds = startSecondsFromUrl(trimmed);
    if (seconds === null) return;
    autoTsUrl.current = trimmed;
    applyLinkTimestamp(seconds, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.url]);

  const copyFromLink = () => {
    const url = form.url.trim();
    if (!url) { log("Paste a video link first."); return; }
    const seconds = startSecondsFromUrl(url);
    if (seconds === null) {
      log("That link has no timestamp — share it with 'Start at' ticked to get a ?t= value.");
      return;
    }
    autoTsUrl.current = url;
    applyLinkTimestamp(seconds, false);
  };

  // `quiet` for the slider, which calls this on every step; the release logs.
  const setLength = (seconds: number, quiet = false) => {
    const start = normalizeTimestamp(form.inPoint);
    if (start === null) {
      if (!quiet) log("ERROR: in point must be SS, MM:SS or HH:MM:SS before a length can be applied.");
      return;
    }
    const end = secondsToTimestamp(toSeconds(start) + seconds);
    setForm((f) => ({ ...f, outPoint: end }));
    if (!quiet) { flashField("out"); log(`Length ${secondsToTimestamp(seconds)} → end point ${end}.`); }
  };

  const currentLength = (() => {
    const a = normalizeTimestamp(form.inPoint);
    const b = normalizeTimestamp(form.outPoint);
    if (a === null || b === null) return null;
    const len = toSeconds(b) - toSeconds(a);
    return len > 0 ? len : null;
  })();

  const setEntire = () => {
    setInPoint("00:00");
    setForm((f) => ({ ...f, inPoint: "00:00", outPoint: "00:00" }));
    log("Both points cleared — the entire video will be downloaded.");
  };

  // ---- preview ---------------------------------------------------------- //
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaLoading, setMetaLoading] = useState(false);
  const metaFor = useRef<string>("");
  useEffect(() => {
    const url = form.url.trim();
    if (!api || !state?.tools.ready) return;
    if (!url) { setMeta(null); metaFor.current = ""; return; }
    if (url === metaFor.current) return;
    const handle = setTimeout(async () => {
      if (state.busy) return;         // the probe shares the job's process slot
      metaFor.current = url;
      setMetaLoading(true);
      try {
        const m = await api.meta(url);
        if (metaFor.current === url) setMeta(m);
      } catch {
        if (metaFor.current === url) setMeta(null);
      } finally {
        if (metaFor.current === url) setMetaLoading(false);
      }
    }, 700);
    return () => clearTimeout(handle);
  }, [form.url, api, state?.tools.ready, state?.busy]);

  // ---- jobs ------------------------------------------------------------- //
  const [pop, setPop] = useState(0);
  const startJob = (insert: boolean) => {
    setPop((n) => n + 1);
    api?.startJob({
      url: form.url, in: form.inPoint, out: form.outPoint,
      quality, insert_at: insertAt, insert,
    });
  };

  // ---- clip library ----------------------------------------------------- //
  const [clips, setClips] = useState<Clip[] | null>(null);
  const [clipsLoading, setClipsLoading] = useState(false);
  const loadClips = useCallback(async () => {
    if (!api) return;
    setClipsLoading(true);
    try {
      setClips(await api.clips());
    } catch {
      /* the log already has the error, if the service is even there */
    } finally {
      setClipsLoading(false);
    }
  }, [api]);
  // On connect, whenever the engine says the folder changed, and when the
  // clips folder setting changes.
  useEffect(() => { if (engine.connected) loadClips(); },
    [engine.connected, engine.clipsVersion, state?.settings.download_dir, loadClips]);

  // ---- panels ----------------------------------------------------------- //
  const [logOpen, setLogOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // First run: shown until the setup was finished or skipped (persisted by
  // the engine), and dismissed locally so it doesn't flash back on refresh.
  const [onboardingDone, setOnboardingDone] = useState(false);
  const showOnboarding = Boolean(api && state && !state.settings.onboarded && !onboardingDone);
  useEffect(() => {
    if (engine.revealLog > 0) setLogOpen(true);
  }, [engine.revealLog]);

  const busy = state?.busy ?? false;
  const ready = Boolean(engine.connected && state?.booted && state.tools.ready);
  const blocked = Boolean(meta?.age_restricted && form.url.trim() === metaFor.current);
  // YEET needs the chosen editor reachable; Download only never does.
  const resolveOk = state?.resolve.level === "ok";
  const progress = state?.progress ?? { fraction: 0, step: "" };

  return (
    <div className="app">
      <div className="left">
        <Header
          resolve={state?.resolve ?? null}
          editor={state?.editor ?? "resolve"}
          connected={engine.connected}
          onRefresh={() => api?.refreshResolve()}
          onLog={() => setLogOpen((o) => !o)}
          onSettings={() => setSettingsOpen(true)}
          theme={theme}
          onTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          logOpen={logOpen}
        />

        {engine.error && <div className="banner banner-error">{engine.error}</div>}

        <div className="left-body">
          <SourceCard
            form={form}
            currentLength={currentLength}
            flash={flash}
            onUrl={onUrl}
            onIn={(v) => setForm((f) => ({ ...f, inPoint: v }))}
            onInCommit={commitIn}
            onOut={(v) => setForm((f) => ({ ...f, outPoint: v }))}
            onLength={setLength}
            onEntire={setEntire}
            onCopyFromLink={copyFromLink}
            disabled={busy}
          />

          <Card className="card-rows">
            <StepRow title="Quality">
              <Select
                options={state?.quality_options ?? ["Best available"]}
                value={quality}
                onChange={setQuality}
                disabled={busy}
              />
            </StepRow>
            <StepRow title="Insert at">
              <Segmented
                options={[
                  { value: "playhead", label: "Playhead", icon: <Play size={16} /> },
                  { value: "start", label: "Start", icon: <List size={16} /> },
                ]}
                value={insertAt}
                onChange={setInsertAt}
                disabled={busy}
              />
            </StepRow>
          </Card>
        </div>

        <div className="left-foot">
          <div className="progress-block">
            <span className="progress-step">{progress.step || (ready ? "Idle" : "Getting tools ready…")}</span>
            <ProgressBar fraction={progress.fraction} />
          </div>
          {busy ? (
            <Button variant="danger" block icon={<Square />} onClick={() => api?.cancel()} className="btn-big is-busy">Stop</Button>
          ) : (
            <Button key={pop} variant="primary" block icon={<Download />} onClick={() => startJob(true)} disabled={!ready || blocked || !resolveOk} className={`btn-big ${pop ? "is-popped" : ""}`}
              title={resolveOk ? undefined : `Connect ${state?.editor === "premiere" ? "Premiere (open the YEETingus panel)" : "Resolve (open a project and timeline)"} first — or use Download only`}>
              YEET into timeline
            </Button>
          )}
          <Button block icon={<Download />} onClick={() => startJob(false)} disabled={!ready || busy || blocked}>
            Download only
          </Button>
        </div>
      </div>

      <div className="right">
        {logOpen ? (
          <LogPanel lines={engine.log} onClear={engine.clearLog} onClose={() => setLogOpen(false)} />
        ) : (
          <>
            <PreviewCard meta={meta} loading={metaLoading} url={form.url} onClear={() => onUrl("")} />
            <History
              clips={clips}
              loading={clipsLoading}
              busy={busy}
              canInsert={ready && resolveOk}
              onInsert={(c) => api?.insertClip(c.path, insertAt)}
              onPlay={(c) => api?.playClip(c.path)}
              onOpen={(c) => api?.openClipFolder(c.path)}
              onDelete={async (list) => {
                // One at a time: the engine refuses deletes while busy, and
                // each one fires a clips event that would otherwise race.
                for (const c of list) await api?.deleteClip(c.path).catch(() => undefined);
              }}
              onRefresh={loadClips}
              onOpenRoot={() => api?.openFolder()}
            />
          </>
        )}
      </div>

      {showOnboarding && api && state && (
        <Onboarding
          api={api}
          state={state}
          toolBusy={engine.toolBusy}
          onDone={() => setOnboardingDone(true)}
          onLog={log}
        />
      )}

      {settingsOpen && api && state && (
        <SettingsDialog
          api={api}
          state={state}
          toolBusy={engine.toolBusy}
          onClose={() => setSettingsOpen(false)}
          onLog={log}
          version={state.version}
        />
      )}
    </div>
  );
}
