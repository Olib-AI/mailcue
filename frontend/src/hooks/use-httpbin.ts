import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  HttpBinBin,
  HttpBinCapturedRequestList,
  CreateBinRequest,
  UpdateBinRequest,
} from "@/types/httpbin";

export const httpbinKeys = {
  all: ["httpbin"] as const,
  bins: () => [...httpbinKeys.all, "bins"] as const,
  bin: (id: string) => [...httpbinKeys.all, "bin", id] as const,
  requests: (binId: string) => [...httpbinKeys.all, "requests", binId] as const,
};

export function useBins() {
  return useQuery({
    queryKey: httpbinKeys.bins(),
    queryFn: () => api.get<HttpBinBin[]>("/httpbin/bins"),
    refetchInterval: 3000,
  });
}

export function useBin(id: string | null) {
  return useQuery({
    queryKey: httpbinKeys.bin(id ?? ""),
    queryFn: () => api.get<HttpBinBin>(`/httpbin/bins/${id}`),
    enabled: !!id,
  });
}

export function useCreateBin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateBinRequest) =>
      api.post<HttpBinBin>("/httpbin/bins", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: httpbinKeys.bins() });
    },
  });
}

export function useUpdateBin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateBinRequest }) =>
      api.put<HttpBinBin>(`/httpbin/bins/${id}`, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: httpbinKeys.all });
    },
  });
}

export function useDeleteBin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/httpbin/bins/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: httpbinKeys.all });
    },
  });
}

export function useBinRequests(binId: string | null) {
  return useQuery({
    queryKey: httpbinKeys.requests(binId ?? ""),
    queryFn: () =>
      api.get<HttpBinCapturedRequestList>(`/httpbin/bins/${binId}/requests`),
    enabled: !!binId,
    staleTime: 0,
    refetchInterval: 3000,
  });
}

export function useDeleteBinRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (requestId: string) =>
      api.delete<void>(`/httpbin/requests/${requestId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: httpbinKeys.all });
    },
  });
}

export function useClearBinRequests() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (binId: string) =>
      api.delete<void>(`/httpbin/bins/${binId}/requests`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: httpbinKeys.all });
    },
  });
}
