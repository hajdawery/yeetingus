/**
 * Client for backend/service.py. Nothing here knows about React or Tauri
 * beyond `resolveService`, which is the one host-specific bit: how to find
 * the port and token. A UXP panel would supply its own.
 */

export interface ServiceInfo {
  port: number;
  token: string;
}

export interface Tools {
  ytdlp: string;
  ytdlp_version: string | null;
  ffmpeg: string;
  ffmpeg_path: string | null;
  video: string;
  js: string;
  deno_path: string | null;
  ffmpeg_manual: boolean;
  ready: boolean;
}

export interface Premiere {
  connected: boolean;
  panel: { host?: string; version?: string; panel?: string };
  installer: boolean;
  panel_source: boolean;
  /** Version Adobe lists, null = not installed, "?" = not known yet. */
  installed: string | null;
  /** "ok: …" or "error: …" from the last Install click, for the Settings card. */
  last_install: string | null;
}

export type Editor = "resolve" | "premiere";
export type Retime = "project" | "nearest" | "blend" | "optical";
export type Conform = "sharp" | "blend" | "off";

export interface ResolveMenu {
  installed: boolean;
  path: string | null;
  target: string | null;
  stale: boolean;
  app_exe: string | null;
  resolve_found: boolean;
  last_install: string | null;
}

export interface EngineState {
  app: string;
  version: string;
  booted: boolean;
  busy: boolean;
  editor: Editor;
  editors: Editor[];
  /** The chosen editor's connection — named for the first one it reported. */
  resolve: { text: string; level: "ok" | "error" };
  resolve_menu: ResolveMenu;
  premiere: Premiere;
  progress: { fraction: number; step: string };
  tools: Tools;
  settings: { download_dir: string; default_length: number; editor: Editor; onboarded: boolean; retime: Retime; conform: Conform };
  retimes: Retime[];
  quality_options: string[];
  insert_modes: string[];
}

export interface Meta {
  id: string;
  title: string;
  channel: string;
  heights: number[];
  duration: number | null;
  thumbnail: string | null;
  age_restricted: boolean;
}

export interface Clip {
  path: string;
  name: string;
  folder: string;
  id: string;
  title: string;
  channel: string;
  url: string | null;
  thumbnail: string | null;
  section: { start: string; end: string } | null;
  quality: string | null;
  kind: "full" | "clip";
  number: number | null;
  size: number;
  mtime: number;
  /** Seconds, once known (probed in the background for older clips). */
  duration: number | null;
  /** The video's page, when known. */
  source: string | null;
}

export type EngineEvent =
  | { kind: "log"; seq: number; t: number; text: string; tag: string | null }
  | { kind: "progress"; seq: number; t: number; fraction: number | null; step: string | null }
  | { kind: "resolve"; seq: number; t: number; text: string; level: "ok" | "error" }
  | { kind: "busy"; seq: number; t: number; busy: boolean }
  | ({ kind: "tools"; seq: number; t: number } & Tools)
  | { kind: "tool_busy"; seq: number; t: number; tool: "ytdlp" | "ffmpeg" | "js" | "premiere" | "resolve_menu"; busy: boolean }
  | ({ kind: "premiere"; seq: number; t: number } & Premiere)
  | ({ kind: "resolve_menu"; seq: number; t: number } & ResolveMenu)
  | ({ kind: "settings"; seq: number; t: number } & EngineState["settings"])
  | { kind: "reveal_log"; seq: number; t: number }
  | { kind: "clips"; seq: number; t: number }
  | ({ kind: "state"; seq: number; t: number } & EngineState);

