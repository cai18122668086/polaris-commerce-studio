"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Check, ChevronRight, CircleHelp, Download, History, ImagePlus, LoaderCircle, Plus, RotateCcw, Sparkles, Upload, X } from "lucide-react";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { getAssetAccessUrl, useUploadAsset } from "@/features/assets/api/assets";
import { useJob } from "@/features/jobs/api/jobs";
import { isLocalDevelopmentAuthEnabled, LOCAL_DEV_AUTH_USER_ID } from "@/lib/auth/local-dev";
import { ReplicaSelect } from "./replica-select";
import styles from "./style-replica-workspace.module.css";

type AssetChoice = { id: string; name: string };
type Product = { title: string | null; platform: string; imageUrls: string[]; descImageUrls: string[]; skuImageUrls: string[] };
type Plan = { reference: { asset_id: string; title: string; aspect_ratio: string }; analysis: Record<string, unknown>; prompt: string };
type ReplicaDocument = { id: string; kind: string; status: string; created_at: string; payload: { replication_method?: "exact" | "style"; analysis_stage?: string; skill_id?: string; product?: Product; product_asset_ids?: string[]; references?: Plan["reference"][]; plans?: Plan[]; plan_hash?: string; job_ids?: string[]; progress?: number; error?: string; facts?: string; confirmed_instructions?: string[]; submission_complete?: boolean; platform_code?: string; language?: string } };
const STEPS = ["选图", "诊断中", "补信息", "确认方案", "生成中", "完成"];

async function replicaRequest<T>(workspaceId: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (isLocalDevelopmentAuthEnabled()) headers["X-User-Id"] = LOCAL_DEV_AUTH_USER_ID;
  const response = await fetch(`/api/v1/workspaces/${workspaceId}/replica${path}`, { method: body === undefined ? "GET" : "POST", headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "include", signal });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message ?? result.detail?.message ?? result.message ?? "服务暂时不可用，请稍后再试。");
  return result;
}

function usableReferenceImage(src: string): Promise<boolean> {
  return new Promise(resolve => {
    const image = new Image();
    const finish = (valid: boolean) => { clearTimeout(timer); image.onload = null; image.onerror = null; resolve(valid); };
    const timer = setTimeout(() => finish(false), 15000);
    image.referrerPolicy = "no-referrer";
    image.onload = () => finish(image.naturalWidth >= 32 && image.naturalHeight >= 32);
    image.onerror = () => finish(false);
    image.src = src;
  });
}

function analysisText(value: unknown): string { if (typeof value === "string") return value; if (Array.isArray(value)) return value.map(analysisText).filter(Boolean).slice(0, 3).join(" · ").slice(0, 220); if (value && typeof value === "object") return analysisText(Object.values(value)); return ""; }

function AssetImage({ workspaceId, assetId, className, onClick }: { workspaceId: string; assetId: string; className?: string; onClick?: (url: string) => void }) {
  const [url, setUrl] = useState("");
  useEffect(() => { let active = true; void getAssetAccessUrl(workspaceId, assetId, "inline").then(value => { if (active) setUrl(value.url); }).catch(() => {}); return () => { active = false; }; }, [workspaceId, assetId]);
  return url ? <img className={className} src={url} alt="商品图片" onClick={() => onClick?.(url)} /> : <span className={styles.imagePlaceholder}><ImagePlus size={22} /></span>;
}

function ResultCard({ workspaceId, jobId, sessionId, outputIndex = 0, title, onPreview, onStatus, onRetry, retrying, retryWhole = false }: { workspaceId: string; jobId: string; sessionId: string; outputIndex?: number; title: string; onPreview: (url: string) => void; onStatus: (id: string, status: string) => void; onRetry: (id: string) => void; retrying: boolean; retryWhole?: boolean }) {
  const job = useJob(workspaceId, jobId);
  const [error, setError] = useState("");
  const data = job.data;
  const asset = data?.assets.filter(item => item.direction === "output" && item.is_deliverable)[outputIndex];
  const terminal = ["completed", "partial", "failed", "cancelled"].includes(data?.status ?? "");
  useEffect(() => { if (data) onStatus(jobId, data.status); }, [data, jobId, onStatus]);
  const download = async () => { try { if (!asset) return; const access = await getAssetAccessUrl(workspaceId, asset.asset_id, "attachment"); const response = await fetch(access.url, { credentials: "include" }); if (!response.ok) throw new Error("图片下载失败，请稍后重试。"); const url = URL.createObjectURL(await response.blob()); const a = document.createElement("a"); a.href = url; a.download = `${title}.png`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); } catch (caught) { setError(caught instanceof Error ? caught.message : "下载失败"); } };
  return <article className={styles.resultCard}>
    <div className={styles.resultMedia}>{asset ? <AssetImage workspaceId={workspaceId} assetId={asset.asset_id} onClick={onPreview} /> : <div className={styles.generating}>{terminal ? <CircleHelp size={26} /> : <LoaderCircle className="spin" size={28} />}<span>{terminal ? "本张暂未完成" : "正在绘制你的商品"}</span><small>{terminal ? data?.error_message ?? data?.items.find(item => item.error_message)?.error_message : `${data?.progress ?? 0}% · 可离开页面，稍后在记录中查看`}</small></div>}</div>
    <div className={styles.resultMeta}><strong>{title}</strong><span>{data?.status === "completed" ? "已完成" : terminal ? "需重试" : "生成中"}</span></div>
    <div className={styles.resultActions}>{asset && <button onClick={() => void download()}><Download size={14} />下载</button>}{terminal && !asset && outputIndex === 0 && <button disabled={retrying} onClick={() => onRetry(jobId)}><RotateCcw size={13} />{retrying ? "正在提交" : retryWhole ? "重新复刻整组" : "重新生成"}</button>}<Link href={`/style-replica?sessionId=${encodeURIComponent(sessionId)}`}>查看任务<ChevronRight size={13} /></Link></div>
    {error && <p className={styles.error}>{error}</p>}
  </article>;
}

