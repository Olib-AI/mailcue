import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { CertificateInfo } from "@/types/api";

const certificateKeys = {
  all: ["certificate"] as const,
  info: () => [...certificateKeys.all, "info"] as const,
};

export function useCertificateInfo() {
  return useQuery({
    queryKey: certificateKeys.info(),
    queryFn: () => api.get<CertificateInfo>("/system/certificate"),
    staleTime: 300_000,
  });
}
