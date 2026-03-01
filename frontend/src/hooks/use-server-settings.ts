import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ServerSettings, UpdateServerSettingsRequest } from "@/types/api";

const serverSettingsKeys = {
  all: ["serverSettings"] as const,
};

export function useServerSettings() {
  return useQuery({
    queryKey: serverSettingsKeys.all,
    queryFn: () => api.get<ServerSettings>("/system/settings"),
    staleTime: 60_000,
  });
}

export function useUpdateServerSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateServerSettingsRequest) =>
      api.put<ServerSettings>("/system/settings", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: serverSettingsKeys.all });
    },
  });
}
