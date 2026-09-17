/**
 * First run: which editor, and the one-time setup for it.
 *
 * Shown while settings.onboarded is false. Choosing an editor saves it at
 * once; "Done" (or "Skip") marks the setup as seen. Everything here is also
 * reachable later from Settings, so nothing is lost by skipping.
 */
import { useState } from "react";
import type { Api, Editor, EngineState } from "../api";
import { Alert, Check } from "../icons";
import { Button } from "./ui";
import { ResolveMenuSetup } from "./ResolveMenuSetup";

export function Onboarding({ api, state, toolBusy, onDone, onLog }: {
  api: Api;
  state: EngineState;
  toolBusy: Record<string, boolean>;
  onDone: () => void;
  onLog: (text: string) => void;
}) {
  const [editor, setEditor] = useState<Editor | null>(null);

  const choose = (e: Editor) => {
    setEditor(e);
    api.saveSettings({ editor: e }).catch((err) => onLog(`ERROR saving settings: ${String(err)}`));
  };
  const finish = () => {
    api.saveSettings({ onboarded: true }).catch((err) => onLog(`ERROR saving settings: ${String(err)}`));
    onDone();
  };

  const resolveOk = state.editor === "resolve" && state.resolve.level === "ok";
  const pm = state.premiere;
  const installed = pm.installed !== null && pm.installed !== "?";

  return (
    <div className="dialog-backdrop">
      <div className="dialog onboarding" role="dialog" aria-modal="true">
        {editor === null && (
          <>
            <header className="onboarding-head">
              <img src="/logo.png" alt="" className="onboarding-logo" />
              <h2>Welcome to {state.app}</h2>
              <p>Paste a link, pick a range, press YEET — the clip lands on your timeline. Which timeline?</p>
            </header>
            <div className="choice-row">
              <button type="button" className="choice" onClick={() => choose("resolve")}>
                <span className="choice-title">DaVinci Resolve</span>
                <span className="choice-sub">Studio · talks to Resolve directly</span>
              </button>
              <button type="button" className="choice" onClick={() => choose("premiere")}>
                <span className="choice-title">Premiere Pro</span>
                <span className="choice-sub">25+ · through a small panel</span>
              </button>
            </div>
            <footer className="dialog-foot">
              <span className="hint">You can change this any time in Settings.</span>
              <span className="log-spacer" />
              <Button onClick={finish}>Skip</Button>
            </footer>
          </>
        )}

        {editor === "resolve" && (
          <>
            <header className="onboarding-head">
              <h2>DaVinci Resolve</h2>
              <p>YEETingus talks to Resolve through its scripting API. Two things to know:</p>
            </header>
            <ol className="steps">
              <li>
                <b>It needs Resolve Studio.</b> External scripting — a program outside Resolve
                putting clips on your timeline — is a Studio feature. On the free version,
                <b> Download only</b> still works; you drag the file in yourself.
              </li>
              <li>
                <b>Turn external scripting on</b>, once: <code>Preferences → System → General →
                External scripting using → Local</code>.
              </li>
              <li>
                <b>Optional:</b> a YEETingus entry in Resolve's Scripts menu, so you can open it from
                inside Resolve.
                <ResolveMenuSetup api={api} state={state} toolBusy={toolBusy} />
              </li>
            </ol>
            <div className={`setup-status ${resolveOk ? "ok" : ""}`}>
              {resolveOk ? <Check size={16} /> : <Alert size={16} />}
              <span>{state.resolve.text}</span>
              <button type="button" className="link-btn" onClick={() => api.refreshResolve()}>re-check</button>
            </div>
            <footer className="dialog-foot">
              <Button onClick={() => setEditor(null)}>Back</Button>
              <span className="log-spacer" />
              <Button variant="primary" onClick={finish}>Done</Button>
            </footer>
          </>
        )}

        {editor === "premiere" && (
          <>
            <header className="onboarding-head">
              <h2>Premiere Pro</h2>
              <p>
                Premiere has no way for another program to reach it, so YEETingus puts a tiny panel
                inside Premiere and talks to that. One-time setup:
              </p>
            </header>
            <ol className="steps">
              <li>
                <b>Install the panel.</b>{" "}
                {pm.installer
                  ? "YEETingus hands it to Adobe's own plugin installer; nothing else to do."
                  : "Adobe's plugin installer wasn't found — it comes with Creative Cloud desktop 5.5 or newer."}
                <div className="stack">
                  <Button
                    variant={installed ? "secondary" : "primary"}
                    onClick={() => api.installPremierePanel()}
                    disabled={toolBusy.premiere || !pm.installer || !pm.panel_source}
                  >
                    {toolBusy.premiere ? "Installing…" : installed ? `Installed (${pm.installed}) — reinstall` : "Install the Premiere panel"}
                  </Button>
                  {pm.last_install && (
                    <p className={`install-result ${pm.last_install.startsWith("ok") ? "ok" : "bad"}`}>
                      {pm.last_install.replace(/^(ok|error): /, "")}
                    </p>
                  )}
                </div>
              </li>
              <li>
                In Premiere: <code>Window → UXP Plugins → YEETingus</code>. <b>Dock it</b> anywhere
                small and <b>save your workspace</b> — Premiere then brings it back on every launch.
              </li>
              <li>
                Keep YEETingus running while you edit. The panel finds it by itself and shows a
                green dot. (Premiere doesn't let a panel start a program — that one's on Adobe.)
              </li>
            </ol>
            <div className={`setup-status ${pm.connected ? "ok" : ""}`}>
              {pm.connected ? <Check size={16} /> : <Alert size={16} />}
              <span>{pm.connected ? `Panel connected · Premiere ${pm.panel.version ?? ""}` : installed ? "Panel installed, not open in Premiere yet" : "Panel not installed"}</span>
            </div>
            <footer className="dialog-foot">
              <Button onClick={() => setEditor(null)}>Back</Button>
              <span className="log-spacer" />
              <Button variant="primary" onClick={finish}>Done</Button>
            </footer>
          </>
        )}
      </div>
    </div>
  );
}
