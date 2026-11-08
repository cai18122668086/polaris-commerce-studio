"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import { ApiError } from "@/lib/api/api-error";
import styles from "./writing-workflow.module.css";

type Fact = { id: string; category: "identity" | "product" | "story"; label: string; value: string | null; status: "user_declared" | "unknown"; source_note: string };
type Facts = { facts: Fact[]; forbidden_terms: string[]; restricted_claims: ("price" | "net_quantity" | "health_effect")[] };
type Analysis = { topic: string; sections: { id: string; first_sentence_id: string; last_sentence_id: string; function: string; explanation: string }[]; source_claims: { sentence_id: string; quote: string; handling: string; reason: string }[]; limitations: string[] };
type Draft = { text: string; draft: { title: string; sentences: { reference_sentence_id: string; text: string; fact_ids: string[] }[]; replacements: { original: string; replacement: string; fact_id: string }[]; missing_facts: string[]; warnings: string[] }; shape_check: { verdict: string; failures?: string[]; warnings?: string[] } };
type CommonDocument = { id: string; created_at: string; reference_document_id: string | null; analysis_document_id: string | null; facts_document_id: string | null; assistance_task_id: string | null };
type Document = CommonDocument & ({ kind: "reference"; body: { original_text: string; sentences: { id: string; text: string }[] } } | { kind: "analysis"; body: Analysis } | { kind: "facts"; body: Facts } | { kind: "draft"; body: Draft });
type Job = { id: string; request_id: string; kind: string; status: string; error_code: string | null; result: { analysis?: Analysis; draft?: Draft["draft"]; text?: string; shape_check?: Draft["shape_check"] } };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const stamp = (date: string) => new Date(date).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
const blankFact = (): Fact => ({ id: crypto.randomUUID(), category: "product", label: "产品信息", value: null, status: "unknown", source_note: "" });

