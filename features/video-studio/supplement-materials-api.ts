// 补充素材面板的接口调用（W4）。所有外站素材都经自家接口代理，前端不直连外站。
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import { uploadWithProgress, type UploadProgress } from "@/lib/api/upload";
import type {
  AiEstimateResponse,
  AiImageRow,
  MaterialRow,
  SourcesResponse,
  StockSearchResponse,
} from "./supplement-materials";

const root = "/api/v1/video-studio/workspaces/{workspace_id}/editing-supplement" as const;
const materials = "/api/v1/video-studio/workspaces/{workspace_id}/projects/{project_id}/editing-materials" as const;

const ws = (workspace_id: string) => ({ params: { path: { workspace_id } } });

export const stockThumbUrl = (workspaceId: string, token: string) =>
  `/api/v1/video-studio/workspaces/${encodeURIComponent(workspaceId)}/editing-supplement/stock/thumb/${token}`;

export async function fetchSources(workspaceId: string): Promise<SourcesResponse> {
  return unwrapApiResponse(await apiClient.GET(`${root}/sources`, ws(workspaceId))) as unknown as SourcesResponse;
}

export async function searchStock(workspaceId: string, scriptText: string, sentenceIndexes?: number[], exclude: number[] = []): Promise<StockSearchResponse> {
  return unwrapApiResponse(await apiClient.POST(`${root}/stock/search`, {
    ...ws(workspaceId),
    signal: AbortSignal.timeout(120000),
    body: { script_text: scriptText, limit: 3, exclude_sentences: exclude, ...(sentenceIndexes ? { sentence_indexes: sentenceIndexes } : {}) },
  })) as unknown as StockSearchResponse;
}

export async function importStock(workspaceId: string, body: {
  project_id: string; request_id: string; token: string; sentence_index: number; sentence: string; work_item_ref?: string;
}): Promise<MaterialRow> {
  return unwrapApiResponse(await apiClient.POST(`${root}/stock/import`, {
    ...ws(workspaceId), signal: AbortSignal.timeout(240000), body,
  })) as unknown as MaterialRow;
}

export async function estimateAiImages(workspaceId: string, scriptText: string, maxImages: number, exclude: number[] = []): Promise<AiEstimateResponse> {
  return unwrapApiResponse(await apiClient.POST(`${root}/ai-images/estimate`, {
    ...ws(workspaceId), signal: AbortSignal.timeout(120000), body: { script_text: scriptText, max_images: maxImages, exclude_sentences: exclude },
  })) as unknown as AiEstimateResponse;
}

export async function createAiImages(workspaceId: string, body: {
  project_id: string; work_item_ref?: string;
  items: { request_id: string; sentence_index: number; sentence: string; subject: string; purpose: string }[];
}): Promise<AiImageRow[]> {
  const result = unwrapApiResponse(await apiClient.POST(`${root}/ai-images`, {
    ...ws(workspaceId), body: body as never,
  })) as unknown as { items: AiImageRow[] };
  return result.items;
}

export async function aiImageStatus(workspaceId: string, projectId: string, ids: string[]): Promise<AiImageRow[]> {
  const result = unwrapApiResponse(await apiClient.GET(`${root}/ai-images`, {
    params: { path: { workspace_id: workspaceId }, query: { project_id: projectId, ids } },
  })) as unknown as { items: AiImageRow[] };
  return result.items;
}

export async function regenerateAiImage(workspaceId: string, imageId: string, requestId: string): Promise<AiImageRow> {
  return unwrapApiResponse(await apiClient.POST(`${root}/ai-images/{image_id}/regenerate`, {
    params: { path: { workspace_id: workspaceId, image_id: imageId } }, body: { request_id: requestId },
  })) as unknown as AiImageRow;
}

export async function listMaterials(workspaceId: string, projectId: string): Promise<MaterialRow[]> {
  const result = unwrapApiResponse(await apiClient.GET(materials, {
    params: { path: { workspace_id: workspaceId, project_id: projectId }, query: { limit: 100 } },
  }));
  return result.items as unknown as MaterialRow[];
}

export async function uploadMaterial(workspaceId: string, projectId: string, file: File, description: string, progress: (value: UploadProgress) => void): Promise<MaterialRow> {
  const form = new FormData();
  form.append("file", file);
  form.append("request_id", crypto.randomUUID());
  form.append("label", file.name.replace(/\.[^.]+$/, "").slice(0, 120) || "我的素材");
  form.append("description", description.slice(0, 400));
  return unwrapApiResponse(await apiClient.POST(materials, {
    params: { path: { workspace_id: workspaceId, project_id: projectId } },
    signal: AbortSignal.timeout(600000),
    body: {} as never, bodySerializer: () => form, fetch: uploadWithProgress(form, progress),
  })) as unknown as MaterialRow;
}

export async function placeMaterial(workspaceId: string, projectId: string, materialId: string, sentence: { index: number; text: string } | null): Promise<MaterialRow> {
  return unwrapApiResponse(await apiClient.PUT(`${materials}/{material_id}/placement`, {
    params: { path: { workspace_id: workspaceId, project_id: projectId, material_id: materialId } },
    body: sentence ? { sentence_index: sentence.index, sentence: sentence.text } : {},
  })) as unknown as MaterialRow;
}

export async function deleteMaterial(workspaceId: string, projectId: string, materialId: string): Promise<void> {
  unwrapApiResponse(await apiClient.DELETE(`${materials}/{material_id}`, {
    params: { path: { workspace_id: workspaceId, project_id: projectId, material_id: materialId } },
  }));
}
