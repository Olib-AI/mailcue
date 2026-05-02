//! Layered configuration: CLI flags > environment > config file > defaults.

use std::net::SocketAddr;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::Deserialize;

use crate::defaults;

/// Resolved, validated edge configuration.
#[derive(Debug, Clone)]
pub struct EdgeConfig {
    /// TCP listen address.
    pub listen_addr: SocketAddr,
    /// Directory holding `server.key` / `server.pub`.
    pub state_dir: PathBuf,
    /// Path to the authorized clients allow-list.
    pub authorized_clients_path: PathBuf,
    /// SMTP ports we are willing to connect to upstream.
    pub allowed_smtp_ports: Vec<u16>,
    /// Maximum raw message size in bytes.
    pub max_message_size_bytes: usize,
    /// Maximum recipients per Relay frame.
    pub max_recipients_per_request: usize,
    /// Per-connection idle timeout (also used as the upper bound for
    /// in-flight relay handlers).
    pub idle_timeout_secs: u64,
    /// Maximum window the SIGTERM drain waits before force-aborting
    /// in-flight tasks. See `defaults::SHUTDOWN_DRAIN_SECS`.
    pub shutdown_drain_secs: u64,
    /// DNS resolvers (empty = use system resolv.conf).
    pub dns_resolvers: Vec<SocketAddr>,
    /// EHLO / HELO override.
    pub helo_hostname: Option<String>,
    /// Per-client concurrency limit.
    pub per_client_concurrency: usize,
    /// MX connect timeout.
    pub connect_timeout_secs: u64,
    /// SMTP per-IO timeout.
    pub smtp_io_timeout_secs: u64,
    /// `tracing` env-filter directive.
    pub log_level: String,
}

impl EdgeConfig {
    /// Path to the long-term private key inside `state_dir`.
    #[must_use]
    pub fn server_key_path(&self) -> PathBuf {
        self.state_dir.join("server.key")
    }

    /// Path to the long-term public key inside `state_dir`.
    #[must_use]
    #[allow(dead_code)] // surfaced for operators / tooling; not used by the daemon itself.
    pub fn server_pub_path(&self) -> PathBuf {
        self.state_dir.join("server.pub")
    }
}

#[derive(Debug, Default, Deserialize)]
struct FileCfg {
    listen_addr: Option<String>,
    state_dir: Option<PathBuf>,
    authorized_clients_path: Option<PathBuf>,
    allowed_smtp_ports: Option<Vec<u16>>,
    max_message_size_bytes: Option<usize>,
    max_recipients_per_request: Option<usize>,
    idle_timeout_secs: Option<u64>,
    shutdown_drain_secs: Option<u64>,
    dns_resolvers: Option<Vec<String>>,
    helo_hostname: Option<String>,
    per_client_concurrency: Option<usize>,
    connect_timeout_secs: Option<u64>,
    smtp_io_timeout_secs: Option<u64>,
    log_level: Option<String>,
}

/// CLI-side overrides for fields that have a `--flag` on `run`.
#[derive(Debug, Default)]
pub struct CliOverrides {
    /// Override `listen_addr`.
    pub listen_addr: Option<String>,
    /// Override `state_dir`.
    pub state_dir: Option<PathBuf>,
    /// Override `authorized_clients_path`.
    pub authorized_clients: Option<PathBuf>,
    /// Override `log_level`.
    pub log_level: Option<String>,
    /// Override `helo_hostname`.
    pub helo_hostname: Option<String>,
}

