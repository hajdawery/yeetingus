import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

// No browser context menu in the app: "Reload"/"Inspect" make no sense
// here. Inputs keep theirs so cut/copy/paste still work.
if ((window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__) {
  document.addEventListener("contextmenu", (e) => {
    const t = e.target as HTMLElement | null;
    if (t?.closest("input, textarea, [contenteditable='true']")) return;
    if (window.getSelection()?.toString()) return;   // selected text: allow Copy
    e.preventDefault();
  });
}

// The saved theme before the first paint, so a light-theme user never sees
// the dark default first (App keeps it in sync from here on).
try {
  const saved = localStorage.getItem("theme");
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
} catch { /* storage blocked: the dark default it is */ }

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
