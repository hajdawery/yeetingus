import { useEffect, useRef } from "react";
import type { LogLine } from "../useEngine";
import { X } from "../icons";
import { useI18n } from "../i18n";

export function LogPanel({ lines, onClear, onClose }: { lines: LogLine[]; onClear: () => void; onClose: () => void }) {
  const { t } = useI18n();
  const end = useRef<HTMLDivElement>(null);
  // The newest line, not the count: past the cap the count stops changing.
  const last = lines.length ? lines[lines.length - 1].seq : 0;
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [last]);
  return (
    <aside className="log-panel">
      <header className="log-head">
        <span className="log-title">{t("LOG")}</span>
        <span className="log-spacer" />
        <button type="button" className="link-btn" onClick={onClear}>{t("clear")}</button>
        <button type="button" className="icon-btn icon-btn-sm" onClick={onClose} aria-label={t("Hide log")}><X size={16} /></button>
      </header>
      <div className="log-body">
        {lines.map((l) => (
          <div key={l.seq} className={`log-line ${l.tag ? `log-${l.tag}` : ""}`}>{l.text}</div>
        ))}
        <div ref={end} />
      </div>
    </aside>
  );
}