export interface JobRequest {
  url: string;
  in: string;
  out: string;
  quality: string;
  insert_at: string;
  insert: boolean;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export class Api {
  private base: string;
  private headers: Record<string, string>;

  constructor(private info: ServiceInfo) {
    this.base = `http://127.0.0.1:${info.port}`;
    this.headers = {
      Authorization: `Bearer ${info.token}`,
      "Content-Type": "application/json",
    };
  }

  private async call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    const res = await fetch(this.base + path, {
      method,
      headers: this.headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new ApiError(res.status, (data as { error?: string }).error ?? res.statusText);
    }
    return data as T;
  }

  state() {
    return this.call<EngineState>("GET", "/api/state");
  }
  startJob(req: JobRequest) {
    // 409 means the engine refused and already said why in the log.
    return this.call<{ started: boolean }>("POST", "/api/jobs", req).catch((e) => {
      if (e instanceof ApiError && e.status === 409) return { started: false };
      throw e;
    });
  }
  cancel() {
    return this.call<{ cancelled: boolean }>("POST", "/api/jobs/cancel", {});
  }
  meta(url: string) {
    return this.call<Meta>("POST", "/api/meta", { url });
  }
  refreshResolve() {
    return this.call<{ connected: boolean }>("POST", "/api/resolve/refresh", {});
  }
  resolveEnv() {
    return this.call<{ status: unknown; env: Record<string, unknown> }>("GET", "/api/resolve");
  }
  updateYtdlp() {
    return this.call<{ started: boolean }>("POST", "/api/tools/update-ytdlp", {});
  }
  installFfmpeg() {
    return this.call<{ started: boolean }>("POST", "/api/tools/install-ffmpeg", {});
  }
  installJs() {
    return this.call<{ started: boolean }>("POST", "/api/tools/install-js", {});
  }
  installResolveMenu() {
    return this.call<{ started: boolean }>("POST", "/api/resolve/menu/install", {});
  }
  installPremierePanel() {
    return this.call<{ started: boolean }>("POST", "/api/premiere/install", {});
  }
  saveSettings(s: { download_dir?: string; default_length?: number; editor?: Editor; onboarded?: boolean; retime?: Retime; conform?: Conform }) {
    return this.call<EngineState["settings"]>("POST", "/api/settings", s);
  }
  log(text: string, tag?: string) {
    return this.call<{ ok: boolean }>("POST", "/api/log", { text, tag: tag ?? null });
  }
  /** The clips folder. In Tauri the app opens it itself so Explorer lands on top. */
  async openFolder(dir?: string) {
    if (dir && (await showPath(dir, false))) return { opened: dir };
    return this.call<{ opened: string }>("POST", "/api/open-folder", {});
  }
  clips() {
    return this.call<{ clips: Clip[] }>("GET", "/api/clips").then((r) => r.clips);
  }
  /** One clip or several, pasted in order as a single job. */
  insertClip(path: string | string[], insert_at: string) {
    const body = Array.isArray(path) ? { paths: path, insert_at } : { path, insert_at };
    return this.call<{ started: boolean }>("POST", "/api/clips/insert", body).catch((e) => {
      if (e instanceof ApiError && e.status === 409) return { started: false };
      throw e;
    });
  }
  deleteClip(path: string) {
    return this.call<{ deleted: boolean }>("POST", "/api/clips/delete", { path }).catch((e) => {
      if (e instanceof ApiError && e.status === 409) return { deleted: false };
      throw e;
    });
  }
  async openClipFolder(path: string) {
    if (await showPath(path, true)) return { opened: path };
    return this.call<{ opened: string }>("POST", "/api/clips/open", { path });
  }
  async playClip(path: string) {
    if (await showPath(path, false)) return { opened: path };
    return this.call<{ opened: string }>("POST", "/api/clips/play", { path });
  }
  openClipSource(path: string) {
    return this.call<{ opened: string }>("POST", "/api/clips/source", { path });
  }

  /**
   * The event stream. Replays the log after `since`, then everything live.
   * Returns a function that closes it.
   */
  events(onEvent: (ev: EngineEvent) => void, onError?: () => void, since = 0): () => void {
    // EventSource can't set headers, hence the token in the query string.
    const url = `${this.base}/api/events?token=${encodeURIComponent(this.info.token)}&since=${since}`;
    const es = new EventSource(url);
    const kinds = ["log", "progress", "resolve", "busy", "tools", "tool_busy", "reveal_log", "clips", "premiere", "resolve_menu", "settings", "state"];
    for (const kind of kinds) {
      es.addEventListener(kind, (e) => {
        onEvent(JSON.parse((e as MessageEvent).data) as EngineEvent);
      });
    }
    es.onerror = () => onError?.();
    return () => es.close();
  }
}

/**
 * Open (or reveal, selected in its folder) a path from the app process, so
 * the window it opens comes to the front on Windows. False outside Tauri or
 * if it failed, and the caller falls back to asking the service.
 */
async function showPath(path: string, reveal: boolean): Promise<boolean> {
  const w = window as unknown as { __TAURI_INTERNALS__?: unknown };
  if (!w.__TAURI_INTERNALS__) return false;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("show_path", { path, reveal });
    return true;
  } catch {
    return false;
  }
}

/** Where the service is. In Tauri, Rust started it and knows. */
export async function resolveService(): Promise<ServiceInfo> {
  const w = window as unknown as { __TAURI_INTERNALS__?: unknown };
  if (w.__TAURI_INTERNALS__) {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<ServiceInfo>("service_info");
  }
  // Plain browser (vite dev without Tauri): a service started by hand, e.g.
  //   py -3.13 backend/service.py --port 47591 --token dev
  const params = new URLSearchParams(window.location.search);
  return {
    port: Number(params.get("port") ?? 47591),
    token: params.get("token") ?? "dev",
  };
}
