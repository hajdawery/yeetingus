/**
 * The window's languages. English text is the key: `t("Clips")` is "Clips"
 * in English and whatever PL says in Polish, and a phrase PL doesn't have
 * falls back to English rather than showing a key. `{name}` placeholders are
 * filled from the second argument.
 *
 * Text the service sends (progress steps, the connection pill, queue steps)
 * goes through `tr`: exact phrases first, then patterns for the ones with a
 * number or a name in them. Anything it doesn't know is shown as sent. The
 * log stays in English — most of it is yt-dlp's and ffmpeg's own output.
 */
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { PL, SERVER_PL, SERVER_PL_PATTERNS } from "./i18n-pl";

export type Lang = "en" | "pl";
export type LangSetting = "auto" | Lang;

/** The language to show for a setting; "auto" follows the system. */
export function resolveLang(setting: string | null | undefined): Lang {
  if (setting === "en" || setting === "pl") return setting;
  const nav = typeof navigator === "undefined" ? "" : (navigator.languages?.[0] ?? navigator.language ?? "");
  return nav.toLowerCase().startsWith("pl") ? "pl" : "en";
}

type Vars = Record<string, string | number>;

function fill(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => (key in vars ? String(vars[key]) : whole));
}

export interface I18n {
  lang: Lang;
  /** A phrase of this window's own. */
  t: (text: string, vars?: Vars) => string;
  /** A phrase the service sent. */
  tr: (text: string) => string;
  /** For toLocale*String: Polish dates in Polish, the system's otherwise. */
  locale: string | undefined;
}

export function makeI18n(lang: Lang): I18n {
  return {
    lang,
    t: (text, vars) => fill(lang === "pl" ? PL[text] ?? text : text, vars),
    tr: (text) => {
      if (lang !== "pl" || !text) return text;
      const exact = SERVER_PL[text];
      if (exact !== undefined) return exact;
      for (const [re, out] of SERVER_PL_PATTERNS) {
        const m = re.exec(text);
        if (m) return out(m);
      }
      return text;
    },
    locale: lang === "pl" ? "pl-PL" : undefined,
  };
}

/**
 * A translated phrase with <b>, <i> or <code> in it, rendered as those
 * elements, so a whole sentence can be translated with its emphasis where
 * the language puts it. Only those three tags; everything else is text.
 */
export function Rich({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  const re = /<(b|i|code)>(.*?)<\/\1>/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const Tag = m[1] as "b" | "i" | "code";
    parts.push(<Tag key={m.index}>{m[2]}</Tag>);
    last = re.lastIndex;
  }
  parts.push(text.slice(last));
  return <>{parts}</>;
}

const Context = createContext<I18n>(makeI18n("en"));

export function I18nProvider({ lang, children }: { lang: Lang; children: ReactNode }) {
  const value = useMemo(() => makeI18n(lang), [lang]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useI18n(): I18n {
  return useContext(Context);
}
