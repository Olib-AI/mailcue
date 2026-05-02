//! `mailcue-relay-edge` — OVH-side listener that relays SMTP from MailCue
//! sidecars to public MX servers.
//!
//! See `tunnel/README.md` for operational guidance and
//! `tunnel/docs/PROTOCOL.md` for the wire protocol.

#![deny(unsafe_code, rust_2018_idioms)]

mod config;
mod defaults;
mod dns;
mod relay;
mod smtp_client;

use std::io::IsTerminal;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, anyhow};
use base64::Engine;
use base64::engine::general_purpose::STANDARD as B64;
use clap::{Args, Parser, Subcommand};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{Mutex, Semaphore};
use tokio::time::timeout;
use tracing::{debug, error, info, warn};
use tracing_subscriber::EnvFilter;

use mailcue_relay_proto::{
    AuthorizedClients, Channel, ErrorCode, Frame, HandshakeRole, KeyPair, PROTO_VERSION,
    perform_handshake,
};

use crate::config::{CliOverrides, EdgeConfig};
use crate::defaults::REASSEMBLY_HEADROOM_BYTES;

const EXIT_OK: u8 = 0;
const EXIT_GENERIC: u8 = 1;
const EXIT_CONFIG: u8 = 2;
const EXIT_KEYGEN: u8 = 3;
const EXIT_BIND: u8 = 4;

/// CLI surface for the edge daemon.
#[derive(Debug, Parser)]
#[command(
    name = "mailcue-relay-edge",
    version,
    about = "MailCue out-of-band SMTP tunnel — edge daemon",
    propagate_version = true
)]
struct Cli {
    #[command(subcommand)]
    cmd: Option<Cmd>,
}

#[derive(Debug, Subcommand)]
enum Cmd {
    /// Run the edge listener (default).
    Run(RunArgs),
    /// Generate `<state_dir>/server.key` + `server.pub` if missing; print pubkey.
    Keygen(KeygenArgs),
    /// Print the server's base64 public key.
    Pubkey(KeygenArgs),
    /// Authorize a sidecar by appending its base64 public key to the allow-list.
    Authorize(AuthorizeArgs),
    /// Revoke a sidecar by removing its base64 public key from the allow-list.
    Revoke(RevokeArgs),
    /// List authorized sidecars (fingerprint + name).
    List(ListArgs),
}

#[derive(Debug, Args)]
struct RunArgs {
    /// Path to the TOML configuration file.
    #[arg(long, env = "MAILCUE_EDGE_CONFIG")]
    config: Option<PathBuf>,
    /// Override the configured listen address.
    #[arg(long, env = "MAILCUE_EDGE_LISTEN_ADDR")]
    listen_addr: Option<String>,
    /// Override the state directory.
    #[arg(long, env = "MAILCUE_EDGE_STATE_DIR")]
    state_dir: Option<PathBuf>,
    /// Override the authorized_clients path.
    #[arg(long, env = "MAILCUE_EDGE_AUTHORIZED_CLIENTS")]
    authorized_clients: Option<PathBuf>,
    /// Override the EHLO/HELO hostname.
    #[arg(long, env = "MAILCUE_EDGE_HELO_HOSTNAME")]
    helo_hostname: Option<String>,
    /// Override `tracing` log level (e.g. `info`, `debug`).
    #[arg(long, env = "MAILCUE_EDGE_LOG_LEVEL")]
    log_level: Option<String>,
}

#[derive(Debug, Args)]
struct KeygenArgs {
    /// State directory (defaults to `/var/lib/mailcue-edge`).
    #[arg(long, env = "MAILCUE_EDGE_STATE_DIR")]
    state_dir: Option<PathBuf>,
}

#[derive(Debug, Args)]
struct AuthorizeArgs {
    /// Base64-encoded 32-byte X25519 sidecar public key (positional).
    pubkey_pos: Option<String>,
    /// Base64-encoded 32-byte X25519 sidecar public key (`--pubkey` form).
    #[arg(long = "pubkey")]
    pubkey_flag: Option<String>,
    /// Optional human label written next to the entry.
    #[arg(long)]
    name: Option<String>,
    /// Path to the authorized_clients file (defaults to
    /// `/etc/mailcue-edge/authorized_clients`).
    #[arg(
        long = "config-path",
        alias = "authorized-clients",
        env = "MAILCUE_EDGE_AUTHORIZED_CLIENTS"
    )]
    config_path: Option<PathBuf>,
}

