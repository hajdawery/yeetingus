/**
 * The building blocks, kept deliberately plain: real <button>, <input> and
 * <select> elements, flexbox layout, no portals, no pointer-capture tricks.
 * That is what lets the same components run inside a Premiere UXP panel
 * later, where the DOM and CSS are a subset of a browser's.
 */
import { useEffect, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import { ChevronDown } from "../icons";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`card ${className}`}>{children}</section>;
}

/** A section heading inside a card. */
export function Step({ title, aside }: { title: string; aside?: ReactNode }) {
  return (
    <div className="step">
      <span className="step-title">{title}</span>
      {aside && <span className="step-aside">{aside}</span>}
    </div>
  );
}

/** A section laid out as one row: label on the left, the control on the right. */
export function StepRow({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="step-row">
      <div className="step"><span className="step-title">{title}</span></div>
      <div className="step-control">{children}</div>
    </div>
  );
}

export function Label({ children }: { children: ReactNode }) {
  return <label className="field-label">{children}</label>;
}

export function Field({ icon, className = "", ...rest }: InputHTMLAttributes<HTMLInputElement> & {
  icon?: ReactNode;
}) {
  return (
    <div className={`field ${icon ? "has-icon" : ""} ${className}`}>
      {icon && <span className="field-icon">{icon}</span>}
      <input {...rest} />
    </div>
  );
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({ variant = "secondary", icon, block, className = "", children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: Variant;
    icon?: ReactNode;
    block?: boolean;
  }) {
  return (
    <button
      type="button"
      className={`btn btn-${variant} ${block ? "btn-block" : ""} ${className}`}
      {...rest}
    >
      {icon && <span className="btn-icon">{icon}</span>}
      {children && <span className="btn-label">{children}</span>}
    </button>
  );
}

export function IconButton({ label, className = "", children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button type="button" className={`icon-btn ${className}`} title={label} aria-label={label} {...rest}>
      {children}
    </button>
  );
}

/** A pill of mutually exclusive choices — the AutoSubs "Timeline | File" control. */
export function Segmented<T extends string>({ options, value, onChange, disabled, className = "" }: {
  options: { value: T; label: string; icon?: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <div className={`segmented ${className}`} role="radiogroup">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          className={`segment ${o.value === value ? "is-active" : ""}`}
          onClick={() => onChange(o.value)}
          disabled={disabled}
        >
          {o.icon && <span className="segment-icon">{o.icon}</span>}
          <span className="segment-label">{o.label}</span>
        </button>
      ))}
    </div>
  );
}

/**
 * A dropdown drawn by us, not the OS: the native <select> popup ignores the
 * page's colours (white list, invisible text on Windows), and UXP has no
 * <select> at all. Same Menu as the length picker.
 */
export function Select({ options, value, onChange, icon, disabled }: {
  options: string[];
  value: string;
  onChange: (v: string) => void;
  icon?: ReactNode;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="menu-anchor select-anchor">
      <button
        type="button"
        className={`select ${icon ? "has-icon" : ""} ${open ? "is-open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {icon && <span className="field-icon">{icon}</span>}
        <span className="select-value">{value}</span>
        <span className="select-chevron"><ChevronDown size={16} /></span>
      </button>
      <Menu open={open} onClose={() => setOpen(false)} up>
        <div role="listbox" className="select-list">
          {options.map((o) => (
            <button
              key={o}
              type="button"
              role="option"
              aria-selected={o === value}
              className={`menu-item ${o === value ? "is-selected" : ""}`}
              onClick={() => { setOpen(false); onChange(o); }}
            >
              {o}
            </button>
          ))}
        </div>
      </Menu>
    </div>
  );
}

export function Switch({ checked, onChange, label, hint, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string; disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={`switch ${checked ? "is-on" : ""}`}
      title={hint}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span className="switch-track"><span className="switch-thumb" /></span>
      <span className="switch-label">{label}</span>
    </button>
  );
}

export function ProgressBar({ fraction }: { fraction: number }) {
  const pct = Math.max(0, Math.min(1, fraction)) * 100;
  return (
    <div className="progress" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <div className="progress-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** A small in-flow popover; opens under its anchor, closes on outside click. */
export function Menu({ open, onClose, up, align = "right", children }: {
  open: boolean; onClose: () => void; up?: boolean; align?: "left" | "right"; children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <>
      <div className="menu-backdrop" onClick={onClose} />
      <div className={`menu ${up ? "menu-up" : ""} ${align === "left" ? "menu-left" : ""}`}>{children}</div>
    </>
  );
}
