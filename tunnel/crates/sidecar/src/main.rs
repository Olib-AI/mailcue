//! `mailcue-relay-sidecar` — loopback SMTP submission shim that tunnels
//! MailCue outbound mail through one or more edges.
//!
//! See `tunnel/README.md` and `tunnel/docs/PROTOCOL.md`.

#![deny(unsafe_code, rust_2018_idioms)]

mod config;
mod metrics;
mod pool;
mod relay;
mod selector;
mod smtp_server;
mod tunnels;

use std::io::IsTerminal;
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use clap::{Args, Parser, Subcommand};
use tokio::net::TcpListener;
use tokio::sync::watch;
use tracing::{error, info, warn};
use tracing_subscriber::EnvFilter;

use mailcue_relay_proto::KeyPair;

use crate::config::{CliOverrides, SidecarConfig};
use crate::pool::Pool;
use crate::relay::SmtpRelay;
use crate::selector::Selector;
use crate::tunnels::{TunnelRegistry, spawn_watcher};

const EXIT_OK: u8 = 0;
const EXIT_GENERIC: u8 = 1;
const EXIT_CONFIG: u8 = 2;
const EXIT_KEYGEN: u8 = 3;
const EXIT_BIND: u8 = 4;

#[derive(Debug, Parser)]
#[command(
    name = "mailcue-relay-sidecar",
    version,
    about = "MailCue out-of-band SMTP tunnel — sidecar daemon"
)]
struct Cli {
    #[command(subcommand)]
    cmd: Option<Cmd>,
}

#[derive(Debug, Subcommand)]
enum Cmd {
    /// Run the sidecar (default).
    Run(RunArgs),
    /// Generate `<state_dir>/client.key` + `client.pub` if missing; print pubkey.
    Keygen(KeygenArgs),
    /// Print the client's base64 public key.
    Pubkey(KeygenArgs),
}

#[derive(Debug, Args)]
struct RunArgs {
    /// Path to the TOML configuration file.
    #[arg(long, env = "MAILCUE_SIDECAR_CONFIG")]
    config: Option<PathBuf>,
    /// Override SMTP listen.
    #[arg(long, env = "MAILCUE_SIDECAR_SMTP_LISTEN")]
    smtp_listen: Option<String>,
    /// Override metrics listen.
    #[arg(long, env = "MAILCUE_SIDECAR_METRICS_LISTEN")]
    metrics_listen: Option<String>,
    /// Override state dir.
    #[arg(long, env = "MAILCUE_SIDECAR_STATE_DIR")]
    state_dir: Option<PathBuf>,
    /// Override tunnels.json path.
    #[arg(long, env = "MAILCUE_SIDECAR_TUNNELS_PATH")]
    tunnels_path: Option<PathBuf>,
    /// Override client static key path.
    #[arg(long, env = "MAILCUE_SIDECAR_CLIENT_STATIC_KEY_PATH")]
    client_static_key_path: Option<PathBuf>,
    /// Override `client_id` sent in `Frame::Hello`.
    #[arg(long, env = "MAILCUE_SIDECAR_CLIENT_ID")]
    client_id: Option<String>,
    /// Override log level.
    #[arg(long, env = "MAILCUE_SIDECAR_LOG_LEVEL")]
    log_level: Option<String>,
}

#[derive(Debug, Args)]
struct KeygenArgs {
    /// State dir (defaults to `/var/lib/mailcue-sidecar`).
    #[arg(long, env = "MAILCUE_SIDECAR_STATE_DIR")]
    state_dir: Option<PathBuf>,
    /// On rotate, the existing key is moved to `client.key.old` first.
    #[arg(long)]
    rotate: bool,
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let cmd = cli.cmd.unwrap_or(Cmd::Run(RunArgs {
        config: None,
        smtp_listen: None,
        metrics_listen: None,
        state_dir: None,
        tunnels_path: None,
        client_static_key_path: None,
        client_id: None,
        log_level: None,
    }));

    match cmd {
        Cmd::Run(args) => run_cmd(args),
        Cmd::Keygen(args) => keygen_cmd(args),
        Cmd::Pubkey(args) => pubkey_cmd(args),
    }
}

fn keygen_cmd(args: KeygenArgs) -> ExitCode {
    let state = state_dir_for(args.state_dir);
    let key_path = state.join("client.key");

    if args.rotate && key_path.exists() {
        let old = state.join("client.key.old");
        if let Err(e) = std::fs::rename(&key_path, &old) {
            eprintln!(
                "error: rotate: rename {} -> {}: {e}",
                key_path.display(),
                old.display()
            );
            return ExitCode::from(EXIT_KEYGEN);
        }
    }

    if key_path.exists() {
        match KeyPair::load(&key_path) {
            Ok(kp) => {
                println!("{}", kp.public_base64());
                ExitCode::from(EXIT_OK)
            }
            Err(e) => {
                eprintln!("error: load existing keypair {}: {e}", key_path.display());
                ExitCode::from(EXIT_KEYGEN)
            }
        }
    } else {
        match KeyPair::generate().and_then(|kp| {
            kp.persist(&key_path)?;
            Ok(kp)
        }) {
            Ok(kp) => {
                println!("{}", kp.public_base64());
                ExitCode::from(EXIT_OK)
            }
            Err(e) => {
                eprintln!("error: generate/persist keypair: {e}");
                ExitCode::from(EXIT_KEYGEN)
            }
        }
    }
}

