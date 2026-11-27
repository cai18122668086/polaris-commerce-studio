"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { useProjectSession } from "./use-project-session";

/**
 * 爆款文案 data flow for one project: search or paste links → confirm up to
 * three benchmarks → transcripts → expert teardown (+ comparison) → user facts
 * → shadow rewrite → adopt into the editor. Every finished step is saved on
 * the server automatically; nothing paid is ever resubmitted on its own.
 */

export type Platform = "douyin" | "xiaohongshu" | "bilibili";
export const PLATFORM_LABEL: Record<Platform, string> = { douyin: "抖音", xiaohongshu: "小红书", bilibili: "B站" };
export const MAX_PICKS = 3;

export type Candidate = {
  platform: Platform; platform_id: string; source_url: string; title: string; description: string; cover_url: string | null;
  author_name: string | null; author_follower_count: number | null; posted_at: string | null; duration_seconds: number | null;
  like_count: number | null; comment_count: number | null; collect_count: number | null; share_count: number | null; view_count?: number | null;
  collect_like_ratio: number | null; share_like_ratio: number | null; comment_like_ratio?: number | null;
};
type PageResult = { page: number; root_task_id: string; platform?: string; mode?: "search" | "links"; keyword: string; items?: Candidate[]; has_more?: boolean; captured_at?: string; skipped_count?: number; received_count?: number };
type Source = { search_task_id: string; platform?: string; platform_id: string; source_url: string; keyword: string; captured_at: string };
export type Job = {
  id: string; request_id: string; project_id: string; kind: string; status: string; stage: string; error_code: string | null;
  can_resume: boolean; benchmark_source?: Source | null; writing_document_saved?: boolean | null; reference_document_id?: string | null;
  result: Record<string, unknown> & { text?: string; validation_issue?: { kind: string; index: number; text: string } | null };
};
export type SearchJob = Job & { result: PageResult };

export type Sentence = { id: string; text: string };
export type Metrics = { platform: Platform; title: string; author_name: string | null; like_count: number | null; collect_count: number | null; comment_count: number | null; share_count: number | null; view_count: number | null; duration_seconds: number | null; readings: string[] };
export type Section = { id: string; first_sentence_id: string; last_sentence_id: string; function: string; explanation: string; technique?: string; emotion?: string };
export type Slot = { id: string; category: "identity" | "product" | "story"; sentence_id: string; source_quote: string; label: string; question: string };
export type Analysis = {
  schema_version: string; topic: string; hook_sentence_ids: string[]; sections: Section[];
  source_claims: { sentence_id: string; quote: string; category: string; handling: string; reason: string }[];
  reusable_structure: string[]; limitations: string[]; title_formula?: string;
  hook?: { sentence_ids: string[]; type: string; technique: string; why: string } | null;
  expressions?: { name: string; sentence_id: string; quote: string; effect: string; how_to_reuse: string }[];
  audience?: { who: string; pain_points: string[]; desire: string } | null;
  conversion?: { sentence_id: string; kind: string; note: string }[];
  replace_slots?: Slot[]; why_hot?: string[];
};
export type Comparison = { common_hooks: string[]; common_structure: string[]; common_expressions: string[]; differences: string[]; template_reuse: string; recommended_reference_document_id: string; recommendation_reason: string };
export type Fact = { id: string; category: "identity" | "product" | "story"; label: string; value: string | null; status: "user_declared" | "unknown"; source_note: string };
export type Facts = { facts: Fact[]; forbidden_terms: string[]; restricted_claims: ("price" | "net_quantity" | "health_effect")[] };
export type DraftLine = { text: string; fact_ids: string[]; reference_sentence_id?: string; rewritten_for?: string; analysis_section_id?: string };
export type Draft = { schema_version?: string; title: string; sentences: DraftLine[]; replacements: { category: string; original: string; replacement: string; fact_id: string }[]; missing_facts: string[]; warnings: string[] };
type Common = { id: string; created_at: string; reference_document_id: string | null; analysis_document_id: string | null; facts_document_id: string | null; assistance_task_id: string | null };
export type ReferenceDoc = Common & { kind: "reference"; body: { original_text: string; source_url: string; source_note: string; sentences: Sentence[]; source_metrics?: Metrics | null } };
export type AnalysisDoc = Common & { kind: "analysis"; body: Analysis };
export type FactsDoc = Common & { kind: "facts"; body: Facts };
export type DraftDoc = Common & { kind: "draft"; body: { text: string; draft: Draft; shape_check: { verdict: string; warnings?: string[]; failures?: string[] }; revision?: { parent_document_id: string } } };
type Doc = ReferenceDoc | AnalysisDoc | FactsDoc | DraftDoc;
export type DraftMode = "shadow" | "structure";

