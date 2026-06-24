import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  APIKey,
  APIKeyCreated,
  CreateAPIKeyRequest,
  ScopeCatalogResponse,
  UpdateAPIKeyRequest,
} from "@/types/api";

const apiKeyKeys = {
  all: ["apiKeys"] as const,
  scopes: ["apiKeyScopes"] as const,
};

export function useApiKeys() {
  return useQuery({
    queryKey: apiKeyKeys.all,
    queryFn: () => api.get<APIKey[]>("/auth/api-keys"),
    staleTime: 30_000,
  });
}

export function useApiKeyScopes() {
  return useQuery({
    queryKey: apiKeyKeys.scopes,
    queryFn: () => api.get<ScopeCatalogResponse>("/auth/api-keys/scopes"),
    staleTime: 5 * 60_000,
  });
}

export function useCreateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateAPIKeyRequest) =>
      api.post<APIKeyCreated>("/auth/api-keys", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: apiKeyKeys.all });
    },
  });
}

export function useUpdateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ keyId, data }: { keyId: string; data: UpdateAPIKeyRequest }) =>
      api.patch<APIKey>(`/auth/api-keys/${keyId}`, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: apiKeyKeys.all });
    },
  });
}

export function useRevokeApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) => api.delete<void>(`/auth/api-keys/${keyId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: apiKeyKeys.all });
    },
  });
}
