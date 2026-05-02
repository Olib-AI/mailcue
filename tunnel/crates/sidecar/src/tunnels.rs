//! Tunnel registry: parsing, validation, and inotify-driven reload of
//! `tunnels.json`.
//!
//! Schema (matches what the MailCue API writes):
//!
//! ```json
//! {
//!   "version": 1,
//!   "selection": "round_robin",
//!   "tunnels": [
//!     {
//!       "id": "ovh-de",
//!       "name": "OVH Frankfurt",
//!       "host": "37.187.0.10",
//!       "port": 7843,
//!       "edge_pubkey": "<base64 32 bytes>",
//!       "weight": 1,
//!       "enabled": true
//!     }
//!   ]
//! }
//! ```

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result, anyhow};
use base64::Engine;
use base64::engine::general_purpose::STANDARD as B64;
use parking_lot::RwLock;
use serde::Deserialize;
use tokio::sync::watch;
use tracing::{info, warn};

/// Selection strategy across enabled+healthy tunnels.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SelectionStrategy {
    /// Round-robin over enabled+healthy.
    #[default]
    RoundRobin,
    /// Uniformly random.
    Random,
    /// Weighted random by `Tunnel::weight`.
    WeightedRandom,
}

/// Raw on-disk tunnel entry (pre-validation).
#[derive(Debug, Clone, Deserialize)]
struct RawTunnel {
    id: String,
    #[serde(default)]
    name: Option<String>,
    host: String,
    port: u16,
    edge_pubkey: String,
    #[serde(default = "default_weight")]
    weight: u32,
    #[serde(default = "default_true")]
    enabled: bool,
}

fn default_weight() -> u32 {
    1
}
fn default_true() -> bool {
    true
}

/// On-disk root document.
#[derive(Debug, Clone, Deserialize)]
struct RawDoc {
    #[serde(default = "one_u32")]
    version: u32,
    #[serde(default)]
    selection: SelectionStrategy,
    #[serde(default)]
    tunnels: Vec<RawTunnel>,
}

fn one_u32() -> u32 {
    1
}

/// A validated tunnel descriptor.
#[derive(Debug, Clone)]
pub struct Tunnel {
    /// Stable id from the API.
    pub id: String,
    /// Human label (defaults to `id`).
    pub name: String,
    /// Edge host (DNS name or IP).
    pub host: String,
    /// Edge TCP port.
    pub port: u16,
    /// Edge X25519 static public key.
    pub edge_pubkey: [u8; 32],
    /// Selector weight.
    pub weight: u32,
    /// Operator-toggleable.
    pub enabled: bool,
}

impl Tunnel {
    /// `host:port` rendering for tracing / logs.
    #[must_use]
    pub fn endpoint(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}

/// Validated registry view.
#[derive(Debug, Clone, Default)]
pub struct TunnelsView {
    /// Selection strategy from the file.
    pub selection: SelectionStrategy,
    /// Validated tunnels in declaration order.
    pub tunnels: Vec<Tunnel>,
}

/// Shared, watch-driven tunnel registry.
#[derive(Debug, Clone)]
pub struct TunnelRegistry {
    inner: Arc<RwLock<TunnelsView>>,
    rx: watch::Receiver<u64>,
    tx: watch::Sender<u64>,
}

impl TunnelRegistry {
    /// Build an empty registry.
    #[must_use]
    pub fn new() -> Self {
        let (tx, rx) = watch::channel(0_u64);
        Self {
            inner: Arc::new(RwLock::new(TunnelsView::default())),
            rx,
            tx,
        }
    }

    /// Snapshot the current view.
    #[must_use]
    pub fn snapshot(&self) -> TunnelsView {
        self.inner.read().clone()
    }

    /// Subscribe to reload notifications. The watched value is a
    /// monotonically-increasing reload counter — consumers can ignore
    /// the value itself and just listen for `changed()`.
    #[must_use]
    pub fn subscribe(&self) -> watch::Receiver<u64> {
        self.rx.clone()
    }

