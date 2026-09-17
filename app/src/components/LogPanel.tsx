import { useEffect, useRef } from "react";
import type { LogLine } from "../useEngine";
import { X } from "../icons";

export function LogPanel({ lines, onClear, onClose }: { lines: LogLine[]; onClear: () => void; onClose: () => void }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [lines.length]);
  return (
    <aside className="log-panel">
      <header className="log-head">
        <span className="log-title">LOG</span>
        <span className="log-spacer" />
        <button type="button" className="link-btn" onClick={onClear}>clear</button>
        <button type="button" className="icon-btn icon-btn-sm" onClick={onClose} aria-label="Hide log"><X size={16} /></button>
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
