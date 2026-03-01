import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  CreateDomainRequest,
  DnsCheckResponse,
  Domain,
  DomainDetail,
  DomainListResponse,
} from "@/types/api";

const domainKeys = {
  all: ["domains"] as const,
  list: () => [...domainKeys.all, "list"] as const,
  detail: (name: string) => [...domainKeys.all, "detail", name] as const,
};

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
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: domainKeys.all });
    },
  });
}