    /// Replace the in-memory view.
    pub fn set(&self, view: TunnelsView) {
        *self.inner.write() = view;
        let next = self.tx.borrow().wrapping_add(1);
        let _ = self.tx.send(next);
    }
}

impl Default for TunnelRegistry {
    fn default() -> Self {
        Self::new()
    }
}

/// Parse a tunnels file. Bad entries are *logged and skipped*, not fatal.
///
/// Returns `Ok` even when the file is missing — the registry is treated
/// as empty (sidecar will refuse to relay until at least one entry is
/// added).
pub fn load_tunnels_file(path: &Path) -> Result<TunnelsView> {
    if !path.exists() {
        return Ok(TunnelsView::default());
    }
    let raw = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    if raw.trim().is_empty() {
        return Ok(TunnelsView::default());
    }
    let doc: RawDoc =
        serde_json::from_str(&raw).with_context(|| format!("parse {}", path.display()))?;
    if doc.version != 1 {
        return Err(anyhow!(
            "unsupported tunnels.json version: {} (expected 1)",
            doc.version
        ));
    }

    let mut tunnels = Vec::with_capacity(doc.tunnels.len());
    for raw in doc.tunnels {
        match validate(raw) {
            Ok(t) => tunnels.push(t),
            Err(e) => warn!(error = %e, "tunnels.json: skipping invalid entry"),
        }
    }
    Ok(TunnelsView {
        selection: doc.selection,
        tunnels,
    })
}

fn validate(raw: RawTunnel) -> Result<Tunnel> {
    if raw.id.trim().is_empty() {
        return Err(anyhow!("empty tunnel id"));
    }
    if raw.host.trim().is_empty() {
        return Err(anyhow!("tunnel `{}`: empty host", raw.id));
    }
    if raw.port == 0 {
        return Err(anyhow!("tunnel `{}`: port 0", raw.id));
    }
    let decoded = B64
        .decode(raw.edge_pubkey.trim())
        .with_context(|| format!("tunnel `{}`: edge_pubkey base64", raw.id))?;
    if decoded.len() != 32 {
        return Err(anyhow!(
            "tunnel `{}`: edge_pubkey must decode to 32 bytes, got {}",
            raw.id,
            decoded.len()
        ));
    }
    let mut pk = [0_u8; 32];
    pk.copy_from_slice(&decoded);
    let name = raw.name.unwrap_or_else(|| raw.id.clone());
    Ok(Tunnel {
        id: raw.id,
        name,
        host: raw.host,
        port: raw.port,
        edge_pubkey: pk,
        weight: raw.weight.max(1),
        enabled: raw.enabled,
    })
}

/// Background task: watch the tunnels file with `notify` and republish on
/// change with a 200ms debounce. Also reloads on SIGHUP — call
/// `force_reload()` from the signal handler.
pub struct TunnelsWatcher {
    /// Path being watched (for diagnostic logs).
    #[allow(dead_code)] // exposed for diagnostics; not used on the hot path.
    pub path: PathBuf,
    /// Forced-reload trigger (e.g. SIGHUP).
    force_tx: tokio::sync::mpsc::UnboundedSender<()>,
}

impl TunnelsWatcher {
    /// Force a reload (e.g. on SIGHUP).
    pub fn force_reload(&self) {
        let _ = self.force_tx.send(());
    }
}

/// Spawn the watcher. The first reload is performed inline and a panic
/// from `notify` setup is surfaced as `Err` (it is not async).
pub fn spawn_watcher(path: PathBuf, registry: TunnelRegistry) -> Result<TunnelsWatcher> {
    use notify::{EventKind, RecursiveMode, Watcher};

    // Initial load.
    match load_tunnels_file(&path) {
        Ok(v) => {
            info!(
                tunnels = v.tunnels.len(),
                strategy = ?v.selection,
                "tunnels.json loaded",
            );
            registry.set(v);
        }
        Err(e) => {
            warn!(error = %format!("{e:#}"), "initial tunnels.json load failed");
            registry.set(TunnelsView::default());
        }
    }

    let (event_tx, mut event_rx) = tokio::sync::mpsc::unbounded_channel::<()>();
    let (force_tx, mut force_rx) = tokio::sync::mpsc::unbounded_channel::<()>();

    let watch_target = path.clone();
    let watch_dir = path
        .parent()
        .map_or_else(|| PathBuf::from("."), Path::to_path_buf);

    // We watch the *parent directory* so atomic-rename writes (the
    // typical writer pattern) are observed.
    let event_sender = event_tx.clone();
    let mut watcher = notify::recommended_watcher(move |res: notify::Result<notify::Event>| {
        if let Ok(ev) = res {
            if !matches!(
                ev.kind,
                EventKind::Create(_) | EventKind::Modify(_) | EventKind::Remove(_)
            ) {
                return;
            }
            // Only fire if the event touches our target file.
            let touches_target = ev.paths.iter().any(|p| p == &watch_target);
            if touches_target || ev.paths.is_empty() {
                let _ = event_sender.send(());
            }
        }
    })
    .context("create file watcher")?;

    if watch_dir.exists() {
        watcher
            .watch(&watch_dir, RecursiveMode::NonRecursive)
            .with_context(|| format!("watch {}", watch_dir.display()))?;
    } else {
        warn!(
            dir = %watch_dir.display(),
            "tunnels.json parent dir does not exist; skipping inotify"
        );
    }

    let path_for_task = path.clone();
    let registry_for_task = registry.clone();
    tokio::spawn(async move {
        // Keep the watcher alive for the lifetime of this task.
        let _watcher = watcher;
        loop {
            tokio::select! {
                _ = event_rx.recv() => {
                    // 200ms debounce — drain.
                    tokio::time::sleep(Duration::from_millis(200)).await;
                    while event_rx.try_recv().is_ok() {}
                    reload(&path_for_task, &registry_for_task);
                }
                _ = force_rx.recv() => {
                    reload(&path_for_task, &registry_for_task);
                }
                else => break,
            }
        }
    });

    Ok(TunnelsWatcher { path, force_tx })
}

fn reload(path: &Path, registry: &TunnelRegistry) {
    match load_tunnels_file(path) {
        Ok(v) => {
            info!(
                tunnels = v.tunnels.len(),
                strategy = ?v.selection,
                "tunnels.json reloaded",
            );
            registry.set(v);
        }
        Err(e) => {
            warn!(error = %format!("{e:#}"), "reload tunnels.json failed; keeping previous view");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn parse_basic_doc() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("tunnels.json");
        let key = B64.encode([7_u8; 32]);
        let raw = format!(
            r#"{{
              "version": 1,
              "selection": "round_robin",
              "tunnels": [
                {{
                  "id": "edge-de",
                  "name": "Frankfurt",
                  "host": "37.187.0.10",
                  "port": 7843,
                  "edge_pubkey": "{key}",
                  "weight": 1,
                  "enabled": true
                }}
              ]
            }}"#
        );
        let mut f = std::fs::File::create(&p).unwrap();
        f.write_all(raw.as_bytes()).unwrap();
        let v = load_tunnels_file(&p).unwrap();
        assert_eq!(v.tunnels.len(), 1);
        assert_eq!(v.tunnels[0].id, "edge-de");
        assert_eq!(v.tunnels[0].port, 7843);
        assert_eq!(v.tunnels[0].edge_pubkey, [7_u8; 32]);
    }

    #[test]
    fn invalid_pubkey_skipped() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("tunnels.json");
        let raw = r#"{
          "version": 1,
          "tunnels": [
            { "id": "good", "host": "h", "port": 7843, "edge_pubkey": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", "weight": 1, "enabled": true },
            { "id": "bad", "host": "h", "port": 7843, "edge_pubkey": "not-base64-!!!", "weight": 1, "enabled": true }
          ]
        }"#;
        std::fs::write(&p, raw).unwrap();
        let v = load_tunnels_file(&p).unwrap();
        assert_eq!(v.tunnels.len(), 1);
        assert_eq!(v.tunnels[0].id, "good");
    }
}
