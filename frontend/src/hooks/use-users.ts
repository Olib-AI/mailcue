import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  UserListResponse,
  RegisterUserRequest,
  UpdateUserRequest,
  User,
} from "@/types/api";

export const userKeys = {
  all: ["users"] as const,
  list: () => [...userKeys.all, "list"] as const,
};

export function useUsers() {
  return useQuery({
    queryKey: userKeys.list(),
    queryFn: () => api.get<UserListResponse>("/auth/users"),
    staleTime: 10_000,
  });
}

export function useCreateUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: RegisterUserRequest) =>
      api.post<User>("/auth/register", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: userKeys.list() });
    },
  });
}

export function useUpdateUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ userId, data }: { userId: string; data: UpdateUserRequest }) =>
      api.put<User>(`/auth/users/${userId}`, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: userKeys.list() });
    },
  });
}

export function useDeleteUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (userId: string) =>
      api.delete<void>(`/auth/users/${userId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: userKeys.list() });
    },
  });
}
