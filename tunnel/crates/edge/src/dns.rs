//! Thin async wrapper around hickory-resolver for MX lookups.

use std::net::SocketAddr;
use std::sync::Arc;

use anyhow::{Context, Result};
use hickory_resolver::TokioResolver;
use hickory_resolver::config::{NameServerConfig, ResolverConfig};
use hickory_resolver::net::runtime::TokioRuntimeProvider;
use hickory_resolver::net::{DnsError, NetError};

/// Async MX resolver, share-friendly via [`Arc`].
#[derive(Clone)]
pub struct MxResolver {
    inner: Arc<TokioResolver>,
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
            // hickory 0.26 replaced `TokioAsyncResolver::tokio_from_system_conf()`
            // with the builder pattern; `builder_tokio` reads the system
            // configuration (`/etc/resolv.conf` on Unix, registry on Windows).
            TokioResolver::builder_tokio()
                .context("read system resolver configuration")?
                .build()
                .context("build system tokio resolver")?
        } else {
            let name_servers: Vec<NameServerConfig> = nameservers
                .iter()
                .map(|a| NameServerConfig::udp(a.ip()))
                .collect();
            let cfg = ResolverConfig::from_parts(None, vec![], name_servers);
            let mut builder =
                TokioResolver::builder_with_config(cfg, TokioRuntimeProvider::default());
            builder.options_mut().timeout = std::time::Duration::from_secs(5);
            builder.build().context("build custom tokio resolver")?
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
                // hickory 0.26 surfaces "no records" via the structured
                // `NetError::Dns(DnsError::NoRecordsFound(_))` variant.
                if matches!(&e, NetError::Dns(DnsError::NoRecordsFound(_))) {
                    // Implicit-MX fallback — RFC 5321 §5.1.
                    return Ok(vec![MxRecord {
                        host: domain.trim_end_matches('.').to_string(),
                        preference: 0,
                    }]);
                }
                return Err(e.into());
            }
        };

        // hickory 0.26 returns the generic `Lookup` from `mx_lookup`; iterate
        // over the answer records and extract `RData::MX` payloads.
        let mut out: Vec<MxRecord> = lookup
            .answers()
            .iter()
            .filter_map(|r| match &r.data {
                hickory_resolver::proto::rr::RData::MX(mx) => Some(MxRecord {
                    host: mx.exchange.to_utf8().trim_end_matches('.').to_string(),
                    preference: mx.preference,
                }),
                _ => None,
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
