//! Tunnel selector.
//!
//! Picks an `enabled && healthy` tunnel from the current registry view
//! using one of three strategies: round-robin, uniform random, or
//! weighted random. State (the round-robin cursor) survives reloads as
//! long as the *set of tunnel ids* is unchanged; if the set changes the
//! cursor resets to 0.

use std::collections::BTreeSet;

use parking_lot::Mutex;
// rand 0.10 split the legacy `Rng` trait: the core sampling methods
// (`random_range`, `random_bool`, ...) moved to `RngExt`. We use only
// the extension methods, so just `RngExt` needs to be in scope.
use rand::RngExt;

use crate::tunnels::{SelectionStrategy, Tunnel, TunnelsView};

/// Per-strategy selection state.
#[derive(Debug, Default)]
pub struct Selector {
    inner: Mutex<SelectorState>,
}

#[derive(Debug, Default)]
struct SelectorState {
    cursor: usize,
    last_ids: BTreeSet<String>,
}

impl Selector {
    /// Create a fresh selector with cursor 0.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Pick a tunnel from `view` whose id appears in `healthy_ids`.
    ///
    /// Returns `None` when no enabled+healthy tunnel exists.
    pub fn pick<'a>(
        &self,
        view: &'a TunnelsView,
        healthy_ids: &BTreeSet<String>,
    ) -> Option<&'a Tunnel> {
        let candidates: Vec<&Tunnel> = view
            .tunnels
            .iter()
            .filter(|t| t.enabled && healthy_ids.contains(&t.id))
            .collect();

        if candidates.is_empty() {
            return None;
        }

        match view.selection {
            SelectionStrategy::RoundRobin => self.round_robin(&candidates, view),
            SelectionStrategy::Random => uniform(&candidates),
            SelectionStrategy::WeightedRandom => weighted(&candidates),
        }
    }

    fn round_robin<'a>(&self, candidates: &[&'a Tunnel], view: &TunnelsView) -> Option<&'a Tunnel> {
        let ids: BTreeSet<String> = view.tunnels.iter().map(|t| t.id.clone()).collect();

        let mut state = self.inner.lock();
        if state.last_ids != ids {
            state.cursor = 0;
            state.last_ids = ids;
        }

        let idx = state.cursor % candidates.len();
        state.cursor = state.cursor.wrapping_add(1);
        Some(candidates[idx])
    }
}

fn uniform<'a>(candidates: &[&'a Tunnel]) -> Option<&'a Tunnel> {
    // rand 0.9: `thread_rng()`/`gen_range` were renamed to `rng()`/`random_range`.
    let mut rng = rand::rng();
    let idx = rng.random_range(0..candidates.len());
    Some(candidates[idx])
}

fn weighted<'a>(candidates: &[&'a Tunnel]) -> Option<&'a Tunnel> {
    let total: u64 = candidates.iter().map(|t| u64::from(t.weight.max(1))).sum();
    if total == 0 {
        return uniform(candidates);
    }
    let mut rng = rand::rng();
    let mut roll = rng.random_range(0..total);
    for t in candidates {
        let w = u64::from(t.weight.max(1));
        if roll < w {
            return Some(*t);
        }
        roll -= w;
    }
    candidates.last().copied()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tunnels::{Tunnel, TunnelsView};

    fn t(id: &str, weight: u32, enabled: bool) -> Tunnel {
        Tunnel {
            id: id.into(),
            name: id.into(),
            host: "127.0.0.1".into(),
            port: 7843,
            edge_pubkey: [0; 32],
            weight,
            enabled,
        }
    }

    fn view(strategy: SelectionStrategy, tunnels: Vec<Tunnel>) -> TunnelsView {
        TunnelsView {
            selection: strategy,
            tunnels,
        }
    }

    fn healthy(ids: &[&str]) -> BTreeSet<String> {
        ids.iter().map(|s| (*s).to_string()).collect()
    }

    #[test]
    fn rr_skips_disabled_and_unhealthy() {
        let v = view(
            SelectionStrategy::RoundRobin,
            vec![t("a", 1, false), t("b", 1, true), t("c", 1, true)],
        );
        let h = healthy(&["b", "c"]);
        let s = Selector::new();
        let mut order = Vec::new();
        for _ in 0..6 {
            order.push(s.pick(&v, &h).unwrap().id.clone());
        }
        assert_eq!(order, vec!["b", "c", "b", "c", "b", "c"]);
    }

    #[test]
    fn rr_resets_when_ids_change() {
        let v1 = view(
            SelectionStrategy::RoundRobin,
            vec![t("a", 1, true), t("b", 1, true)],
        );
        let h = healthy(&["a", "b"]);
        let s = Selector::new();
        assert_eq!(s.pick(&v1, &h).unwrap().id, "a");
        assert_eq!(s.pick(&v1, &h).unwrap().id, "b");

        // Set changes — cursor resets.
        let v2 = view(
            SelectionStrategy::RoundRobin,
            vec![t("c", 1, true), t("d", 1, true)],
        );
        let h2 = healthy(&["c", "d"]);
        assert_eq!(s.pick(&v2, &h2).unwrap().id, "c");
        assert_eq!(s.pick(&v2, &h2).unwrap().id, "d");
    }

    #[test]
    fn returns_none_when_no_candidates() {
        let v = view(SelectionStrategy::RoundRobin, vec![t("a", 1, true)]);
        let h = healthy(&[]); // none healthy
        let s = Selector::new();
        assert!(s.pick(&v, &h).is_none());
    }

    #[test]
    fn weighted_selects_with_positive_weights() {
        let v = view(
            SelectionStrategy::WeightedRandom,
            vec![t("a", 1, true), t("b", 9, true)],
        );
        let h = healthy(&["a", "b"]);
        let s = Selector::new();
        let mut hits_b = 0;
        for _ in 0..1000 {
            if s.pick(&v, &h).unwrap().id == "b" {
                hits_b += 1;
            }
        }
        // b has 90% of the weight; a probabilistic sanity bound.
        assert!(hits_b > 700, "expected lots of `b`, got {hits_b}");
    }
}