type ProjectSession = ReturnType<typeof useProjectSession>["session"];
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const RUNNING = ["queued", "running"];
// openapi-fetch path typing is exhaustive; the writing routes return loose dicts.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const api = apiClient as any;

function newest<T extends { created_at: string; id: string }>(rows: T[]) {
  return [...rows].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.id.localeCompare(a.id));
}

export function useViralWriting({ workspaceId, projectId, session }: { workspaceId: string; projectId: string; session: ProjectSession }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string>("");
  const [config, setConfig] = useState<{ search: boolean; extract: boolean; writing: boolean; generate: boolean }>();
  const runKey = `polaris-viral-run:${workspaceId}:${projectId}`;
  const [run, setRunState] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem(runKey) || "[]") as string[]; } catch { return []; }
  });
  const saving = useRef(new Set<string>());
  const opts = useCallback(() => ({ params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(15000), cache: "no-store" as const }), [workspaceId]);

  const setRun = (ids: string[]) => { setRunState(ids); try { localStorage.setItem(runKey, JSON.stringify(ids)); } catch {} };

  useEffect(() => {
    let live = true;
    void Promise.all([
      api.GET(`${root}/benchmark-config`, opts()).then(unwrapApiResponse).catch(() => null),
      api.GET(`${root}/writing-config`, opts()).then(unwrapApiResponse).catch(() => null),
    ]).then(([bench, writing]) => {
      if (!live) return;
      setConfig({ search: !!bench?.enabled, extract: !!bench?.can_extract, writing: !!writing?.enabled, generate: !!writing?.can_generate });
    });
    return () => { live = false; };
  }, [opts]);

  const reload = useCallback(async () => {
    if (!projectId) return;
    const [rows, page] = await Promise.all([
      api.GET(`${root}/assistance-tasks`, { ...opts(), params: { path: { workspace_id: workspaceId }, query: { project_id: projectId } } }).then(unwrapApiResponse) as Promise<Job[]>,
      api.GET(`${root}/writing-documents/page`, { ...opts(), params: { path: { workspace_id: workspaceId }, query: { project_id: projectId } } }).then(unwrapApiResponse) as Promise<{ items: Doc[]; linked_documents: Doc[] }>,
    ]);
    setJobs(rows.filter(job => job.project_id === projectId));
    setDocs(newest([...new Map([...page.items, ...page.linked_documents].map(doc => [doc.id, doc])).values()]));
  }, [opts, workspaceId, projectId]);

  useEffect(() => {
    let live = true;
    void Promise.resolve().then(() => live ? reload() : undefined).catch(() => { if (live) setError("资料暂时读不到，请刷新重试。"); });
    return () => { live = false; };
  }, [reload]);
  const running = jobs.some(job => RUNNING.includes(job.status));
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => { void reload().catch(() => undefined); }, 3000);
    return () => clearInterval(timer);
  }, [running, reload]);

  const attempt = async (label: string, work: () => Promise<void>) => {
    setBusy(label); setError("");
    try { await work(); } catch (caught) { setError(caught instanceof Error && caught.message ? caught.message : "操作没有完成，请稍后重试。"); }
    finally { setBusy(""); }
  };
  /** The project must exist on the server before anything is attached to it. */
  const ensureSaved = async () => {
    const target = session.state.projectId;
    await session.save();
    if (session.state.projectId !== target) throw new Error("项目已切换，请重新操作。");
    return session.state.revision;
  };

  // ---- 1. search / links ----------------------------------------------------
  const searches = jobs.filter((job): job is SearchJob => job.kind === "benchmark_search");
  const searchRoots = searches.filter(job => job.result.page === 1);
  const search = (platform: Platform, keyword: string, publishTime: string) => attempt("search", async () => {
    const revision = await ensureSaved();
    const job = unwrapApiResponse(await api.POST(`${root}/benchmark-searches`, { ...opts(), body: { request_id: crypto.randomUUID(), project_id: projectId, expected_revision: revision, platform, keyword, sort: "most_liked", publish_time: publishTime } })) as Job;
    setJobs(rows => [job, ...rows.filter(row => row.id !== job.id)]);
  });
  const pasteLinks = (text: string) => attempt("links", async () => {
    const revision = await ensureSaved();
    const job = unwrapApiResponse(await api.POST(`${root}/benchmark-links`, { ...opts(), body: { request_id: crypto.randomUUID(), project_id: projectId, expected_revision: revision, text } })) as Job;
    setJobs(rows => [job, ...rows.filter(row => row.id !== job.id)]);
  });
  const nextPage = (id: string) => attempt("next", async () => {
    const job = unwrapApiResponse(await api.POST(`${root}/benchmark-searches/{task_id}/next`, { ...opts(), params: { path: { workspace_id: workspaceId, task_id: id } } })) as Job;
    setJobs(rows => [job, ...rows.filter(row => row.id !== job.id)]);
  });
  const pagesOf = (rootId: string) => searches.filter(job => job.result.root_task_id === rootId).sort((a, b) => a.result.page - b.result.page);

  // ---- 2. confirm + transcripts ---------------------------------------------
  const extractions = jobs.filter(job => job.kind === "extract" && job.benchmark_source);
  const fallbackRun = extractions.slice(0, MAX_PICKS).map(job => job.id);
  const runIds = run.length ? run.filter(id => extractions.some(job => job.id === id)) : fallbackRun;
  const runJobs = runIds.map(id => extractions.find(job => job.id === id)).filter((job): job is Job => !!job);
  const confirm = (picks: { search_task_id: string; platform_id: string }[]) => attempt("confirm", async () => {
    const revision = await ensureSaved();
    const created = unwrapApiResponse(await api.POST(`${root}/benchmark-extractions`, { ...opts(), body: { project_id: projectId, expected_revision: revision, items: picks } })) as Job[];
    setRun(created.map(job => job.id));
    await reload();
  });
  const resume = (id: string) => attempt("resume", async () => {
    unwrapApiResponse(await api.POST(`${root}/assistance-tasks/{task_id}/resume`, { ...opts(), params: { path: { workspace_id: workspaceId, task_id: id } } }));
    await reload();
  });
  const refDocs = docs.filter((doc): doc is ReferenceDoc => doc.kind === "reference");
  const refOf = (job: Job) => refDocs.find(doc => doc.assistance_task_id === job.id);
  const runRefs = runJobs.map(refOf).filter((doc): doc is ReferenceDoc => !!doc);

  // Completed transcripts become reference documents without a click (free, idempotent).
  useEffect(() => {
    for (const job of runJobs) {
      if (job.status !== "completed" || refOf(job) || saving.current.has(job.id)) continue;
      saving.current.add(job.id);
      void api.POST(`${root}/writing-documents/reference/from-benchmark/{task_id}`, { ...opts(), params: { path: { workspace_id: workspaceId, task_id: job.id } } })
        .then(unwrapApiResponse).then(() => reload()).catch(() => { saving.current.delete(job.id); });
    }
  });

  // ---- 3. teardown ----------------------------------------------------------
  const analysisDocs = docs.filter((doc): doc is AnalysisDoc => doc.kind === "analysis");
  const analysisOf = (ref: ReferenceDoc | undefined) => ref && analysisDocs.find(doc => doc.reference_document_id === ref.id);
  const writingJobs = jobs.filter(job => ["ref_analysis", "fact_draft", "ref_compare"].includes(job.kind));
  const analysisJobOf = (ref: ReferenceDoc) => writingJobs.find(job => job.kind === "ref_analysis" && job.reference_document_id === ref.id);
  const submitTask = async (body: Record<string, unknown>) => {
    const revision = await ensureSaved();
    const job = unwrapApiResponse(await api.POST(`${root}/writing-tasks`, { ...opts(), body: { request_id: crypto.randomUUID(), project_id: projectId, expected_revision: revision, ...body } })) as Job;
    setJobs(rows => [job, ...rows.filter(row => row.id !== job.id)]);
    return job;
  };
  const analyse = (refs: ReferenceDoc[]) => attempt("analyse", async () => {
    for (const ref of refs) await submitTask({ kind: "ref_analysis", reference_document_id: ref.id });
  });
  const compareJobs = writingJobs.filter(job => job.kind === "ref_compare");
  const latestCompare = compareJobs[0];
  const comparison = latestCompare?.status === "completed" ? (latestCompare.result.comparison as Comparison | undefined) : undefined;
  const compare = (analyses: AnalysisDoc[], main: ReferenceDoc) => attempt("compare", async () => {
    await submitTask({ kind: "ref_compare", reference_document_id: main.id, analysis_document_ids: analyses.map(doc => doc.id) });
  });

  // Finished analyses and drafts are saved as documents without a click.
  useEffect(() => {
    for (const job of writingJobs) {
      if (job.kind === "ref_compare" || job.status !== "completed" || job.result.validation_error || job.writing_document_saved || docs.some(doc => doc.assistance_task_id === job.id) || saving.current.has(job.id)) continue;
      saving.current.add(job.id);
      void api.POST(`${root}/writing-documents/result`, { ...opts(), body: { request_id: job.id, task_id: job.id } })
        .then(unwrapApiResponse).then(() => reload()).catch(() => { saving.current.delete(job.id); });
    }
  });

  // ---- 4/5. facts → draft → adopt --------------------------------------------
  const factsDocs = docs.filter((doc): doc is FactsDoc => doc.kind === "facts");
  const draftDocs = docs.filter((doc): doc is DraftDoc => doc.kind === "draft");
  const draftsOf = (ref: ReferenceDoc | undefined) => ref ? draftDocs.filter(doc => doc.reference_document_id === ref.id) : [];
  const write = (ref: ReferenceDoc, analysis: AnalysisDoc, facts: Facts, mode: DraftMode) => attempt("write", async () => {
    await ensureSaved();
    const saved = unwrapApiResponse(await api.POST(`${root}/writing-documents/facts`, { ...opts(), body: { request_id: crypto.randomUUID(), project_id: projectId, body: facts } })) as FactsDoc;
    setDocs(rows => newest([saved, ...rows]));
    await submitTask({ kind: "fact_draft", reference_document_id: ref.id, analysis_document_id: analysis.id, facts_document_id: saved.id, draft_mode: mode, presentation: "unspecified" });
  });
  const revise = (draft: DraftDoc, title: string, sentences: DraftLine[]) => attempt("revise", async () => {
    const doc = unwrapApiResponse(await api.POST(`${root}/writing-documents/{document_id}/revise`, { ...opts(), params: { path: { workspace_id: workspaceId, document_id: draft.id } }, body: { request_id: crypto.randomUUID(), title, sentences } })) as DraftDoc;
    setDocs(rows => newest([doc, ...rows]));
  });
  const adopt = (draft: DraftDoc, after: () => Promise<void>) => attempt("adopt", async () => {
    const revision = await ensureSaved();
    unwrapApiResponse(await api.POST(`${root}/writing-documents/{document_id}/apply`, { ...opts(), params: { path: { workspace_id: workspaceId, document_id: draft.id } }, body: { request_id: crypto.randomUUID(), expected_revision: revision } }));
    await after();
  });

  const latestTask = (kind: string) => writingJobs.find(job => job.kind === kind);
  return {
    config, error, setError, busy, running, reload,
    searchRoots, pagesOf, search, pasteLinks, nextPage,
    runJobs, runRefs, refOf, confirm, resume, extractions,
    analysisOf, analysisJobOf, analyse, analysisJobs: writingJobs.filter(job => job.kind === "ref_analysis"),
    comparison, latestCompare, compare,
    factsDocs, draftsOf, write, revise, adopt, latestTask,
  };
}