#[derive(Debug, Args)]
struct RevokeArgs {
    /// Base64-encoded 32-byte X25519 sidecar public key (positional).
    pubkey_pos: Option<String>,
    /// Base64-encoded 32-byte X25519 sidecar public key (`--pubkey` form).
    #[arg(long = "pubkey")]
    pubkey_flag: Option<String>,
    /// Path to the authorized_clients file.
    #[arg(
        long = "config-path",
        alias = "authorized-clients",
        env = "MAILCUE_EDGE_AUTHORIZED_CLIENTS"
    )]
    config_path: Option<PathBuf>,
}

#[derive(Debug, Args)]
struct ListArgs {
    /// Path to the authorized_clients file.
    #[arg(
        long = "config-path",
        alias = "authorized-clients",
        env = "MAILCUE_EDGE_AUTHORIZED_CLIENTS"
    )]
    config_path: Option<PathBuf>,
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let cmd = cli.cmd.unwrap_or(Cmd::Run(RunArgs {
        config: None,
        listen_addr: None,
        state_dir: None,
        authorized_clients: None,
        helo_hostname: None,
        log_level: None,
    }));

    match cmd {
        Cmd::Run(args) => run_command(args),
        Cmd::Keygen(args) => keygen_command(args),
        Cmd::Pubkey(args) => pubkey_command(args),
        Cmd::Authorize(args) => authorize_command(args),
        Cmd::Revoke(args) => revoke_command(args),
        Cmd::List(args) => list_command(args),
    }
}

// ---------------------------------------------------------------------------
// `run` — server loop
// ---------------------------------------------------------------------------

