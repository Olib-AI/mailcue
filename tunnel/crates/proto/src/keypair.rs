//! Long-term X25519 static keys, persisted on disk.
//!
//! Format: a single line, base64-encoded 32-byte private key. The matching
//! public key is written next to it as `<stem>.pub`. File modes are `0600`
//! for the private key and `0644` for the public key on Unix.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use base64::Engine;
use base64::engine::general_purpose::STANDARD as B64;
use snow::Builder;
use snow::params::{DHChoice, NoiseParams};
use snow::resolvers::{CryptoResolver, DefaultResolver};
use thiserror::Error;
use zeroize::Zeroizing;

use crate::NOISE_PATTERN;

/// Errors returned by [`KeyPair`] operations.
#[derive(Debug, Error)]
pub enum KeyPairError {
    /// Filesystem I/O failure (read/write/permissions).
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    /// Base64 decoding failure.
    #[error("base64 decode: {0}")]
    Base64(#[from] base64::DecodeError),
    /// `snow` builder / handshake error.
    #[error("snow: {0}")]
    Snow(#[from] snow::Error),
    /// On-disk private key was the wrong length.
    #[error("invalid key length: expected 32, got {0}")]
    InvalidKeyLength(usize),
    /// Failed to parse the Noise pattern string.
    #[error("invalid noise pattern: {0}")]
    Pattern(String),
    /// `snow`'s default resolver did not provide an X25519 implementation.
    #[error("noise default resolver missing X25519 DH")]
    MissingDh,
}

/// A persisted X25519 static keypair used for the Noise IK handshake.
///
/// The private key is held inside a [`Zeroizing`] buffer so it is wiped
/// when this value is dropped. The public key is plain bytes — it is not
/// secret.
#[derive(Debug)]
pub struct KeyPair {
    private: Zeroizing<[u8; 32]>,
    public: [u8; 32],
}

impl KeyPair {
    /// Generate a fresh keypair using `snow`'s default RNG.
    pub fn generate() -> Result<Self, KeyPairError> {
        let params = noise_params()?;
        let builder = Builder::new(params);
        let kp = builder.generate_keypair()?;

        let mut private = Zeroizing::new([0u8; 32]);
        private.copy_from_slice(&kp.private);
        let mut public = [0u8; 32];
        public.copy_from_slice(&kp.public);

        Ok(Self { private, public })
    }

    /// Load a keypair from `path`, or generate and persist one if `path`
    /// does not exist. The matching public key is written to
    /// `pub_path(path)`.
    pub fn load_or_generate(path: &Path) -> Result<Self, KeyPairError> {
        if path.exists() {
            return Self::load(path);
        }
        let kp = Self::generate()?;
        kp.persist(path)?;
        Ok(kp)
    }

    /// Load a keypair from `path`. The file must contain a single base64
    /// token decoding to 32 raw bytes (whitespace is trimmed).
    pub fn load(path: &Path) -> Result<Self, KeyPairError> {
        let raw = fs::read_to_string(path)?;
        let trimmed = raw.trim();
        let decoded = B64.decode(trimmed)?;
        if decoded.len() != 32 {
            return Err(KeyPairError::InvalidKeyLength(decoded.len()));
        }
        let mut private = Zeroizing::new([0u8; 32]);
        private.copy_from_slice(&decoded);
        let public = derive_public(&private)?;
        Ok(Self { private, public })
    }

    /// Persist the private key to `path` (mode `0600` on Unix) and the
    /// public key alongside it (mode `0644`).
    pub fn persist(&self, path: &Path) -> Result<(), KeyPairError> {
        if let Some(parent) = path.parent()
            && !parent.as_os_str().is_empty()
        {
            fs::create_dir_all(parent)?;
        }

        let priv_b64 = B64.encode(self.private.as_ref());
        write_secret(path, priv_b64.as_bytes())?;

        let p = pub_path(path);
        let pub_b64 = B64.encode(self.public);
        let mut f = fs::File::create(&p)?;
        f.write_all(pub_b64.as_bytes())?;
        f.write_all(b"\n")?;
        f.sync_all()?;
        Ok(())
    }

    /// 32-byte private key bytes (zeroized on drop).
    #[must_use]
    pub fn private_bytes(&self) -> &[u8; 32] {
        &self.private
    }

    /// 32-byte public key bytes.
    #[must_use]
    pub fn public_bytes(&self) -> &[u8; 32] {
        &self.public
    }

    /// Base64-encoded public key (single line, no padding stripping).
    #[must_use]
    pub fn public_base64(&self) -> String {
        B64.encode(self.public)
    }
}

/// Path where a keypair's public component is stored.
#[must_use]
pub fn pub_path(priv_path: &Path) -> PathBuf {
    if priv_path.extension().is_some_and(|e| e == "key") {
        let mut alt = priv_path.to_path_buf();
        alt.set_extension("pub");
        return alt;
    }
    let mut name = priv_path.file_name().map_or_else(
        || std::ffi::OsString::from("server"),
        std::ffi::OsString::from,
    );
    name.push(".pub");
    let mut p = priv_path.to_path_buf();
    p.set_file_name(name);
    p
}

fn noise_params() -> Result<NoiseParams, KeyPairError> {
    NOISE_PATTERN
        .parse::<NoiseParams>()
        .map_err(|e| KeyPairError::Pattern(e.to_string()))
}

fn derive_public(private: &[u8; 32]) -> Result<[u8; 32], KeyPairError> {
    // Use snow's default resolver to do an X25519 scalar-base multiplication.
    let resolver = DefaultResolver;
    let mut dh = resolver
        .resolve_dh(&DHChoice::Curve25519)
        .ok_or(KeyPairError::MissingDh)?;
    dh.set(private);
    let mut public = [0u8; 32];
    public.copy_from_slice(dh.pubkey());
    Ok(public)
}

#[cfg(unix)]
fn write_secret(path: &Path, contents: &[u8]) -> std::io::Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    let mut f = fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(path)?;
    f.write_all(contents)?;
    f.write_all(b"\n")?;
    f.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn write_secret(path: &Path, contents: &[u8]) -> std::io::Result<()> {
    let mut f = fs::File::create(path)?;
    f.write_all(contents)?;
    f.write_all(b"\n")?;
    f.sync_all()?;
    Ok(())
}
