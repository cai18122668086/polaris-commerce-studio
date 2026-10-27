"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRef } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";

export type Purchase = components["schemas"]["CreditPurchaseResponse"];
export type Product = components["schemas"]["CreditPackage"];

export function useCreditProducts(workspaceId: string) {
  return useQuery({
    queryKey: ["credit-products", workspaceId],
    queryFn: async ({ signal }) =>
      unwrapApiResponse(
        await apiClient.GET(
          "/api/v1/workspaces/{workspace_id}/credits/packages",
          {
            params: {
              path: { workspace_id: workspaceId },
              query: { include_memberships: true },
            },
            signal,
          },
        ),
      ),
    retry: false,
  });
}
export function useMembership(workspaceId: string) {
  return useQuery({
    queryKey: ["credit-membership", workspaceId],
    queryFn: async ({ signal }) =>
      unwrapApiResponse(
        await apiClient.GET(
          "/api/v1/workspaces/{workspace_id}/credits/membership",
          { params: { path: { workspace_id: workspaceId } }, signal },
        ),
      ),
    refetchInterval: 5000,
    retry: false,
  });
}
export function usePurchaseHistory(workspaceId: string) {
  return useInfiniteQuery({
    queryKey: ["credit-orders", workspaceId],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam, signal }) =>
      unwrapApiResponse(
        await apiClient.GET(
          "/api/v1/workspaces/{workspace_id}/credits/purchases",
          {
            params: {
              path: { workspace_id: workspaceId },
              query: { cursor: pageParam, limit: 30 },
            },
            signal,
          },
        ),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    refetchInterval: 5000,
    retry: false,
  });
}
export function useLedgerHistory(workspaceId: string) {
  return useInfiniteQuery({
    queryKey: ["credit-ledger-history", workspaceId],
    initialPageParam: undefined as number | undefined,
    queryFn: async ({ pageParam, signal }) =>
      unwrapApiResponse(
        await apiClient.GET(
          "/api/v1/workspaces/{workspace_id}/credits/ledger",
          {
            params: {
              path: { workspace_id: workspaceId },
              query: { before_id: pageParam, limit: 50 },
            },
            signal,
          },
        ),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    refetchInterval: 5000,
    retry: false,
  });
}
export function usePurchaseOrder(workspaceId: string, orderId: string | null) {
  return useQuery({
    queryKey: ["credit-purchase", workspaceId, orderId],
    enabled: Boolean(orderId),
    queryFn: async ({ signal }) =>
      unwrapApiResponse(
        await apiClient.GET(
          "/api/v1/workspaces/{workspace_id}/credits/purchases/{purchase_id}",
          {
            params: {
              path: { workspace_id: workspaceId, purchase_id: orderId! },
            },
            signal,
          },
        ),
      ),
    refetchInterval: (query) =>
      query.state.data?.status === "paid" ? false : 2500,
    retry: false,
  });
}
export function useCreatePurchase(workspaceId: string) {
  const queryClient = useQueryClient();
  const intent = useRef<{ productId: string; key: string } | null>(null);
  const mutation = useMutation({
    mutationFn: async (productId: string) => {
      if (!intent.current || intent.current.productId !== productId)
        intent.current = { productId, key: crypto.randomUUID() };
      return unwrapApiResponse(
        await apiClient.POST(
          "/api/v1/workspaces/{workspace_id}/credits/purchases",
          {
            params: {
              path: { workspace_id: workspaceId },
              header: { "Idempotency-Key": intent.current.key },
            },
            body: { package_id: productId },
          },
        ),
      );
    },
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["credit-orders", workspaceId],
      }),
  });
  return {
    ...mutation,
    newIntent: () => {
      intent.current = null;
      mutation.reset();
    },
  };
}
