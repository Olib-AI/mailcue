//! Thin async wrapper around hickory-resolver for MX lookups.

use std::net::SocketAddr;
use std::sync::Arc;

use anyhow::{Context, Result};
use hickory_resolver::TokioAsyncResolver;
use hickory_resolver::config::{NameServerConfig, Protocol, ResolverConfig, ResolverOpts};

/// Async MX resolver, share-friendly via [`Arc`].
#[derive(Clone)]
pub struct MxResolver {
    inner: Arc<TokioAsyncResolver>,
}

/// One MX answer.
#[derive(Debug, Clone)]
pub struct MxRecord {
    /// Hostname (with trailing dot stripped).
    pub host: String,
    /// MX preference (lower = higher priority).
    pub preference: u16,
}

impl MxResolver {
    /// Build a resolver. If `nameservers` is empty, the system
    /// configuration (`/etc/resolv.conf` on Unix) is used.
    ///
    /// # Errors
    ///
    /// Returns an error if the system resolver cannot be probed.
    pub fn new(nameservers: &[SocketAddr]) -> Result<Self> {
        let resolver = if nameservers.is_empty() {
            TokioAsyncResolver::tokio_from_system_conf()
                .context("read system resolver configuration")?
        } else {
            let mut cfg = ResolverConfig::new();
            for &addr in nameservers {
                cfg.add_name_server(NameServerConfig {
                    socket_addr: addr,
                    protocol: Protocol::Udp,
                    tls_dns_name: None,
                    trust_negative_responses: false,
                    bind_addr: None,
                });
            }
            let mut opts = ResolverOpts::default();
            opts.timeout = std::time::Duration::from_secs(5);
            TokioAsyncResolver::tokio(cfg, opts)
        };
        Ok(Self {
            inner: Arc::new(resolver),
        })
    }

    /// Resolve MX records for `domain`. Returns sorted records (lowest
    /// preference first). If MX lookup yields no records, falls back to
    /// the implicit-MX rule: the domain itself with preference 0.
    ///
    /// # Errors
    ///
    /// Propagates resolver errors. NXDOMAIN / no-records is *not* an
    /// error — it is reported via an empty fallback.
    pub async fn resolve_mx(&self, domain: &str) -> Result<Vec<MxRecord>> {
        let lookup = match self.inner.mx_lookup(domain).await {
            Ok(l) => l,
            Err(e) => {
                let kind = e.kind();
                if matches!(
                    kind,
                    hickory_resolver::error::ResolveErrorKind::NoRecordsFound { .. }
                ) {
                    // Implicit-MX fallback — RFC 5321 §5.1.
                    return Ok(vec![MxRecord {
                        host: domain.trim_end_matches('.').to_string(),
                        preference: 0,
                    }]);
                }
                return Err(e.into());
            }
        };

        let mut out: Vec<MxRecord> = lookup
            .iter()
            .map(|m| MxRecord {
                host: m.exchange().to_utf8().trim_end_matches('.').to_string(),
                preference: m.preference(),
            })
            .filter(|r| !r.host.is_empty() && r.host != ".")
            .collect();
        out.sort_by_key(|r| r.preference);

        if out.is_empty() {
            return Ok(vec![MxRecord {
                host: domain.trim_end_matches('.').to_string(),
                preference: 0,
            }]);
        }
        Ok(out)
    }
}
