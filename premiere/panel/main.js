// The panel's half of the conversation with the YEETingus service.
//
// The service is an HTTP server on localhost; this panel is its client and
// long-polls it: GET /api/premiere/poll waits up to 25 s for a command, the
// panel runs it against Premiere (host.js) and POSTs the reply. UXP has fetch
// and nothing needs a WebSocket, so nothing here needs one.
//
// WHICH PORTS: the same list as backend/service.py PANEL_PORTS. The service
// binds the first free one; the panel dials them in turn, so a second
// YEETingus (or a port held by something else) is found within a few tries.
const { createAdapter } = require("./host.js");
const adapter = createAdapter(require("premierepro"), require("uxp").host.version);

const PORTS = [47591, 47592, 47593, 47594, 47595];
// Both spellings of loopback: the service listens on 127.0.0.1 and ::1, and
// which one a given UXP build reaches first isn't something to bet on.
const HOSTS = ["127.0.0.1", "localhost"];
const POLL_WAIT = 25;          // seconds the service holds a poll open
const RETRY_MS = 2500;         // between dial attempts while nothing answers

const dot = document.getElementById("dot");
const state = document.getElementById("connection");
const log = document.getElementById("log");

let base = null;               // "http://127.0.0.1:<port>" once found
let lastTried = "";
let portIndex = 0;
let generation = 0;            // bumps on Reconnect so an old loop stops
let queue = Promise.resolve(); // Premiere edits run one at a time

function status(text, ok) {
  state.textContent = text;
  dot.classList.toggle("on", Boolean(ok));
}
function say(value) {
  log.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}
function serialize(work) {
  const task = queue.then(work);
  queue = task.catch(() => {});
  return task;
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function post(path, body) {
  const res = await fetch(base + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error(path + " → " + res.status);
  return res.json();
}

// One attempt to find a service: say hello on the next port in the list.
// Keep in step with manifest.json and backend/version.py.
const PANEL_VERSION = "2.1.0";

async function dial() {
  const port = PORTS[Math.floor(portIndex / HOSTS.length)];
  const host = HOSTS[portIndex % HOSTS.length];
  portIndex = (portIndex + 1) % (PORTS.length * HOSTS.length);
  const candidate = "http://" + host + ":" + port;
  lastTried = candidate;
  const res = await fetch(candidate + "/api/premiere/hello", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ host: "premiere", panel: PANEL_VERSION,
      version: require("uxp").host.version }),
  });
  if (!res.ok) throw new Error("port " + port + " answered " + res.status);
  const info = await res.json();
  base = candidate;
  return info;
}

async function run(cmd) {
  try {
    const result = await serialize(() => adapter.dispatch(cmd.method, cmd.params || {}));
    return { id: cmd.id, result };
  } catch (error) {
    return { id: cmd.id, error: { kind: error.kind || "PremiereError", message: error.message || String(error) } };
  }
}

// The loop: find a service, then poll it until it goes away, then start over.
async function loop(myGeneration) {
  status("Looking for YEETingus…", false);
  while (myGeneration === generation) {
    let info;
    try { info = await dial(); }
    catch (error) {
      status("Waiting for YEETingus…", false);
      say("No YEETingus at " + lastTried + " (" + (error && error.message ? error.message : error) + ")");
      await sleep(RETRY_MS); continue;
    }
    status("Connected to YEETingus " + (info.version || ""), true);
    say("Connected on " + base + ".");

    while (myGeneration === generation) {
      let reply;
      try {
        const res = await fetch(base + "/api/premiere/poll?wait=" + POLL_WAIT);
        if (!res.ok) throw new Error("poll → " + res.status);
        reply = await res.json();
      } catch (_) {
        break;                 // service gone; dial again
      }
      if (!reply.cmd) continue;   // quiet 25 s; poll again
      const answer = await run(reply.cmd);
      say(answer.error ? "✗ " + answer.error.message : answer.result);
      try { await post("/api/premiere/reply", answer); } catch (_) { break; }
    }
    base = null;
    status("Waiting for YEETingus…", false);
    // A port that answered is the one to keep dialling first.
    portIndex = (portIndex + PORTS.length * HOSTS.length - 1) % (PORTS.length * HOSTS.length);
    await sleep(RETRY_MS);
  }
}

// Premiere's brightness, not a guess at it (see Sherlock's panel).
function wearTheme(theme) {
  const name = typeof theme === "string" ? theme : "dark";
  document.body.classList.remove("theme-light", "theme-dark", "theme-darkest");
  document.body.classList.add("theme-" + (["light", "dark", "darkest"].includes(name) ? name : "dark"));
}
function followTheme() {
  if (!document.theme) { wearTheme("dark"); return; }
  wearTheme(document.theme.getCurrent());
  document.theme.onUpdated.addListener(wearTheme);
}

document.getElementById("connect").addEventListener("click", () => {
  generation += 1;
  base = null;
  loop(generation);
});
// LAUNCHING THE APP FROM HERE. A UXP panel can't start a process, but it can
// hand a URL to the OS, and an installed YEETingus registers the yeetingus://
// scheme (Tauri's deep-link plugin, at install time). Whether this Premiere
// build lets a custom scheme through shell.openExternal is not documented;
// when it refuses, or nothing owns the scheme, the panel says so and the
// user starts YEETingus by hand, exactly as before this button existed.
// NO LAUNCH BUTTON, on purpose. Tried on Premiere 26.3: shell.openExternal
// refuses custom schemes ("URI scheme yeetingus is not accepted") and
// shell.openPath refuses executables ("Extension .exe is not accepted"). A
// UXP panel cannot start a program; the user starts YEETingus, and the panel
// finds it by itself.
document.getElementById("probe").addEventListener("click", () =>
  serialize(adapter.status).then(say).catch(e => say("✗ " + e.message)));

followTheme();
loop(generation);
