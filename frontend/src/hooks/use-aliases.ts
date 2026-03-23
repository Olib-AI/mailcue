import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  Alias,
  AliasListResponse,
  CreateAliasRequest,
  UpdateAliasRequest,
} from "@/types/api";

// --- Query Keys ---

export const aliasKeys = {
  all: ["aliases"] as const,
  list: () => [...aliasKeys.all, "list"] as const,
  detail: (id: string) => [...aliasKeys.all, "detail", id] as const,
};

// --- Hooks ---

export function useAliases() {
  return useQuery({
    queryKey: aliasKeys.list(),
    queryFn: () => api.get<AliasListResponse>("/aliases"),
    staleTime: 30_000,
  });
}

export function useCreateAlias() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateAliasRequest) =>
      api.post<Alias>("/aliases", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: aliasKeys.list(),
      });
    },
  });
}

export function useUpdateAlias() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: UpdateAliasRequest;
    }) => api.put<Alias>(`/aliases/${id}`, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: aliasKeys.all,
      });
    },
  });
}

export function useDeleteAlias() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api.delete<void>(`/aliases/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: aliasKeys.list(),
      });
    },
  });
}
