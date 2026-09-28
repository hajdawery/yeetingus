import { List, Moon, Refresh, Settings, Sun } from "../icons";
import { useI18n } from "../i18n";
import { IconButton } from "./ui";

export function Header({ resolve, editor, connected, onRefresh, onLog, onSettings, theme, onTheme, logOpen }: {
  resolve: { text: string; level: "ok" | "error" } | null;
  editor: "resolve" | "premiere";
  connected: boolean;
  onRefresh: () => void;
  onLog: () => void;
  onSettings: () => void;
  theme: "dark" | "light";
  onTheme: () => void;
  logOpen: boolean;
}) {
  const { t, tr } = useI18n();
  const level = !connected ? "error" : resolve?.level ?? "error";
  const text = !connected ? t("Service not connected") : resolve ? tr(resolve.text) : t("Connecting…");
  return (
    <header className="topbar">
      <button
        type="button"
        className={`status status-${level}`}
        onClick={onRefresh}
        title={t("Re-check the connection to {editor}", { editor: editor === "premiere" ? "Premiere Pro" : "DaVinci Resolve" })}
      >
        <span className="status-text">{text}</span>
        <span className="status-refresh"><Refresh size={14} /></span>
      </button>
      <div className="topbar-actions">
        <IconButton label={logOpen ? t("Hide log") : t("Show log")} onClick={onLog} className={logOpen ? "is-active" : ""}>
          <List size={20} />
        </IconButton>
        <IconButton label={t("Settings")} onClick={onSettings}><Settings size={20} /></IconButton>
        <IconButton label={theme === "dark" ? t("Light theme") : t("Dark theme")} onClick={onTheme}>
          {theme === "dark" ? <Moon size={20} /> : <Sun size={20} />}
        </IconButton>
      </div>
    </header>
  );
}
