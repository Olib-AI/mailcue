//! Sidecar configuration: TOML file + `MAILCUE_SIDECAR_*` env overrides.
//!
//! Defaults (matching `tunnel/deploy/docker/Dockerfile.sidecar` expectations):
//!
//! - `smtp_listen        = 127.0.0.1:2525`
//! - `metrics_listen     = 127.0.0.1:9325`
//! - `state_dir          = /var/lib/mailcue-sidecar`
//! - `tunnels_path       = /etc/mailcue-sidecar/tunnels.json`
//! - `client_static_key_path = <state_dir>/client.key`
//! - `max_message_size_bytes = 50 MiB`
//! - `max_recipients_per_request = 100`
//! - `connect_timeout_secs   = 10`
//! - `request_timeout_secs   = 120`
//! - `pool_idle_per_tunnel   = 2`
//! - `pool_idle_timeout_secs = 60`
//! - `keepalive_interval_secs = 30`
//! - `unhealthy_after_consecutive_failures = 3`
//! - `partial_failure_policy = retry`

use std::net::SocketAddr;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::Deserialize;

/// Sidecar config file path (default).
#[must_use]
pub fn default_config_path() -> PathBuf {
    PathBuf::from("/etc/mailcue-sidecar/config.toml")
}

/// State dir default.
#[must_use]
pub fn default_state_dir() -> PathBuf {
    PathBuf::from("/var/lib/mailcue-sidecar")
}

/// Tunnels file default.
#[must_use]
pub fn default_tunnels_path() -> PathBuf {
    PathBuf::from("/etc/mailcue-sidecar/tunnels.json")
}

/// Default SMTP listen.
pub const DEFAULT_SMTP_LISTEN: &str = "127.0.0.1:2525";
/// Default metrics listen.
pub const DEFAULT_METRICS_LISTEN: &str = "127.0.0.1:9325";
/// Default cap on message size in bytes (50 MiB).
pub const DEFAULT_MAX_MESSAGE_SIZE: usize = 52_428_800;
/// Default cap on recipients per submitted message (sidecar-local SMTP).
pub const DEFAULT_MAX_RECIPIENTS: usize = 100;
/// Default connect timeout (seconds).
pub const DEFAULT_CONNECT_TIMEOUT_SECS: u64 = 10;
/// Default per-relay request timeout (seconds).
pub const DEFAULT_REQUEST_TIMEOUT_SECS: u64 = 120;
/// Default pool idle conns per tunnel.
pub const DEFAULT_POOL_IDLE_PER_TUNNEL: usize = 2;
/// Default pool idle eviction timeout (seconds).
pub const DEFAULT_POOL_IDLE_TIMEOUT_SECS: u64 = 60;
/// Default keepalive interval (seconds).
pub const DEFAULT_KEEPALIVE_INTERVAL_SECS: u64 = 30;
/// Default consecutive failures before a tunnel is marked unhealthy.
pub const DEFAULT_UNHEALTHY_AFTER: u32 = 3;
/// Default `tracing` log level.
pub const DEFAULT_LOG_LEVEL: &str = "info";

/// Reassembly headroom matching `tunnel/crates/edge/src/defaults.rs`.
pub const REASSEMBLY_HEADROOM_BYTES: usize = 4 * 1024 * 1024;

/// Behaviour when a `RelayResult` mixes Delivered + PermFail recipients.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PartialFailurePolicy {
    /// Bounce the whole submission with `451 4.7.1` so Postfix retries.
    #[default]
    Retry,
    /// Accept the submission and report `250` with mixed details.
    AcceptPartial,
}

/// Resolved, validated sidecar configuration.
#[derive(Debug, Clone)]
#[allow(dead_code)] // `state_dir` is exposed for tooling/diagnostics; not read on the hot path.
pub struct SidecarConfig {
    /// Loopback SMTP listen.
    pub smtp_listen: SocketAddr,
    /// Metrics / health listen.
    pub metrics_listen: SocketAddr,
    /// State directory for `client.key` / `client.pub`.
    pub state_dir: PathBuf,
    /// Tunnels JSON path.
    pub tunnels_path: PathBuf,
    /// Path to the long-term client static key.
    pub client_static_key_path: PathBuf,
    /// Free-form id sent in `Frame::Hello.client_id`.
    pub client_id: String,
    /// Max accepted message size on the loopback SMTP.
    pub max_message_size_bytes: usize,
    /// Max recipients per submitted SMTP message.
    pub max_recipients_per_request: usize,
    /// Connect / handshake timeout.
    pub connect_timeout_secs: u64,
    /// Per-relay request timeout (sidecar-side).
    pub request_timeout_secs: u64,
    /// Pool: idle conns per tunnel.
    pub pool_idle_per_tunnel: usize,
    /// Pool: idle eviction window.
    pub pool_idle_timeout_secs: u64,
    /// Keepalive interval.
    pub keepalive_interval_secs: u64,
    /// Failure threshold for `unhealthy`.
    pub unhealthy_after_consecutive_failures: u32,
    /// Partial-failure mapping policy.
    pub partial_failure_policy: PartialFailurePolicy,
    /// `tracing` env-filter directive.
    pub log_level: String,
    /// CIDR networks (in addition to loopback) trusted to submit on
    /// the local SMTP listener. Empty means "loopback only" — the
    /// secure default for non-containerised installs. For docker-
    /// compose deployments where the sidecar is on a private bridge
    /// (e.g. mailcue connecting from `172.18.0.0/16`), set this via
    /// `MAILCUE_SIDECAR_SMTP_TRUSTED_NETWORKS`.
    pub smtp_trusted_networks: Vec<ipnet::IpNet>,
}

