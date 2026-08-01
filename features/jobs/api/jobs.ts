"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { apiClient } from "@/lib/api/client";
import {
  IdempotencyIntentRegistry,
  intentSignature,
  type IdempotentOperation,
} from "@/lib/api/idempotency";
import { unwrapApiResponse } from "@/lib/api/request";
import {
  activeJobStatuses,
  isActiveJob,
  type JobCreate,
  type JobDetail,
  type JobStatus,
  type JobType,
  type RetryScope,
} from "@/lib/api/types";
import { jobKeys } from "./jobs-keys";
import { assertJobAction } from "@/lib/jobs/actions";

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
  operation: IdempotentOperation,
  signatureInput: (variables: TVariables) => unknown,
  mutationFn: (
    workspaceId: string,
    variables: TVariables,
    idempotencyKey: string,
  ) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  const registry = useRef<IdempotencyIntentRegistry | null>(null);
  registry.current ??= new IdempotencyIntentRegistry();
  const signatureFor = (variables: TVariables) =>
    intentSignature(operation, signatureInput(variables));
  const mutation = useMutation({
    mutationFn: async (variables: TVariables) => {
      if (!workspaceId) throw new Error("工作区尚未就绪。");
      const signature = signatureFor(variables);
      return mutationFn(
        workspaceId,
        variables,
        registry.current!.keyFor(signature),
      );
    },
    onSuccess: async (_, variables) => {
      registry.current!.complete(signatureFor(variables));
      await queryClient.invalidateQueries({
        queryKey: jobKeys.all(workspaceId!),
      });
    },
  });
  return {
    ...mutation,
    abandonIntent: (variables: TVariables) =>
      registry.current!.abandon(signatureFor(variables)),
  };
}

export function useCreateJob(workspaceId: string | undefined) {
  return useJobMutation<JobDetail, JobCreate>(
    workspaceId,
    "create-job",
    (body) => body,
    async (id, body, key) => {
      const result = await apiClient.POST(
        "/api/v1/workspaces/{workspace_id}/jobs",
        {
          params: {
            path: { workspace_id: id },
            header: { "Idempotency-Key": key },
          },
          body,
        },
      );
      return unwrapApiResponse(result);
    },
  );
}

type AuthorizedJobAction = {
  jobId: string;
  allowedActions: string[];
};

export function useCancelJob(workspaceId: string | undefined) {
  return useJobMutation<JobDetail, AuthorizedJobAction>(
    workspaceId,
    "cancel-job",
    ({ jobId }) => ({ jobId }),
    async (id, input, key) => {
      assertJobAction(input.allowedActions, "cancel");
      const result = await apiClient.POST(
        "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/cancel",
        {
          params: {
            path: { workspace_id: id, job_id: input.jobId },
            header: { "Idempotency-Key": key },
          },
          body: { reason: "用户在内部 mock 内测界面取消" },
        },
      );
      return unwrapApiResponse(result);
    },
  );
}

type RetryJobAction = AuthorizedJobAction & {
  scope?: RetryScope;
  itemIds?: string[];
};

export function useRetryJob(workspaceId: string | undefined) {
  return useJobMutation<JobDetail, RetryJobAction>(
    workspaceId,
    "retry-job",
    ({ jobId, scope = "failed", itemIds = [] }) => ({
      jobId,
      scope,
      itemIds,
    }),
    async (id, input, key) => {
      assertJobAction(input.allowedActions, "retry");
      const result = await apiClient.POST(
        "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/retry",
        {
          params: {
            path: { workspace_id: id, job_id: input.jobId },
            header: { "Idempotency-Key": key },
          },
          body: {
            scope: input.scope ?? "failed",
            item_ids: input.itemIds ?? [],
          },
        },
      );
      return unwrapApiResponse(result);
    },
  );
}

export function useConfirmPlan(workspaceId: string | undefined) {
  return useJobMutation<
    JobDetail,
    AuthorizedJobAction & { revision: number }
  >(
    workspaceId,
    "confirm-plan",
    ({ jobId, revision }) => ({ jobId, revision }),
    async (id, input, key) => {
      assertJobAction(input.allowedActions, "confirm_plan");
      const result = await apiClient.POST(
        "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/plan/confirm",
        {
          params: {
            path: { workspace_id: id, job_id: input.jobId },
            header: { "Idempotency-Key": key },
          },
          body: { expected_revision: input.revision },
        },
      );
      return unwrapApiResponse(result);
    },
  );
}

export { activeJobStatuses };
