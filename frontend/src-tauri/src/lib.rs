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
    "ingestor-daemon.exe"
} else {
    "ingestor-daemon"
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

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CliPathSettings {
    supported: bool,
    path: String,
    in_path: bool,
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

#[tauri::command]
fn get_cli_path_settings(app: AppHandle) -> CliPathSettings {
    cli_path_settings(&app)
}

#[tauri::command]
fn add_cli_to_path(app: AppHandle) -> Result<CliPathSettings, String> {
    let cli_dir = resolve_cli_dir(&app)?;

    #[cfg(windows)]
    {
        if user_path_contains(&cli_dir)? {
            return Ok(cli_path_settings(&app));
        }

        add_to_user_path(&cli_dir)?;
        return Ok(cli_path_settings(&app));
    }

    #[cfg(not(windows))]
    {
        Err("PATH management is only available in the installed Windows app.".to_string())
    }
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

fn resolve_cli_dir(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(path) = env::var("INGESTOR_CLI_DIR") {
        return Ok(PathBuf::from(path));
    }

    if cfg!(debug_assertions) {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        return Ok(manifest_dir.join("binaries"));
    }

    app.path()
        .resource_dir()
        .map(|path| path.join("binaries"))
        .map_err(|error| format!("Could not resolve resource directory: {error}"))
}

fn cli_path_settings(app: &AppHandle) -> CliPathSettings {
    match resolve_cli_dir(app) {
        Ok(cli_dir) => {
            let in_path = user_path_contains(&cli_dir).unwrap_or(false);
            CliPathSettings {
                supported: cfg!(windows) && cli_dir.exists(),
                path: cli_dir.to_string_lossy().into_owned(),
                in_path,
            }
        }
        Err(_) => CliPathSettings {
            supported: false,
            path: String::new(),
            in_path: false,
        },
    }
}

fn normalize_path_entry(path: &str) -> String {
    path.trim()
        .trim_matches('"')
        .trim_end_matches(['\\', '/'])
        .to_ascii_lowercase()
}

fn path_list_contains(path_list: &str, path: &PathBuf) -> bool {
    let target = normalize_path_entry(&path.to_string_lossy());
    path_list
        .split(';')
        .map(normalize_path_entry)
        .any(|entry| !entry.is_empty() && entry == target)
}

#[cfg(windows)]
fn read_user_path() -> Result<String, String> {
    let output = Command::new("powershell.exe")
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Environment]::GetEnvironmentVariable('Path', 'User')",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(|error| format!("Could not read user PATH: {error}"))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

#[cfg(windows)]
fn user_path_contains(path: &PathBuf) -> Result<bool, String> {
    let user_path = read_user_path()?;
    Ok(path_list_contains(&user_path, path))
}

#[cfg(not(windows))]
fn user_path_contains(_path: &PathBuf) -> Result<bool, String> {
    Ok(false)
}

#[cfg(windows)]
fn add_to_user_path(path: &PathBuf) -> Result<(), String> {
    let script = r#"
$cli = $env:INGESTOR_CLI_DIR
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$parts = @()
if (-not [string]::IsNullOrWhiteSpace($userPath)) {
  $parts = $userPath -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
}
if ($parts -notcontains $cli) {
  $nextPath = if ($parts.Count -eq 0) { $cli } else { ($parts + $cli) -join ';' }
  [Environment]::SetEnvironmentVariable('Path', $nextPath, 'User')
}
Add-Type -Namespace Win32 -Name NativeMethods -MemberDefinition '[DllImport("user32.dll", SetLastError=true, CharSet=CharSet.Auto)] public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);'
$result = [UIntPtr]::Zero
[Win32.NativeMethods]::SendMessageTimeout([IntPtr]0xffff, 0x1A, [UIntPtr]::Zero, 'Environment', 0x2, 5000, [ref]$result) | Out-Null
"#;

    let output = Command::new("powershell.exe")
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-Command",
            script,
        ])
        .env("INGESTOR_CLI_DIR", path)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(|error| format!("Could not update user PATH: {error}"))?;

    if output.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
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
                "app.daemon",
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
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            get_backend_url,
            get_startup_settings,
            set_startup_enabled,
            get_cli_path_settings,
            add_cli_to_path
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