fn pubkey_cmd(args: KeygenArgs) -> ExitCode {
    let state = state_dir_for(args.state_dir);
    let pub_file = state.join("client.pub");
    let key_file = state.join("client.key");

    if pub_file.exists() {
        match std::fs::read_to_string(&pub_file) {
            Ok(s) => {
                println!("{}", s.trim());
                ExitCode::from(EXIT_OK)
            }
            Err(e) => {
                eprintln!("error: read {}: {e}", pub_file.display());
                ExitCode::from(EXIT_KEYGEN)
            }
        }
    } else if key_file.exists() {
        match KeyPair::load(&key_file) {
            Ok(kp) => {
                println!("{}", kp.public_base64());
                ExitCode::from(EXIT_OK)
            }
            Err(e) => {
                eprintln!("error: load {}: {e}", key_file.display());
                ExitCode::from(EXIT_KEYGEN)
            }
        }
    } else {
        eprintln!(
            "error: neither {} nor {} exists; run `mailcue-relay-sidecar keygen` first",
            pub_file.display(),
            key_file.display()
        );
        ExitCode::from(EXIT_KEYGEN)
    }
}

fn run_cmd(args: RunArgs) -> ExitCode {
    let config_path = args
        .config
        .clone()
        .or_else(|| std::env::var_os("MAILCUE_SIDECAR_CONFIG").map(PathBuf::from))
        .unwrap_or_else(config::default_config_path);

    let cli_overrides = CliOverrides {
        smtp_listen: args.smtp_listen.clone(),
        metrics_listen: args.metrics_listen.clone(),
        state_dir: args.state_dir.clone(),
        tunnels_path: args.tunnels_path.clone(),
        client_static_key_path: args.client_static_key_path.clone(),
        client_id: args.client_id.clone(),
        log_level: args.log_level.clone(),
    };

    let cfg = match config::load(&config_path, cli_overrides) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("error: load config: {e:#}");
            return ExitCode::from(EXIT_CONFIG);
        }
    };

    init_tracing(&cfg.log_level);

    let runtime = match tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
    {
        Ok(rt) => rt,
        Err(e) => {
            error!(error = %e, "build tokio runtime");
            return ExitCode::from(EXIT_GENERIC);
        }
    };

    runtime.block_on(async move {
        match serve(cfg).await {
            Ok(()) => ExitCode::from(EXIT_OK),
            Err(ServeError::Bind(e)) => {
                error!(error = %e, "bind listener");
                ExitCode::from(EXIT_BIND)
            }
            Err(ServeError::Other(e)) => {
                error!(error = %format!("{e:#}"), "sidecar serve loop");
                ExitCode::from(EXIT_GENERIC)
            }
        }
    })
}

#[derive(Debug)]
enum ServeError {
    Bind(std::io::Error),
    Other(anyhow::Error),
}