#[derive(Debug, Default, Deserialize)]
struct FileCfg {
    smtp_listen: Option<String>,
    metrics_listen: Option<String>,
    state_dir: Option<PathBuf>,
    tunnels_path: Option<PathBuf>,
    client_static_key_path: Option<PathBuf>,
    client_id: Option<String>,
    max_message_size_bytes: Option<usize>,
    max_recipients_per_request: Option<usize>,
    connect_timeout_secs: Option<u64>,
    request_timeout_secs: Option<u64>,
    pool_idle_per_tunnel: Option<usize>,
    pool_idle_timeout_secs: Option<u64>,
    keepalive_interval_secs: Option<u64>,
    unhealthy_after_consecutive_failures: Option<u32>,
    partial_failure_policy: Option<PartialFailurePolicy>,
    log_level: Option<String>,
    smtp_trusted_networks: Option<Vec<String>>,
}

/// CLI-side overrides to layer on top of file + env config.
#[derive(Debug, Default, Clone)]
pub struct CliOverrides {
    /// Override `smtp_listen`.
    pub smtp_listen: Option<String>,
    /// Override `metrics_listen`.
    pub metrics_listen: Option<String>,
    /// Override `state_dir`.
    pub state_dir: Option<PathBuf>,
    /// Override `tunnels_path`.
    pub tunnels_path: Option<PathBuf>,
    /// Override `client_static_key_path`.
    pub client_static_key_path: Option<PathBuf>,
    /// Override `client_id`.
    pub client_id: Option<String>,
    /// Override `log_level`.
    pub log_level: Option<String>,
}

