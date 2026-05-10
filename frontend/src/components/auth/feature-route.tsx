import { Navigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useFeatures } from "@/hooks/use-features";
import type { FeatureFlags } from "@/types/api";

interface FeatureRouteProps {
  flag: keyof FeatureFlags;
  children: ReactNode;
  /** Where to send the user when the feature is off. */
  fallback?: string;
}

/**
 * Route guard for feature-flagged pages.
 *
 * Renders ``children`` when the flag is on, redirects to ``fallback``
 * (default ``/mail``) when off.  While the flag is still loading we
 * render the page optimistically — the same default ``useFeatures``
 * uses — so dev/test mode never flashes a redirect to ``/mail`` and
 * back.  Production gets the redirect within ~1 RTT, before the user
 * can interact with the disabled feature.
 */
function FeatureRoute({ flag, children, fallback = "/mail" }: FeatureRouteProps) {
  const { features, ready } = useFeatures();
  if (ready && !features[flag]) {
    return <Navigate to={fallback} replace />;
  }
  return <>{children}</>;
}

export { FeatureRoute };