/// Load configuration with the documented precedence:
///
/// 1. CLI flags.
/// 2. `MAILCUE_EDGE_*` environment variables.
/// 3. TOML file at `config_path` (if it exists).
/// 4. Compiled-in [`defaults`].
///
/// # Errors
///
/// Returns an error if the TOML file is malformed, an env var fails to
/// parse, or any address fails to resolve.
pub fn load(config_path: &Path, cli: CliOverrides) -> Result<EdgeConfig> {
    let file: FileCfg = if config_path.exists() {
        let raw = std::fs::read_to_string(config_path)
            .with_context(|| format!("read config {}", config_path.display()))?;
        toml::from_str(&raw).with_context(|| format!("parse config {}", config_path.display()))?
    } else {
        FileCfg::default()
    };

    let listen_addr = first_some(&[
        cli.listen_addr.as_deref().map(str::to_string),
        env_str("MAILCUE_EDGE_LISTEN_ADDR"),
        file.listen_addr.clone(),
    ])
    .unwrap_or_else(|| defaults::LISTEN_ADDR.to_string());
    let listen_addr: SocketAddr = listen_addr
        .parse()
        .with_context(|| format!("listen_addr `{listen_addr}` is not a valid socket address"))?;

    let state_dir = cli
        .state_dir
        .or_else(|| env_str("MAILCUE_EDGE_STATE_DIR").map(PathBuf::from))
        .or(file.state_dir)
        .unwrap_or_else(defaults::state_dir);

    let authorized_clients_path = cli
        .authorized_clients
        .or_else(|| env_str("MAILCUE_EDGE_AUTHORIZED_CLIENTS").map(PathBuf::from))
        .or(file.authorized_clients_path)
        .unwrap_or_else(defaults::authorized_clients_path);

    let allowed_smtp_ports = env_ports("MAILCUE_EDGE_ALLOWED_SMTP_PORTS")?
        .or(file.allowed_smtp_ports.clone())
        .unwrap_or_else(|| defaults::ALLOWED_SMTP_PORTS.to_vec());

    let max_message_size_bytes = env_usize("MAILCUE_EDGE_MAX_MESSAGE_SIZE_BYTES")?
        .or(file.max_message_size_bytes)
        .unwrap_or(defaults::MAX_MESSAGE_SIZE_BYTES);

    let max_recipients_per_request = env_usize("MAILCUE_EDGE_MAX_RECIPIENTS_PER_REQUEST")?
        .or(file.max_recipients_per_request)
        .unwrap_or(defaults::MAX_RECIPIENTS_PER_REQUEST);

    let shutdown_drain_secs = env_u64("MAILCUE_EDGE_SHUTDOWN_DRAIN_SECS")?
        .or(file.shutdown_drain_secs)
        .unwrap_or(defaults::SHUTDOWN_DRAIN_SECS);
    let idle_timeout_secs = env_u64("MAILCUE_EDGE_IDLE_TIMEOUT_SECS")?
        .or(file.idle_timeout_secs)
        .unwrap_or(defaults::IDLE_TIMEOUT_SECS);

    let dns_resolvers = parse_resolvers(
        env_str("MAILCUE_EDGE_DNS_RESOLVERS")
            .as_deref()
            .map(str::to_string)
            .or_else(|| file.dns_resolvers.as_ref().map(|v| v.join(","))),
    )?;

    let helo_hostname = cli
        .helo_hostname
        .or_else(|| env_str("MAILCUE_EDGE_HELO_HOSTNAME"))
        .or(file.helo_hostname);

    let per_client_concurrency = env_usize("MAILCUE_EDGE_PER_CLIENT_CONCURRENCY")?
        .or(file.per_client_concurrency)
        .unwrap_or(defaults::PER_CLIENT_CONCURRENCY)
        .max(1);

    let connect_timeout_secs = env_u64("MAILCUE_EDGE_CONNECT_TIMEOUT_SECS")?
        .or(file.connect_timeout_secs)
        .unwrap_or(defaults::CONNECT_TIMEOUT_SECS);

    let smtp_io_timeout_secs = env_u64("MAILCUE_EDGE_SMTP_IO_TIMEOUT_SECS")?
        .or(file.smtp_io_timeout_secs)
        .unwrap_or(defaults::SMTP_IO_TIMEOUT_SECS);

    let log_level = cli
        .log_level
        .or_else(|| env_str("MAILCUE_EDGE_LOG_LEVEL"))
        .or(file.log_level)
        .unwrap_or_else(|| defaults::LOG_LEVEL.to_string());

    Ok(EdgeConfig {
        listen_addr,
        state_dir,
        authorized_clients_path,
        allowed_smtp_ports,
        max_message_size_bytes,
        max_recipients_per_request,
        idle_timeout_secs,
        shutdown_drain_secs,
        dns_resolvers,
        helo_hostname,
        per_client_concurrency,
        connect_timeout_secs,
        smtp_io_timeout_secs,
        log_level,
    })
}

fn first_some<T: Clone>(xs: &[Option<T>]) -> Option<T> {
    xs.iter().find_map(|x| x.clone())
}

fn env_str(key: &str) -> Option<String> {
    std::env::var(key)
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

fn env_usize(key: &str) -> Result<Option<usize>> {
    match env_str(key) {
        None => Ok(None),
        Some(v) => Ok(Some(v.parse().with_context(|| format!("{key}=`{v}`"))?)),
    }
}

fn env_u64(key: &str) -> Result<Option<u64>> {
    match env_str(key) {
        None => Ok(None),
        Some(v) => Ok(Some(v.parse().with_context(|| format!("{key}=`{v}`"))?)),
    }
}

fn env_ports(key: &str) -> Result<Option<Vec<u16>>> {
    match env_str(key) {
        None => Ok(None),
        Some(v) => {
            let mut out = Vec::new();
            for tok in v.split(',') {
                let tok = tok.trim();
                if tok.is_empty() {
                    continue;
                }
                out.push(
                    tok.parse()
                        .with_context(|| format!("{key}: invalid port `{tok}`"))?,
                );
            }
            Ok(Some(out))
        }
    }
}

fn parse_resolvers(raw: Option<String>) -> Result<Vec<SocketAddr>> {
    let Some(raw) = raw else {
        return Ok(Vec::new());
    };
    let mut out = Vec::new();
    for tok in raw.split(',') {
        let tok = tok.trim();
        if tok.is_empty() {
            continue;
        }
        let addr: SocketAddr = if tok.contains(':') {
            tok.parse()
                .with_context(|| format!("dns_resolvers: invalid `{tok}`"))?
        } else {
            format!("{tok}:53")
                .parse()
                .with_context(|| format!("dns_resolvers: invalid `{tok}`"))?
        };
        out.push(addr);
    }
    Ok(out)
}