/// Load the sidecar config (CLI > env > file > defaults).
pub fn load(config_path: &Path, cli: CliOverrides) -> Result<SidecarConfig> {
    let file: FileCfg = if config_path.exists() {
        let raw = std::fs::read_to_string(config_path)
            .with_context(|| format!("read config {}", config_path.display()))?;
        toml::from_str(&raw).with_context(|| format!("parse config {}", config_path.display()))?
    } else {
        FileCfg::default()
    };

    let smtp_listen_s = cli
        .smtp_listen
        .or_else(|| env_str("MAILCUE_SIDECAR_SMTP_LISTEN"))
        .or(file.smtp_listen)
        .unwrap_or_else(|| DEFAULT_SMTP_LISTEN.to_string());
    let smtp_listen: SocketAddr = smtp_listen_s
        .parse()
        .with_context(|| format!("smtp_listen `{smtp_listen_s}` is not a socket address"))?;

    let metrics_listen_s = cli
        .metrics_listen
        .or_else(|| env_str("MAILCUE_SIDECAR_METRICS_LISTEN"))
        .or(file.metrics_listen)
        .unwrap_or_else(|| DEFAULT_METRICS_LISTEN.to_string());
    let metrics_listen: SocketAddr = metrics_listen_s
        .parse()
        .with_context(|| format!("metrics_listen `{metrics_listen_s}` is not a socket address"))?;

    let state_dir = cli
        .state_dir
        .or_else(|| env_str("MAILCUE_SIDECAR_STATE_DIR").map(PathBuf::from))
        .or(file.state_dir)
        .unwrap_or_else(default_state_dir);

    let tunnels_path = cli
        .tunnels_path
        .or_else(|| env_str("MAILCUE_SIDECAR_TUNNELS_PATH").map(PathBuf::from))
        .or(file.tunnels_path)
        .unwrap_or_else(default_tunnels_path);

    let client_static_key_path = cli
        .client_static_key_path
        .or_else(|| env_str("MAILCUE_SIDECAR_CLIENT_STATIC_KEY_PATH").map(PathBuf::from))
        .or(file.client_static_key_path)
        .unwrap_or_else(|| state_dir.join("client.key"));

    let client_id = cli
        .client_id
        .or_else(|| env_str("MAILCUE_SIDECAR_CLIENT_ID"))
        .or(file.client_id)
        .unwrap_or_else(|| gethostname::gethostname().to_string_lossy().into_owned());

    let max_message_size_bytes = env_usize("MAILCUE_SIDECAR_MAX_MESSAGE_SIZE_BYTES")?
        .or(file.max_message_size_bytes)
        .unwrap_or(DEFAULT_MAX_MESSAGE_SIZE);
    let max_recipients_per_request = env_usize("MAILCUE_SIDECAR_MAX_RECIPIENTS_PER_REQUEST")?
        .or(file.max_recipients_per_request)
        .unwrap_or(DEFAULT_MAX_RECIPIENTS)
        .max(1);
    let connect_timeout_secs = env_u64("MAILCUE_SIDECAR_CONNECT_TIMEOUT_SECS")?
        .or(file.connect_timeout_secs)
        .unwrap_or(DEFAULT_CONNECT_TIMEOUT_SECS);
    let request_timeout_secs = env_u64("MAILCUE_SIDECAR_REQUEST_TIMEOUT_SECS")?
        .or(file.request_timeout_secs)
        .unwrap_or(DEFAULT_REQUEST_TIMEOUT_SECS);
    let pool_idle_per_tunnel = env_usize("MAILCUE_SIDECAR_POOL_IDLE_PER_TUNNEL")?
        .or(file.pool_idle_per_tunnel)
        .unwrap_or(DEFAULT_POOL_IDLE_PER_TUNNEL)
        .max(1);
    let pool_idle_timeout_secs = env_u64("MAILCUE_SIDECAR_POOL_IDLE_TIMEOUT_SECS")?
        .or(file.pool_idle_timeout_secs)
        .unwrap_or(DEFAULT_POOL_IDLE_TIMEOUT_SECS);
    let keepalive_interval_secs = env_u64("MAILCUE_SIDECAR_KEEPALIVE_INTERVAL_SECS")?
        .or(file.keepalive_interval_secs)
        .unwrap_or(DEFAULT_KEEPALIVE_INTERVAL_SECS);
    let unhealthy_after_consecutive_failures =
        env_u32("MAILCUE_SIDECAR_UNHEALTHY_AFTER_CONSECUTIVE_FAILURES")?
            .or(file.unhealthy_after_consecutive_failures)
            .unwrap_or(DEFAULT_UNHEALTHY_AFTER)
            .max(1);

    let partial_failure_policy = match env_str("MAILCUE_SIDECAR_PARTIAL_FAILURE_POLICY").as_deref()
    {
        Some(v) => match v {
            "retry" => PartialFailurePolicy::Retry,
            "accept_partial" => PartialFailurePolicy::AcceptPartial,
            other => {
                return Err(anyhow::anyhow!(
                    "MAILCUE_SIDECAR_PARTIAL_FAILURE_POLICY: unknown value `{other}`"
                ));
            }
        },
        None => file.partial_failure_policy.unwrap_or_default(),
    };

    let log_level = cli
        .log_level
        .or_else(|| env_str("MAILCUE_SIDECAR_LOG_LEVEL"))
        .or(file.log_level)
        .unwrap_or_else(|| DEFAULT_LOG_LEVEL.to_string());

    // Comma-separated CIDRs in addition to loopback. Empty / unset =
    // loopback-only (the secure default for non-containerised installs).
    let trusted_strings: Vec<String> =
        if let Some(raw) = env_str("MAILCUE_SIDECAR_SMTP_TRUSTED_NETWORKS") {
            raw.split(',')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect()
        } else {
            file.smtp_trusted_networks.unwrap_or_default()
        };
    let mut smtp_trusted_networks = Vec::with_capacity(trusted_strings.len());
    for s in &trusted_strings {
        let net: ipnet::IpNet = s.parse().with_context(|| {
            format!("smtp_trusted_networks: `{s}` is not a CIDR (e.g. 172.18.0.0/16)")
        })?;
        smtp_trusted_networks.push(net);
    }

    Ok(SidecarConfig {
        smtp_listen,
        metrics_listen,
        state_dir,
        tunnels_path,
        client_static_key_path,
        client_id,
        max_message_size_bytes,
        max_recipients_per_request,
        connect_timeout_secs,
        request_timeout_secs,
        pool_idle_per_tunnel,
        pool_idle_timeout_secs,
        keepalive_interval_secs,
        unhealthy_after_consecutive_failures,
        partial_failure_policy,
        log_level,
        smtp_trusted_networks,
    })
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

fn env_u32(key: &str) -> Result<Option<u32>> {
    match env_str(key) {
        None => Ok(None),
        Some(v) => Ok(Some(v.parse().with_context(|| format!("{key}=`{v}`"))?)),
    }
}
