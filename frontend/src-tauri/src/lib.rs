use serde::Serialize;
use std::{
    env,
    net::{SocketAddr, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager};

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: u16 = 8765;
const BACKEND_BINARY_NAME: &str = if cfg!(windows) {
    "ingestor-backend.exe"
} else {
    "ingestor-backend"
};

#[derive(Default)]
struct BackendProcess(Mutex<Option<Child>>);

impl Drop for BackendProcess {
    fn drop(&mut self) {
        if let Ok(mut process) = self.0.lock() {
            if let Some(child) = process.as_mut() {
                terminate_backend_process(child);
            }
        }
    }
}

fn terminate_backend_process(child: &mut Child) {
    #[cfg(windows)]
    {
        let _ = Command::new("taskkill")
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        let _ = child.wait();
        return;
    }

    #[cfg(not(windows))]
    {
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendStatus {
    online: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct StartupSettings {
    supported: bool,
    open_at_login: bool,
}

#[tauri::command]
fn get_backend_url() -> String {
    backend_url()
}

#[tauri::command]
fn get_startup_settings() -> StartupSettings {
    StartupSettings {
        supported: false,
        open_at_login: false,
    }
}

#[tauri::command]
fn set_startup_enabled(_enabled: bool) -> StartupSettings {
    get_startup_settings()
}

fn backend_url() -> String {
    format!("http://{BACKEND_HOST}:{BACKEND_PORT}")
}

fn backend_addr() -> SocketAddr {
    format!("{BACKEND_HOST}:{BACKEND_PORT}")
        .parse()
        .expect("backend socket address should be valid")
}

fn backend_is_listening() -> bool {
    TcpStream::connect_timeout(&backend_addr(), Duration::from_millis(300)).is_ok()
}

fn wait_for_backend(timeout: Duration) -> Result<(), String> {
    let started_at = Instant::now();
    while started_at.elapsed() < timeout {
        if backend_is_listening() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(250));
    }
    Err(format!("Backend did not become ready at {}", backend_url()))
}

fn resolve_dev_backend_dir() -> PathBuf {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.join("..").join("..").join("backend")
}

fn resolve_backend_executable(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(path) = env::var("INGESTOR_BACKEND") {
        return Ok(PathBuf::from(path));
    }

    if cfg!(debug_assertions) {
        return Err("Packaged backend executable is not used in development.".to_string());
    }

    app.path()
        .resource_dir()
        .map(|path| path.join("binaries").join(BACKEND_BINARY_NAME))
        .map_err(|error| format!("Could not resolve resource directory: {error}"))
}

fn resolve_skills_dir(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(path) = env::var("INGESTOR_SKILLS_DIR") {
        return Ok(PathBuf::from(path));
    }

    if cfg!(debug_assertions) {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        return Ok(manifest_dir.join("..").join("..").join("skills"));
    }

    app.path()
        .resource_dir()
        .map(|path| path.join("skills"))
        .map_err(|error| format!("Could not resolve resource directory: {error}"))
}

fn resolve_python(backend_dir: &PathBuf) -> PathBuf {
    if let Ok(path) = env::var("INGESTOR_PYTHON") {
        return PathBuf::from(path);
    }

    let venv_python = if cfg!(windows) {
        backend_dir.join(".venv").join("Scripts").join("python.exe")
    } else {
        backend_dir.join(".venv").join("bin").join("python")
    };

    if venv_python.exists() {
        return venv_python;
    }

    PathBuf::from(if cfg!(windows) { "python.exe" } else { "python3" })
}

fn start_backend(app: &AppHandle) -> Result<(), String> {
    if backend_is_listening() {
        return Ok(());
    }

    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("Could not resolve app data directory: {error}"))?
        .join("data");
    let skills_dir = resolve_skills_dir(app)?;

    let mut command = if cfg!(debug_assertions) {
        let backend_dir = resolve_dev_backend_dir();
        let python = resolve_python(&backend_dir);
        let mut command = Command::new(python);
        command
            .args([
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                BACKEND_HOST,
                "--port",
                &BACKEND_PORT.to_string(),
            ])
            .current_dir(backend_dir);
        command
    } else {
        let backend_executable = resolve_backend_executable(app)?;
        let mut command = Command::new(backend_executable);
        command.args([
            "--host",
            BACKEND_HOST,
            "--port",
            &BACKEND_PORT.to_string(),
        ]);
        command
    };

    command
        .env("INGESTOR_DATA_DIR", data_dir)
        .env("INGESTOR_SKILLS_DIR", skills_dir);

    if cfg!(debug_assertions) {
        command.stdout(Stdio::inherit()).stderr(Stdio::inherit());
    } else {
        command.stdout(Stdio::null()).stderr(Stdio::null());
    }

    let child = command
        .spawn()
        .map_err(|error| format!("Could not start backend: {error}"))?;
    *app.state::<BackendProcess>().0.lock().map_err(|error| error.to_string())? = Some(child);
    wait_for_backend(Duration::from_secs(30))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(BackendProcess::default())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            get_backend_url,
            get_startup_settings,
            set_startup_enabled
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            match start_backend(&handle) {
                Ok(()) => {
                    let _ = handle.emit("backend-status", BackendStatus { online: true });
                }
                Err(error) => {
                    eprintln!("{error}");
                    let _ = handle.emit("backend-status", BackendStatus { online: false });
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