async fn serve(cfg: SidecarConfig) -> Result<(), ServeError> {
    // Ensure state dir exists for the keypair.
    if let Some(parent) = cfg.client_static_key_path.parent()
        && !parent.as_os_str().is_empty()
    {
        std::fs::create_dir_all(parent).map_err(|e| {
            ServeError::Other(anyhow::anyhow!(
                "create state dir {}: {e}",
                parent.display()
            ))
        })?;
    }

    // Load or generate the client static keypair.
    let kp = KeyPair::load_or_generate(&cfg.client_static_key_path).map_err(|e| {
        ServeError::Other(anyhow::anyhow!(
            "load/generate {}: {e}",
            cfg.client_static_key_path.display()
        ))
    })?;
    let priv_bytes = *kp.private_bytes();
    let client_pub = kp.public_base64();
    drop(kp);

    info!(
        smtp_listen = %cfg.smtp_listen,
        metrics_listen = %cfg.metrics_listen,
        tunnels_path = %cfg.tunnels_path.display(),
        client_id = %cfg.client_id,
        client_pubkey = %client_pub,
        sidecar_version = env!("CARGO_PKG_VERSION"),
        "sidecar starting",
    );

    let cfg = Arc::new(cfg);

    // Tunnels registry + watcher.
    let registry = TunnelRegistry::new();
    let watcher =
        spawn_watcher(cfg.tunnels_path.clone(), registry.clone()).map_err(ServeError::Other)?;

    // Pool.
    let pool = Pool::new(Arc::clone(&cfg), priv_bytes);
    {
        // Pre-register every tunnel id so metrics aren't blank.
        for t in &registry.snapshot().tunnels {
            pool.ensure(&t.id);
        }
    }
    let pool_for_keepalive = pool.clone();
    tokio::spawn(async move {
        pool_for_keepalive.keepalive_loop().await;
    });

    // Reload-driven retain task: drain conns to removed tunnels.
    let mut reload_rx = registry.subscribe();
    {
        let pool = pool.clone();
        let registry = registry.clone();
        tokio::spawn(async move {
            loop {
                if reload_rx.changed().await.is_err() {
                    break;
                }
                let view = registry.snapshot();
                let keep: std::collections::BTreeSet<String> =
                    view.tunnels.iter().map(|t| t.id.clone()).collect();
                pool.retain(&keep);
                for t in &view.tunnels {
                    pool.ensure(&t.id);
                }
            }
        });
    }

    let selector = Arc::new(Selector::new());
    let smtp_relay = SmtpRelay::new(Arc::clone(&cfg), registry.clone(), pool.clone(), selector);

    // Bind listeners.
    let smtp_listener = TcpListener::bind(cfg.smtp_listen)
        .await
        .map_err(ServeError::Bind)?;
    let metrics_listener = TcpListener::bind(cfg.metrics_listen)
        .await
        .map_err(ServeError::Bind)?;

    let metrics = Arc::new(metrics::Metrics::new(pool.clone()));
    metrics.set_ready(true);

    let (cancel_tx, cancel_rx) = watch::channel(false);

    let smtp_handle = {
        let cfg = Arc::clone(&cfg);
        let metrics = Arc::clone(&metrics);
        let relay = smtp_relay.clone();
        let cancel = cancel_rx.clone();
        tokio::spawn(async move {
            smtp_server::run(smtp_listener, cfg, relay, metrics, cancel).await;
        })
    };

    let metrics_handle = {
        let metrics = Arc::clone(&metrics);
        let cancel = cancel_rx.clone();
        tokio::spawn(async move {
            metrics::run(metrics_listener, metrics, cancel).await;
        })
    };

    // Signal handling: SIGTERM/SIGINT → graceful shutdown; SIGHUP → reload tunnels.
    install_signals(cancel_tx, watcher).await;

    // Drain.
    let drain_window = Duration::from_secs(cfg.request_timeout_secs.max(5));
    if tokio::time::timeout(drain_window, async {
        let _ = smtp_handle.await;
        let _ = metrics_handle.await;
    })
    .await
    .is_err()
    {
        warn!("drain window exceeded; forcing shutdown");
    }

    info!("sidecar stopped");
    Ok(())
}

fn state_dir_for(cli: Option<PathBuf>) -> PathBuf {
    cli.or_else(|| std::env::var_os("MAILCUE_SIDECAR_STATE_DIR").map(PathBuf::from))
        .unwrap_or_else(config::default_state_dir)
}

fn init_tracing(level: &str) {
    let filter = EnvFilter::try_from_default_env()
        .or_else(|_| EnvFilter::try_new(level))
        .unwrap_or_else(|_| EnvFilter::new("info"));
    let is_tty = std::io::stdout().is_terminal();
    if is_tty {
        let _ = tracing_subscriber::fmt()
            .with_env_filter(filter)
            .with_target(false)
            .try_init();
    } else {
        let _ = tracing_subscriber::fmt()
            .json()
            .with_env_filter(filter)
            .try_init();
    }
}

#[cfg(unix)]
async fn install_signals(cancel_tx: watch::Sender<bool>, watcher: tunnels::TunnelsWatcher) {
    use tokio::signal::unix::{SignalKind, signal};
    let mut term = match signal(SignalKind::terminate()) {
        Ok(s) => s,
        Err(e) => {
            warn!(error = %e, "install SIGTERM");
            return;
        }
    };
    let mut intr = match signal(SignalKind::interrupt()) {
        Ok(s) => s,
        Err(e) => {
            warn!(error = %e, "install SIGINT");
            return;
        }
    };
    let mut hup = match signal(SignalKind::hangup()) {
        Ok(s) => s,
        Err(e) => {
            warn!(error = %e, "install SIGHUP");
            return;
        }
    };
    loop {
        tokio::select! {
            _ = term.recv() => {
                info!("SIGTERM received; shutting down");
                let _ = cancel_tx.send(true);
                return;
            }
            _ = intr.recv() => {
                info!("SIGINT received; shutting down");
                let _ = cancel_tx.send(true);
                return;
            }
            _ = hup.recv() => {
                info!("SIGHUP received; reloading tunnels.json");
                watcher.force_reload();
            }
        }
    }
}

#[cfg(not(unix))]
async fn install_signals(cancel_tx: watch::Sender<bool>, _watcher: tunnels::TunnelsWatcher) {
    let _ = tokio::signal::ctrl_c().await;
    let _ = cancel_tx.send(true);
}
