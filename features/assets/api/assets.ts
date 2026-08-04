"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { apiClient } from "@/lib/api/client";
import {
  IdempotencyIntentRegistry,
  uploadIntentSignature,
} from "@/lib/api/idempotency";
import { unwrapApiResponse } from "@/lib/api/request";
import type { AssetOriginKind } from "@/lib/api/types";
import { assetKeys } from "./assets-keys";

export function useAssets(
  workspaceId: string | undefined,
  filters: { originKind?: AssetOriginKind; limit?: number } = {},
) {
  return useQuery({
    queryKey: assetKeys.list(workspaceId ?? "pending", filters),
    enabled: Boolean(workspaceId),
    queryFn: async ({ signal }) => {
      const result = await apiClient.GET(
        "/api/v1/workspaces/{workspace_id}/assets",
        {
          params: {
            path: { workspace_id: workspaceId! },
            query: {
              origin_kind: filters.originKind,
              media_kind: "image",
              limit: filters.limit ?? 100,
              include_total: true,
            },
          },
          signal,
        },
      );
      return unwrapApiResponse(result);
    },
  });
}

export function useUploadAsset(workspaceId: string | undefined) {
  const queryClient = useQueryClient();
  const registry = useRef<IdempotencyIntentRegistry | null>(null);
  registry.current ??= new IdempotencyIntentRegistry();
  const signatureByInput = useRef(
    new WeakMap<File, Map<"image" | "mask", Promise<string>>>(),
  );
  const signatureFor = (input: { file: File; mediaKind?: "image" | "mask" }) => {
    const mediaKind = input.mediaKind ?? "image";
    const signatures =
      signatureByInput.current.get(input.file) ??
      new Map<"image" | "mask", Promise<string>>();
    signatureByInput.current.set(input.file, signatures);
    const existing = signatures.get(mediaKind);
    if (existing) return existing;
    const signature = uploadIntentSignature(input.file, mediaKind);
    signatures.set(mediaKind, signature);
    return signature;
  };
  const mutation = useMutation({
    mutationFn: async ({
      file,
      mediaKind = "image",
    }: {
      file: File;
      mediaKind?: "image" | "mask";
    }) => {
      if (!workspaceId) throw new Error("工作区尚未就绪。");
      const signature = await signatureFor({ file, mediaKind });
      const idempotencyKey = registry.current!.keyFor(signature);
      const result = await apiClient.POST(
        "/api/v1/workspaces/{workspace_id}/assets",
        {
          params: {
            path: { workspace_id: workspaceId },
            header: { "Idempotency-Key": idempotencyKey },
          },
          body: {
            file: file as unknown as string,
            media_kind: mediaKind,
            origin_kind: "upload",
          },
          bodySerializer() {
            const form = new FormData();
            form.set("file", file);
            form.set("media_kind", mediaKind);
            form.set("origin_kind", "upload");
            return form;
          },
        },
      );
      return unwrapApiResponse(result);
    },
    onSuccess: async (_, input) => {
      registry.current!.complete(await signatureFor(input));
      await queryClient.invalidateQueries({
        queryKey: assetKeys.lists(workspaceId!),
      });
    },
  });
  return {
    ...mutation,
    abandonIntent: async (input: {
      file: File;
      mediaKind?: "image" | "mask";
    }) => registry.current!.abandon(await signatureFor(input)),
  };
}

export async function getAssetAccessUrl(
  workspaceId: string,
  assetId: string,
  disposition: "inline" | "attachment" = "inline",
) {
  const result = await apiClient.POST(
    "/api/v1/workspaces/{workspace_id}/assets/{asset_id}/access-url",
    {
      params: { path: { workspace_id: workspaceId, asset_id: assetId } },
      body: { disposition, variant: "original" },
    },
  );
  return unwrapApiResponse(result);
}

export function useAssetAccessUrl(
  workspaceId: string | undefined,
  assetId: string | undefined,
) {
  return useQuery({
    queryKey: ["asset-access-url", workspaceId, assetId, "inline"],
    enabled: Boolean(workspaceId && assetId),
    queryFn: () => getAssetAccessUrl(workspaceId!, assetId!),
    staleTime: 4 * 60_000,
  });
}
