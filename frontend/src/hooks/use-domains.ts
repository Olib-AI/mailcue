import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  CreateDomainRequest,
  DnsCheckResponse,
  Domain,
  DomainDetail,
  DomainDnsState,
  DomainListResponse,
} from "@/types/api";

const domainKeys = {
  all: ["domains"] as const,
  list: () => [...domainKeys.all, "list"] as const,
  detail: (name: string) => [...domainKeys.all, "detail", name] as const,
  dnsState: (name: string) => [...domainKeys.all, "dns-state", name] as const,
};

// Module-level guard so we only warn once per session if the dns-state
// endpoint is missing (backend may land later than the frontend).
let dnsStateMissingWarned = false;

export function useDomains() {
  return useQuery({
    queryKey: domainKeys.list(),
    queryFn: () => api.get<DomainListResponse>("/domains"),
    staleTime: 60_000,
  });
}

export function useDomainDetail(name: string | null) {
  return useQuery({
    queryKey: domainKeys.detail(name ?? ""),
    queryFn: () => api.get<DomainDetail>(`/domains/${name}`),
    enabled: !!name,
    staleTime: 60_000,
  });
}

export function useAddDomain() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateDomainRequest) =>
      api.post<Domain>("/domains", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: domainKeys.all });
    },
  });
}

export function useRemoveDomain() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.delete(`/domains/${name}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: domainKeys.all });
    },
  });
}

export function useVerifyDns() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.post<DnsCheckResponse>(`/domains/${name}/verify-dns`),
    onSuccess: (_data, name) => {
      // Refresh the canonical *_verified booleans on the list…
      void queryClient.invalidateQueries({ queryKey: domainKeys.list() });
      // …the per-domain detail (expected/current values)…
      void queryClient.invalidateQueries({
        queryKey: domainKeys.detail(name),
      });
      // …and the new dns-state poll so drift banners settle immediately.
      void queryClient.invalidateQueries({
        queryKey: domainKeys.dnsState(name),
      });
    },
  });
}

export function useDnsState(name: string | null) {
  return useQuery<DomainDnsState>({
    queryKey: domainKeys.dnsState(name ?? ""),
    queryFn: async () => {
      try {
        return await api.get<DomainDnsState>(`/domains/${name}/dns-state`);
      } catch (err) {
        // Backend endpoint may not be merged yet. Surface a single dev-time
        // warning and re-throw so the consumer can fall back to detail data.
        if (
          !dnsStateMissingWarned &&
          err instanceof Error &&
          /404|not\s*found/i.test(err.message)
        ) {
          dnsStateMissingWarned = true;
          console.warn(
            "[mailcue] /domains/{name}/dns-state returned 404; drift banner disabled until backend lands.",
          );
        }
        throw err;
      }
    },
    enabled: !!name,
    staleTime: 0,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    // Don't spam the network with retries when the endpoint is missing.
    retry: (failureCount, err) => {
      if (err instanceof Error && /404|not\s*found/i.test(err.message)) {
        return false;
      }
      return failureCount < 2;
    },
  });
}
