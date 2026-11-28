"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Download, Film, History, RotateCcw, Shuffle, Upload, X } from "lucide-react";
import { ApiError } from "@/lib/api/api-error";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import { mediaUrl } from "@/lib/api/base-url";
import { uploadWithProgress } from "@/lib/api/upload";
import type { components } from "@/lib/api/generated/openapi";
import type { GenerationJob } from "@/features/video-studio/library";
import { FREE_TRIAL_TEXT, isPriced, whenPriced, type CostNote } from "@/features/video-studio/credit-notes";
import { editingHref, finishHref } from "@/features/video-studio/flow-params";
import { editingMessage } from "@/features/video-studio/editing-presentation";
import { templateAppearance } from "@/features/video-studio/template-appearance";
import {
  PROGRESS_LABELS, SOURCE_LABEL, batchFinished, batchPlan, candidateKey, durationLabel, finishAction, generationSummary, itemStatus, templateNeeds,
  type EditingCandidate,
} from "@/features/video-studio/editing-batch";
import { DEFAULT_SUPPLEMENT, supplementForWorkItem, supplementSummary, type SupplementMaterialsValue, type SupplementWorkItem } from "@/features/video-studio/supplement-materials";
import { SupplementMaterialsPanel } from "./supplement-materials-panel";
import { EditingTemplateGallery, type TemplateCard } from "./editing-template-gallery";
import styles from "./editing-batch-flow.module.css";

type Batch = components["schemas"]["WorkBatchResponse"];
type BatchView = components["schemas"]["EditingBatchResponse"];
type SourceRow = components["schemas"]["EditingSourceView"];
type SourceTab = "batch" | "library" | "upload";
type Upload = { name: string; percent: number; error?: string; key?: string };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const opts = (workspaceId: string, ms = 12000) => ({ params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(ms) });
const STEP_TITLES = ["选视频", "选模板", "补充素材", "生成"] as const;

