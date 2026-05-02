//! Allow-list parser for the edge's `authorized_clients` file.
//!
//! Format: one entry per line. A non-comment line contains a base64-encoded
//! 32-byte X25519 public key, optionally followed by whitespace and a
//! free-form name. Lines whose first non-whitespace character is `#` are
//! comments. Empty lines are ignored.
//!
//! ```text
//! # ovh-de production sidecar
//! AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8= prod-de
//! ```

use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::Path;

use base64::Engine;
use base64::engine::general_purpose::STANDARD as B64;
use thiserror::Error;

/// Errors returned by [`AuthorizedClients`] operations.
#[derive(Debug, Error)]
pub enum AuthorizedError {
    /// Filesystem I/O error.
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    /// Malformed line.
    #[error("authorized_clients: line {line}: {reason}")]
    BadLine {
        /// 1-based line number in the source file.
        line: usize,
        /// Human-readable reason.
        reason: String,
    },
}

/// One row in the allow-list.
#[derive(Debug, Clone)]
pub struct ClientEntry {
    /// Optional human label, used only in logs.
    pub name: Option<String>,
}

/// In-memory representation of the parsed allow-list.
#[derive(Debug, Default, Clone)]
pub struct AuthorizedClients {
    by_pubkey: HashMap<[u8; 32], ClientEntry>,
}

impl AuthorizedClients {
    /// Parse the file at `path`. A missing file is treated as an empty
    /// allow-list (which causes every connection attempt to be rejected
    /// — fail-closed).
    ///
    /// # Errors
    ///
    /// Returns [`AuthorizedError`] for I/O failures or malformed lines.
    pub fn load(path: &Path) -> Result<Self, AuthorizedError> {
        if !path.exists() {
            return Ok(Self::default());
        }
        let raw = fs::read_to_string(path)?;
        let mut by_pubkey = HashMap::new();
        for (idx, line) in raw.lines().enumerate() {
            let trimmed = line.trim();
            if trimmed.is_empty() || trimmed.starts_with('#') {
                continue;
            }
            let mut parts = trimmed.splitn(2, char::is_whitespace);
            let key_b64 = parts.next().unwrap_or("");
            let name = parts
                .next()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty());
            let decoded = B64.decode(key_b64).map_err(|e| AuthorizedError::BadLine {
                line: idx + 1,
                reason: format!("base64 decode: {e}"),
            })?;
            if decoded.len() != 32 {
                return Err(AuthorizedError::BadLine {
                    line: idx + 1,
                    reason: format!("expected 32 bytes, got {}", decoded.len()),
                });
            }
            let mut pk = [0u8; 32];
            pk.copy_from_slice(&decoded);
            by_pubkey.insert(pk, ClientEntry { name });
        }
        Ok(Self { by_pubkey })
    }

    /// Look up an entry by its 32-byte X25519 public key.
    #[must_use]
    pub fn lookup(&self, pubkey: &[u8; 32]) -> Option<&ClientEntry> {
        self.by_pubkey.get(pubkey)
    }

    /// Number of authorized clients.
    #[must_use]
    pub fn len(&self) -> usize {
        self.by_pubkey.len()
    }

    /// Whether the allow-list is empty (which causes all auth to fail).
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.by_pubkey.is_empty()
    }

    /// Append a new entry to `path` if and only if it is not already
    /// present. Creates the file (mode `0640` on Unix) and parent
    /// directory on first call. Returns `true` if a new line was added.
    ///
    /// # Errors
    ///
    /// Returns [`AuthorizedError`] for parse / write failures.
    pub fn authorize_in_file(
        path: &Path,
        pubkey: &[u8; 32],
        name: Option<&str>,
    ) -> Result<bool, AuthorizedError> {
        let mut existing = Self::load(path)?;
        if existing.lookup(pubkey).is_some() {
            return Ok(false);
        }
        if let Some(parent) = path.parent()
            && !parent.as_os_str().is_empty()
        {
            fs::create_dir_all(parent)?;
        }

        let mut line = B64.encode(pubkey);
        if let Some(n) = name {
            let trimmed = n.trim();
            if !trimmed.is_empty() {
                line.push(' ');
                line.push_str(trimmed);
            }
        }
        line.push('\n');

        append_with_mode(path, line.as_bytes(), 0o640)?;

        existing.by_pubkey.insert(
            *pubkey,
            ClientEntry {
                name: name.map(|s| s.to_string()),
            },
        );
        let _ = existing;
        Ok(true)
    }

    /// Remove every line authorizing `pubkey` from `path`. Returns the
    /// number of removed entries.
    ///
    /// # Errors
    ///
    /// Returns [`AuthorizedError`] for parse / write failures.
    pub fn revoke_in_file(path: &Path, pubkey: &[u8; 32]) -> Result<usize, AuthorizedError> {
        if !path.exists() {
            return Ok(0);
        }
        let raw = fs::read_to_string(path)?;
        let mut removed = 0usize;
        let mut out = String::with_capacity(raw.len());
        for line in raw.lines() {
            if let Some(line_pk) = parse_pubkey(line)
                && line_pk == *pubkey
            {
                removed += 1;
                continue;
            }
            out.push_str(line);
            out.push('\n');
        }
        write_atomic(path, out.as_bytes(), 0o640)?;
        Ok(removed)
    }
}

