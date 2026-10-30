"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse, errorMessage } from "@/lib/api/request";
import { useDraftState } from "@/lib/hooks/use-creation-draft";

const labels = { open: "待处理", in_progress: "跟进中", resolved: "已解决" };

export function SupportCases({ workspaceId }: { workspaceId: string }) {
  const search = useSearchParams();
  const client = useQueryClient();
  const intent = useRef<string | null>(null);
  const [issue, setIssue] = useDraftState(workspaceId, "support", "issue", "");
  const [jobId, setJobId] = useState(search.get("jobId") ?? "");
  const list = useQuery({ queryKey: ["support-cases", workspaceId], queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(
    "/api/v1/workspaces/{workspace_id}/support-cases", { params: { path: { workspace_id: workspaceId } }, signal },
  )), refetchInterval: 15000 });
  const submit = useMutation({ mutationFn: async () => {
    intent.current ??= crypto.randomUUID();
    return unwrapApiResponse(await apiClient.POST("/api/v1/workspaces/{workspace_id}/support-cases", {
      params: { path: { workspace_id: workspaceId }, header: { "Idempotency-Key": intent.current } },
      body: { issue, job_id: jobId.trim() || null },
    }));
  }, onSuccess: () => { setIssue(""); intent.current = null; void client.invalidateQueries({ queryKey: ["support-cases", workspaceId] }); } });
  return <section className="support-cases panel">
    <h2>任务与售后帮助</h2><p>描述问题并关联任务，方便工作人员核对进度、出图和积分。处理结果会保留在这里。</p>
    <form onSubmit={event => { event.preventDefault(); submit.mutate(); }}>
      <label>关联任务编号（选填）<input value={jobId} onChange={event => { setJobId(event.target.value); intent.current = null; }} placeholder="可从生成记录复制任务编号" maxLength={40} /></label>
      <label>问题描述<textarea value={issue} onChange={event => { setIssue(event.target.value); intent.current = null; submit.reset(); }} maxLength={4000} rows={4} placeholder="请说明遇到的问题、预期效果以及已经尝试的步骤。" required minLength={3} /></label>
      <button className="primary-button" disabled={submit.isPending || issue.trim().length < 3}>{submit.isPending ? "正在提交…" : "提交帮助请求"}</button>
    </form>
    {submit.isError && <p role="alert">{errorMessage(submit.error)}</p>}{submit.isSuccess && <p role="status">问题已登记，可在下方查看处理状态。</p>}
    {list.isError ? <button onClick={() => void list.refetch()}>记录加载失败，点击重试</button> : list.data?.map(item => <article key={item.id} className="support-case"><strong>{labels[item.status as keyof typeof labels] ?? item.status}</strong><p>{item.issue}</p>{item.job_id && <Link href={`/jobs?jobId=${encodeURIComponent(item.job_id)}`}>查看关联任务</Link>}{item.resolution && <p>处理结果：{item.resolution}</p>}<small>记录编号：{item.id}</small></article>)}
  </section>;
}
