//! The Tauri shell for YEETingus.
//!
//! Deliberately thin: it starts the Python service (backend/service.py, or the
//! frozen copy of it shipped next to this exe), tells the page where it is,
//! and stops it on exit. Everything else the window does is an HTTP request
//! to that service — see backend/service.py for the routes.

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Condvar, Mutex};

use serde::Serialize;
use tauri::Manager;

/// Where the service ended up; handed to the page by `service_info`.
#[derive(Clone, Serialize)]
struct ServiceInfo {
    port: u16,
    token: String,
}

struct ServiceState {
    info: ServiceInfo,
    child: Mutex<Option<Child>>,
}

/// The service starts on a background thread so the window can paint at
/// once; `service_info` waits here until the handshake is in (or failed).
#[derive(Default)]
struct ServiceSlot {
    result: Mutex<Option<Result<ServiceInfo, String>>>,
    ready: Condvar,
}

impl ServiceSlot {
    fn wait(&self) -> Result<ServiceInfo, String> {
        let mut guard = self.result.lock().map_err(|e| e.to_string())?;
        while guard.is_none() {
            guard = self.ready.wait(guard).map_err(|e| e.to_string())?;
        }
        guard.as_ref().cloned().unwrap()
    }

    fn set(&self, value: Result<ServiceInfo, String>) {
        if let Ok(mut guard) = self.result.lock() {
            *guard = Some(value);
        }
        self.ready.notify_all();
    }
}

/// A random bearer token so nothing else on this machine can drive the
/// service through the browser of an unrelated page.
fn make_token() -> String {
    use rand::RngCore;
    let mut bytes = [0u8; 16];
    rand::thread_rng().fill_bytes(&mut bytes);
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
}

/// The command that runs the service.
///
/// In a dev build that is the repo's backend/service.py under the Python the
/// Resolve bridge supports (see resolve_bridge.MAX_PY). In a release build it
/// is the PyInstaller-frozen service that build.py places beside this exe.
fn service_command(app: &tauri::AppHandle) -> Result<Command, String> {
    if cfg!(debug_assertions) {
        let script = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../backend/service.py");
        let mut cmd = if cfg!(windows) {
            let mut c = Command::new("py");
            c.arg("-3.13");
            c
        } else {
            Command::new("python3")
        };
        cmd.arg(script);
        Ok(cmd)
    } else {
        // The frozen service is a folder (see build.py build_service), shipped
        // as a Tauri resource: <resource dir>/service/yeetingus-service[.exe].
        // On Windows the resource dir is the install dir; on macOS it's
        // Contents/Resources inside the bundle.
        let name = if cfg!(windows) {
            "yeetingus-service.exe"
        } else {
            "yeetingus-service"
        };
        let resource_dir = app.path().resource_dir().map_err(|e| e.to_string())?;
        let exe_dir = std::env::current_exe()
            .map_err(|e| e.to_string())?
            .parent()
            .ok_or("no exe dir")?
            .to_path_buf();
        // The list form of bundle.resources keeps the folder's tree, under
        // the path it had in src-tauri: <resource dir>/resources/service/.
        let candidates = [
            resource_dir.join("resources").join("service").join(name),
            resource_dir.join("service").join(name),
            exe_dir.join("resources").join("service").join(name),
            exe_dir.join("service").join(name),
        ];
        for path in &candidates {
            if path.is_file() {
                let mut cmd = Command::new(path);
                if let Some(dir) = path.parent() {
                    cmd.current_dir(dir);
                }
                return Ok(cmd);
            }
        }
        Err(format!("service missing: {}", candidates[0].display()))
    }
}

fn start_service(app: &tauri::AppHandle) -> Result<ServiceState, String> {
    let token = make_token();
    let mut cmd = service_command(app)?;
    cmd.args(["--port", "0", "--token", &token]);
    if let Ok(exe) = std::env::current_exe() {
        cmd.arg("--app-exe").arg(exe);
    }
    // Launched from Resolve's Scripts menu, this process inherits Resolve's
    // PYTHONHOME and friends, and a PyInstaller-frozen service that inherits
    // PYTHONHOME crashes on startup (1.x needed a .bat shim for this). Strip
    // them here so the launcher can start the app directly.
    for var in ["PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE",
                "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE"] {
        cmd.env_remove(var);
    }
    cmd
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .stdin(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = cmd.spawn().map_err(|e| format!("couldn't start the service: {e}"))?;

    // The service prints one JSON line with its port before anything else.
    let stdout = child.stdout.take().ok_or("no stdout from service")?;
    let mut first = String::new();
    BufReader::new(stdout)
        .read_line(&mut first)
        .map_err(|e| e.to_string())?;
    let parsed: serde_json::Value = serde_json::from_str(first.trim())
        .map_err(|e| format!("bad service handshake '{}': {e}", first.trim()))?;
    let port = parsed["port"]
        .as_u64()
        .ok_or("service handshake had no port")? as u16;

    Ok(ServiceState {
        info: ServiceInfo { port, token },
        child: Mutex::new(Some(child)),
    })
}

fn stop_service(state: &ServiceState) {
    // Ask nicely first so it can remove its info file; then make sure.
    let url = format!("http://127.0.0.1:{}/api/quit", state.info.port);
    let _ = ureq::post(&url)
        .set("Authorization", &format!("Bearer {}", state.info.token))
        .timeout(std::time::Duration::from_secs(2))
        .send_string("{}");
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            std::thread::sleep(std::time::Duration::from_millis(300));
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn focus_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[tauri::command]
async fn service_info(slot: tauri::State<'_, Arc<ServiceSlot>>) -> Result<ServiceInfo, String> {
    let slot = Arc::clone(&slot);
    tauri::async_runtime::spawn_blocking(move || slot.wait())
        .await
        .map_err(|e| e.to_string())?
}

/// Open a file or folder with the shell, or reveal it selected in its folder.
///
/// Done here rather than in the service on purpose: Windows only lets the
/// process that owns the foreground window put a new window on top, and
/// that's this one. Opened from the service, Explorer came up behind the app.
#[tauri::command]
fn show_path(path: String, reveal: bool) -> Result<(), String> {
    if reveal {
        tauri_plugin_opener::reveal_item_in_dir(&path).map_err(|e| e.to_string())
    } else {
        tauri_plugin_opener::open_path(&path, None::<&str>).map_err(|e| e.to_string())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // One YEETingus at a time: a second launch (the Start menu, or the
        // Premiere panel's yeetingus:// link) brings the running window up
        // instead of starting another service.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            focus_main(app);
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // The installer registers yeetingus:// for a packaged build; a dev
            // build registers it for itself here, so the panel's Launch button
            // can be tried before packaging exists.
            #[cfg(any(windows, target_os = "linux"))]
            {
                use tauri_plugin_deep_link::DeepLinkExt;
                let _ = app.deep_link().register_all();
            }
            // Starting the service (a frozen Python app) takes a few
            // seconds; doing it here on the main thread kept the window
            // blank until it answered. Spawn it and let the page wait.
            let slot = Arc::new(ServiceSlot::default());
            app.manage(Arc::clone(&slot));
            let handle = app.handle().clone();
            std::thread::spawn(move || match start_service(&handle) {
                Ok(state) => {
                    slot.set(Ok(state.info.clone()));
                    handle.manage(state);
                }
                Err(e) => slot.set(Err(e)),
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.app_handle().try_state::<ServiceState>() {
                    stop_service(&state);
                }
            }
        })
        .invoke_handler(tauri::generate_handler![service_info, show_path])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