fn run_command(args: RunArgs) -> ExitCode {
    let config_path = args
        .config
        .clone()
        .or_else(|| std::env::var_os("MAILCUE_EDGE_CONFIG").map(PathBuf::from))
        .unwrap_or_else(defaults::config_path);

    let cli_overrides = CliOverrides {
        listen_addr: args.listen_addr.clone(),
        state_dir: args.state_dir.clone(),
        authorized_clients: args.authorized_clients.clone(),
        log_level: args.log_level.clone(),
        helo_hostname: args.helo_hostname.clone(),
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
                error!(error = %format!("{e:#}"), "edge serve loop");
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

async fn serve(cfg: EdgeConfig) -> Result<(), ServeError> {
    // Load or generate the long-term keypair.
    let key_path = cfg.server_key_path();
    let kp = KeyPair::load_or_generate(&key_path).map_err(|e| {
        ServeError::Other(anyhow!(
            "load/generate server key at {}: {e}",
            key_path.display()
        ))
    })?;
    let local_priv = *kp.private_bytes();
    let pub_b64 = kp.public_base64();
    drop(kp);

    let allow_path = cfg.authorized_clients_path.clone();
    let cfg = Arc::new(cfg);

    let helo_name = cfg
        .helo_hostname
        .clone()
        .unwrap_or_else(|| gethostname::gethostname().to_string_lossy().into_owned());

    let resolver = dns::MxResolver::new(&cfg.dns_resolvers)
        .map_err(|e| ServeError::Other(anyhow!("init DNS resolver: {e:#}")))?;
    let resolver = Arc::new(resolver);

    let listener = TcpListener::bind(cfg.listen_addr)
        .await
        .map_err(ServeError::Bind)?;
    info!(
        listen_addr = %cfg.listen_addr,
        server_pubkey = %pub_b64,
        proto_version = PROTO_VERSION,
        edge_version = env!("CARGO_PKG_VERSION"),
        "edge listener up",
    );

    // Per-client semaphores keyed by hex(client_pubkey). All access
    // serialized through one mutex; it is only touched on connection
    // accept / drop.
    let semaphores: Arc<Mutex<std::collections::HashMap<[u8; 32], Arc<Semaphore>>>> =
        Arc::new(Mutex::new(std::collections::HashMap::new()));

    let shutdown = install_signal_handler();
    tokio::pin!(shutdown);

    let connections: Arc<tokio::sync::Mutex<tokio::task::JoinSet<()>>> =
        Arc::new(tokio::sync::Mutex::new(tokio::task::JoinSet::new()));

    loop {
        tokio::select! {
            biased;
            () = &mut shutdown => {
                info!("shutdown signal received; draining in-flight connections");
                break;
            }
            accept_res = listener.accept() => {
                let (stream, peer) = match accept_res {
                    Ok(p) => p,
                    Err(e) => {
                        warn!(error = %e, "accept failed");
                        continue;
                    }
                };
                let _ = stream.set_nodelay(true);

                let cfg = Arc::clone(&cfg);
                let resolver = Arc::clone(&resolver);
                let allow_path = allow_path.clone();
                let helo_name = helo_name.clone();
                let semaphores = Arc::clone(&semaphores);

                let conns = Arc::clone(&connections);
                let mut guard = conns.lock().await;
                guard.spawn(async move {
                    if let Err(e) = handle_connection(
                        stream,
                        peer,
                        &cfg,
                        &allow_path,
                        &local_priv,
                        &resolver,
                        &helo_name,
                        &semaphores,
                    )
                    .await
                    {
                        debug!(peer = %peer, error = %format!("{e:#}"), "connection ended with error");
                    }
                });
            }
        }
    }

    // Graceful drain.
    let drain_window = Duration::from_secs(cfg.idle_timeout_secs);
    let drain = async {
        let mut guard = connections.lock().await;
        while let Some(res) = guard.join_next().await {
            if let Err(e) = res {
                debug!(error = %e, "connection task aborted");
            }
        }
    };
    if timeout(drain_window, drain).await.is_err() {
        warn!(
            timeout_secs = cfg.idle_timeout_secs,
            "drain window exceeded; aborting in-flight tasks"
        );
        let mut guard = connections.lock().await;
        guard.shutdown().await;
    }

    info!("edge listener stopped");
    Ok(())
}

#[allow(clippy::too_many_arguments)]
async fn handle_connection(
    mut stream: TcpStream,
    peer: SocketAddr,
    cfg: &EdgeConfig,
    allow_path: &Path,
    local_priv: &[u8; 32],
    resolver: &Arc<dns::MxResolver>,
    helo_name: &str,
    semaphores: &Arc<Mutex<std::collections::HashMap<[u8; 32], Arc<Semaphore>>>>,
) -> Result<()> {
    // Bound the handshake itself.
    let hs_timeout = Duration::from_secs(cfg.connect_timeout_secs.max(5));
    let handshake = timeout(
        hs_timeout,
        perform_handshake(&mut stream, local_priv, HandshakeRole::Responder),
    )
    .await;

    let (transport, remote_static) = match handshake {
        Ok(Ok(p)) => p,
        Ok(Err(e)) => {
            info!(peer = %peer, error = %e, "handshake failed");
            return Ok(());
        }
        Err(_) => {
            info!(peer = %peer, "handshake timeout");
            return Ok(());
        }
    };

    let pubkey_short = short_fingerprint(&remote_static);

    // Re-load the allow-list on every handshake — no restart required.
    let auth = match AuthorizedClients::load(allow_path) {
        Ok(a) => a,
        Err(e) => {
            warn!(peer = %peer, error = %e, "load authorized_clients");
            AuthorizedClients::default()
        }
    };
    let entry = auth.lookup(&remote_static).cloned();

    let mut channel = Channel::new(stream, transport, REASSEMBLY_HEADROOM_BYTES);

    let Some(client_entry) = entry else {
        info!(
            peer = %peer,
            client_pubkey = %pubkey_short,
            "handshake ok but pubkey not authorized"
        );
        let _ = channel
            .send_frame(&Frame::Error {
                request_id: None,
                code: ErrorCode::Unauthorized,
                message: "pubkey not in allow-list".into(),
            })
            .await;
        return Ok(());
    };

    info!(
        peer = %peer,
        client_pubkey = %pubkey_short,
        client_name = client_entry.name.as_deref().unwrap_or("-"),
        "handshake ok; authorized"
    );

    // Acquire / create the per-client semaphore.
    let sem = {
        let mut map = semaphores.lock().await;
        Arc::clone(
            map.entry(remote_static)
                .or_insert_with(|| Arc::new(Semaphore::new(cfg.per_client_concurrency.max(1)))),
        )
    };

    // Wait for Hello.
    let idle = Duration::from_secs(cfg.idle_timeout_secs);

    let hello = match timeout(idle, channel.recv_frame()).await {
        Ok(Ok(f)) => f,
        Ok(Err(e)) => {
            info!(peer = %peer, error = %e, "no Hello before close");
            return Ok(());
        }
        Err(_) => {
            info!(peer = %peer, "idle timeout before Hello");
            return Ok(());
        }
    };

    let (client_id, sidecar_version) = match hello {
        Frame::Hello {
            proto_version,
            client_id,
            sidecar_version,
        } => {
            if proto_version != PROTO_VERSION {
                let _ = channel
                    .send_frame(&Frame::Error {
                        request_id: None,
                        code: ErrorCode::ProtocolViolation,
                        message: format!(
                            "proto_version mismatch: expected {PROTO_VERSION}, got {proto_version}"
                        ),
                    })
                    .await;
                return Ok(());
            }
            (client_id, sidecar_version)
        }
        _ => {
            let _ = channel
                .send_frame(&Frame::Error {
                    request_id: None,
                    code: ErrorCode::ProtocolViolation,
                    message: "expected Hello as first frame".into(),
                })
                .await;
            return Ok(());
        }
    };

    info!(
        peer = %peer,
        client_pubkey = %pubkey_short,
        client_id = %client_id,
        sidecar_version = %sidecar_version,
        "Hello accepted",
    );

    let server_time = unix_now();
    if let Err(e) = channel
        .send_frame(&Frame::HelloAck {
            proto_version: PROTO_VERSION,
            edge_version: env!("CARGO_PKG_VERSION").to_string(),
            server_time_unix: server_time,
        })
        .await
    {
        info!(peer = %peer, error = %e, "send HelloAck failed");
        return Ok(());
    }

    // Main dispatch loop.
    loop {
        let frame = match timeout(idle, channel.recv_frame()).await {
            Ok(Ok(f)) => f,
            Ok(Err(mailcue_relay_proto::ChannelError::UnexpectedEof)) => {
                debug!(peer = %peer, "client closed connection");
                return Ok(());
            }
            Ok(Err(e)) => {
                info!(peer = %peer, error = %e, "channel recv error");
                return Ok(());
            }
            Err(_) => {
                debug!(peer = %peer, "idle timeout — closing");
                return Ok(());
            }
        };

        match frame {
            Frame::Relay {
                request_id,
                envelope_from,
                recipients,
                raw_message,
                opts,
            } => {
                // Acquire concurrency permit.
                let permit = sem.clone().acquire_owned().await;
                let Ok(_permit) = permit else {
                    let _ = channel
                        .send_frame(&Frame::Error {
                            request_id: Some(request_id),
                            code: ErrorCode::Internal,
                            message: "concurrency semaphore closed".into(),
                        })
                        .await;
                    return Ok(());
                };

                let helo = opts
                    .helo_name
                    .clone()
                    .unwrap_or_else(|| helo_name.to_string());
                let started = std::time::Instant::now();
                let total_bytes = raw_message.len();
                let recipient_count = recipients.len();

                let result = relay::handle_relay(
                    cfg,
                    resolver.as_ref(),
                    &helo,
                    &envelope_from,
                    &recipients,
                    &raw_message,
                    &opts,
                )
                .await;

                let elapsed_ms = started.elapsed().as_millis();

                match result {
                    Ok(per_recipient) => {
                        let counts = relay::summarise(&per_recipient);
                        info!(
                            peer = %peer,
                            client_pubkey = %pubkey_short,
                            client_id = %client_id,
                            request_id,
                            envelope_from = %envelope_from,
                            recipient_count,
                            total_bytes,
                            elapsed_ms = u64::try_from(elapsed_ms).unwrap_or(u64::MAX),
                            delivered = counts.delivered,
                            temp = counts.temp,
                            perm = counts.perm,
                            "relay complete",
                        );
                        if let Err(e) = channel
                            .send_frame(&Frame::RelayResult {
                                request_id,
                                per_recipient,
                            })
                            .await
                        {
                            info!(peer = %peer, error = %e, "send RelayResult failed");
                            return Ok(());
                        }
                    }
                    Err(rej) => {
                        let (code, message) = match &rej {
                            relay::RelayReject::BadSender(m)
                            | relay::RelayReject::BadRecipients(m) => {
                                (ErrorCode::ProtocolViolation, m.clone())
                            }
                            relay::RelayReject::MessageTooLarge => {
                                (ErrorCode::MessageTooLarge, "message too large".into())
                            }
                            relay::RelayReject::TooManyRecipients => {
                                (ErrorCode::TooManyRecipients, "too many recipients".into())
                            }
                        };
                        info!(
                            peer = %peer,
                            client_pubkey = %pubkey_short,
                            request_id,
                            recipient_count,
                            total_bytes,
                            ?rej,
                            "relay rejected",
                        );
                        let _ = channel
                            .send_frame(&Frame::Error {
                                request_id: Some(request_id),
                                code,
                                message,
                            })
                            .await;
                        return Ok(());
                    }
                }
            }
            Frame::Ping { ts_unix: _, nonce } => {
                if let Err(e) = channel
                    .send_frame(&Frame::Pong {
                        ts_unix: unix_now(),
                        nonce,
                    })
                    .await
                {
                    info!(peer = %peer, error = %e, "send Pong failed");
                    return Ok(());
                }
            }
            // Anything else is a protocol violation.
            Frame::Hello { .. }
            | Frame::HelloAck { .. }
            | Frame::RelayResult { .. }
            | Frame::Pong { .. }
            | Frame::Error { .. }
            | Frame::RelayChunk(_) => {
                let _ = channel
                    .send_frame(&Frame::Error {
                        request_id: None,
                        code: ErrorCode::ProtocolViolation,
                        message: "unexpected frame from client".into(),
                    })
                    .await;
                return Ok(());
            }
        }
    }
}

// ---------------------------------------------------------------------------
// `keygen` / `pubkey`
// ---------------------------------------------------------------------------

fn keygen_command(args: KeygenArgs) -> ExitCode {
    let state = state_dir_for(args.state_dir);
    let key_path = state.join("server.key");
    let pub_path_buf = state.join("server.pub");

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
        let _ = pub_path_buf;
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

fn pubkey_command(args: KeygenArgs) -> ExitCode {
    let state = state_dir_for(args.state_dir);
    let pub_file = state.join("server.pub");
    let key_file = state.join("server.key");

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
            "error: neither {} nor {} exists; run `mailcue-relay-edge keygen` first",
            pub_file.display(),
            key_file.display()
        );
        ExitCode::from(EXIT_KEYGEN)
    }
}

// ---------------------------------------------------------------------------
// `authorize` / `revoke` / `list`
// ---------------------------------------------------------------------------

fn authorize_command(args: AuthorizeArgs) -> ExitCode {
    let pubkey_b64 =
        match resolve_pubkey_arg(args.pubkey_pos.as_deref(), args.pubkey_flag.as_deref()) {
            Ok(p) => p,
            Err(e) => {
                eprintln!("error: {e}");
                return ExitCode::from(EXIT_GENERIC);
            }
        };
    let pk = match decode_pubkey(&pubkey_b64) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("error: {e}");
            return ExitCode::from(EXIT_GENERIC);
        }
    };
    let path = args
        .config_path
        .unwrap_or_else(defaults::authorized_clients_path);

    match AuthorizedClients::authorize_in_file(&path, &pk, args.name.as_deref()) {
        Ok(true) => {
            println!(
                "authorized: {} ({})",
                short_fingerprint(&pk),
                path.display()
            );
            ExitCode::from(EXIT_OK)
        }
        Ok(false) => {
            println!("already authorized: {}", short_fingerprint(&pk));
            ExitCode::from(EXIT_OK)
        }
        Err(e) => {
            eprintln!("error: authorize: {e}");
            ExitCode::from(EXIT_GENERIC)
        }
    }
}

