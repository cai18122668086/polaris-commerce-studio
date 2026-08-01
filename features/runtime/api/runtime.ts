"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { CapabilityStatus, RuntimeStatus } from "@/lib/api/types";

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

export function resolveRuntimeCapability(
  runtime: RuntimeStatus | null | undefined,
  capabilityKey: string,
): CapabilityStatus | undefined {
  if (!runtime) return undefined;

  const featureCapabilities = runtime.capabilities.features ?? {};
  const directFeature = featureCapabilities[capabilityKey];
  if (directFeature) return directFeature;

  const familyKey = capabilityKey.split(".", 1)[0];
  const familyFeature = featureCapabilities[familyKey];
  if (familyFeature) return familyFeature;

  if (capabilityKey === "local_edit") return runtime.capabilities.local_edit;
  if (capabilityKey === "detail_pack") return runtime.capabilities.detail_pack;
  return undefined;
}

export type WorkflowPresentation = {
  mode: "provider" | "mock" | "local" | "unavailable" | "unknown";
  canDeliverImages: boolean;
  canSubmit: boolean;
  badge: string;
  message: string;
  reasonCode?: string | null;
};

export function presentWorkflow(
  capability: CapabilityStatus | null | undefined,
): WorkflowPresentation {
  if (!capability) {
    return {
      mode: "unknown",
      canDeliverImages: false,
      canSubmit: false,
      badge: "能力状态未知",
      message: "按 fail-closed 处理：能力状态确认前不会创建任务。",
    };
  }
  if (capability.availability !== "available") {
    return {
      mode: "unavailable",
      canDeliverImages: false,
      canSubmit: false,
      badge: "真实 Provider 未接入",
      message: "当前运行环境未注册此功能的真实 Provider，提交入口已关闭。",
      reasonCode: capability.reason_code,
    };
  }
  if (capability.execution === "provider") {
    return {
      mode: "provider",
      canDeliverImages: true,
      canSubmit: true,
      badge: "Provider 可用",
      message: "任务将由后端已注册 Provider 执行并交付图片。",
      reasonCode: capability.reason_code,
    };
  }
  if (capability.execution === "mock") {
    return {
      mode: "mock",
      canDeliverImages: false,
      canSubmit: true,
      badge: "Mock 可用",
      message: "可验证上传、建单和状态轮询；mock 不会伪造可交付图片。",
      reasonCode: capability.reason_code,
    };
  }
  if (capability.execution === "local") {
    return {
      mode: "local",
      canDeliverImages: true,
      canSubmit: true,
      badge: "本地能力可用",
      message: "任务将在后端本地能力边界内执行。",
      reasonCode: capability.reason_code,
    };
  }
  return {
    mode: "unavailable",
    canDeliverImages: false,
    canSubmit: false,
    badge: "能力不可用",
    message: "当前能力没有可执行后端，提交入口已关闭。",
    reasonCode: capability.reason_code,
  };
}

function supportsProvider(capability: CapabilityStatus | undefined): boolean {
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
  const allMock = workflows.every(
    (item) => item.availability === "available" && item.execution === "mock",
  );

  if (allMock) {
    return {
      badge: "内部 mock 内测",
      summary: "资产与任务状态会真实写入零付费后端；mock 不会伪造可交付图片。",
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
