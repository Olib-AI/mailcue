import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ProductionStatus } from "@/types/api";

export const productionStatusKeys = {
  all: ["production-status"] as const,
};

export function useProductionStatus() {
  return useQuery({
    queryKey: productionStatusKeys.all,
    queryFn: () => api.get<ProductionStatus>("/system/production-status"),
    staleTime: 60_000,
  });
}
