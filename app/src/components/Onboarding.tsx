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
import { Rich, useI18n, type LangSetting } from "../i18n";
import { Button, Segmented } from "./ui";
import { ResolveMenuSetup } from "./ResolveMenuSetup";

export function Onboarding({ api, state, toolBusy, onDone, onLog, language, onLanguage }: {
  api: Api;
  state: EngineState;
  toolBusy: Record<string, boolean>;
  onDone: () => void;
  onLog: (text: string) => void;
  /** The language shown, and a way to change it right here. */
  language: "en" | "pl";
  onLanguage: (lang: LangSetting) => void;
}) {
  const { t, tr } = useI18n();
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
              <h2>{t("Welcome to {app}", { app: state.app })}</h2>
              <p>{t("Paste a link, pick a range, press YEET — the clip lands on your timeline. Which timeline?")}</p>
            </header>
            <div className="choice-row">
              <button type="button" className="choice" onClick={() => choose("resolve")}>
                <span className="choice-title">DaVinci Resolve</span>
                <span className="choice-sub">{t("Studio · talks to Resolve directly")}</span>
              </button>
              <button type="button" className="choice" onClick={() => choose("premiere")}>
                <span className="choice-title">Premiere Pro</span>
                <span className="choice-sub">{t("25+ · through a small panel")}</span>
              </button>
            </div>
            <footer className="dialog-foot">
              <Segmented<"en" | "pl">
                className="lang-switch"
                options={[{ value: "en", label: "English" }, { value: "pl", label: "Polski" }]}
                value={language}
                onChange={onLanguage}
              />
              <span className="hint">{t("You can change this any time in Settings.")}</span>
              <span className="log-spacer" />
              <Button onClick={finish}>{t("Skip")}</Button>
            </footer>
          </>
        )}

        {editor === "resolve" && (
          <>
            <header className="onboarding-head">
              <h2>DaVinci Resolve</h2>
              <p>{t("YEETingus talks to Resolve through its scripting API. Two things to know:")}</p>
            </header>
            <ol className="steps">
              <li>
                <Rich text={t("<b>It needs Resolve Studio.</b> External scripting — a program outside Resolve putting clips on your timeline — is a Studio feature. On the free version, <b>Download only</b> still works; you drag the file in yourself.")} />
              </li>
              <li>
                <Rich text={t("<b>Turn external scripting on</b>, once: <code>Preferences → System → General → External scripting using → Local</code>.")} />
              </li>
              <li>
                <Rich text={t("<b>Optional:</b> a YEETingus entry in Resolve's Scripts menu, so you can open it from inside Resolve.")} />
                <ResolveMenuSetup api={api} state={state} toolBusy={toolBusy} />
              </li>
            </ol>
            <div className={`setup-status ${resolveOk ? "ok" : ""}`}>
              {resolveOk ? <Check size={16} /> : <Alert size={16} />}
              <span>{tr(state.resolve.text)}</span>
              <button type="button" className="link-btn" onClick={() => api.refreshResolve()}>{t("re-check")}</button>
            </div>
            <footer className="dialog-foot">
              <Button onClick={() => setEditor(null)}>{t("Back")}</Button>
              <span className="log-spacer" />
              <Button variant="primary" onClick={finish}>{t("Done")}</Button>
            </footer>
          </>
        )}

        {editor === "premiere" && (
          <>
            <header className="onboarding-head">
              <h2>Premiere Pro</h2>
              <p>{t("Premiere has no way for another program to reach it, so YEETingus puts a tiny panel inside Premiere and talks to that. One-time setup:")}</p>
            </header>
            <ol className="steps">
              <li>
                <b>{t("Install the panel.")}</b>{" "}
                {pm.installer
                  ? t("YEETingus hands it to Adobe's own plugin installer; nothing else to do.")
                  : t("Adobe's plugin installer wasn't found — it comes with Creative Cloud desktop 5.5 or newer.")}
                <div className="stack">
                  <Button
                    variant={installed ? "secondary" : "primary"}
                    onClick={() => api.installPremierePanel()}
                    disabled={toolBusy.premiere || !pm.installer || !pm.panel_source}
                  >
                    {toolBusy.premiere
                      ? t("Installing…")
                      : installed ? t("Installed ({version}) — reinstall", { version: pm.installed ?? "" }) : t("Install the Premiere panel")}
                  </Button>
                  {pm.last_install && (
                    <p className={`install-result ${pm.last_install.startsWith("ok") ? "ok" : "bad"}`}>
                      {tr(pm.last_install.replace(/^(ok|error): /, ""))}
                    </p>
                  )}
                </div>
              </li>
              <li>
                <Rich text={t("In Premiere: <code>Window → UXP Plugins → YEETingus</code>. <b>Dock it</b> anywhere small and <b>save your workspace</b> — Premiere then brings it back on every launch.")} />
              </li>
              <li>
                {t("Keep YEETingus running while you edit. The panel finds it by itself and shows a green dot. (Premiere doesn't let a panel start a program — that one's on Adobe.)")}
              </li>
            </ol>
            <div className={`setup-status ${pm.connected ? "ok" : ""}`}>
              {pm.connected ? <Check size={16} /> : <Alert size={16} />}
              <span>
                {pm.connected
                  ? t("Panel connected · Premiere {version}", { version: pm.panel.version ?? "" })
                  : installed ? t("Panel installed, not open in Premiere yet") : t("Panel not installed")}
              </span>
            </div>
            <footer className="dialog-foot">
              <Button onClick={() => setEditor(null)}>{t("Back")}</Button>
              <span className="log-spacer" />
              <Button variant="primary" onClick={finish}>{t("Done")}</Button>
            </footer>
          </>
        )}
      </div>
    </div>
  );
}
