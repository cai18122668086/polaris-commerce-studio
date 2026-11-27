"use client";

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { useProjectSession } from "./use-project-session";
import type { AnalysisDoc, Candidate, Comparison, DraftDoc, DraftLine, Job, Platform, ReferenceDoc } from "./use-viral-writing";

/**
 * 全自动爆款文案：the user gives a platform, a keyword or links and their own
 * facts once; the server picks benchmarks, extracts, analyses and writes
 * several versions. This hook reads the run (an assistance task of kind
 * "auto_writing") and the documents it produced.
 */

export type AutoBenchmark = { platform_id: string; reason: string; extraction_id: string; reference_id: string; analysis_id?: string; analysis_failed?: boolean; no_speech_note?: boolean };
export type AutoDraft = { key: string; label: string; mode: "shadow" | "structure"; reference_id: string; task_id: string; document_id: string | null; error?: unknown };
export type AutoResult = {
  stage?: string; stage_label?: string; message?: string; started_at?: string;
  search_task_id?: string; mode?: "search" | "links"; candidate_count?: number;
  ranked?: { platform_id: string; reason: string }[];
  benchmarks?: AutoBenchmark[]; main_reference_id?: string; comparison?: Comparison;
  facts_document_id?: string; drafts?: AutoDraft[];
  request?: Partial<AutoStart>;
};
export type AutoRun = Job & { result: AutoResult; source_revision?: number };
export type AutoStart = { platform: Platform; query: string; facts_text: string; restricted_claims: ("price" | "net_quantity" | "health_effect")[]; forbidden_terms: string[] };
type Doc = ReferenceDoc | AnalysisDoc | DraftDoc | { id: string; kind: "facts"; created_at: string; reference_document_id: string | null; analysis_document_id: string | null; facts_document_id: string | null; assistance_task_id: string | null; body: unknown };
type ProjectSession = ReturnType<typeof useProjectSession>["session"];

const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const api = apiClient as any;
export const AUTO_STAGES: { key: string; label: string }[] = [
  { key: "search", label: "按点赞找爆款" },
  { key: "pick", label: "AI 挑选对标" },
  { key: "extract", label: "提取口播原文" },
  { key: "analyse", label: "拆解对标" },
  { key: "facts", label: "整理你的事实" },
  { key: "write", label: "写口播稿" },
];

export function useAutoWriting({ workspaceId, projectId, session }: { workspaceId: string; projectId: string; session: ProjectSession }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const opts = useCallback(() => ({ params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(15000), cache: "no-store" as const }), [workspaceId]);

  const reload = useCallback(async () => {
    if (!projectId) return;
    const query = { params: { path: { workspace_id: workspaceId }, query: { project_id: projectId } } };
    const [rows, page] = await Promise.all([
      api.GET(`${root}/assistance-tasks`, { ...opts(), ...query }).then(unwrapApiResponse) as Promise<Job[]>,
      api.GET(`${root}/writing-documents/page`, { ...opts(), ...query }).then(unwrapApiResponse) as Promise<{ items: Doc[]; linked_documents: Doc[] }>,
    ]);
    setJobs(rows.filter(row => row.project_id === projectId));
    setDocs([...new Map([...page.items, ...page.linked_documents].map(doc => [doc.id, doc])).values()]);
  }, [opts, workspaceId, projectId]);

  useEffect(() => {
    let live = true;
    void Promise.resolve().then(() => live ? reload() : undefined).catch(() => { if (live) setError("资料暂时读不到，请刷新重试。"); });
    return () => { live = false; };
  }, [reload]);

  const runs = jobs.filter((job): job is AutoRun => job.kind === "auto_writing");
  const run = runs[0];
  const running = run?.status === "running" || run?.status === "queued";
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => { void reload().catch(() => undefined); }, 4000);
    return () => clearInterval(timer);
  }, [running, reload]);

  const attempt = async (label: string, work: () => Promise<void>) => {
    setBusy(label); setError("");
    try { await work(); } catch (caught) { setError(caught instanceof Error && caught.message ? caught.message : "操作没有完成，请稍后重试。"); }
    finally { setBusy(""); }
  };
  const ensureSaved = async () => {
    const target = session.state.projectId;
    await session.save();
    if (session.state.projectId !== target) throw new Error("项目已切换，请重新操作。");
    return session.state.revision;
  };

  const start = (input: AutoStart) => attempt("start", async () => {
    const revision = await ensureSaved();
    const job = unwrapApiResponse(await api.POST(`${root}/auto-writing`, { ...opts(), body: { request_id: crypto.randomUUID(), project_id: projectId, expected_revision: revision, ...input } })) as Job;
    setJobs(rows => [job, ...rows.filter(row => row.id !== job.id)]);
  });
  const resume = (id: string) => attempt("resume", async () => {
    const job = unwrapApiResponse(await api.POST(`${root}/auto-writing/{run_id}/resume`, { ...opts(), params: { path: { workspace_id: workspaceId, run_id: id } } })) as Job;
    setJobs(rows => [job, ...rows.filter(row => row.id !== job.id)]);
  });
  const revise = (draft: DraftDoc, title: string, sentences: DraftLine[]) => attempt("revise", async () => {
    const doc = unwrapApiResponse(await api.POST(`${root}/writing-documents/{document_id}/revise`, { ...opts(), params: { path: { workspace_id: workspaceId, document_id: draft.id } }, body: { request_id: crypto.randomUUID(), title, sentences } })) as DraftDoc;
    setDocs(rows => [doc, ...rows]);
  });
  const adopt = (draft: DraftDoc, after: () => Promise<void>) => attempt("adopt", async () => {
    const revision = await ensureSaved();
    unwrapApiResponse(await api.POST(`${root}/writing-documents/{document_id}/apply`, { ...opts(), params: { path: { workspace_id: workspaceId, document_id: draft.id } }, body: { request_id: crypto.randomUUID(), expected_revision: revision } }));
    await after();
  });

  const doc = <T extends Doc>(id: string | null | undefined) => (id ? docs.find(d => d.id === id) : undefined) as T | undefined;
  /** The latest manual revision of a draft, if the user edited it. */
  const latest = (draft: DraftDoc | undefined) => {
    let current = draft;
    for (let depth = 0; current && depth < 20; depth += 1) {
      const parent: DraftDoc = current;
      const next = docs.filter((d): d is DraftDoc => d.kind === "draft" && (d as DraftDoc).body.revision?.parent_document_id === parent.id)
        .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
      if (!next) break;
      current = next;
    }
    return current;
  };
  const candidates = (): Map<string, Candidate> => {
    const page = jobs.find(job => job.id === run?.result.search_task_id) as (Job & { result: { items?: Candidate[] } }) | undefined;
    return new Map((page?.result.items || []).map(item => [item.platform_id, item]));
  };

  return { workspaceId, run, runs, running, busy, error, setError, reload, start, resume, revise, adopt, doc, latest, candidates };
}
