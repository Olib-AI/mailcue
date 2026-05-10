import { useProductionStatus } from "@/hooks/use-production-status";
import type { FeatureFlags } from "@/types/api";

const ALL_ENABLED: FeatureFlags = {
  inject: true,
  messaging_sandbox: true,
  httpbin: true,
};

interface UseFeaturesResult {
  features: FeatureFlags;
  /** True once the server's flags have arrived; false during the
   *  optimistic-default window after first paint. */
  ready: boolean;
}

/**
 * Read the server's feature flags.
 *
 * Until the ``/system/production-status`` query resolves we *optimistically*
 * assume every feature is on — that matches the historical behaviour and
 * avoids a flash of disabled UI on first paint in dev/test mode.  In
 * production the response (within ~1 RTT) flips off the test-only menu
 * items before the user can interact with them.
 *
 * The endpoint is admin-only, so non-admins always see the optimistic
 * defaults — fine, because the surfaces gated by these flags are admin-
 * only anyway.
 */
export function useFeatures(): UseFeaturesResult {
  const { data } = useProductionStatus();
  return {
    features: data?.features ?? ALL_ENABLED,
    ready: data !== undefined,
  };
}
