"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";

export const workspaceKeys = {
  all: ["workspaces"] as const,
};

export function useWorkspace() {
  const query = useQuery({
    queryKey: workspaceKeys.all,
    queryFn: async ({ signal }) => {
      const result = await apiClient.GET("/api/v1/workspaces", { signal });
      return unwrapApiResponse(result);
    },
    staleTime: 5 * 60_000,
  });

  const workspace = query.isSuccess ? query.data[0] ?? null : undefined;

  return {
    ...query,
    workspace,
    isEmpty: query.isSuccess && query.data.length === 0,
    workspaceState: query.isPending
      ? ("loading" as const)
      : query.isError
        ? ("error" as const)
        : query.data.length === 0
          ? ("empty" as const)
          : ("ready" as const),
  };
}
