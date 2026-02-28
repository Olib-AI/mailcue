import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  GpgKey,
  GpgKeyListResponse,
  GenerateGpgKeyRequest,
  ImportGpgKeyRequest,
  GpgKeyExportResponse,
} from "@/types/api";

// --- Query Keys ---

export const gpgKeys = {
  all: ["gpg-keys"] as const,
  list: () => [...gpgKeys.all, "list"] as const,
  detail: (address: string) => [...gpgKeys.all, "detail", address] as const,
};

// --- Hooks ---

export function useGpgKeys() {
  return useQuery({
    queryKey: gpgKeys.list(),
    queryFn: () => api.get<GpgKeyListResponse>("/gpg/keys"),
    staleTime: 30_000,
  });
}

export function useGpgKey(address: string | undefined) {
  return useQuery({
    queryKey: gpgKeys.detail(address ?? ""),
    queryFn: () =>
      api.get<GpgKey>(`/gpg/keys/${encodeURIComponent(address!)}`),
    enabled: !!address,
    retry: false,
  });
}

export function useGenerateGpgKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: GenerateGpgKeyRequest) =>
      api.post<GpgKey>("/gpg/keys/generate", request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: gpgKeys.all });
    },
  });
}

export function useImportGpgKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: ImportGpgKeyRequest) =>
      api.post<GpgKey>("/gpg/keys/import", request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: gpgKeys.all });
    },
  });
}

export function useDeleteGpgKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (address: string) =>
      api.delete<void>(`/gpg/keys/${encodeURIComponent(address)}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: gpgKeys.all });
    },
  });
}

export function useExportGpgKey() {
  return useMutation({
    mutationFn: (address: string) =>
      api.get<GpgKeyExportResponse>(
        `/gpg/keys/${encodeURIComponent(address)}/export`
      ),
  });
}
