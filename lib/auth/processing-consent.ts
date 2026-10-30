import notice from "@/backend/app/processing_notice.json";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";

export const PROCESSING_NOTICE = notice;
export type ProcessingConsentChoice = { policyVersion: string; hongKongProcessing: boolean; aiTraining: boolean };
export const processingChoice = (hongKongProcessing: boolean, aiTraining: boolean): ProcessingConsentChoice => ({ policyVersion: notice.version, hongKongProcessing, aiTraining });
export const processingConsentKey = (userId?: string) => ["auth", "processing-consent", userId] as const;

export async function requestProcessingConsent(method: "GET" | "POST" | "DELETE" = "GET", choice?: ProcessingConsentChoice) {
  const options = { signal: AbortSignal.timeout(20_000) };
  if (method === "POST") return unwrapApiResponse(await apiClient.POST("/api/v1/me/processing-consent", { ...options, body: choice! }));
  if (method === "DELETE") return unwrapApiResponse(await apiClient.DELETE("/api/v1/me/processing-consent", options));
  return unwrapApiResponse(await apiClient.GET("/api/v1/me/processing-consent", options));
}
