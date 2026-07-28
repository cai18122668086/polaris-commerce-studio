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

  return {
    ...query,
    workspace: query.data?.[0] ?? null,
  };
}