export function WritingWorkflow({ workspaceId, projectId, revision, saved, references, productFacts, onApplied }: {
  workspaceId: string; projectId: string; revision: number; saved: boolean;
  references: { id: string; original_text: string }[]; productFacts: string; onApplied: () => Promise<void>;
}) {
  const [config, setConfig] = useState<{ enabled: boolean; can_generate: boolean }>();
  const [open, setOpen] = useState(false);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [source, setSource] = useState("");
  const [referenceId, setReferenceId] = useState("");
  const [factsId, setFactsId] = useState("");
  const [analysisId, setAnalysisId] = useState("");
  const [facts, setFacts] = useState<Fact[]>(() => productFacts.trim() && productFacts.length <= 1000 ? [{ ...blankFact(), label: "现有产品资料", value: productFacts, status: "user_declared", source_note: "沿用项目资料，请核对后保存" }] : [blankFact()]);
  const [forbidden, setForbidden] = useState("");
  const [restrictions, setRestrictions] = useState<Facts["restricted_claims"]>([]);
  const [duration, setDuration] = useState("");
  const [presentation, setPresentation] = useState<"on_camera" | "hands_only" | "unspecified">("unspecified");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const freeIntents = useRef(new Map<string, string>());
  const options = useCallback(() => ({ params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(12000) }), [workspaceId]);
  useEffect(() => { let live = true; void apiClient.GET(`${root}/writing-config`, options()).then(result => { if (live) setConfig(unwrapApiResponse(result) as { enabled: boolean; can_generate: boolean }); }).catch(() => undefined); return () => { live = false; }; }, [options]);
  const reload = useCallback(async () => {
    const opts = { ...options(), params: { path: { workspace_id: workspaceId }, query: { project_id: projectId } } };
    const [docs, tasks] = await Promise.all([apiClient.GET(`${root}/writing-documents`, opts), apiClient.GET(`${root}/assistance-tasks`, opts)]);
    const rows = unwrapApiResponse(tasks) as Job[];
    setDocuments(unwrapApiResponse(docs) as Document[]); setJobs(rows.filter(j => ["ref_analysis", "fact_draft"].includes(j.kind)));
    return rows;
  }, [options, workspaceId, projectId]);
  useEffect(() => { if (!open || !revision) return; let live = true; const update = () => { if (live) void reload().catch(() => { if (live) setError("文稿资料暂时无法读取，请刷新重试。"); }); }; update(); const timer = setInterval(update, 4000); return () => { live = false; clearInterval(timer); }; }, [open, revision, reload]);
  const attempt = async (run: () => Promise<void>) => { setBusy(true); setError(""); try { await run(); } catch (caught) { setError(caught instanceof Error ? caught.message : "本次操作尚未确认，请刷新原任务。"); } finally { setBusy(false); } };
  const freeIntent = (action: string, payload: unknown) => { const key = JSON.stringify([action, payload]); let id = freeIntents.current.get(key); if (!id) { id = crypto.randomUUID(); freeIntents.current.set(key, id); } return id; };
  const refDocs = documents.filter((d): d is Document & { kind: "reference" } => d.kind === "reference");
  const factDocs = documents.filter((d): d is Document & { kind: "facts" } => d.kind === "facts");
  const selectedReference = refDocs.find(d => d.id === referenceId) || refDocs[0];
  const selectedFacts = factDocs.find(d => d.id === factsId) || factDocs[0];
  const editedFacts: Facts = { facts, forbidden_terms: forbidden.split(/\n/).map(s => s.trim()).filter(Boolean), restricted_claims: restrictions };
  const factsDirty = !selectedFacts || JSON.stringify(editedFacts) !== JSON.stringify(selectedFacts.body);
  const analysisDocs = documents.filter((d): d is Document & { kind: "analysis" } => d.kind === "analysis" && d.reference_document_id === selectedReference?.id);
  const selectedAnalysis = analysisDocs.find(d => d.id === analysisId) || analysisDocs[0];
  const draftDocs = documents.filter((d): d is Document & { kind: "draft" } => d.kind === "draft" && d.reference_document_id === selectedReference?.id);
  const latestDraft = draftDocs[0];
  const running = jobs.some(j => ["queued", "running", "unknown"].includes(j.status));
  const unsavedResults = jobs.filter(j => j.status === "completed" && !documents.some(d => d.assistance_task_id === j.id));
  const saveReference = () => attempt(async () => {
    const reference = references.find(r => r.id === source);
    if (!reference) throw new Error("请先在参考文案工具中保存原文。");
    const body = { project_id: projectId, expected_revision: revision, reference_id: reference.id };
    const doc = unwrapApiResponse(await apiClient.POST(`${root}/writing-documents/reference`, { ...options(), body: { ...body, request_id: freeIntent("reference", body) } })) as Document;
    setReferenceId(doc.id); await reload();
  });
  const saveFacts = () => attempt(async () => {
    const body = { project_id: projectId, body: { facts, forbidden_terms: forbidden.split(/\n/).map(s => s.trim()).filter(Boolean), restricted_claims: restrictions } };
    const doc = unwrapApiResponse(await apiClient.POST(`${root}/writing-documents/facts`, { ...options(), body: { ...body, request_id: freeIntent("facts", body) } })) as Document;
    setFactsId(doc.id); await reload();
  });
  const generate = (kind: "ref_analysis" | "fact_draft") => attempt(async () => {
    if (!selectedReference) throw new Error("请先保存参考原文。");
    const payload = { project_id: projectId, expected_revision: revision, kind, reference_document_id: selectedReference.id, presentation: kind === "fact_draft" ? presentation : "unspecified" as const,
      ...(kind === "fact_draft" ? { analysis_document_id: selectedAnalysis?.id, facts_document_id: selectedFacts?.id, presentation, target_duration_seconds: duration ? Number(duration) : null } : {}) };
    const key = `tengli-writing-intent:${workspaceId}:${projectId}:${kind}`;
    let intent: { request_id: string; payload: string } | undefined;
    try { const stored = sessionStorage.getItem(key); if (stored) intent = JSON.parse(stored) as typeof intent; } catch {}
    if (intent && intent.payload !== JSON.stringify(payload)) throw new Error("已有提交待核对，请先刷新并查看原任务，避免重复调用。");
    intent ||= { request_id: crypto.randomUUID(), payload: JSON.stringify(payload) };
    sessionStorage.setItem(key, JSON.stringify(intent));
    try {
      unwrapApiResponse(await apiClient.POST(`${root}/writing-tasks`, { ...options(), body: { ...payload, request_id: intent.request_id } }));
      sessionStorage.removeItem(key); await reload();
    } catch (caught) {
      const rows = await reload().catch(() => []);
      if (rows.some(j => j.request_id === intent.request_id)) { sessionStorage.removeItem(key); return; }
      if (caught instanceof ApiError && caught.status && caught.status >= 400 && caught.status < 500) sessionStorage.removeItem(key);
      throw caught;
    }
  });
  const keepResult = (job: Job) => attempt(async () => {
    unwrapApiResponse(await apiClient.POST(`${root}/writing-documents/result`, { ...options(), body: { request_id: freeIntent("result", job.id), task_id: job.id } })); await reload();
  });
  const apply = () => attempt(async () => {
    if (!latestDraft) return;
    unwrapApiResponse(await apiClient.POST(`${root}/writing-documents/{document_id}/apply`, { ...options(), params: { path: { workspace_id: workspaceId, document_id: latestDraft.id } }, body: { request_id: freeIntent("apply", [latestDraft.id, revision]), expected_revision: revision } }));
    await onApplied(); await reload();
  });
  const editFact = (id: string, change: Partial<Fact>) => setFacts(rows => rows.map(f => f.id === id ? { ...f, ...change } : f));
  if (!config?.enabled) return null;
  return <details className={styles.workflow} open={open} onToggle={event => setOpen(event.currentTarget.open)}><summary>拆解与事实写稿</summary>
    <p>原文、拆解、事实卡与草稿分别留档。生成结果需要核对后采用，现有确认稿由原流程保留。</p>
    {!saved && <p role="status">请先保存当前项目，再开始拆解或采用新稿。</p>}
    <fieldset disabled={busy || !saved}><legend>1. 保存参考原文</legend>
      <select aria-label="选择项目参考原文" value={source} onChange={e => setSource(e.target.value)}><option value="">选择已保存的参考文案</option>{references.filter(r => r.original_text.trim()).map(r => <option key={r.id} value={r.id}>{r.original_text.slice(0, 35)}</option>)}</select>
      <button type="button" disabled={!source} onClick={() => void saveReference()}>保存原文版本</button>
      {refDocs.length > 0 && <label>使用原文版本<select aria-label="使用原文版本" value={selectedReference?.id || ""} onChange={e => setReferenceId(e.target.value)}>{refDocs.map(d => <option key={d.id} value={d.id}>{stamp(d.created_at)} · {d.body.original_text.slice(0, 22)}</option>)}</select></label>}
      {selectedReference && <details><summary>查看原文</summary><p className={styles.document}>{selectedReference.body.original_text}</p></details>}
    </fieldset>
    <fieldset disabled={busy}><legend>2. 核对用户事实</legend>
      <small>编辑区保存后才会成为新的事实卡版本。</small>
      {productFacts.length > 1000 && <details><summary>查看现有产品资料，逐项整理事实</summary><p className={styles.document}>{productFacts}</p></details>}
      {facts.map(f => <div className={styles.fact} key={f.id}><select aria-label="事实类别" value={f.category} onChange={e => editFact(f.id, { category: e.target.value as Fact["category"] })}><option value="identity">身份</option><option value="product">产品</option><option value="story">经历</option></select><input aria-label="事实名称" value={f.label} maxLength={100} onChange={e => editFact(f.id, { label: e.target.value })} /><select aria-label={`${f.label}是否已知`} value={f.status} onChange={e => editFact(f.id, { status: e.target.value as Fact["status"], value: e.target.value === "unknown" ? null : "" })}><option value="unknown">未知</option><option value="user_declared">我已提供</option></select>{f.status === "user_declared" && <textarea aria-label={`${f.label}内容`} value={f.value || ""} maxLength={1000} rows={2} onChange={e => editFact(f.id, { value: e.target.value })} />}<input aria-label={`${f.label}来源说明`} placeholder="来源或依据（选填）" value={f.source_note} maxLength={1000} onChange={e => editFact(f.id, { source_note: e.target.value })} /><button type="button" disabled={facts.length <= 1} onClick={() => setFacts(rows => rows.filter(row => row.id !== f.id))}>移除</button></div>)}
      <button type="button" disabled={facts.length >= 60} onClick={() => setFacts(rows => [...rows, blankFact()])}>添加事实</button>
      <label>禁词（每行一个）<textarea aria-label="写稿禁词" rows={2} value={forbidden} maxLength={10000} onChange={e => setForbidden(e.target.value)} /></label>
      <div className={styles.restrictions}>{([ ["price", "不写价格"], ["net_quantity", "不写净含量"], ["health_effect", "不写疗效"] ] as const).map(([key, label]) => <label key={key}><input type="checkbox" checked={restrictions.includes(key)} onChange={e => setRestrictions(rows => e.target.checked ? [...rows, key] : rows.filter(v => v !== key))} />{label}</label>)}</div>
      <button type="button" disabled={!saved} onClick={() => void saveFacts()}>保存事实卡版本</button>
      {factDocs.length > 0 && <label>使用事实卡<select aria-label="使用事实卡" value={selectedFacts?.id || ""} onChange={e => setFactsId(e.target.value)}>{factDocs.map(d => <option key={d.id} value={d.id}>{stamp(d.created_at)} · {d.body.facts.filter(f => f.status === "user_declared").length} 项已提供</option>)}</select></label>}
      {selectedFacts && <><ul>{selectedFacts.body.facts.map(f => <li key={f.id}><b>{f.label}</b>：{f.status === "unknown" ? "未知" : f.value}{f.source_note && <small>{f.source_note}</small>}</li>)}</ul><button type="button" onClick={() => { setFacts(selectedFacts.body.facts.map(f => ({ ...f }))); setForbidden(selectedFacts.body.forbidden_terms.join("\n")); setRestrictions([...selectedFacts.body.restricted_claims]); }}>载入此版本继续编辑</button></>}
      {factsDirty && selectedFacts && <p role="status">编辑区与选中版本不同，请保存为新版本或载入选中版本后继续生成。</p>}
    </fieldset>
    <fieldset disabled={busy || !saved || running}><legend>3. 拆解原文，再按事实写稿</legend>
      <small>会调用现有文稿模型。没有画面、互动或跨号样本时，只做文字拆解。</small>
      <button type="button" disabled={!config.can_generate || !selectedReference} onClick={() => void generate("ref_analysis")}>调用模型拆解原文</button>
      {selectedAnalysis && <><label>使用拆解<select aria-label="使用拆解版本" value={selectedAnalysis.id} onChange={e => setAnalysisId(e.target.value)}>{analysisDocs.map(d => <option key={d.id} value={d.id}>{stamp(d.created_at)} · {d.body.topic}</option>)}</select></label><ol>{selectedAnalysis.body.sections.map(section => <li key={section.id}><b>{section.function}</b><p>{section.explanation}</p></li>)}</ol>{selectedAnalysis.body.source_claims.map((claim, i) => <p key={i}>“{claim.quote}” · {claim.reason}</p>)}{selectedAnalysis.body.limitations.map((text, i) => <small key={i}>{text}</small>)}</>}
      <label>口播形式<select aria-label="写稿口播形式" value={presentation} onChange={e => setPresentation(e.target.value as typeof presentation)}><option value="unspecified">暂不设置字数预算</option><option value="on_camera">出镜口播</option><option value="hands_only">手部快切 / 画外音</option></select></label>
      <label>目标秒数（选填）<input aria-label="写稿目标秒数" type="number" min={5} max={300} value={duration} onChange={e => setDuration(e.target.value)} /></label>
      <button type="button" disabled={!config.can_generate || !selectedReference || !selectedAnalysis || factsDirty || !selectedFacts?.body.facts.some(f => f.status === "user_declared") || (!!duration && presentation === "unspecified")} onClick={() => void generate("fact_draft")}>按事实卡逐句生成草稿</button>
      {!config.can_generate && <small>文稿模型暂未配置，可以先保存原文与事实卡。</small>}
    </fieldset>
    {jobs.filter(j => ["queued", "running", "unknown", "failed"].includes(j.status)).slice(0, 3).map(j => <p key={j.id} role="status">{j.status === "unknown" ? "原提交结果待核对，请勿再次调用。" : j.status === "failed" ? "本次结果未通过检查，请查看原任务并核对事实。" : "文稿模型正在处理…"}</p>)}
    {unsavedResults.map(job => <div key={job.id} className={styles.result}><b>{job.kind === "ref_analysis" ? "拆解结果待保存" : "新稿结果待保存"}</b><p className={styles.document}>{job.result.analysis?.topic || job.result.text}</p><button type="button" disabled={busy} onClick={() => void keepResult(job)}>保存这份{job.kind === "ref_analysis" ? "拆解" : "草稿"}</button></div>)}
    {latestDraft && <section className={styles.result}><b>逐句核对新稿</b><ol>{latestDraft.body.draft.sentences.map(sentence => { const original = selectedReference?.body.sentences.find(s => s.id === sentence.reference_sentence_id); const card = factDocs.find(f => f.id === latestDraft.facts_document_id); return <li key={sentence.reference_sentence_id}><small>原句：{original?.text}</small><p>{sentence.text}</p><small>映射事实：{sentence.fact_ids.map(id => card?.body.facts.find(f => f.id === id)?.label || "需核对").join("、") || "未引用产品事实"}</small></li>; })}</ol><p>结构检查：{latestDraft.body.shape_check.verdict}。通过结构检查仍需逐句对义。</p>{[...latestDraft.body.draft.missing_facts, ...latestDraft.body.draft.warnings, ...(latestDraft.body.shape_check.warnings || [])].map((text, i) => <p key={i}>{text}</p>)}<button type="button" disabled={busy || !saved || latestDraft.body.draft.missing_facts.length > 0 || latestDraft.body.shape_check.verdict === "FAIL"} onClick={() => void apply()}>采用为编辑器草稿</button></section>}
    <button type="button" disabled={busy || !revision} onClick={() => void attempt(async () => { await reload(); })}>刷新资料与原任务</button>
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </details>;
}
