import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  ForwardingRule,
  ForwardingRuleListResponse,
  CreateForwardingRuleRequest,
  UpdateForwardingRuleRequest,
  TestForwardingRuleResponse,
} from "@/types/api";

// --- Query Keys ---

export const forwardingRuleKeys = {
  all: ["forwarding-rules"] as const,
  list: () => [...forwardingRuleKeys.all, "list"] as const,
  detail: (id: string) => [...forwardingRuleKeys.all, "detail", id] as const,
};

// --- Hooks ---

export function useForwardingRules() {
  return useQuery({
    queryKey: forwardingRuleKeys.list(),
    queryFn: () => api.get<ForwardingRuleListResponse>("/forwarding-rules"),
    staleTime: 30_000,
  });
}

export function useForwardingRule(id: string | null) {
  return useQuery({
    queryKey: forwardingRuleKeys.detail(id ?? ""),
    queryFn: () => api.get<ForwardingRule>(`/forwarding-rules/${id}`),
    enabled: !!id,
  });
}

export function useCreateForwardingRule() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateForwardingRuleRequest) =>
      api.post<ForwardingRule>("/forwarding-rules", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: forwardingRuleKeys.list(),
      });
    },
  });
}

export function useUpdateForwardingRule() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: UpdateForwardingRuleRequest;
    }) => api.put<ForwardingRule>(`/forwarding-rules/${id}`, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: forwardingRuleKeys.all,
      });
    },
  });
}

export function useDeleteForwardingRule() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api.delete<void>(`/forwarding-rules/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: forwardingRuleKeys.list(),
      });
    },
  });
}

export function useTestForwardingRule() {
  return useMutation({
    mutationFn: (id: string) =>
      api.post<TestForwardingRuleResponse>(`/forwarding-rules/${id}/test`),
  });
}
