import { useEffect, useRef, useState } from "react";
import { openExternal, type Api, type Conform, type Editor, type EngineState, type Retime } from "../api";
import { Folder, X } from "../icons";
import { Button, Card, Field, IconButton, Segmented, Switch } from "./ui";
import { ResolveMenuSetup } from "./ResolveMenuSetup";

const LENGTH_CHOICES = [15, 30, 60, 90];

const AUTHOR_URL = "https://github.com/hajdawery";

/**
 * One "Frame rate" control over two settings. Sharp and Blend convert the
 * file here (conform) so no retime is needed; Optical Flow leaves the file
 * alone and asks Resolve for its optical-flow retime; Off does neither.
 */
type FrameRate = "sharp" | "blend" | "optical" | "off";
const FRAME_RATE: Record<FrameRate, { conform: Conform; retime: Retime }> = {
  sharp: { conform: "sharp", retime: "nearest" },
  blend: { conform: "blend", retime: "nearest" },
  optical: { conform: "off", retime: "optical" },
  off: { conform: "off", retime: "nearest" },
};
function frameRateOf(conform: Conform, retime: Retime): FrameRate {
  if (conform === "sharp") return "sharp";
  if (conform === "blend") return "blend";
  return retime === "optical" ? "optical" : "off";
}

export function SettingsDialog({ api, state, toolBusy, onClose, onLog, version }: {
  api: Api;
  state: EngineState;
  toolBusy: Record<string, boolean>;
  onClose: () => void;
  onLog: (text: string) => void;
  version: string;
}) {
  const [dir, setDir] = useState(state.settings.download_dir);
  const [editor, setEditor] = useState<Editor>(state.settings.editor);
  const [initialFrameRate] = useState<FrameRate>(() => frameRateOf(state.settings.conform, state.settings.retime));
  const [frameRate, setFrameRate] = useState<FrameRate>(initialFrameRate);
  const [length, setLength] = useState(
    String(LENGTH_CHOICES.reduce((a, b) =>
      Math.abs(b - state.settings.default_length) < Math.abs(a - state.settings.default_length) ? b : a)),
  );
  const [resolveEnv, setResolveEnv] = useState<Record<string, unknown> | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [checkUpdates, setCheckUpdates] = useState(state.settings.check_updates ?? true);
  const up = state.update;
  const downOnBackdrop = useRef(false);
  const [canBrowse, setCanBrowse] = useState(false);

  useEffect(() => {
    api.resolveEnv().then((r) => setResolveEnv(r.env)).catch(() => setResolveEnv(null));
    setCanBrowse(Boolean((window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__));
  }, [api]);

  const browse = async () => {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const chosen = await open({ directory: true, defaultPath: dir || undefined, title: "Choose where clips are saved" });
    if (typeof chosen === "string") setDir(chosen);
  };

  const save = async () => {
    setSaveError(null);
    try {
      await api.saveSettings({ download_dir: dir.trim(), default_length: parseInt(length, 10), editor,
        // Only when changed here: the mapping would otherwise rewrite a
        // retime set elsewhere (e.g. "blend") every time Settings is saved.
        ...(frameRate !== initialFrameRate ? FRAME_RATE[frameRate] : {}) });
      onClose();
    } catch (e) {
      // Shown here too: the log is behind this dialog, so a silent failure
      // just looked like a button that does nothing.
      const msg = String((e as Error).message ?? e);
      setSaveError(msg);
      onLog(`ERROR saving settings: ${msg}`);
    }
  };

  const t = state.tools;
  const pyOk = Boolean(resolveEnv?.python_ok);
  const libOk = Boolean(resolveEnv?.lib_exists);

  return (
    <div
      className="dialog-backdrop is-settings"
      // Close only on a click that also started on the backdrop: a text
      // selection dragged out of a field used to close the dialog.
      onMouseDown={(e) => { downOnBackdrop.current = e.target === e.currentTarget; }}
      onClick={(e) => { if (downOnBackdrop.current && e.target === e.currentTarget) onClose(); }}
    >
      <div className="dialog dialog-settings" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <header className="dialog-head">
          <h2>Settings</h2>
          <button type="button" className="icon-btn icon-btn-sm" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </header>
        <div className="dialog-body">
          <div className="settings-cols">
          <div className="settings-col">
          <Card>
            <h3 className="card-title">Editor</h3>
            <p className="card-subtitle">Where YEET pastes the clip.</p>
            <Segmented<Editor>
              options={[
                { value: "resolve", label: "DaVinci Resolve" },
                { value: "premiere", label: "Premiere Pro" },
              ]}
              value={editor}
              onChange={(e) => {
                // Applied at once, not on Save: someone who picks Premiere,
                // installs the panel and closes the dialog with × should be
                // on Premiere.
                setEditor(e);
                api.saveSettings({ editor: e }).catch((err) => onLog(`ERROR saving settings: ${String(err)}`));
              }}
            />
            {editor === "resolve" && (
              <div className="premiere-setup">
                <ResolveMenuSetup api={api} state={state} toolBusy={toolBusy} />
              </div>
            )}
            {editor === "premiere" && (
              <div className="premiere-setup">
                <p className="hint">
                  Premiere is driven through a small YEETingus panel inside it. Install it once, open it from
                  <b>Window → UXP Plugins → YEETingus</b>, dock it and save your workspace — Premiere then
                  brings it back every launch. Keep YEETingus running; the panel connects by itself.
                </p>
                <dl className="tools">
                  <dt>Panel</dt>
                  <dd className={state.premiere.installed === null ? "bad" : ""}>
                    {state.premiere.installed === "?"
                      ? "checking…"
                      : state.premiere.installed === null
                        ? "not installed"
                        : `installed (${state.premiere.installed})`}
                    {" · "}
                    <span className={state.premiere.connected ? "ok" : "bad"}>
                      {state.premiere.connected
                        ? `open in Premiere ${state.premiere.panel.version ?? ""}`
                        : "not open in Premiere"}
                    </span>
                  </dd>
                  <dt>Installer</dt>
                  <dd className={state.premiere.installer ? "" : "bad"}>
                    {state.premiere.installer ? "Adobe's plugin installer found" : "Adobe's plugin installer not found (needs Creative Cloud 5.5+)"}
                  </dd>
                </dl>
                <div className="stack">
                  <Button
                    block
                    onClick={() => api.installPremierePanel()}
                    disabled={state.busy || toolBusy.premiere || !state.premiere.installer || !state.premiere.panel_source}
                  >
                    {toolBusy.premiere ? "Installing…" : state.premiere.installed && state.premiere.installed !== "?" ? "Reinstall the Premiere panel" : "Install the Premiere panel"}
                  </Button>
                  {state.premiere.last_install && (
                    <p className={`install-result ${state.premiere.last_install.startsWith("ok") ? "ok" : "bad"}`}>
                      {state.premiere.last_install.replace(/^(ok|error): /, "")}
                    </p>
                  )}
                </div>
              </div>
            )}
          </Card>


          <Card>
            <h3 className="card-title">Default clip length</h3>
            <p className="card-subtitle">End point set from the in point when the app opens.</p>
            <Segmented
              options={LENGTH_CHOICES.map((s) => ({ value: String(s), label: `${s}s` }))}
              value={length}
              onChange={setLength}
            />
          </Card>
          <Card>
            <h3 className="card-title">Clip storage</h3>
            <p className="card-subtitle">Downloaded clips are saved here.</p>
            <div className="row dir-row">
              <Field value={dir} onChange={(e) => setDir(e.target.value)} spellCheck={false} />
              {canBrowse && (
                <IconButton label="Choose the folder" className="dir-browse" onClick={browse}>
                  <Folder size={18} />
                </IconButton>
              )}
            </div>
            <p className="hint">Existing clips are left where they are.</p>
          </Card>
          </div>
          <div className="settings-col">
          <Card>
            <h3 className="card-title">Frame rate</h3>
            <p className="card-subtitle">What happens when a clip's frame rate differs from the timeline's.</p>
            <Segmented<FrameRate>
              options={[
                { value: "sharp", label: "Sharp" },
                { value: "blend", label: "Blend" },
                ...(editor === "resolve" ? [{ value: "optical" as const, label: "Optical Flow" }] : []),
                { value: "off", label: "Off" },
              ]}
              value={editor !== "resolve" && frameRate === "optical" ? "off" : frameRate}
              onChange={setFrameRate}
            />
            <p className="hint">
              <b>Sharp</b> and <b>Blend</b> convert the file here, once, to the timeline's rate: Sharp keeps every
              frame crisp (a 60 fps clip on 24p gets the same 2-3 pulldown any NLE gives it), Blend mixes
              neighbouring frames, smoother but ghosted on fast footage.
              {editor === "resolve" && <> <b>Optical Flow</b> keeps the file as is and has Resolve retime it, smooth <i>and</i> sharp, but GPU-heavy.</>}
              {" "}<b>Off</b> inserts the clip at its own rate and lets the editor cope.
            </p>
          </Card>


          <Card>
            <h3 className="card-title">Tools</h3>
            <p className="card-subtitle">What YEETingus found on this machine.</p>
            <dl className="tools">
              <dt>yt-dlp</dt><dd>{t.ytdlp}</dd>
              <dt>ffmpeg</dt><dd>{t.ffmpeg}</dd>
              <dt>video</dt><dd>{t.video}</dd>
              <dt>JS</dt><dd>{t.js}</dd>
              <dt>Resolve</dt>
              <dd className={resolveEnv && !(pyOk && libOk) ? "bad" : ""}>
                {resolveEnv
                  ? `Python ${String(resolveEnv.python)} ${pyOk ? "OK" : "UNSUPPORTED"} · library ${libOk ? "found" : "MISSING"}`
                  : "…"}
              </dd>
            </dl>
            <div className="stack">
              <Button block onClick={() => api.updateYtdlp()} disabled={state.busy || toolBusy.ytdlp}>Update yt-dlp</Button>
              {!t.deno_path && (
                <Button block onClick={() => api.installJs()} disabled={state.busy || toolBusy.js}>Install JavaScript runtime (Deno)</Button>
              )}
              {t.ffmpeg_manual && !t.ffmpeg_path && (
                <Button block onClick={() => api.installFfmpeg()} disabled={state.busy || toolBusy.ffmpeg}>Install ffmpeg (Homebrew)</Button>
              )}
            </div>
          </Card>
          </div>
          </div>
        </div>
        <footer className="dialog-foot">
          <span className="credit">
            {state.app} v{version}
            {up.checking && <> · checking…</>}
            {!up.checking && up.available && (
              <> · <button type="button" className="link-btn update-link"
                onClick={() => openExternal(up.download ?? up.page ?? "")}>{up.latest} is out, download</button></>
            )}
            {!up.checking && !up.available && up.latest && <> · up to date</>}
            {" · "}<a href={AUTHOR_URL} target="_blank" rel="noreferrer">© 2026 haej</a>
          </span>
          <span className="log-spacer" />
          <Switch
            checked={checkUpdates}
            onChange={(v) => {
              // Applied at once, like the editor choice.
              setCheckUpdates(v);
              api.saveSettings({ check_updates: v }).catch((err) => onLog(`ERROR saving settings: ${String(err)}`));
            }}
            label="Check for updates"
            hint="Asks GitHub for the latest release when the app starts and every few hours. Nothing else is sent."
          />
          <button type="button" className="link-btn" disabled={up.checking} onClick={() => api.checkUpdate()}>Check now</button>
          {saveError && <span className="install-result bad">Couldn't save: {saveError}</span>}
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={save}>Save</Button>
        </footer>
      </div>
    </div>
  );
}