export function StyleReplicaWorkspace() {
  const { workspace } = useWorkspace();
  const workspaceId = workspace?.id;
  const upload = useUploadAsset(workspaceId);
  const [mode, setMode] = useState<"link" | "image">("link");
  const [replicationMethod, setReplicationMethod] = useState<"exact" | "style">("exact");
  const [products, setProducts] = useState<AssetChoice[]>([]);
  const [references, setReferences] = useState<AssetChoice[]>([]);
  const [sourcePlatform, setSourcePlatform] = useState("auto");
  const [url, setUrl] = useState("");
  const [productDoc, setProductDoc] = useState<ReplicaDocument>();
  const [sessionDoc, setSessionDoc] = useState<ReplicaDocument>();
  const [selected, setSelected] = useState<string[]>([]);
  const [unavailableSources, setUnavailableSources] = useState<string[]>([]);
  const [imageTab, setImageTab] = useState<"imageUrls" | "descImageUrls" | "skuImageUrls">("imageUrls");
  const [platform, setPlatform] = useState("auto");
  const [language, setLanguage] = useState("zh-CN");
  const [mainRatio, setMainRatio] = useState("1:1");
  const [detailRatio, setDetailRatio] = useState("3:4");
  const [ratio, setRatio] = useState("follow-reference");
  const [selectedReferences, setSelectedReferences] = useState<string[]>([]);
  const actionLock = useRef(false);
  const retryIntents = useRef<Record<string, string>>({});
  const [facts, setFacts] = useState("");
  const [analysisRequestId, setAnalysisRequestId] = useState("");
  const [instructions, setInstructions] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [modal, setModal] = useState<"history" | "help" | "fees" | null>(null);
  const [history, setHistory] = useState<ReplicaDocument[]>([]);
  const [preview, setPreview] = useState("");
  const [jobStatuses, setJobStatuses] = useState<Record<string, string>>({});
  const [hydratedWorkspace, setHydratedWorkspace] = useState("");
  const draftWorkspace = useRef("");
  const selectedReferenceCount = references.filter(item => selectedReferences.includes(item.id)).length;
  const status = sessionDoc?.status;
  const working = busy !== "" || ["analysing"].includes(status ?? "") || productDoc?.status === "fetching";
  const product = productDoc?.payload.product;
  const sourceImages = (key: "imageUrls" | "descImageUrls" | "skuImageUrls") => (product?.[key] ?? []).filter(src => !unavailableSources.includes(src));
  const hideSource = (src: string) => { setUnavailableSources(current => current.includes(src) ? current : [...current, src]); setSelected(current => current.filter(value => value !== src)); };

  const plans = sessionDoc?.payload.plans ?? [];
  const native = !!sessionDoc?.payload.replication_method;
  const jobs = sessionDoc?.payload.job_ids ?? [];
  const complete = jobs.length > 0 && sessionDoc?.payload.submission_complete !== false && jobs.every(id => ["completed", "partial", "failed", "cancelled"].includes(jobStatuses[id]));
  const step = jobs.length ? complete ? 5 : 4 : status === "awaiting_confirmation" ? 3 : status === "analysing" ? 1 : 0;
  const reportStatus = useState(() => (id: string, value: string) => setJobStatuses(current => current[id] === value ? current : { ...current, [id]: value }))[0];

  useEffect(() => {
    if (!workspaceId || draftWorkspace.current === workspaceId) return;
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      draftWorkspace.current = workspaceId;
      setSessionDoc(undefined); setProductDoc(undefined); setSelected([]); setInstructions([]); setJobStatuses({});
      try { const saved = JSON.parse(localStorage.getItem(`polaris-replica:${workspaceId}`) ?? "{}"); setProducts(saved.products ?? []); setReferences(saved.references ?? []); setAnalysisRequestId(saved.analysisRequestId ?? crypto.randomUUID()); setUrl(saved.url ?? ""); setSourcePlatform(saved.sourcePlatform ?? "auto"); setImageTab(saved.imageTab ?? "imageUrls"); if (saved.productDocId) void replicaRequest<ReplicaDocument>(workspaceId, `/documents/${saved.productDocId}`).then(value => { if (active) { setProductDoc(value); setSelected(saved.selected ?? []); } }).catch(() => {}); setMode(saved.mode ?? "link"); setReplicationMethod(saved.replicationMethod ?? "exact"); setFacts(saved.facts ?? ""); setPlatform(saved.platform ?? "auto"); setLanguage(saved.language ?? "zh-CN"); setMainRatio(saved.mainRatio ?? "1:1"); setDetailRatio(saved.detailRatio ?? "3:4"); setRatio(saved.ratio ?? "follow-reference"); setSelectedReferences(saved.selectedReferences ?? (saved.references ?? []).map((item: AssetChoice) => item.id)); if (saved.sessionId && !new URLSearchParams(window.location.search).has("sessionId") && !new URLSearchParams(window.location.search).has("jobId")) void replicaRequest<ReplicaDocument>(workspaceId, `/documents/${saved.sessionId}`).then(value => { if (active) setSessionDoc(value); }).catch(() => {}); } catch { /* A stale draft must not block the workspace. */ }
      setHydratedWorkspace(workspaceId);
    });
    return () => { active = false; };
  }, [workspaceId]);
  useEffect(() => { if (workspaceId && hydratedWorkspace === workspaceId) localStorage.setItem(`polaris-replica:${workspaceId}`, JSON.stringify({ products, references, mode, replicationMethod, facts, platform, language, mainRatio, detailRatio, ratio, selectedReferences, analysisRequestId, url, sourcePlatform, imageTab, selected, productDocId: productDoc?.id, sessionId: sessionDoc?.id })); }, [workspaceId, hydratedWorkspace, products, references, mode, replicationMethod, facts, platform, language, mainRatio, detailRatio, ratio, selectedReferences, analysisRequestId, url, sourcePlatform, imageTab, selected, productDoc?.id, sessionDoc?.id]);
  useEffect(() => {
    if (!workspaceId) return;
    const pending = productDoc?.status === "fetching" ? productDoc : sessionDoc?.status === "analysing" ? sessionDoc : null;
    if (!pending) return;
    const controller = new AbortController();
    const timer = setInterval(() => { void replicaRequest<ReplicaDocument>(workspaceId, `/documents/${pending.id}`, undefined, controller.signal).then(value => { if (value.kind === "product") setProductDoc(value); else setSessionDoc(value); if (value.status === "failed") setError(value.payload.error ?? "任务暂未完成。"); }).catch(caught => { if (!controller.signal.aborted) setError(caught.message); }); }, 2000);
    return () => { clearInterval(timer); controller.abort(); };
  }, [workspaceId, productDoc, sessionDoc]);
  useEffect(() => { if (!preview) return; const close = (event: KeyboardEvent) => { if (event.key === "Escape") setPreview(""); }; window.addEventListener("keydown", close); return () => window.removeEventListener("keydown", close); }, [preview]);

  useEffect(() => {
    if (!workspaceId || hydratedWorkspace !== workspaceId) return;
    const controller = new AbortController();
    const load = () => {
      const params = new URLSearchParams(window.location.search);
      const id = params.get("sessionId"), jobId = params.get("jobId");
      const path = id ? `/documents/${encodeURIComponent(id)}` : jobId ? `/jobs/${encodeURIComponent(jobId)}/session` : null;
      if (path) void replicaRequest<ReplicaDocument>(workspaceId, path, undefined, controller.signal)
        .then(item => { if (!controller.signal.aborted && item.kind === "session") {
          setSessionDoc(item); setReplicationMethod(item.payload.replication_method ?? "exact"); setInstructions(item.payload.confirmed_instructions ?? []);
          setProducts((item.payload.product_asset_ids ?? []).map((assetId, index) => ({id: assetId, name: `产品图 ${index + 1}`})));
          const ids = [...new Set((item.payload.references ?? []).map(value => value.asset_id))];
          setReferences(ids.map((assetId, index) => ({id: assetId, name: `参考图 ${index + 1}`}))); setSelectedReferences(ids);
          setMode("image"); setFacts(item.payload.facts ?? ""); setPlatform(item.payload.platform_code ?? "auto"); setLanguage(item.payload.language ?? "zh-CN"); setProductDoc(undefined); setSelected([]);
        } })
        .catch(caught => { if (!controller.signal.aborted) setError(caught.message); });
    };
    load(); window.addEventListener("popstate", load);
    return () => { controller.abort(); window.removeEventListener("popstate", load); };
  }, [workspaceId, hydratedWorkspace]);
  const currentSessionId = sessionDoc?.id;
  useEffect(() => { if (currentSessionId) window.history.replaceState(null, "", `/style-replica?sessionId=${encodeURIComponent(currentSessionId)}`); }, [currentSessionId]);

  const perform = async (label: string, action: () => Promise<void>) => { if (actionLock.current) return; actionLock.current = true; setBusy(label); setError(""); try { await action(); } catch (caught) { setError(caught instanceof Error ? caught.message : "处理失败，请稍后再试。"); } finally { actionLock.current = false; setBusy(""); } };
  const uploadFiles = async (files: FileList | null, role: "product" | "reference") => {
    if (!files || !workspaceId) return;
    const current = role === "product" ? products : references;
    const limit = role === "product" ? 6 : 20;
    await perform("上传图片", async () => {
      const added: AssetChoice[] = [];
      for (const file of Array.from(files).slice(0, limit - current.length)) {
        if (file.size > 20 * 1024 * 1024) throw new Error("单张图片不能超过20MB。");
        const result = await upload.mutateAsync({ file }); added.push({ id: result.id, name: file.name });
        if (role === "product") setProducts([...current, ...added]); else { setReferences([...current, ...added]); setSelectedReferences(currentIds => [...new Set([...currentIds, result.id])]); }
      }
      if (files.length > limit - current.length) throw new Error(`该区域最多支持${limit}张图片，已上传可用部分。`);
    });
  };
  const fetchProduct = () => workspaceId && perform("拉取商品", async () => { setSelected([]); setUnavailableSources([]); setProductDoc(undefined); setProductDoc(await replicaRequest<ReplicaDocument>(workspaceId, "/products", { url, platform: sourcePlatform })); });
  const analyse = () => workspaceId && perform("准备分析", async () => {
    let choices: Plan["reference"][] = [];
    if (mode === "link") {
      if (!productDoc || !selected.length) throw new Error("请先拉取商品并勾选参考图。");
      const readable = await Promise.all(selected.map(usableReferenceImage));
      const invalid = selected.filter((_, index) => !readable[index]);
      if (invalid.length) { invalid.forEach(hideSource); throw new Error("已移除空白或无法读取的参考图，请重新选择后开始诊断。"); }
      const imported = await replicaRequest<{ asset_id: string; url: string; role: string }[]>(workspaceId, `/products/${productDoc.id}/import`, { urls: selected });
      choices = imported.map((item, index) => ({ asset_id: item.asset_id, title: `${item.role} ${index + 1}`, aspect_ratio: "follow-reference" }));
    } else {
      if (!selectedReferenceCount) throw new Error("请勾选要复刻的参考图。");
      choices = references.filter(item => selectedReferences.includes(item.id)).map((item, index) => ({ asset_id: item.id, title: `参考图 ${index + 1}`, aspect_ratio: "follow-reference" }));
    }
    if (!products.length) throw new Error("请上传自己的产品图。");
    setInstructions([]); setJobStatuses({});
    const result = await replicaRequest<ReplicaDocument>(workspaceId, "/sessions", { request_id: analysisRequestId || crypto.randomUUID(), product_asset_ids: products.map(item => item.id), references: choices, replication_method: replicationMethod, platform_code: platform === "auto" ? product?.platform ?? "tmall" : platform, language, facts });
    setSessionDoc(result);
  });
  const confirm = () => workspaceId && sessionDoc && perform("提交生成", async () => { try { setSessionDoc(await replicaRequest<ReplicaDocument>(workspaceId, `/sessions/${sessionDoc.id}/confirm`, { plan_hash: sessionDoc.payload.plan_hash, instructions: sessionDoc.payload.confirmed_instructions ?? instructions })); } catch (caught) { setSessionDoc(await replicaRequest<ReplicaDocument>(workspaceId, `/documents/${sessionDoc.id}`)); throw caught; } });
  const retryImage = (jobId: string) => workspaceId && sessionDoc && perform("重新生成", async () => { const requestId = retryIntents.current[jobId] ?? crypto.randomUUID(); retryIntents.current[jobId] = requestId; setSessionDoc(await replicaRequest<ReplicaDocument>(workspaceId, `/sessions/${sessionDoc.id}/jobs/${jobId}/retry`, { request_id: requestId })); });
  const restoreSession = (item: ReplicaDocument) => { setSessionDoc(item); setReplicationMethod(item.payload.replication_method ?? "exact"); setInstructions(item.payload.confirmed_instructions ?? []); setProducts((item.payload.product_asset_ids ?? []).map((id, index) => ({ id, name: `产品图 ${index + 1}` }))); const referenceIds = [...new Set((item.payload.references ?? []).map(value => value.asset_id))]; setReferences(referenceIds.map((id, index) => ({ id, name: `参考图 ${index + 1}` }))); setSelectedReferences(referenceIds); setMode("image"); setFacts(item.payload.facts ?? ""); setPlatform(item.payload.platform_code ?? "auto"); setLanguage(item.payload.language ?? "zh-CN"); setProductDoc(undefined); setSelected([]); setError(""); setModal(null); };
  const showHistory = () => workspaceId && perform("读取历史", async () => { setHistory(await replicaRequest<ReplicaDocument[]>(workspaceId, "/sessions")); setModal("history"); });
  const retryAnalysis = () => workspaceId && sessionDoc && perform("重试分析", async () => { setSessionDoc(await replicaRequest<ReplicaDocument>(workspaceId, `/sessions/${sessionDoc.id}/retry`, {})); });
  const reset = () => { window.history.replaceState(null, "", "/style-replica"); setAnalysisRequestId(crypto.randomUUID()); setSessionDoc(undefined); setInstructions([]); setError(""); setJobStatuses({}); };
  const uploadBox = (role: "product" | "reference", items: AssetChoice[], limit: number) => <div className={styles.uploadArea}>
    {items.length > 0 && <div className={styles.uploadGrid}>{items.map(item => <div key={item.id} className={styles.uploadThumb}>{workspaceId && <AssetImage workspaceId={workspaceId} assetId={item.id} onClick={setPreview} />}<button type="button" disabled={working} onClick={() => role === "product" ? setProducts(products.filter(p => p.id !== item.id)) : (setReferences(references.filter(p => p.id !== item.id)), setSelectedReferences(selectedReferences.filter(id => id !== item.id)))} aria-label={`移除${item.name}`}><X size={12} /></button></div>)}</div>}
    {items.length < limit && <label className={items.length ? styles.addUpload : styles.uploadTarget}><input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={working} onChange={event => { void uploadFiles(event.target.files, role); event.target.value = ""; }} /><Upload size={25} /><span>{items.length ? "添加图片" : role === "product" ? "点击或选择图片上传" : "上传构图、光影与色调参考"}</span>{!items.length && <small>JPG / PNG / WebP · 单张不超过20MB</small>}</label>}
  </div>;

  return <div className={styles.page}>
    <div className={styles.stepper} aria-label="复刻进度">{STEPS.map((label, index) => <div key={label} className={`${styles.stepItem} ${index === step ? styles.stepCurrent : ""} ${index < step ? styles.stepDone : ""}`}><span>{index < step ? <Check size={13} /> : index + 1}</span><b>{label}</b>{index < STEPS.length - 1 && <i />}</div>)}</div>
    <div className={styles.layout}>
      <aside className={styles.sidebar}>
        <button className={styles.feeLink} onClick={() => setModal("fees")}>用量说明 <ChevronRight size={12} /></button>
        <fieldset className={styles.inputFields} disabled={working || !!sessionDoc}>
        <div className={styles.methodChoice} role="radiogroup" aria-label="复刻方式">{([["exact", "一比一模仿", "风格最像，存在侵权风险"], ["style", "风格复刻", "提取风格机制，原创重构商品画面"]] as const).map(([value, title, note]) => <label key={value} className={replicationMethod === value ? styles.methodSelected : ""}><input type="radio" name="replication-method" value={value} checked={replicationMethod === value} onChange={() => { setReplicationMethod(value); setAnalysisRequestId(crypto.randomUUID()); }} /><span><strong>{title}</strong><small>{note}</small></span></label>)}</div><div className={styles.fieldHeading}><strong><ImagePlus size={15} /><em>*</em>上传你的产品图</strong><small>{products.length}/6</small></div>
        <p className={styles.hint}>上传必要角度，清晰展示商品外观；产品图决定最终商品身份。</p>
        {uploadBox("product", products, 6)}
        <div className={styles.modeTabs} role="tablist" aria-label="参考来源"><button role="tab" aria-selected={mode === "link"} className={mode === "link" ? styles.activeTab : ""} onClick={() => setMode("link")}>商品链接</button><button role="tab" aria-selected={mode === "image"} className={mode === "image" ? styles.activeTab : ""} onClick={() => setMode("image")}>风格参考图</button></div>
        {mode === "link" ? <>
          <div className={styles.guide}><strong>复刻流程</strong><p>粘贴想要参考的商品链接，勾选喜欢的图片。AI 分析构图、补充商品信息、确认方案，再生成你的商品图。</p></div>
          <label className={styles.field}><span><em>*</em>商品链接 / 商品 ID</span><div className={styles.linkInput}><input value={url} onChange={event => setUrl(event.target.value)} placeholder="淘宝 / 天猫 / 京东 / 1688 链接" aria-label="商品链接" /><button disabled={working || !url.trim() || !workspaceId} onClick={() => void fetchProduct()}>{productDoc?.status === "fetching" ? <LoaderCircle className="spin" size={16} /> : "拉取商品"}</button></div></label>
          {/^\d+$/.test(url.trim()) && <label className={styles.field}><span>来源平台</span><ReplicaSelect label="来源平台" value={sourcePlatform} onChange={setSourcePlatform} options={[["auto", "从链接自动识别"], ["taobao", "淘宝"], ["tmall", "天猫"], ["1688", "1688"], ["jd", "京东"]]} /></label>}
        </> : <>
          <div className={styles.fieldHeading}><strong><em>*</em>风格参考图</strong><small>{references.length}/20</small></div>{uploadBox("reference", references, 20)}
        </>}
        <label className={styles.field}><span><em>*</em>目标平台</span><ReplicaSelect label="目标平台" value={platform} onChange={setPlatform} options={[["auto", "智能匹配"], ["tmall", "天猫"], ["taobao", "淘宝"], ["jd", "京东"], ["pinduoduo", "拼多多"], ["douyin", "抖音"], ["1688", "1688"], ["amazon-us", "亚马逊"], ["temu", "TEMU"], ["shopee", "Shopee"], ["tiktok", "TikTok"]]} /></label>
        <label className={styles.field}><span><em>*</em>目标语言</span><ReplicaSelect label="目标语言" value={language} onChange={setLanguage} options={[["zh-CN", "中文（简体）"], ["zh-TW", "中文（繁体）"], ["en-US", "英语"], ["ja-JP", "日语"], ["ko-KR", "韩语"], ["de-DE", "德语"], ["fr-FR", "法语"], ["es-ES", "西班牙语"], ["ar-SA", "阿拉伯语"], ["ru-RU", "俄语"]]} /></label>
        <p className={styles.hint}>{replicationMethod === "exact" ? "按参考图逐屏保留构图和比例，长图会先拆屏。" : "根据参考内容选择画幅；连续详情按相邻双屏生成。"}最终数量与画幅会在方案中展示。</p>
        <details className={styles.optionalFacts}><summary>补充商品信息与要求（选填）</summary><label className={styles.field}><span>商品卖点与复刻要求</span><textarea value={facts} onChange={event => setFacts(event.target.value)} placeholder="写下自己的品牌、卖点、参数，或希望保留的构图。留空也可以开始。" maxLength={4000} rows={3} /></label></details></fieldset>
        {error && <p className={styles.error} role="alert">{error}</p>}
        <div className={styles.sidebarFooter}><button className={styles.startButton} disabled={!!sessionDoc || working || !workspaceId || !products.length || (mode === "image" ? !selectedReferenceCount : !selected.length)} onClick={() => void analyse()}>{working ? <><LoaderCircle className="spin" size={16} />{busy || (status === "analysing" ? "正在诊断" : "正在拉取商品")}</> : <><Sparkles size={16} />开始诊断</>}</button>
        <p className={styles.footerNote}>{mode === "image" ? `已选择 ${selectedReferenceCount} 张参考图` : `已选择 ${selected.length} 张参考图`} · 选哪张，复刻哪张</p></div>
      </aside>
      <section className={styles.stage}>
        <header className={styles.stageHeader}><div><Sparkles size={18} /><h1>一键复刻</h1><span>让好灵感，成为你的商品图</span></div><nav><button onClick={() => void showHistory()}><History size={14} />历史记录</button><button onClick={() => setModal("help")}><CircleHelp size={14} />使用教程</button></nav></header>
        {mode === "link" && product && !sessionDoc && <div className={styles.sourcePanel}><div className={styles.sourceHeading}><div><span className={styles.sourceBadge}>{product.platform}</span><strong>{product.title ?? "商品参考图"}</strong></div><span>已选 {selected.length}/20</span></div><div className={styles.selectionActions}><span>点击图片选择，长图会拆屏，最终数量以诊断方案为准</span><button onClick={() => setSelected([...new Set([...selected, ...sourceImages(imageTab)])].slice(0,20))}>全选本组</button><button onClick={() => setSelected([])}>清空选择</button></div><div className={styles.sourceTabs}>{[["imageUrls", "主图"], ["descImageUrls", "详情图"], ["skuImageUrls", "SKU 图"]].map(([key, label]) => <button className={imageTab === key ? styles.sourceTabActive : ""} key={key} onClick={() => setImageTab(key as typeof imageTab)}>{label}<b>{sourceImages(key as "imageUrls" | "descImageUrls" | "skuImageUrls").length}</b></button>)}</div><div className={styles.sourceGrid}>{sourceImages(imageTab).map((src, index) => <div key={src} className={`${styles.sourceTile} ${selected.includes(src) ? styles.sourceSelected : ""}`}><img src={src} alt={`参考图 ${index + 1}`} loading="lazy" referrerPolicy="no-referrer" onLoad={event => { if (event.currentTarget.naturalWidth < 32 || event.currentTarget.naturalHeight < 32) hideSource(src); }} onError={() => hideSource(src)} onClick={() => setSelected(selected.includes(src) ? selected.filter(item => item !== src) : selected.length < 20 ? [...selected, src] : selected)} /><button aria-label={`${selected.includes(src) ? "取消选择" : "选择"}参考图 ${index + 1}`} onClick={() => setSelected(selected.includes(src) ? selected.filter(item => item !== src) : selected.length < 20 ? [...selected, src] : selected)}>{selected.includes(src) ? <Check size={13} /> : index + 1}</button><button className={styles.previewTile} onClick={() => setPreview(src)}>放大</button></div>)}</div>{unavailableSources.length > 0 && <p className={styles.hint}>已隐藏 {unavailableSources.length} 张空白或无法读取的图片。<button className={styles.textButton} onClick={() => setUnavailableSources([])}>重新检查</button></p>}{!sourceImages(imageTab).length && <p className={styles.hint}>当前分组暂无图片，可以选择其他分组或上传参考图。</p>}</div>}
        {mode === "image" && references.length > 0 && !sessionDoc && workspaceId && <div className={styles.sourcePanel}><div className={styles.sourceHeading}><strong>选择想要复刻的参考图</strong><span>已选 {selectedReferenceCount}/{references.length}</span></div><div className={styles.selectionActions}><span>全部选中参考均纳入分析，长图会拆屏</span><button onClick={() => setSelectedReferences(references.map(item => item.id))}>全选</button><button onClick={() => setSelectedReferences([])}>清空选择</button></div><div className={styles.sourceGrid}>{references.map((item, index) => <div key={item.id} className={`${styles.sourceTile} ${selectedReferences.includes(item.id) ? styles.sourceSelected : ""}`}><AssetImage workspaceId={workspaceId} assetId={item.id} onClick={() => setSelectedReferences(selectedReferences.includes(item.id) ? selectedReferences.filter(id => id !== item.id) : [...selectedReferences, item.id])} /><button aria-label={`${selectedReferences.includes(item.id) ? "取消选择" : "选择"}参考图 ${index + 1}`} onClick={() => setSelectedReferences(selectedReferences.includes(item.id) ? selectedReferences.filter(id => id !== item.id) : [...selectedReferences, item.id])}>{selectedReferences.includes(item.id) ? <Check size={13} /> : index + 1}</button></div>)}</div></div>}
        {status === "analysing" && <div className={styles.analysisState}><div className={styles.orbit}><Sparkles size={28} /></div><h2>正在读懂你的商品与参考风格</h2><p>分析构图、光影和信息层级，为每张图准备专属方案。</p><progress max={100} value={sessionDoc?.payload.progress ?? 5} /><small>{native ? sessionDoc?.payload.analysis_stage ?? "正在准备复刻方案" : `${plans.length} / ${sessionDoc?.payload.references?.length ?? 0} 张方案已完成`}</small></div>}
        {status === "failed" && <div className={styles.emptyState}><CircleHelp size={38} /><h2>这次诊断暂未完成</h2><p>{sessionDoc?.payload.error}</p><button disabled={!!busy} onClick={() => void retryAnalysis()}>重试未完成的分析</button><button onClick={reset}>返回修改选图</button></div>}
        {status === "awaiting_confirmation" && <div className={styles.planPanel}><div className={styles.planIntro}><div><span className={styles.eyebrow}>你的专属复刻方案</span><h2>灵感已就位，确认后开始绘制</h2><p>你的产品图决定真实外观。确认拆屏与方案后开始生成；补充要求请返回修改并重新诊断。</p></div><button className={styles.textButton} onClick={reset}><RotateCcw size={14} />返回修改</button></div><div className={styles.plans}>{plans.map((plan, index) => <article className={styles.planCard} key={index}><div className={styles.planReference}>{workspaceId && <AssetImage workspaceId={workspaceId} assetId={plan.reference.asset_id} onClick={setPreview} />}</div><div><span className={styles.eyebrow}>方案 {String(index + 1).padStart(2, "0")}</span><h3>{plan.reference.title}</h3><p>{analysisText(plan.analysis.commercial_intent) || "保留参考构图、光影与色调，用你的商品重新演绎。"}</p><details><summary>查看画面方案</summary><p>{plan.prompt}</p></details>{!native && <textarea rows={2} disabled={sessionDoc?.payload.confirmed_instructions !== undefined} value={sessionDoc?.payload.confirmed_instructions?.[index] ?? instructions[index] ?? ""} maxLength={4000} onChange={event => setInstructions(current => plans.map((_, position) => position === index ? event.target.value : current[position] ?? ""))} placeholder="补充本张图的要求（选填）" aria-label={`方案${index + 1}补充要求`} />}</div></article>)}</div><div className={styles.confirmBar}><div><strong>共 {plans.length} 张独立图片</strong><small>生成结果自动进入个人素材库与生成记录</small></div><button disabled={!!busy} className={styles.startButton} onClick={() => void confirm()}>{busy ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}确认方案并生成</button></div></div>}
        {jobs.length > 0 && workspaceId && <div className={styles.results}><div className={styles.planIntro}><div><span className={styles.eyebrow}>生成结果</span><h2>{sessionDoc?.payload.submission_complete === false ? `还有 ${plans.length - jobs.length} 张待生成` : complete ? (jobs.every(id => jobStatuses[id] === "completed") ? "你的商品图已完成" : "部分图片暂未通过验收，可重试") : "灵感正在成为新画面"}</h2><p>点击图片放大，下载保存，或进入任务继续编辑。</p></div><div>{sessionDoc?.payload.submission_complete === false && <button disabled={!!busy} className={styles.textButton} onClick={() => void confirm()}>继续提交剩余图片</button>}<button className={styles.textButton} onClick={reset}><Plus size={14} />新建复刻</button></div></div><div className={styles.resultGrid}>{(native ? plans.map((_, index) => ({ id: jobs[0], index })) : jobs.map((id, index) => ({ id, index }))).map(({id, index}) => <ResultCard key={`${id}-${index}`} workspaceId={workspaceId} jobId={id} sessionId={sessionDoc!.id} outputIndex={native ? index : 0} retryWhole={native} title={plans[index]?.reference.title ?? `商品图 ${index + 1}`} onPreview={setPreview} onStatus={reportStatus} onRetry={id => void retryImage(id)} retrying={busy === "重新生成"} />)}</div></div>}
        {!sessionDoc && (mode === "link" ? !product : !references.length) && <div className={styles.emptyState}><div className={styles.emptyIcon}><Sparkles size={34} /></div><h2>好构图，换成你的好商品</h2><p>上传产品图，添加商品链接或风格参考图<br />点击「开始诊断」，让 AI 为你规划与创作</p><div className={styles.emptySteps}><span>01 上传产品</span><ChevronRight size={13} /><span>02 选择参考</span><ChevronRight size={13} /><span>03 确认生成</span></div></div>}
      </section>
    </div>
    {modal && <div className={styles.overlay} onClick={() => setModal(null)}><section className={styles.modal} role="dialog" aria-modal="true" aria-label={modal === "history" ? "复刻历史" : modal === "fees" ? "用量说明" : "使用教程"} onClick={event => event.stopPropagation()}><button className={styles.closeModal} onClick={() => setModal(null)} aria-label="关闭"><X size={20} /></button>{modal === "history" ? <><h2>复刻历史</h2>{history.length ? history.map(item => <button className={styles.historyRow} key={item.id} onClick={() => restoreSession(item)}><span>{new Date(item.created_at).toLocaleString("zh-CN")}<small>{item.payload.plans?.length ?? item.payload.references?.length ?? 0} 张图片</small></span><b>{item.status === "awaiting_confirmation" ? "待确认" : item.status === "analysing" ? "诊断中" : item.status === "failed" ? "未完成" : "查看结果"}</b><ChevronRight size={16} /></button>) : <p>还没有复刻记录，完成首次诊断后会显示在这里。</p>}</> : modal === "fees" ? <><h2>用量说明</h2><p>商品拉取通过第三方数据服务完成；同一商品当天再次查询会复用已有结果。</p><p>图片诊断与生成分别记录使用量，生成按图片任务计入账户用量。新复刻按整组方案验收；未通过时可重新复刻整组，重试会产生新的用量。</p><Link href="/dashboard">查看账户用量与余额 <ChevronRight size={14} /></Link></> : <><h2>把参考风格，变成你的商品图</h2><ol><li>上传自己的产品图，让外观、材质与品牌清晰可见。</li><li>粘贴商品链接选图，或直接上传风格参考图。</li><li>选择目标平台、语言与比例，可补充自己的真实卖点。</li><li>开始诊断，查看并补充每张图片的方案。</li><li>确认后生成，结果保存在素材库和生成记录中。</li></ol><p>参考图用于学习构图、光影和排版。商品参数、认证与售后承诺请以自己的真实信息为准。</p></>}</section></div>}
    {preview && <div className={styles.lightbox} role="dialog" aria-modal="true" aria-label="图片预览" onClick={() => setPreview("")}><button onClick={() => setPreview("")} aria-label="关闭图片预览"><X size={24} /></button><img src={preview} alt="图片预览" referrerPolicy="no-referrer" /></div>}
  </div>;
}
