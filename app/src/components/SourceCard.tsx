import { useState } from "react";
import { ChevronDown, Clock, Copy, Link } from "../icons";
import { Button, Card, Field, Label, Step } from "./ui";
import { secondsToTimestamp } from "../time";

export const QUICK_LENGTHS: [string, number][] = [["15s", 15], ["30s", 30], ["60s", 60]];
// The slider behind the dropdown: any length up to five minutes.
export const SLIDER_MAX = 300;

export interface SourceForm {
  url: string;
  inPoint: string;
  outPoint: string;
}

export function SourceCard({ form, currentLength, flash, onUrl, onIn, onInCommit, onOut, onLength, onEntire, onCopyFromLink, disabled }: {
  form: SourceForm;
  /** End minus in, in seconds, when both parse — what the slider starts at. */
  currentLength: number | null;
  /** Which of the two points the app just changed by itself. */
  flash: { in: boolean; out: boolean };
  onUrl: (v: string) => void;
  onIn: (v: string) => void;
  onInCommit: () => void;
  onOut: (v: string) => void;
  onLength: (seconds: number, quiet?: boolean) => void;
  onEntire: () => void;
  onCopyFromLink: () => void;
  disabled: boolean;
}) {
  const [more, setMore] = useState(false);
  const [slider, setSlider] = useState(30);
  const openSlider = () => {
    setSlider(Math.min(SLIDER_MAX, Math.max(1, Math.round(currentLength ?? 30))));
    setMore(true);
  };
  return (
    <Card>
      <Step title="Source" />

      <Field
        icon={<Link />}
        placeholder="Paste a video link…"
        value={form.url}
        onChange={(e) => onUrl(e.target.value)}
        disabled={disabled}
        spellCheck={false}
        autoComplete="off"
      />

      <div className="row two">
        <div>
          <Label>In point</Label>
          <Field
            className={flash.in ? "is-flash" : ""}
            icon={<Clock />}
            value={form.inPoint}
            onChange={(e) => onIn(e.target.value)}
            onBlur={onInCommit}
            onKeyDown={(e) => e.key === "Enter" && onInCommit()}
            disabled={disabled}
            title={"Leave both points at 00:00 to download the entire video.\nOtherwise the end point follows automatically, using the default clip length from Settings."}
          />
        </div>
        <div>
          <Label>End point</Label>
          <Field
            className={flash.out ? "is-flash" : ""}
            icon={<Clock />}
            value={form.outPoint}
            onChange={(e) => onOut(e.target.value)}
            disabled={disabled}
            title="Leave both points at 00:00 to download the entire video."
          />
        </div>
      </div>

      <Label>Clip length from in point</Label>
      <div className="row lengths">
        {QUICK_LENGTHS.map(([label, s]) => (
          <Button key={label} onClick={() => onLength(s)} disabled={disabled}>{label}</Button>
        ))}
        <Button onClick={onEntire} disabled={disabled} title="Reset both points to 00:00 — downloads the whole video.">Whole</Button>
        <Button
          onClick={() => (more ? setMore(false) : openSlider())}
          disabled={disabled}
          className={`btn-square ${more ? "is-open" : ""}`}
          aria-label="Pick a length"
          aria-expanded={more}
          title="Any length up to 5 minutes"
        >
          <ChevronDown />
        </Button>
        <Button onClick={onCopyFromLink} disabled={disabled} icon={<Copy size={16} />} title="Use the link's ?t= timestamp as the in point">
          From link
        </Button>
      </div>
      {more && (
        // Inline rather than floating: a popover gets clipped by the scrolling
        // column whichever side it opens on, and this also works in UXP.
        <div className="slider-inline">
          <div className="slider-head">
            <span>Clip length</span>
            <strong>{secondsToTimestamp(slider)}</strong>
          </div>
          <input
            type="range"
            min={1}
            max={SLIDER_MAX}
            step={1}
            value={slider}
            autoFocus
            onChange={(e) => { const v = Number(e.target.value); setSlider(v); onLength(v, true); }}
            onMouseUp={() => onLength(slider)}
            onKeyUp={(e) => { if (e.key === "Escape") setMore(false); else onLength(slider); }}
          />
          <div className="slider-scale"><span>0:01</span><span>2:30</span><span>5:00</span></div>
        </div>
      )}
      <p className="hint">mm:ss, hh:mm:ss or seconds · both at 00:00 = entire video</p>
    </Card>
  );
}