fn revoke_command(args: RevokeArgs) -> ExitCode {
    let pubkey_b64 =
        match resolve_pubkey_arg(args.pubkey_pos.as_deref(), args.pubkey_flag.as_deref()) {
            Ok(p) => p,
            Err(e) => {
                eprintln!("error: {e}");
                return ExitCode::from(EXIT_GENERIC);
            }
        };
    let pk = match decode_pubkey(&pubkey_b64) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("error: {e}");
            return ExitCode::from(EXIT_GENERIC);
        }
    };
    let path = args
        .config_path
        .unwrap_or_else(defaults::authorized_clients_path);

    match AuthorizedClients::revoke_in_file(&path, &pk) {
        Ok(0) => {
            println!("not authorized: {}", short_fingerprint(&pk));
            ExitCode::from(EXIT_OK)
        }
        Ok(n) => {
            println!(
                "revoked: {} ({n} entr{})",
                short_fingerprint(&pk),
                if n == 1 { "y" } else { "ies" }
            );
            ExitCode::from(EXIT_OK)
        }
        Err(e) => {
            eprintln!("error: revoke: {e}");
            ExitCode::from(EXIT_GENERIC)
        }
    }
}

fn list_command(args: ListArgs) -> ExitCode {
    let path = args
        .config_path
        .unwrap_or_else(defaults::authorized_clients_path);

    let raw = match std::fs::read_to_string(&path) {
        Ok(s) => s,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            println!("(no authorized clients: {} does not exist)", path.display());
            return ExitCode::from(EXIT_OK);
        }
        Err(e) => {
            eprintln!("error: read {}: {e}", path.display());
            return ExitCode::from(EXIT_GENERIC);
        }
    };

    let mut count = 0_usize;
    for line in raw.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let mut parts = trimmed.splitn(2, char::is_whitespace);
        let key_b64 = parts.next().unwrap_or("");
        let name = parts.next().map(|s| s.trim()).unwrap_or("-");
        let Ok(decoded) = B64.decode(key_b64) else {
            continue;
        };
        if decoded.len() != 32 {
            continue;
        }
        let mut pk = [0_u8; 32];
        pk.copy_from_slice(&decoded);
        println!("{}\t{}", short_fingerprint(&pk), name);
        count += 1;
    }
    if count == 0 {
        println!("(no authorized clients)");
    }
    ExitCode::from(EXIT_OK)
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

