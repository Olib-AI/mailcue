import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  SandboxProvider,
  SandboxConversation,
  SandboxMessageList,
  SandboxMessage,
  CreateProviderRequest,
  UpdateProviderRequest,
  SendRequest,
  SimulateRequest,
  WebhookEndpoint,
  WebhookDelivery,
  CreateWebhookRequest,
} from "@/types/sandbox";

// --- Query Keys ---

export const sandboxKeys = {
  all: ["sandbox"] as const,
  providers: () => [...sandboxKeys.all, "providers"] as const,
  provider: (id: string) => [...sandboxKeys.all, "provider", id] as const,
  conversations: (providerId: string) =>
    [...sandboxKeys.all, "conversations", providerId] as const,
  messages: (providerId: string, conversationId?: string) =>
    [...sandboxKeys.all, "messages", providerId, conversationId] as const,
  allMessages: (providerId?: string) =>
    [...sandboxKeys.all, "allMessages", providerId] as const,
  webhooks: (providerId: string) =>
    [...sandboxKeys.all, "webhooks", providerId] as const,
  deliveries: (providerId: string) =>
    [...sandboxKeys.all, "deliveries", providerId] as const,
};

// --- Provider Hooks ---

export function useProviders() {
  return useQuery({
    queryKey: sandboxKeys.providers(),
    queryFn: () => api.get<SandboxProvider[]>("/sandbox/providers"),
  });
}

export function useProvider(id: string | null) {
  return useQuery({
    queryKey: sandboxKeys.provider(id ?? ""),
    queryFn: () => api.get<SandboxProvider>(`/sandbox/providers/${id}`),
    enabled: !!id,
  });
}

export function useCreateProvider() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateProviderRequest) =>
      api.post<SandboxProvider>("/sandbox/providers", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sandboxKeys.providers(),
      });
    },
  });
}

export function useUpdateProvider() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: UpdateProviderRequest;
    }) => api.put<SandboxProvider>(`/sandbox/providers/${id}`, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sandboxKeys.providers(),
      });
    },
  });
}

export function useDeleteProvider() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api.delete<void>(`/sandbox/providers/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sandboxKeys.providers(),
      });
    },
  });
}

// --- Conversation Hooks ---

export function useConversations(providerId: string | null) {
  return useQuery({
    queryKey: sandboxKeys.conversations(providerId ?? ""),
    queryFn: () =>
      api.get<SandboxConversation[]>(
        `/sandbox/providers/${providerId}/conversations`
      ),
    enabled: !!providerId,
  });
}

// --- Message Hooks ---

export function useMessages(
  providerId: string | null,
  conversationId?: string | null
) {
  return useQuery({
    queryKey: conversationId
      ? sandboxKeys.messages(providerId ?? "", conversationId)
      : sandboxKeys.allMessages(providerId ?? ""),
    queryFn: () => {
      if (conversationId) {
        return api.get<SandboxMessageList>(
          `/sandbox/providers/${providerId}/conversations/${conversationId}/messages`
        );
      }
      return api.get<SandboxMessageList>(
        `/sandbox/messages?provider_id=${providerId}`
      );
    },
    enabled: !!providerId,
    refetchInterval: 5000,
  });
}

export function useSimulateMessage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      providerId,
      data,
    }: {
      providerId: string;
      data: SimulateRequest;
    }) =>
      api.post<SandboxMessage>(
        `/sandbox/providers/${providerId}/simulate`,
        data
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sandboxKeys.all,
      });
    },
  });
}

export function useSendMessage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      providerId,
      data,
    }: {
      providerId: string;
      data: SendRequest;
    }) =>
      api.post<SandboxMessage>(
        `/sandbox/providers/${providerId}/send`,
        data
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sandboxKeys.all,
      });
    },
  });
}

export function useDeleteConversation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      providerId,
      conversationId,
    }: {
      providerId: string;
      conversationId: string;
    }) =>
      api.delete<void>(
        `/sandbox/providers/${providerId}/conversations/${conversationId}`
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sandboxKeys.all,
      });
    },
  });
}

// --- Message Hooks ---

export function useDeleteMessage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (messageId: string) =>
      api.delete<void>(`/sandbox/messages/${messageId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sandboxKeys.all,
      });
    },
  });
}

// --- Webhook Hooks ---

export function useWebhooks(providerId: string | null) {
  return useQuery({
    queryKey: sandboxKeys.webhooks(providerId ?? ""),
    queryFn: () =>
      api.get<WebhookEndpoint[]>(
        `/sandbox/providers/${providerId}/webhooks`
      ),
    enabled: !!providerId,
  });
}

export function useCreateWebhook() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      providerId,
      data,
    }: {
      providerId: string;
      data: CreateWebhookRequest;
    }) =>
      api.post<WebhookEndpoint>(
        `/sandbox/providers/${providerId}/webhooks`,
        data
      ),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: sandboxKeys.webhooks(variables.providerId),
      });
    },
  });
}

export function useDeleteWebhook() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api.delete<void>(`/sandbox/webhooks/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sandboxKeys.all,
      });
    },
  });
}

export function useWebhookDeliveries(providerId: string | null) {
  return useQuery({
    queryKey: sandboxKeys.deliveries(providerId ?? ""),
    queryFn: () =>
      api.get<WebhookDelivery[]>(
        `/sandbox/providers/${providerId}/webhook-deliveries`
      ),
    enabled: !!providerId,
  });
}
