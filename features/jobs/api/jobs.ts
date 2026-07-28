"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, createIdempotencyKey } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import {
  activeJobStatuses,
  isActiveJob,
  type DetailPackJobCreate,
  type JobDetail,
  type JobStatus,
  type JobType,
  type LocalEditJobCreate,
} from "@/lib/api/types";
import { jobKeys } from "./jobs-keys";

type JobFilters = {
  type?: JobType;
  statuses?: JobStatus[];
  limit?: number;
};

export function useJobs(
  workspaceId: string | undefined,
  filters: JobFilters = {},
) {
  const query = useQuery({
    queryKey: jobKeys.list(workspaceId ?? "pending", filters),
    enabled: Boolean(workspaceId),
    queryFn: async ({ signal }) => {
      const result = await apiClient.GET(
        "/api/v1/workspaces/{workspace_id}/jobs",
        {
          params: {
            path: { workspace_id: workspaceId! },
            query: {
              type: filters.type,
              statuses: filters.statuses,
              limit: filters.limit ?? 100,
              include_total: true,
            },
          },
          signal,
        },
      );
      return unwrapApiResponse(result);
    },
    refetchInterval(current) {
      return current.state.data?.items.some((job) => isActiveJob(job.status))
        ? 2_000
        : false;
    },
  });
  return query;
}

export function useJob(
  workspaceId: string | undefined,
  jobId: string | undefined,
) {
  return useQuery({
    queryKey: jobKeys.detail(workspaceId ?? "pending", jobId ?? "pending"),
    enabled: Boolean(workspaceId && jobId),
    queryFn: async ({ signal }) => {
      const result = await apiClient.GET(
        "/api/v1/workspaces/{workspace_id}/jobs/{job_id}",
        {
          params: {
            path: { workspace_id: workspaceId!, job_id: jobId! },
          },
          signal,
        },
      );
      return unwrapApiResponse(result);
    },
    refetchInterval(current) {
      const status = current.state.data?.status;
      return status && isActiveJob(status) ? 1_500 : false;
    },
  });
}

function useJobMutation<TResult, TVariables>(
  workspaceId: string | undefined,
  mutationFn: (workspaceId: string, variables: TVariables) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (variables: TVariables) => {
      if (!workspaceId) throw new Error("工作区尚未就绪。");
      return mutationFn(workspaceId, variables);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: jobKeys.all(workspaceId!),
      });
    },
  });
}

export function useCreateJob(workspaceId: string | undefined) {
  return useJobMutation<
    JobDetail,
    LocalEditJobCreate | DetailPackJobCreate
  >(workspaceId, async (id, body) => {
    const result = await apiClient.POST(
      "/api/v1/workspaces/{workspace_id}/jobs",
      {
        params: {
          path: { workspace_id: id },
          header: { "Idempotency-Key": createIdempotencyKey() },
        },
        body,
      },
    );
    return unwrapApiResponse(result);
  });
}

export function useCancelJob(workspaceId: string | undefined) {
  return useJobMutation<JobDetail, string>(workspaceId, async (id, jobId) => {
    const result = await apiClient.POST(
      "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/cancel",
      {
        params: {
          path: { workspace_id: id, job_id: jobId },
          header: { "Idempotency-Key": createIdempotencyKey() },
        },
        body: { reason: "用户在内部 mock 内测界面取消" },
      },
    );
    return unwrapApiResponse(result);
  });
}

export function useRetryJob(workspaceId: string | undefined) {
  return useJobMutation<JobDetail, string>(workspaceId, async (id, jobId) => {
    const result = await apiClient.POST(
      "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/retry",
      {
        params: {
          path: { workspace_id: id, job_id: jobId },
          header: { "Idempotency-Key": createIdempotencyKey() },
        },
        body: { scope: "failed", item_ids: [] },
      },
    );
    return unwrapApiResponse(result);
  });
}

export function useConfirmPlan(workspaceId: string | undefined) {
  return useJobMutation<JobDetail, { jobId: string; revision: number }>(
    workspaceId,
    async (id, input) => {
      const result = await apiClient.POST(
        "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/plan/confirm",
        {
          params: {
            path: { workspace_id: id, job_id: input.jobId },
            header: { "Idempotency-Key": createIdempotencyKey() },
          },
          body: { expected_revision: input.revision },
        },
      );
      return unwrapApiResponse(result);
    },
  );
}

export { activeJobStatuses };
