//! Default values for every tunable field. Centralised so they can be
//! referenced from CLI, config-file, and env-var resolution code.

use std::path::PathBuf;

/// Default TCP listen address.
pub const LISTEN_ADDR: &str = "0.0.0.0:7843";

/// Default state directory.
pub fn state_dir() -> PathBuf {
    PathBuf::from("/var/lib/mailcue-edge")
}

/// Default config file location.
pub fn config_path() -> PathBuf {
    PathBuf::from("/etc/mailcue-edge/config.toml")
}

/// Default authorized clients file location.
pub fn authorized_clients_path() -> PathBuf {
    PathBuf::from("/etc/mailcue-edge/authorized_clients")
}

/// Default upstream SMTP ports we will connect to.
pub const ALLOWED_SMTP_PORTS: &[u16] = &[25, 465, 587];

/// Default 50 MiB cap on raw message size.
pub const MAX_MESSAGE_SIZE_BYTES: usize = 52_428_800;

/// Default recipient list cap.
pub const MAX_RECIPIENTS_PER_REQUEST: usize = 100;

/// Idle timeout for in-flight relays during graceful shutdown (seconds).
pub const IDLE_TIMEOUT_SECS: u64 = 120;

/// Concurrent relays per authenticated client.
pub const PER_CLIENT_CONCURRENCY: usize = 8;

/// Connect timeout when dialling an upstream MX (seconds).
pub const CONNECT_TIMEOUT_SECS: u64 = 30;

/// Per-command SMTP I/O timeout (seconds).
pub const SMTP_IO_TIMEOUT_SECS: u64 = 120;

/// Default log level filter.
pub const LOG_LEVEL: &str = "info";

/// Maximum reassembled relay payload (matches `max_message_size_bytes`
/// plus a generous overhead for envelope + framing). Used to cap the
/// `Channel`'s reassembly buffer.
pub const REASSEMBLY_HEADROOM_BYTES: usize = 4 * 1024 * 1024;
