"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { RuntimeStatus } from "@/lib/api/types";

export const runtimeKeys = {
  status: ["runtime-status"] as const,
};

export function useRuntimeStatus() {
  return useQuery({
    queryKey: runtimeKeys.status,
    queryFn: async ({ signal }) => {
      const result = await apiClient.GET("/api/v1/runtime", { signal });
      return unwrapApiResponse(result);
    },
    staleTime: 60_000,
    retry: 1,
  });
}

type WorkflowCapability =
  RuntimeStatus["capabilities"]["local_edit"];

export type WorkflowPresentation = {
  mode: "provider" | "mock" | "unavailable" | "unknown";
  canDeliverImages: boolean;
};

export function presentWorkflow(
  capability: WorkflowCapability | null | undefined,
): WorkflowPresentation {
  if (!capability) {
    return { mode: "unknown", canDeliverImages: false };
  }
  if (capability.availability !== "available") {
    return { mode: "unavailable", canDeliverImages: false };
  }
  if (capability.execution === "provider") {
    return { mode: "provider", canDeliverImages: true };
  }
  if (capability.execution === "mock") {
    return { mode: "mock", canDeliverImages: false };
  }
  return { mode: "unavailable", canDeliverImages: false };
}

function supportsProvider(capability: WorkflowCapability | undefined): boolean {
  return (
    capability?.availability === "available" &&
    capability.execution === "provider"
  );
}

export type RuntimePresentation = {
  badge: string;
  summary: string;
  assurance: string;
  providerGenerationEnabled: boolean;
};

export function presentRuntime(
  runtime: RuntimeStatus | null | undefined,
): RuntimePresentation {
  const localEditProvider = supportsProvider(runtime?.capabilities.local_edit);
  const detailPackProvider = supportsProvider(runtime?.capabilities.detail_pack);
  const providerGenerationEnabled = localEditProvider || detailPackProvider;

  if (!runtime) {
    return {
      badge: "能力状态未知",
      summary: "按 fail-closed 处理：内部接口可测试，真实图片生成未启用。",
      assurance: "不调用付费 Provider",
      providerGenerationEnabled: false,
    };
  }

  const workflows = [
    runtime.capabilities.local_edit,
    runtime.capabilities.detail_pack,
  ];
  const allMock =
    workflows.every(
      (item) =>
        item.availability === "available" && item.execution === "mock",
    );

  if (allMock) {
    return {
      badge: "内部 mock 内测",
      summary: "资产与任务状态会真实写入零付费后端；局部修改与详情图均无可交付生成图片。",
      assurance: "真实生成未启用",
      providerGenerationEnabled: false,
    };
  }

  return {
    badge: runtime.environment === "production" ? "运行能力" : "内部能力",
    summary: providerGenerationEnabled
      ? "部分工作流报告为 Provider 执行；请按各工作流能力状态操作。"
      : "当前工作流不可用或仅支持本地/mock 执行，无可交付 Provider 生成图片。",
    assurance: providerGenerationEnabled
      ? "按 runtime 能力执行"
      : "真实生成未启用",
    providerGenerationEnabled,
  };
}
