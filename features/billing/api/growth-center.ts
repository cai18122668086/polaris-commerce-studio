"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";

type Offer = components["schemas"]["NewcomerOffer"];

export const newcomerOfferKey = (workspaceId: string | undefined) => ["newcomer-offer", workspaceId] as const;

export function useNewcomerOffer(workspaceId: string | undefined) {
  return useQuery<Offer>({queryKey:newcomerOfferKey(workspaceId),enabled:Boolean(workspaceId),retry:false,refetchInterval:query=>query.state.data?.waiting_for_result ? 5_000 : query.state.data?.eligible ? 30_000 : false,
    queryFn:async({signal})=>unwrapApiResponse(await apiClient.GET("/api/v1/workspaces/{workspace_id}/promotions/newcomer-offer",{params:{path:{workspace_id:workspaceId!}},signal}))});
}

export async function claimOfferImpression(workspaceId: string) {
  return unwrapApiResponse(await apiClient.POST(
    "/api/v1/workspaces/{workspace_id}/promotions/newcomer-offer/impression",
    { params: { path: { workspace_id: workspaceId } } },
  ));
}

export async function recordNewcomerResult(workspaceId: string, assetId: string) {
  return unwrapApiResponse(await apiClient.POST(
    "/api/v1/workspaces/{workspace_id}/promotions/newcomer-offer/viewed",
    { params: { path: { workspace_id: workspaceId } }, body: { asset_id: assetId } },
  ));
}

export type InvitationFilter = "all"|"paid"|"unpaid"|"refunded";
export function useInvitationCenter(workspaceId:string, status:InvitationFilter, offset:number) {
  return useQuery({queryKey:["invitation-center",workspaceId,status,offset],retry:false,refetchInterval:30_000,staleTime:15_000,placeholderData:keepPreviousData,
    queryFn:async({signal})=>unwrapApiResponse(await apiClient.GET("/api/v1/workspaces/{workspace_id}/invitations",{params:{path:{workspace_id:workspaceId},query:{status,offset,limit:20}},signal}))});
}
