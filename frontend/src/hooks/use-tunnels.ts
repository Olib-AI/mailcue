import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EffectiveTunnelStatusResponse } from "@/types/api";

export function useTunnelStatus() {
  return useQuery({
    queryKey: ["tunnels", "status"],
    queryFn: () => api.get<EffectiveTunnelStatusResponse>("/tunnels/status"),
    staleTime: 0,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
}
