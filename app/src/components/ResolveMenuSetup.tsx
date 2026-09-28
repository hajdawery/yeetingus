import type { Api, EngineState } from "../api";
import { useI18n } from "../i18n";
import { Button } from "./ui";

/** The "add YEETingus to Resolve's Scripts menu" block, used by Settings and the first run. */
export function ResolveMenuSetup({ api, state, toolBusy }: {
  api: Api; state: EngineState; toolBusy: Record<string, boolean>;
}) {
  const { t, tr } = useI18n();
  const m = state.resolve_menu;
  const busy = Boolean(toolBusy.resolve_menu);
  const label = busy ? t("Adding…") : m.installed ? (m.stale ? t("Update the Resolve menu entry") : t("Re-add to Resolve's Scripts menu")) : t("Add to Resolve's Scripts menu");
  return (
    <div className="stack">
      <dl className="tools">
        <dt>{t("Menu")}</dt>
        <dd className={m.installed && !m.stale ? "" : "bad"}>
          {!m.resolve_found
            ? t("Resolve's Scripts folder not found — is Resolve installed for this user?")
            : m.installed
              ? m.stale ? t("entry is out of date — update it") : t("in Workspace → Scripts → Utility")
              : t("not in Resolve's menu yet")}
        </dd>
      </dl>
      <Button block onClick={() => api.installResolveMenu()} disabled={busy || state.busy || !m.app_exe}>
        {label}
      </Button>
      {m.last_install && (
        <p className={`install-result ${m.last_install.startsWith("ok") ? "ok" : "bad"}`}>
          {tr(m.last_install.replace(/^(ok|error): /, ""))}
        </p>
      )}
      <p className="hint">{t("Needed on Resolve Free: clicking it starts the bridge that inserts your clips. On Studio it just opens YEETingus. Resolve reads its menu at startup, so restart it afterwards.")}</p>
    </div>
  );
}