fn parse_pubkey(line: &str) -> Option<[u8; 32]> {
    let trimmed = line.trim();
    if trimmed.is_empty() || trimmed.starts_with('#') {
        return None;
    }
    let key = trimmed.split_whitespace().next()?;
    let decoded = B64.decode(key).ok()?;
    if decoded.len() != 32 {
        return None;
    }
    let mut pk = [0u8; 32];
    pk.copy_from_slice(&decoded);
    Some(pk)
}

#[cfg(unix)]
fn append_with_mode(path: &Path, contents: &[u8], mode: u32) -> std::io::Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    let exists = path.exists();
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .mode(mode)
        .open(path)?;
    if !exists {
        // Re-apply mode in case umask stripped it on creation.
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(mode))?;
    }
    f.write_all(contents)?;
    f.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn append_with_mode(path: &Path, contents: &[u8], _mode: u32) -> std::io::Result<()> {
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?;
    f.write_all(contents)?;
    f.sync_all()?;
    Ok(())
}

#[cfg(unix)]
fn write_atomic(path: &Path, contents: &[u8], mode: u32) -> std::io::Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;
    let tmp = path.with_extension("authorized_clients.tmp");
    {
        let mut f = fs::OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(true)
            .mode(mode)
            .open(&tmp)?;
        f.write_all(contents)?;
        f.sync_all()?;
    }
    fs::set_permissions(&tmp, fs::Permissions::from_mode(mode))?;
    fs::rename(&tmp, path)?;
    Ok(())
}

#[cfg(not(unix))]
fn write_atomic(path: &Path, contents: &[u8], _mode: u32) -> std::io::Result<()> {
    let tmp = path.with_extension("authorized_clients.tmp");
    {
        let mut f = fs::File::create(&tmp)?;
        f.write_all(contents)?;
        f.sync_all()?;
    }
    fs::rename(&tmp, path)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn parse_basic() {
        let dir = tempdir().unwrap();
        let p = dir.path().join("authorized");
        let key = [7u8; 32];
        let line = format!("{} alice\n# comment\n\n", B64.encode(key));
        fs::write(&p, line).unwrap();
        let auth = AuthorizedClients::load(&p).unwrap();
        assert_eq!(auth.len(), 1);
        assert_eq!(auth.lookup(&key).unwrap().name.as_deref(), Some("alice"));
    }

    #[test]
    fn authorize_and_revoke() {
        let dir = tempdir().unwrap();
        let p = dir.path().join("authorized");
        let key = [9u8; 32];
        assert!(AuthorizedClients::authorize_in_file(&p, &key, Some("bob")).unwrap());
        assert!(!AuthorizedClients::authorize_in_file(&p, &key, Some("bob")).unwrap());
        assert_eq!(AuthorizedClients::load(&p).unwrap().len(), 1);
        assert_eq!(AuthorizedClients::revoke_in_file(&p, &key).unwrap(), 1);
        assert_eq!(AuthorizedClients::load(&p).unwrap().len(), 0);
    }
}
