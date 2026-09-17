import type { Api, EngineState } from "../api";
import { Button } from "./ui";

/** The "add YEETingus to Resolve's Scripts menu" block, used by Settings and the first run. */
export function ResolveMenuSetup({ api, state, toolBusy }: {
  api: Api; state: EngineState; toolBusy: Record<string, boolean>;
}) {
  const m = state.resolve_menu;
  const busy = Boolean(toolBusy.resolve_menu);
  const label = busy ? "Adding…" : m.installed ? (m.stale ? "Update the Resolve menu entry" : "Re-add to Resolve's Scripts menu") : "Add to Resolve's Scripts menu";
  return (
    <div className="stack">
      <dl className="tools">
        <dt>Menu</dt>
        <dd className={m.installed && !m.stale ? "" : "bad"}>
          {!m.resolve_found
            ? "Resolve's Scripts folder not found — is Resolve installed for this user?"
            : m.installed
              ? m.stale ? "entry points at another YEETingus — update it" : "in Workspace → Scripts → Utility"
              : "not in Resolve's menu yet"}
        </dd>
      </dl>
      <Button block onClick={() => api.installResolveMenu()} disabled={busy || state.busy || !m.app_exe}>
        {label}
      </Button>
      {m.last_install && (
        <p className={`install-result ${m.last_install.startsWith("ok") ? "ok" : "bad"}`}>
          {m.last_install.replace(/^(ok|error): /, "")}
        </p>
      )}
      <p className="hint">Optional — it just launches YEETingus from inside Resolve. Resolve reads its menu at startup, so restart it afterwards.</p>
    </div>
  );
}
