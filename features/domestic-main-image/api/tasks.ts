"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

type SourceRole = "primary" | "detail" | "back" | "package" | "structure";

export type DomesticMainImagePlanRow = {
  page_index: number;
  page_role: string;
  main_selling_point: string;
  supporting_selling_points: string[];
  visual_proof: string;
  composition_and_subject: string;
  reading_path_and_type_hierarchy: string;
  non_repetition_reason: string;
  commercial_closure: string;
};

export type DomesticMainImageTask = {
  id: string;
  workspace_id: string;
  technical_status: string;
  skill_state: string;
  revision: number;
  allowed_actions: string[];
  skill_name: string;
  skill_version: string;
  skill_digest: string;
  startup_git_commit: string;
  provider_capability_status: string;
  image_model: string | null;
  image_model_version: string | null;
  campaign_style_summary: string | null;
  plan: DomesticMainImagePlanRow[];
  generation_request_ready: boolean;
  generation_prompt_sha256: string | null;
  reference_roles: string[];
  edit_target_role: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  sources: Array<{
    asset_id: string;
    evidence_id: string;
    ordinal: number;
    role: SourceRole;
    sha256: string;
  }>;
  created_at: string;
  updated_at: string;
};

export type DomesticMainImageCreate = {
  product_name: string;
  category: string;
  product_information: string;
  verified_selling_points: string[];
  sources: Array<{ asset_id: string; role: SourceRole }>;
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Request-Id": crypto.randomUUID(),
      ...init?.headers,
    },
  });
  const body = await response.json().catch(() => undefined);
  if (!response.ok) {
    const message = body?.error?.message;
    throw new Error(typeof message === "string" ? message : "国内主图请求未完成。");
  }
  return body as T;
}

export function useDomesticMainImageTask(
  workspaceId: string | undefined,
  taskId: string | undefined,
) {
  return useQuery({
    queryKey: ["domestic-main-image", workspaceId, taskId],
    enabled: Boolean(workspaceId && taskId),
    queryFn: () =>
      requestJson<DomesticMainImageTask>(
        `/api/v1/workspaces/${workspaceId}/domestic-main-image/tasks/${taskId}`,
      ),
    refetchInterval(query) {
      const task = query.state.data;
      return task && !["FINALIZED", "AWAITING_USER_FINAL_REVIEW"].includes(task.skill_state)
        ? 2_000
        : false;
    },
  });
}

export function useCreateDomesticMainImageTask(workspaceId: string | undefined) {
  return useMutation({
    mutationFn: (payload: DomesticMainImageCreate) => {
      if (!workspaceId) throw new Error("工作区尚未就绪。");
      return requestJson<DomesticMainImageTask>(
        `/api/v1/workspaces/${workspaceId}/domestic-main-image/tasks`,
        {
          method: "POST",
          headers: { "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify(payload),
        },
      );
    },
  });
}

export function useAuthorizeDomesticMainImageTask(
  workspaceId: string | undefined,
) {
  return useMutation({
    mutationFn: ({ taskId, revision }: { taskId: string; revision: number }) => {
      if (!workspaceId) throw new Error("工作区尚未就绪。");
      return requestJson<DomesticMainImageTask>(
        `/api/v1/workspaces/${workspaceId}/domestic-main-image/tasks/${taskId}/authorize`,
        {
          method: "POST",
          body: JSON.stringify({
            expected_revision: revision,
            approval_text: "我确认这份六图规划，并授权按原版 Skill 进入顺序执行。",
          }),
        },
      );
    },
  });
}

export type { SourceRole };