fn state_dir_for(cli: Option<PathBuf>) -> PathBuf {
    cli.or_else(|| std::env::var_os("MAILCUE_EDGE_STATE_DIR").map(PathBuf::from))
        .unwrap_or_else(defaults::state_dir)
}

fn resolve_pubkey_arg(pos: Option<&str>, flag: Option<&str>) -> Result<String> {
    match (pos, flag) {
        (Some(_), Some(_)) => Err(anyhow!(
            "specify the pubkey either positionally or via --pubkey, not both"
        )),
        (Some(s), None) | (None, Some(s)) => Ok(s.trim().to_string()),
        (None, None) => Err(anyhow!(
            "missing pubkey: pass it positionally or via --pubkey"
        )),
    }
}

fn decode_pubkey(s: &str) -> Result<[u8; 32]> {
    let raw = B64.decode(s.trim()).context("base64 decode pubkey")?;
    if raw.len() != 32 {
        return Err(anyhow!("pubkey must decode to 32 bytes, got {}", raw.len()));
    }
    let mut pk = [0_u8; 32];
    pk.copy_from_slice(&raw);
    Ok(pk)
}

fn short_fingerprint(pk: &[u8; 32]) -> String {
    hex::encode(&pk[..8])
}

fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
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
async fn install_signal_handler() {
    use tokio::signal::unix::{SignalKind, signal};
    let mut term = match signal(SignalKind::terminate()) {
        Ok(s) => s,
        Err(e) => {
            warn!(error = %e, "install SIGTERM handler");
            return std::future::pending().await;
        }
    };
    let mut intr = match signal(SignalKind::interrupt()) {
        Ok(s) => s,
        Err(e) => {
            warn!(error = %e, "install SIGINT handler");
            return std::future::pending().await;
        }
    };
    tokio::select! {
        _ = term.recv() => {}
        _ = intr.recv() => {}
    }
}

#[cfg(not(unix))]
async fn install_signal_handler() {
    let _ = tokio::signal::ctrl_c().await;
}
