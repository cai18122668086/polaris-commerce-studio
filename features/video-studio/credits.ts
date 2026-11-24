"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import { costNote, type CreditAccount, type PricedAction, type PriceTable } from "./credit-notes";

export { costNote, type PricedAction } from "./credit-notes";

/** Configured video prices plus the workspace balance; either may be missing and the page still works. */
export function useVideoCredits(workspaceId: string) {
  const prices = useQuery({
    queryKey: ["video-studio", "credit-prices", workspaceId],
    staleTime: 5 * 60_000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET("/api/v1/video-studio/workspaces/{workspace_id}/credit-prices", {
      params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    })),
  });
  const account = useQuery({
    queryKey: ["video-studio", "credit-account", workspaceId],
    staleTime: 30_000,
    retry: false,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET("/api/v1/workspaces/{workspace_id}/credits", {
      params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    })),
  });
  const table: PriceTable = Object.fromEntries((prices.data?.prices ?? []).map(item => [item.action, item.credits ?? null]));
  const balance: CreditAccount | undefined = account.data
    ? { available: account.data.available_credits, enforced: account.data.enforcement_enabled }
    : undefined;
  return {
    balance,
    note: (actions: PricedAction[]) => costNote(actions, table, balance),
  };
}
