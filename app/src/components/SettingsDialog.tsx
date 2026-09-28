import { useEffect, useRef, useState } from "react";
import { openExternal, type Api, type Conform, type Editor, type EngineState, type Retime } from "../api";
import { Folder, X } from "../icons";
import { Rich, useI18n, type LangSetting } from "../i18n";
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

export function SettingsDialog({ api, state, toolBusy, onClose, onLog, version, language, onLanguage }: {
  api: Api;
  state: EngineState;
  toolBusy: Record<string, boolean>;
  onClose: () => void;
  onLog: (text: string) => void;
  version: string;
  /** The language setting ("auto" follows the system), applied at once. */
  language: LangSetting;
  onLanguage: (lang: LangSetting) => void;
}) {
  const { t, tr } = useI18n();
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
    const chosen = await open({ directory: true, defaultPath: dir || undefined, title: t("Choose where clips are saved") });
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

  const tools = state.tools;
  // The engine won't swap tools out from under running downloads.
  const queueRunning = state.queue.some((i) => i.status === "running");
  const toolsTitle = queueRunning ? t("Wait for the queue to finish downloading") : undefined;
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
          <h2>{t("Settings")}</h2>
          <button type="button" className="icon-btn icon-btn-sm" onClick={onClose} aria-label={t("Close")}><X size={16} /></button>
        </header>
        <div className="dialog-body">
          <div className="settings-cols">
          <div className="settings-col">
          <Card>
            <h3 className="card-title">{t("Editor")}</h3>
            <p className="card-subtitle">{t("Where YEET pastes the clip.")}</p>
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
                  <Rich text={t("Premiere is driven through a small YEETingus panel inside it. Install it once, open it from <b>Window → UXP Plugins → YEETingus</b>, dock it and save your workspace — Premiere then brings it back every launch. Keep YEETingus running; the panel connects by itself.")} />
                </p>
                <dl className="tools">
                  <dt>{t("Panel")}</dt>
                  <dd className={state.premiere.installed === null ? "bad" : ""}>
                    {state.premiere.installed === "?"
                      ? t("checking…")
                      : state.premiere.installed === null
                        ? t("not installed")
                        : t("installed ({version})", { version: state.premiere.installed })}
                    {" · "}
                    <span className={state.premiere.connected ? "ok" : "bad"}>
                      {state.premiere.connected
                        ? t("open in Premiere {version}", { version: state.premiere.panel.version ?? "" })
                        : t("not open in Premiere")}
                    </span>
                  </dd>
                  <dt>{t("Installer")}</dt>
                  <dd className={state.premiere.installer ? "" : "bad"}>
                    {state.premiere.installer ? t("Adobe's plugin installer found") : t("Adobe's plugin installer not found (needs Creative Cloud 5.5+)")}
                  </dd>
                </dl>
                <div className="stack">
                  <Button
                    block
                    onClick={() => api.installPremierePanel()}
                    disabled={state.busy || toolBusy.premiere || !state.premiere.installer || !state.premiere.panel_source}
                  >
                    {toolBusy.premiere
                      ? t("Installing…")
                      : state.premiere.installed && state.premiere.installed !== "?" ? t("Reinstall the Premiere panel") : t("Install the Premiere panel")}
                  </Button>
                  {state.premiere.last_install && (
                    <p className={`install-result ${state.premiere.last_install.startsWith("ok") ? "ok" : "bad"}`}>
                      {tr(state.premiere.last_install.replace(/^(ok|error): /, ""))}
                    </p>
                  )}
                </div>
              </div>
            )}
          </Card>


          <Card>
            <h3 className="card-title">{t("Default clip length")}</h3>
            <p className="card-subtitle">{t("End point set from the in point when the app opens.")}</p>
            <Segmented
              options={LENGTH_CHOICES.map((s) => ({ value: String(s), label: `${s}s` }))}
              value={length}
              onChange={setLength}
            />
          </Card>
          <Card>
            <h3 className="card-title">{t("Clip storage")}</h3>
            <p className="card-subtitle">{t("Downloaded clips are saved here.")}</p>
            <div className="row dir-row">
              <Field value={dir} onChange={(e) => setDir(e.target.value)} spellCheck={false} />
              {canBrowse && (
                <IconButton label={t("Choose the folder")} className="dir-browse" onClick={browse}>
                  <Folder size={18} />
                </IconButton>
              )}
            </div>
            <p className="hint">{t("Existing clips are left where they are.")}</p>
          </Card>
          </div>
          <div className="settings-col">
          <Card>
            <h3 className="card-title">{t("Language")}</h3>
            <p className="card-subtitle">{t("Auto follows your system.")}</p>
            <Segmented<LangSetting>
              options={[
                { value: "auto", label: t("Auto") },
                { value: "en", label: "English" },
                { value: "pl", label: "Polski" },
              ]}
              value={language}
              onChange={onLanguage}
            />
          </Card>
          <Card>
            <h3 className="card-title">{t("Frame rate")}</h3>
            <p className="card-subtitle">{t("What happens when a clip's frame rate differs from the timeline's.")}</p>
            <Segmented<FrameRate>
              options={[
                { value: "sharp", label: t("Sharp") },
                { value: "blend", label: t("Blend") },
                ...(editor === "resolve" ? [{ value: "optical" as const, label: t("Optical Flow") }] : []),
                { value: "off", label: t("Off") },
              ]}
              value={editor !== "resolve" && frameRate === "optical" ? "off" : frameRate}
              onChange={setFrameRate}
            />
            <p className="hint">
              <Rich text={t("<b>Sharp</b> and <b>Blend</b> convert the file here, once, to the timeline's rate: Sharp keeps every frame crisp (a 60 fps clip on 24p gets the same 2-3 pulldown any NLE gives it), Blend mixes neighbouring frames, smoother but ghosted on fast footage.")} />
              {editor === "resolve" && <> <Rich text={t("<b>Optical Flow</b> keeps the file as is and has Resolve retime it, smooth <i>and</i> sharp, but GPU-heavy.")} /></>}
              {" "}<Rich text={t("<b>Off</b> inserts the clip at its own rate and lets the editor cope.")} />
            </p>
          </Card>


          <Card>
            <h3 className="card-title">{t("Tools")}</h3>
            <p className="card-subtitle">{t("What YEETingus found on this machine.")}</p>
            <dl className="tools">
              <dt>yt-dlp</dt><dd>{tr(tools.ytdlp)}</dd>
              <dt>ffmpeg</dt><dd>{tr(tools.ffmpeg)}</dd>
              <dt>{t("video")}</dt><dd>{tr(tools.video)}</dd>
              <dt>JS</dt><dd>{tr(tools.js)}</dd>
              <dt>Resolve</dt>
              <dd className={resolveEnv && !(pyOk && libOk) ? "bad" : ""}>
                {resolveEnv
                  ? `Python ${String(resolveEnv.python)} ${pyOk ? "OK" : t("UNSUPPORTED")} · ${t("library")} ${libOk ? t("found") : t("MISSING")}`
                  : "…"}
              </dd>
            </dl>
            <div className="stack">
              <Button block onClick={() => api.updateYtdlp()} disabled={state.busy || queueRunning || toolBusy.ytdlp} title={toolsTitle}>{t("Update yt-dlp")}</Button>
              {!tools.deno_path && (
                <Button block onClick={() => api.installJs()} disabled={state.busy || queueRunning || toolBusy.js} title={toolsTitle}>{t("Install JavaScript runtime (Deno)")}</Button>
              )}
              {tools.ffmpeg_manual && !tools.ffmpeg_path && (
                <Button block onClick={() => api.installFfmpeg()} disabled={state.busy || queueRunning || toolBusy.ffmpeg} title={toolsTitle}>{t("Install ffmpeg (Homebrew)")}</Button>
              )}
            </div>
          </Card>
          </div>
          </div>
        </div>
        <footer className="dialog-foot">
          <span className="credit">
            {state.app} v{version}
            {up.checking && <> · {t("checking…")}</>}
            {!up.checking && up.available && (
              <> · <button type="button" className="link-btn update-link"
                onClick={() => openExternal(up.download ?? up.page ?? "")}>{t("{version} is out, download", { version: up.latest ?? "" })}</button></>
            )}
            {!up.checking && !up.available && up.latest && <> · {t("up to date")}</>}
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
            label={t("Check for updates")}
            hint={t("Asks GitHub for the latest release when the app starts and every few hours. Nothing else is sent.")}
          />
          <button type="button" className="link-btn" disabled={up.checking} onClick={() => api.checkUpdate()}>{t("Check now")}</button>
          {saveError && <span className="install-result bad">{t("Couldn't save: {error}", { error: saveError })}</span>}
          <Button onClick={onClose}>{t("Cancel")}</Button>
          <Button variant="primary" onClick={save}>{t("Save")}</Button>
        </footer>
      </div>
    </div>
  );
}
