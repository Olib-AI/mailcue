import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  TlsCertificateStatus,
  UploadTlsCertificateRequest,
} from "@/types/api";

const tlsCertificateKeys = {
  all: ["tlsCertificate"] as const,
};

export function useTlsCertificateStatus() {
  return useQuery({
    queryKey: tlsCertificateKeys.all,
    queryFn: () => api.get<TlsCertificateStatus>("/system/tls"),
    staleTime: 60_000,
  });
}

export function useUploadTlsCertificate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: UploadTlsCertificateRequest) =>
      api.put<TlsCertificateStatus>("/system/tls", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: tlsCertificateKeys.all });
      void queryClient.invalidateQueries({ queryKey: ["certificate"] });
    },
  });
}