/** 剪辑页：① 选视频 → ② 选模板 → ③ 补充素材 → ④ 生成，批量出片，刷新可恢复。 */
export function EditingBatchFlow({ workspaceId, batchId, jobs, uploadProjectId, ensureUploadProject, cost }: {
  workspaceId: string;
  /** URL 上的 ?batch=（口播批次或之前的剪辑批次） */
  batchId: string | null;
  jobs: GenerationJob[];
  /** 上传视频存放的项目；没有时先保存一个 */
  uploadProjectId: string;
  ensureUploadProject: () => Promise<string>;
  /** 每条：编排 + 出片的积分 */
  cost?: CostNote;
}) {
  const router = useRouter();
  const [tab, setTab] = useState<SourceTab>(batchId ? "batch" : "library");
  const [batch, setBatch] = useState<Batch>();
  const [view, setView] = useState<BatchView>();
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [talkingBatches, setTalkingBatches] = useState<Batch[]>([]);
  const [queue, setQueue] = useState<components["schemas"]["EditingQueueView"]>();
  /** 视频库里选中的口播结果所属批次（与 URL 上的批次不同时单独加载） */
  const [planBatch, setPlanBatch] = useState<Batch>();
  const [selected, setSelected] = useState<EditingCandidate[]>([]);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [templates, setTemplates] = useState<TemplateCard[]>([]);
  const [template, setTemplate] = useState<TemplateCard>();
  const [perItem, setPerItem] = useState(false);
  const [itemTemplates, setItemTemplates] = useState<Record<string, string>>({});
  const [supplement, setSupplement] = useState<SupplementMaterialsValue>(DEFAULT_SUPPLEMENT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  /** B5 换模板重剪：正在确认的对象（一条或整批）和选的新模板 */
  const [redoTarget, setRedoTarget] = useState<{ itemId: string } | { batch: true } | null>(null);
  const [redoTemplate, setRedoTemplate] = useState("");
  const redoRequest = useRef<{ key: string; id: string }>(undefined);
  const createRequest = useRef<{ key: string; id: string }>(undefined);
  const submitRequest = useRef<{ key: string; id: string }>(undefined);

  // --- data -------------------------------------------------------------------------------
  useEffect(() => {
    const controller = new AbortController();
    void apiClient.GET(`${root}/editing-template-catalog`, { params: { path: { workspace_id: workspaceId } }, signal: controller.signal })
      .then(result => setTemplates(unwrapApiResponse(result))).catch(() => undefined);
    void apiClient.GET(`${root}/editing-sources`, { params: { path: { workspace_id: workspaceId }, query: { limit: 50 } }, signal: controller.signal })
      .then(result => setSources(unwrapApiResponse(result))).catch(() => undefined);
    void apiClient.GET(`${root}/work-batches`, { params: { path: { workspace_id: workspaceId }, query: { source: "talking", limit: 20 } }, signal: controller.signal })
      .then(result => setTalkingBatches(unwrapApiResponse(result))).catch(() => undefined);
    return () => controller.abort();
  }, [workspaceId]);

  const loadBatch = useCallback(async (id: string) => {
    const result = unwrapApiResponse(await apiClient.GET(`${root}/work-batches/{batch_id}/editing`, { params: { path: { workspace_id: workspaceId, batch_id: id } }, signal: AbortSignal.timeout(15000) }));
    setView(result);
    setBatch(result.batch);
    return result;
  }, [workspaceId]);

  useEffect(() => {
    if (!batchId) return;
    let live = true;
    // Deferred to a microtask: the load sets state after the effect has run.
    void Promise.resolve().then(() => (live ? loadBatch(batchId) : undefined)).catch(caught => { if (live) setError(editingMessage(caught, "暂时读不到这个批次，请刷新重试。")); });
    return () => { live = false; };
  }, [batchId, loadBatch]);

  const started = !!view?.editing.some(row => row.phase);
  // Before submitting: how busy the shared editing worker is right now (every user).
  useEffect(() => {
    if (started) return;
    let live = true;
    const read = () => void apiClient.GET(`${root}/editing-queue`, { params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(10000) })
      .then(result => { if (live) setQueue(unwrapApiResponse(result)); }).catch(() => undefined);
    const first = window.setTimeout(read, 0);
    const timer = window.setInterval(read, 30000);
    return () => { live = false; window.clearTimeout(first); window.clearInterval(timer); };
  }, [started, workspaceId]);
  const progress = batchFinished(view?.editing ?? []);
  // Poll while anything is waiting or running; the server also keeps going with the page closed.
  useEffect(() => {
    if (!batchId || !started || progress.active === 0) return;
    const timer = window.setInterval(() => { void loadBatch(batchId).catch(() => undefined); }, 5000);
    return () => window.clearInterval(timer);
  }, [batchId, started, progress.active, loadBatch]);

  // --- candidates ---------------------------------------------------------------------------
  const jobsById = useMemo(() => new Map(jobs.map(job => [job.id, job])), [jobs]);
  const batchCandidates: EditingCandidate[] = useMemo(() => (batch?.items ?? []).map(item => {
    const ref = item.source_video_ref;
    const job = ref ? jobsById.get(ref.id) : undefined;
    const source = ref ? sources.find(row => row.id === ref.id) : undefined;
    const ready = !!ref?.id && (item.stage !== "talking" || item.status === "succeeded");
    const title = item.publish_title || item.script_text.slice(0, 18) || `视频 ${item.position + 1}`;
    return {
      key: candidateKey("talking", item.id), kind: "talking", refId: ref?.id ?? item.id, itemId: item.id, batchId: item.batch_id,
      projectId: job?.project_id ?? source?.project_id ?? null, title,
      videoUrl: (job?.video_url ? mediaUrl(job.video_url) : source ? mediaUrl(source.video_url) : null) ?? null,
      durationMs: job?.audio_duration_seconds ? job.audio_duration_seconds * 1000 : source?.duration_ms, createdAt: item.created_at, ready,
      note: ready ? undefined : item.status === "failed" ? "口播没有生成成功" : "口播还在生成",
    };
  }), [batch, jobsById, sources]);
  // A talking result that belongs to a talking batch is that batch's work item (its title,
  // body and script live there): pick it as the item, never as a copy.
  const talkingItemByJob = useMemo(() => {
    const map = new Map<string, { item: Batch["items"][number]; batch: Batch }>();
    for (const row of talkingBatches) for (const item of row.items) {
      const job = item.generation_task_id ?? (item.source_video_ref?.kind === "talking" ? item.source_video_ref.id : null);
      if (job) map.set(job, { item, batch: row });
    }
    return map;
  }, [talkingBatches]);
  const libraryCandidates: EditingCandidate[] = useMemo(() => [
    ...jobs.filter(job => job.kind === "lipsync" && job.status === "completed" && job.video_url).map(job => {
      const owner = talkingItemByJob.get(job.id);
      const base = { projectId: job.project_id, videoUrl: mediaUrl(job.video_url) ?? null, durationMs: job.audio_duration_seconds ? job.audio_duration_seconds * 1000 : null, createdAt: job.created_at, ready: true };
      return owner
        ? { ...base, key: candidateKey("talking", owner.item.id), kind: "talking" as const, refId: job.id, itemId: owner.item.id, batchId: owner.batch.id, title: owner.item.publish_title || job.snapshot?.draft.name || "口播视频", note: `口播批次 ${new Date(owner.batch.created_at).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })}` }
        : { ...base, key: candidateKey("library", job.id), kind: "library" as const, refId: job.id, title: job.snapshot?.draft.name || "口播视频", note: "我的口播" };
    }),
    ...sources.map(row => ({
      key: candidateKey("library", row.id), kind: "library" as const, refId: row.id, projectId: row.project_id,
      title: row.file_name || "上传的视频", videoUrl: mediaUrl(row.video_url) ?? null, durationMs: row.duration_ms, createdAt: String(row.created_at), ready: true, note: "已上传",
    })),
  ], [jobs, sources, talkingItemByJob]);

  // Coming from 口播: every finished video of the batch is selected automatically.
  const autoPicked = useRef("");
  useEffect(() => {
    if (!batch || autoPicked.current === batch.id || started) return;
    autoPicked.current = batch.id;
    setSelected(batchCandidates.filter(row => row.ready));
  }, [batch, batchCandidates, started]);

  const toggle = (row: EditingCandidate) => {
    if (!row.ready || started) return;
    const adding = !selected.some(item => item.key === row.key);
    setSelected(current => current.some(item => item.key === row.key) ? current.filter(item => item.key !== row.key) : [...current, row]);
    // A talking result from an older talking batch (not in the recent list) is still that
    // batch's item: say so right away and go there, instead of failing at「开始剪辑」.
    if (adding && row.kind === "library" && jobsById.has(row.refId)) {
      void apiClient.GET(`${root}/editing-source-owners`, { params: { path: { workspace_id: workspaceId }, query: { generation_ids: row.refId } }, signal: AbortSignal.timeout(10000) })
        .then(result => {
          const owner = unwrapApiResponse(result)[0];
          if (!owner) return;
          setSelected(current => current.filter(item => item.key !== row.key));
          setNotice("这条口播属于一个口播批次，已为你打开那一批（标题和正文会一起带上）。");
          router.push(editingHref(owner.batch_id));
        }).catch(() => undefined);
    }
  };

  // Takes a plain array: the input's FileList is live and is emptied when the input is reset.
  const uploadFiles = async (list: File[]) => {
    if (!list.length) return;
    setError("");
    let projectId = uploadProjectId;
    try { projectId = await ensureUploadProject(); } catch (caught) { setError(editingMessage(caught, "项目暂未保存，请稍后再上传。")); return; }
    setUploads(current => [...current, ...list.map(file => ({ name: file.name, percent: 0 }))]);
    for (const file of list) {
      const update = (patch: Partial<Upload>) => setUploads(current => current.map(row => row.name === file.name && !row.key ? { ...row, ...patch } : row));
      try {
        const form = new FormData();
        form.append("project_id", projectId);
        form.append("request_id", crypto.randomUUID());
        form.append("file", file);
        const uploaded = unwrapApiResponse(await apiClient.POST(`${root}/editing-sources`, {
          ...opts(workspaceId, 600000), body: {} as never, bodySerializer: () => form,
          fetch: uploadWithProgress(form, value => update({ percent: value.total ? Math.round((value.loaded / value.total) * 100) : 0 })),
        }));
        const row: EditingCandidate = { key: candidateKey("upload", uploaded.id), kind: "upload", refId: uploaded.id, projectId, title: file.name.replace(/\.[^.]+$/, ""), videoUrl: URL.createObjectURL(file), ready: true, note: "刚上传" };
        update({ percent: 100, key: row.key });
        setSelected(current => current.some(item => item.key === row.key) ? current : [...current, row]);
      } catch (caught) {
        update({ error: editingMessage(caught, "上传没有成功，请检查文件后重试。") });
      }
    }
    void apiClient.GET(`${root}/editing-sources`, { params: { path: { workspace_id: workspaceId }, query: { limit: 50 } } })
      .then(result => setSources(unwrapApiResponse(result))).catch(() => undefined);
  };

  // --- ① -> batch ---------------------------------------------------------------------------
  const plan = batchPlan(selected);
  const ensureBatch = async (): Promise<{ id: string; itemIds: string[] } | undefined> => {
    if (plan.kind === "empty") { setError("请先选择要剪的视频。"); return undefined; }
    if (plan.kind === "conflict") { setError(plan.reason); return undefined; }
    if (plan.kind === "existing") return { id: plan.batchId, itemIds: plan.itemIds };
    const key = JSON.stringify(plan.items);
    if (createRequest.current?.key !== key) createRequest.current = { key, id: crypto.randomUUID() };
    const created = unwrapApiResponse(await apiClient.POST(`${root}/work-batches`, {
      ...opts(workspaceId, 20000), body: { request_id: createRequest.current.id, source: "editing_upload", items: plan.items },
    }));
    setBatch(created);
    router.replace(editingHref(created.id));
    return { id: created.id, itemIds: created.item_ids };
  };

  const planBatchId = plan.kind === "existing" && plan.batchId !== batch?.id ? plan.batchId : null;
  useEffect(() => {
    if (!planBatchId) return;
    let live = true;
    void Promise.resolve().then(async () => {
      const row = unwrapApiResponse(await apiClient.GET(`${root}/work-batches/{batch_id}`, { params: { path: { workspace_id: workspaceId, batch_id: planBatchId } }, signal: AbortSignal.timeout(15000) }));
      if (live) setPlanBatch(row);
    }).catch(() => undefined);
    return () => { live = false; };
  }, [planBatchId, workspaceId]);
  const itemsBatch = planBatchId && planBatch?.id === planBatchId ? planBatch : batch;

  // --- ③ work items for the supplement panel ------------------------------------------------
  const chosenIds = useMemo(() => {
    if (plan.kind === "existing") return plan.itemIds;
    if (batch && batch.source === "editing_upload") return batch.item_ids;
    return [];
  }, [plan, batch]);
  const conflict = plan.kind === "conflict" ? plan.reason : "";
  // Per-item templates are keyed by the candidate; batch items map back to it.
  const keyOfItem = useCallback((itemId: string) => {
    const item = (itemsBatch ?? batch)?.items.find(entry => entry.id === itemId);
    const match = selected.find(row => row.itemId === itemId) ?? selected.find(row => !!item?.source_video_ref && row.refId === item.source_video_ref.id);
    return match?.key ?? candidateKey("talking", itemId);
  }, [itemsBatch, batch, selected]);
  const templateOf = useCallback((itemId: string) => templates.find(card => card.id === (perItem ? itemTemplates[keyOfItem(itemId)] : undefined)) ?? template, [templates, perItem, itemTemplates, keyOfItem, template]);
  const workItems: SupplementWorkItem[] = useMemo(() => (itemsBatch?.items ?? []).filter(item => chosenIds.includes(item.id)).map(item => {
    const card = templateOf(item.id);
    const candidate = [...batchCandidates, ...selected].find(row => row.itemId === item.id || row.refId === item.source_video_ref?.id);
    return {
      id: item.id, project_id: candidate?.projectId ?? uploadProjectId, title: item.publish_title || candidate?.title || `视频 ${item.position + 1}`,
      script_text: item.script_text, template_id: card?.id ?? null,
      supports_images: !!card && ((card.capabilities ?? []).includes("images") || card.material_mode === "images"),
      supports_mg: card?.engine === "bihuo-full-suite",
    };
  }), [itemsBatch, chosenIds, templateOf, batchCandidates, selected, uploadProjectId]);

  // --- ④ submit -----------------------------------------------------------------------------
  const count = plan.kind === "existing" ? plan.itemIds.length : plan.kind === "create" ? plan.items.length : 0;
  const summary = generationSummary(selected.filter(row => row.ready).slice(0, count).map(row => row.durationMs), cost?.credits, queue);
  const missingTemplate = !template;
  const generate = async () => {
    setBusy(true); setError(""); setNotice("");
    try {
      const target = await ensureBatch();
      if (!target || !template) return;
      const usableKeys = selected.filter(row => row.ready).map(row => row.key);
      const items = Object.fromEntries(target.itemIds.map((id, index) => {
        const own = supplementForWorkItem(supplement, id);
        const key = plan.kind === "existing" ? keyOfItem(id) : usableKeys[index];
        const chosen = perItem && key ? itemTemplates[key] : undefined;
        return [id, { ...(chosen ? { template_id: chosen } : {}), material_ids: own.material_ids, ...(own.supplement ? { supplement: own.supplement } : {}) }];
      }));
      const body = { template_id: template.id, music: "template" as const, item_ids: target.itemIds, items };
      const key = JSON.stringify([target.id, body]);
      if (submitRequest.current?.key !== key) submitRequest.current = { key, id: crypto.randomUUID() };
      const result = unwrapApiResponse(await apiClient.POST(`${root}/work-batches/{batch_id}/editing`, {
        params: { path: { workspace_id: workspaceId, batch_id: target.id } }, signal: AbortSignal.timeout(30000),
        body: { request_id: submitRequest.current.id, ...body },
      }));
      setView(result); setBatch(result.batch);
      if (target.id !== batchId) router.replace(editingHref(target.id));
      if (result.notice) setNotice(result.notice);
      requestAnimationFrame(() => document.getElementById("editing-batch-results")?.scrollIntoView({ block: "start" }));
    } catch (caught) {
      const owner = caught instanceof ApiError && caught.code === "VIDEO_WORK_SOURCE_HAS_ITEM" ? (caught.details as { batch_id?: string } | undefined)?.batch_id : undefined;
      if (owner) { router.replace(editingHref(owner)); return; }
      setError(editingMessage(caught, "提交还在确认中，不会重复扣费；稍后刷新查看。"));
    } finally { setBusy(false); }
  };
  const redoItems = (view?.editing ?? []).filter(row => row.phase === "done" || row.phase === "failed");
  const redoCount = redoTarget ? ("batch" in redoTarget ? redoItems.length : 1) : 0;
  const openRedo = (target: { itemId: string } | { batch: true }, current?: string | null) => {
    setRedoTarget(target);
    // Default to a different template than the one used: the point is to change it.
    setRedoTemplate(templates.find(card => card.id !== current && !card.id.startsWith("chenxi"))?.id ?? "");
  };
  const redo = async () => {
    if (!redoTarget || !redoTemplate || !batch) return;
    setBusy(true); setError("");
    // One request id per (target, template): a double click or a lost response never builds a second round.
    const key = JSON.stringify([redoTarget, redoTemplate]);
    if (redoRequest.current?.key !== key) redoRequest.current = { key, id: crypto.randomUUID() };
    const body = { request_id: redoRequest.current.id, template_id: redoTemplate, music: "template" as const };
    try {
      const result = unwrapApiResponse("batch" in redoTarget
        ? await apiClient.POST(`${root}/work-batches/{batch_id}/editing-redo`, { params: { path: { workspace_id: workspaceId, batch_id: batch.id } }, signal: AbortSignal.timeout(30000), body })
        : await apiClient.POST(`${root}/work-items/{item_id}/editing-redo`, { params: { path: { workspace_id: workspaceId, item_id: redoTarget.itemId } }, signal: AbortSignal.timeout(20000), body }));
      setView(result); setBatch(result.batch); setRedoTarget(null);
      setNotice("已开始重剪，旧成片保留在「上一版」里。剪完后到成片页可以重新生成封面。");
    } catch (caught) { setError(editingMessage(caught, "重剪还在确认中，不会重复扣费；稍后刷新查看。")); }
    finally { setBusy(false); }
  };
  const retry = async (itemId: string) => {
    setBusy(true); setError("");
    try {
      const result = unwrapApiResponse(await apiClient.POST(`${root}/work-items/{item_id}/editing-retry`, { params: { path: { workspace_id: workspaceId, item_id: itemId } }, signal: AbortSignal.timeout(20000) }));
      setView(result); setBatch(result.batch);
    } catch (caught) { setError(editingMessage(caught, "重试还在确认中，请稍后刷新。")); }
    finally { setBusy(false); }
  };

  // --- render -------------------------------------------------------------------------------
  const stepState = (index: number) => {
    const done = [selected.length > 0 || started, !!template || started, started, progress.finished];
    const current = done.findIndex(value => !value);
    return done[index] ? "done" : index === current ? "current" : "todo";
  };
  const shown = tab === "batch" ? batchCandidates : tab === "library" ? libraryCandidates : uploads.map(row => selected.find(item => item.key === row.key)).filter((row): row is EditingCandidate => !!row);
  const items = batch?.items ?? [];
  const nameOf = (id?: string | null) => { const card = templates.find(row => row.id === id); return card ? templateAppearance(card).name : ""; };

  return <section className={styles.flow} aria-label="批量剪辑">
    <ol className={styles.steps} aria-label="剪辑步骤">{STEP_TITLES.map((title, index) => <li key={title} data-state={stepState(index)}>
      <a href={`#editing-step-${index + 1}`} aria-current={stepState(index) === "current" ? "step" : undefined}>{index + 1} · {title}{stepState(index) === "done" && <Check size={12} aria-label="已完成" />}</a>
    </li>)}</ol>

    {!started && <>
      <section id="editing-step-1" className={styles.step}>
        <header><h2>选视频</h2><p>选好的每条视频都会单独剪成一条成片，可以一次剪多条。</p></header>
        <div className={styles.tabs} role="tablist" aria-label="视频来源">
          {(["batch", "library", "upload"] as SourceTab[]).map(key => <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>
            {key === "batch" ? (batch?.source === "editing_upload" ? "本批视频" : "来自口播批次") : key === "library" ? "视频库" : "上传"}
          </button>)}
        </div>
        {tab === "batch" && !batch && (talkingBatches.length ? <ul className={styles.batches}>{talkingBatches.slice(0, 8).map(row => {
          const done = row.items.filter(item => item.status === "succeeded" || item.stage !== "talking").length;
          return <li key={row.id}><a href={editingHref(row.id)}><b>{row.items[0]?.publish_title || row.items[0]?.script_text.slice(0, 16) || "口播批次"}{row.items.length > 1 ? ` 等 ${row.items.length} 条` : ""}</b><small>{new Date(row.created_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })} · 已生成 {done}/{row.items.length}</small></a></li>;
        })}</ul> : <p className={styles.empty}>还没有口播批次。在口播页生成后点「去剪辑」，这一批会自动带过来。</p>)}
        {tab === "upload" && <label className={styles.drop}><Upload size={20} /><b>选择视频文件</b><small>可以一次选多个；建议竖屏 9:16 的口播视频，MP4 / MOV</small>
          <input type="file" multiple accept="video/mp4,video/quicktime,video/webm" aria-label="上传视频" disabled={busy} onChange={event => { const files = [...(event.target.files ?? [])]; event.target.value = ""; void uploadFiles(files); }} /></label>}
        {tab === "upload" && uploads.length > 0 && <ul className={styles.uploads}>{uploads.map((row, index) => <li key={`${row.name}-${index}`}>
          <span>{row.name}</span>{row.error ? <em>{row.error}</em> : <><progress max={100} value={row.percent} aria-label={`${row.name} 上传进度`} /><small>{row.percent >= 100 ? "已上传" : `${row.percent}%`}</small></>}
        </li>)}</ul>}
        {tab !== "upload" && <div className={styles.grid}>{shown.map(row => {
          const active = selected.some(item => item.key === row.key);
          return <button key={row.key} type="button" className={styles.card} data-selected={active} data-disabled={!row.ready} aria-pressed={active} disabled={!row.ready} onClick={() => toggle(row)}>
            <span className={styles.thumb}>{row.videoUrl ? <video src={row.videoUrl} preload="metadata" muted playsInline /> : <Film size={22} />}{active && <i><Check size={13} /></i>}</span>
            <b>{row.title}</b><small>{[row.note, durationLabel(row.durationMs)].filter(Boolean).join(" · ")}</small>
          </button>;
        })}{!shown.length && tab === "library" && <p className={styles.empty}>视频库还是空的，可以去口播页生成，或直接上传。</p>}</div>}
        {selected.length > 0 && <div className={styles.selected}><b>已选 {selected.length} 条</b><ul>{selected.map(row => <li key={row.key}>
          <span className={styles.mini}>{row.videoUrl ? <video src={row.videoUrl} preload="metadata" muted playsInline /> : <Film size={14} />}</span>
          <span><b>{row.title}</b><small>{SOURCE_LABEL[row.kind]}{durationLabel(row.durationMs) && ` · ${durationLabel(row.durationMs)}`}</small></span>
          <button type="button" aria-label={`移除 ${row.title}`} onClick={() => toggle(row)}><X size={14} /></button>
        </li>)}</ul></div>}
      </section>

      <section id="editing-step-2" className={styles.step} data-locked={!selected.length}>
        <header><h2>选模板</h2><p>默认所有视频用同一个模板，也可以每条单独选。</p></header>
        <div className={styles.gallery}><EditingTemplateGallery workspaceId={workspaceId} projectId="" selected={template?.id || ""} onSelect={setTemplate} onRestore={setTemplate} sampleRevision="" /></div>
        {template && <p className={styles.needs}>{templateNeeds(template)}</p>}
        {selected.length > 1 && <label className={styles.switch}><input type="checkbox" checked={perItem} onChange={event => setPerItem(event.target.checked)} />每条单独选模板</label>}
        {perItem && <ul className={styles.perItem}>{selected.map((row, index) => {
          return <li key={row.key}><span>{row.title || `视频 ${index + 1}`}</span><select aria-label={`${row.title} 的模板`} value={itemTemplates[row.key] ?? template?.id ?? ""} onChange={event => setItemTemplates(current => ({ ...current, [row.key]: event.target.value }))}>
            {templates.filter(card => !card.id.startsWith("chenxi")).map(card => <option key={card.id} value={card.id}>{templateAppearance(card).collection} · {templateAppearance(card).name}</option>)}
          </select></li>;
        })}</ul>}
      </section>

      <section id="editing-step-3" className={styles.step} data-locked={!template}>
        <header><h2>补充素材 <small>可选</small></h2><p>默认不加素材，直接按口播剪。需要配图或动效时再打开。</p></header>
        {workItems.length ? <SupplementMaterialsPanel workspaceId={workspaceId} value={supplement} onChange={setSupplement} workItems={workItems} />
          : <p className={styles.empty}>{selected.length ? "进入下一步时会为每条视频准备素材位置；也可以不加素材直接生成。" : "先选视频和模板。"}</p>}
        {!workItems.length && plan.kind === "create" && template && <button type="button" className={styles.secondary} disabled={busy} onClick={() => { setBusy(true); void ensureBatch().catch(caught => setError(editingMessage(caught, "暂时无法准备素材位置，请重试。"))).finally(() => setBusy(false)); }}>为每条视频添加素材</button>}
      </section>

      <section id="editing-step-4" className={styles.step} data-locked={!template || !count}>
        <header><h2>生成</h2></header>
        <dl className={styles.summary}>
          <div><dt>视频</dt><dd>{count} 条</dd></div>
          <div><dt>模板</dt><dd>{perItem ? "每条单独选" : template ? templateAppearance(template).name : "未选"}</dd></div>
          <div><dt>素材</dt><dd>{supplementSummary(supplement)}</dd></div>
          <div><dt>积分</dt><dd>{count ? summary.credits ?? FREE_TRIAL_TEXT : "—"}</dd></div>
          <div><dt>耗时</dt><dd>{count ? summary.time : "—"}</dd></div>
        </dl>
        <p className={styles.fine}>预览确认已合并到生成里：每条剪完自动导出高清，不满意可以在结果里「精修这一条」或「换模板重剪」。{whenPriced(cost?.credits, "重复点击不会重复扣费。")}</p>
        {cost?.insufficient && <p role="alert" className={styles.error}>积分不足，充值后再生成。</p>}
        <button type="button" className={styles.primary} disabled={busy || !count || missingTemplate || supplement.pending > 0 || !!cost?.insufficient} onClick={() => void generate()}>
          {busy ? "正在提交…" : supplement.pending > 0 ? "素材还在准备…" : count ? `开始剪辑 ${count} 条` : "先选视频"}
        </button>
      </section>
    </>}

    {!started && conflict && <p role="alert" className={styles.error}>{conflict}</p>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {notice && <p role="status" className={styles.fine}>{notice}</p>}

    {started && view && <section id="editing-batch-results" className={styles.step} aria-label="剪辑结果">
      <header className={styles.resultsHead}><div><h2>剪辑结果</h2><p>{progress.finished ? `完成 ${progress.done} 条${progress.failed ? `，${progress.failed} 条未完成可重试` : ""}` : `进行中 ${progress.active} 条 · 已完成 ${progress.done} 条。剪辑服务全站按顺序处理，每人最多同时处理 ${view.parallel_limit} 条，其余自动排队；可以关掉页面，回来刷新即可。`}</p></div>
        {redoItems.length > 1 && !redoTarget && <button type="button" className={styles.secondary} disabled={busy} onClick={() => openRedo({ batch: true }, redoItems[0]?.template_id)}><Shuffle size={13} />整批换模板重剪</button>}
      </header>
      {redoTarget && <div className={styles.redo} role="dialog" aria-label="换模板重剪">
        <b>{"batch" in redoTarget ? `整批换模板重剪（${redoCount} 条）` : "这一条换模板重剪"}</b>
        <label><span>新模板</span><select aria-label="重剪用的模板" value={redoTemplate} onChange={event => setRedoTemplate(event.target.value)}>
          {templates.filter(card => !card.id.startsWith("chenxi")).map(card => <option key={card.id} value={card.id}>{templateAppearance(card).collection} · {templateAppearance(card).name}</option>)}
        </select></label>
        <p className={styles.fine}>会用同一条口播按新模板重新编排、生成一次（口播识别结果直接复用）。{isPriced(cost?.credits) ? `每条 ${cost?.credits} 积分，共 ${(cost?.credits ?? 0) * redoCount} 积分。` : `${FREE_TRIAL_TEXT}。`}旧成片会保留在「上一版」里，可以随时查看、下载；剪完后成片页会提示重新生成封面。</p>
        <div className={styles.redoActions}><button type="button" className={styles.primary} disabled={busy || !redoTemplate} onClick={() => void redo()}>{busy ? "正在提交…" : `确认重剪${redoCount > 1 ? ` ${redoCount} 条` : ""}`}</button><button type="button" className={styles.secondary} disabled={busy} onClick={() => setRedoTarget(null)}>取消</button></div>
      </div>}
      <div className={styles.results}>{view.editing.map(row => {
        const item = items.find(entry => entry.id === row.item_id);
        const status = itemStatus(row);
        return <article key={row.item_id} className={styles.result} data-tone={status.tone}>
          <div className={styles.player}>{row.final_url ? <video src={mediaUrl(row.final_url)} poster={mediaUrl(row.poster_url ?? undefined)} controls playsInline preload="metadata" aria-label={`${item?.publish_title || "成片"} 预览`} /> : <span><Film size={22} /></span>}</div>
          <div className={styles.resultBody}>
            <b>{item?.publish_title || `视频 ${row.position + 1}`}</b>
            <small>{nameOf(row.template_id)}{row.duration_ms ? ` · ${durationLabel(row.duration_ms)}` : ""}</small>
            <p className={styles.state}>{status.label}</p>
            {row.phase && row.phase !== "done" && row.phase !== "failed" && <ol className={styles.progress} aria-label="进度">{PROGRESS_LABELS.map((label, index) => <li key={label} data-done={index < status.done} data-current={index === status.done && status.tone === "work"}>{label}</li>)}</ol>}
            {status.detail && <p className={status.tone === "bad" ? styles.error : styles.fine}>{status.detail}</p>}
            <div className={styles.actions}>
              {row.final_url && <a href={mediaUrl(row.final_url)} download><Download size={13} />下载</a>}
              {row.can_retry && <button type="button" disabled={busy} onClick={() => void retry(row.item_id)}><RotateCcw size={13} />重试这一条</button>}
              {(row.phase === "done" || row.phase === "failed") && <button type="button" disabled={busy} onClick={() => openRedo({ itemId: row.item_id }, row.template_id)}><Shuffle size={13} />换模板重剪</button>}
              {row.render_task_id && row.project_id && (row.phase === "done" || row.phase === "failed") && <a href={`/video-studio/editing?project=${encodeURIComponent(row.project_id)}&mode=refine&item=${encodeURIComponent(row.item_id)}${batch ? `&batch=${encodeURIComponent(batch.id)}` : ""}#editing-task-${row.render_task_id}`}>精修这一条</a>}
            </div>
            {(row.history?.length ?? 0) > 0 && <ul className={styles.history} aria-label="上一版">{row.history?.map(old => <li key={old.attempt}>
              <History size={12} />{old.final_url ? <a href={mediaUrl(old.final_url)} target="_blank" rel="noreferrer">第 {old.attempt} 版 · {nameOf(old.template_id) || "原模板"}</a> : <span>第 {old.attempt} 版 · {nameOf(old.template_id) || "原模板"}（未剪完）</span>}
            </li>)}</ul>}
          </div>
        </article>;
      })}</div>
      {progress.canFinish && batch && <div className={styles.next}>
        <button type="button" className={styles.primary} onClick={() => router.push(finishHref({ batch: batch.id }))}>{finishAction(progress).label}</button>
        {finishAction(progress).note && <p className={styles.fine}>{finishAction(progress).note}</p>}
      </div>}
    </section>}
  </section>;
}
