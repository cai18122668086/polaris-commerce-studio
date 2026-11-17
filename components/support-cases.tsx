"use client";
import { WECHAT_SUPPORT_URL } from "@/lib/customer-support";
import { TaskWorkspaceLink } from "@/components/task-workspace-link";

import { useRef, useState } from "react";
import { ArrowUpRight, Check, ClipboardList, LoaderCircle, MessageCircle, Send } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse, errorMessage } from "@/lib/api/request";
import { useDraftState } from "@/lib/hooks/use-creation-draft";
import styles from "./support-cases.module.css";

const labels = { open: "待处理", in_progress: "跟进中", resolved: "已解决" };

export function SupportCases({ workspaceId }: { workspaceId: string }) {
  const search = useSearchParams();
  const requestedJobId = search.get("jobId")?.trim() ?? "";
  return <SupportCaseForm key={JSON.stringify([workspaceId, requestedJobId])} workspaceId={workspaceId} initialJobId={requestedJobId} />;
}

function SupportCaseForm({ workspaceId, initialJobId }: { workspaceId: string; initialJobId: string }) {
  const client = useQueryClient();
  const intent = useRef<string | null>(null);
  const [issue, setIssue] = useDraftState(workspaceId, "support", "issue", "");
  const [jobId, setJobId] = useState(initialJobId);
  const casesKey = ["support-cases", workspaceId];
  const list = useQuery({ queryKey: casesKey, queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(
    "/api/v1/workspaces/{workspace_id}/support-cases", { params: { path: { workspace_id: workspaceId } }, signal },
  )), refetchInterval: 15000 });
  const submit = useMutation({ mutationFn: async () => {
    intent.current ??= crypto.randomUUID();
    return unwrapApiResponse(await apiClient.POST("/api/v1/workspaces/{workspace_id}/support-cases", {
      params: { path: { workspace_id: workspaceId }, header: { "Idempotency-Key": intent.current } },
      body: { welcome_bonus: false, issue: issue.trim(), job_id: jobId.trim() || null },
    }));
  }, onSuccess: created => {
    setIssue("");
    intent.current = null;
    client.setQueryData<NonNullable<typeof list.data>>(casesKey, previous => [
      created, ...(previous ?? []).filter(item => item.id !== created.id),
    ]);
    void client.invalidateQueries({ queryKey: casesKey });
  } });
  const canSubmit = !submit.isPending && issue.trim().length >= 3;
  return <section className={`support-cases ${styles.panel}`} aria-label="任务与售后帮助">
    <header className={styles.header}>
      <div>
        <h2>任务与售后帮助</h2>
        <p>描述出图、任务或积分问题，处理结果会显示在客服记录中。</p>
      </div>
      <a className={styles.contact} href={WECHAT_SUPPORT_URL} target="_blank" rel="noopener noreferrer">
        <MessageCircle size={17} aria-hidden="true" />联系企业微信客服<ArrowUpRight size={14} aria-hidden="true" />
      </a>
    </header>
    <form aria-label="提交帮助请求" onSubmit={event => { event.preventDefault(); if (canSubmit) submit.mutate(); }}>
      <fieldset disabled={submit.isPending}>
        <label>
          <span>关联任务编号 <small>选填</small></span>
          <input value={jobId} onChange={event => { setJobId(event.target.value); intent.current = null; submit.reset(); }} placeholder="从生成记录复制任务编号" maxLength={40} />
        </label>
        <label>
          <span>问题描述</span>
          <textarea value={issue} onChange={event => { setIssue(event.target.value); intent.current = null; submit.reset(); }} maxLength={4000} rows={4} placeholder="请说明遇到的问题和已尝试的操作。" required minLength={3} />
        </label>
      </fieldset>
      <div className={styles.formActions}>
        <button className={styles.submit} type="submit" disabled={!canSubmit}>
          {submit.isPending ? <LoaderCircle className="spin" size={16} aria-hidden="true" /> : <Send size={16} aria-hidden="true" />}
          {submit.isPending ? "正在提交…" : submit.isError ? "重新提交" : "提交帮助请求"}
        </button>
        <small className={styles.counter}>{issue.length} / 4000</small>
      </div>
      {submit.isError && <p className={styles.error} role="alert">{errorMessage(submit.error)}</p>}
      {submit.isSuccess && <p className={styles.success} role="status"><Check size={17} aria-hidden="true" />已提交，可在下方查看处理状态。</p>}
    </form>
    <section className={styles.history} aria-label="客服记录">
      <h3><ClipboardList size={19} aria-hidden="true" />客服记录</h3>
      {list.isPending ? <p className={styles.empty} role="status">正在读取客服记录…</p> : list.isError ? (
        <div className={styles.historyError}>
          <p role="alert">暂时无法读取客服记录。</p>
          <button type="button" onClick={() => void list.refetch()} disabled={list.isFetching}>重新读取</button>
        </div>
      ) : list.data.length === 0 ? <p className={styles.empty}>暂无客服记录</p> : null}
      {list.data?.map(item => <article key={item.id} className={styles.record}>
        <header>
          <h4>{item.welcome_bonus ? "新人客服赠分申请" : "帮助请求"}</h4>
          <span className={styles.recordStatus} data-status={item.status}>
            {item.welcome_bonus && item.status === "open" ? "待核实" : labels[item.status as keyof typeof labels] ?? item.status}
          </span>
        </header>
        <p>{item.issue}</p>
        {item.resolution && <p className={styles.resolution}><strong>处理结果</strong>{item.resolution}</p>}
        <footer>
          <small>记录编号 {item.id}</small>
          {item.job_id && <TaskWorkspaceLink href={`/jobs?jobId=${encodeURIComponent(item.job_id)}`}>查看关联任务<ArrowUpRight size={14} aria-hidden="true" /></TaskWorkspaceLink>}
        </footer>
      </article>)}
    </section>
  </section>;
}
