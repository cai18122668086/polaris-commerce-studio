"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertCircle, ArrowRight, Check, CheckCircle2, CircleDollarSign, Clock3,
  FileCheck2, Globe2, GripVertical, ImagePlus, Info, Languages, LoaderCircle,
  MapPin, RotateCcw, ShieldCheck, Sparkles, Store, Upload, X,
} from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { HelpPanel } from "@/components/help-panel";
import { JobResultImage } from "@/components/job-result-image";
import { StatusBadge } from "@/components/status-badge";
import { WorkspaceHeader } from "@/components/workspace-header";
import { useUploadAsset } from "@/features/assets/api/assets";
import { useConfirmPlan, useCreateJob, useJob, useRetryJob } from "@/features/jobs/api/jobs";
import { presentWorkflow, useRuntimeStatus, type WorkflowPresentation } from "@/features/runtime/api/runtime";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { errorMessage } from "@/lib/api/request";
import type { Asset } from "@/lib/api/types";
import { allowsJobAction } from "@/lib/jobs/actions";
import { jobNote } from "@/lib/jobs/presentation";
import { selectJobResultAssets } from "@/lib/jobs/results";
import {
  marketplaceGroups,
  type MarketplaceImageSize,
  type MarketRegion,
} from "@/lib/marketplaces";

type UploadedSource = { asset: Asset; previewUrl: string };
type PlanPage = { title: string; description?: string; quality?: string };

const DEFAULT_DETAIL_SIZE: MarketplaceImageSize = "1024x1536";

function readPlanPages(payload: Record<string, unknown> | undefined): PlanPage[] {
  if (!payload) return [];
  const nested = payload.plan && typeof payload.plan === "object"
    ? (payload.plan as Record<string, unknown>).screens
    : undefined;
  const pages = Array.isArray(payload.pages) ? payload.pages : Array.isArray(nested) ? nested : [];
  return pages.flatMap((item, index) => {
    if (!item || typeof item !== "object") return [];
    const page = item as Record<string, unknown>;
    const planDetails = [page.role, page.structure, page.subject_scale, page.composition, page.device]
      .filter((value): value is string => typeof value === "string" && Boolean(value.trim()));
    return [{
      title: typeof page.title === "string" ? page.title : `页面 ${index + 1}`,
      description: planDetails.length > 0
        ? planDetails.join(" · ")
        : typeof page.description === "string"
          ? page.description
          : typeof page.goal === "string"
            ? page.goal
            : undefined,
      quality: typeof page.quality === "string" ? page.quality : undefined,
    }];
  });
}

function planItemPresentation(
  itemStatus: string | undefined,
  jobStatus: string | undefined,
  workflow: WorkflowPresentation,
) {
  const completed = ["succeeded", "reused"].includes(itemStatus ?? "") || jobStatus === "completed";
  const failed = itemStatus === "failed" || ["partial", "failed", "cancelled"].includes(jobStatus ?? "");
  if (completed) return {
    className: "completed",
    label: workflow.mode === "provider" ? "Provider 图片完成" : workflow.mode === "mock" ? "模拟流程完成 · 无真实图片产物" : "任务状态已完成 · 图片能力未知",
    icon: "done",
  };
  if (failed) return {
    className: "failed",
    label: workflow.mode === "provider" ? "Provider 流程未完成" : workflow.mode === "mock" ? "模拟流程结束 · 无真实图片产物" : "任务已结束 · 图片能力未知",
    icon: "failed",
  };
  return {
    className: "queued",
    label: workflow.mode === "provider" ? "Provider 流程处理中" : workflow.mode === "mock" ? "模拟流程处理中" : "能力未知 · 真实生成未启用",
    icon: "waiting",
  };
}

export default function DetailPackPage() {
  const fileInput = useRef<HTMLInputElement>(null);
  const [pageCount, setPageCount] = useState(6);
  const [marketRegion, setMarketRegion] = useState<MarketRegion>("domestic");
  const [marketplaceId, setMarketplaceId] = useState("tmall");
  const [imageSize, setImageSize] = useState<MarketplaceImageSize>(DEFAULT_DETAIL_SIZE);
  const [language, setLanguage] = useState<"zh-CN" | "en-US">("zh-CN");
  const [productName, setProductName] = useState("");
  const [sellingPoints, setSellingPoints] = useState("");
  const [sources, setSources] = useState<UploadedSource[]>([]);
  const [jobId, setJobId] = useState<string>();
  const { workspace } = useWorkspace();
  const upload = useUploadAsset(workspace?.id);
  const createJob = useCreateJob(workspace?.id);
  const confirmPlan = useConfirmPlan(workspace?.id);
  const retryJob = useRetryJob(workspace?.id);
  const job = useJob(workspace?.id, jobId);
  const runtime = useRuntimeStatus();
  const workflow = presentWorkflow(runtime.data?.capabilities.detail_pack);
  const workflowAvailable = workflow.mode === "mock" || workflow.mode === "provider";
  const selectedMarketplace = marketplaceGroups[marketRegion].find((item) => item.id === marketplaceId) ?? marketplaceGroups[marketRegion][0];
  const planPages = readPlanPages(job.data?.plan?.payload);
  const resultAssets = selectJobResultAssets(job.data);
  const requestError = upload.error ?? createJob.error ?? confirmPlan.error ?? retryJob.error ?? job.error;

  const sourcesRef = useRef(sources);
  useEffect(() => { sourcesRef.current = sources; }, [sources]);
  useEffect(() => () => {
    sourcesRef.current.forEach((source) => URL.revokeObjectURL(source.previewUrl));
  }, []);

  const selectRegion = (region: MarketRegion) => {
    const marketplace = marketplaceGroups[region][0];
    setMarketRegion(region);
    setMarketplaceId(marketplace.id);
    setImageSize(region === "international" ? marketplace.sizePresets?.[0]?.value ?? DEFAULT_DETAIL_SIZE : DEFAULT_DETAIL_SIZE);
    setLanguage(region === "domestic" ? "zh-CN" : "en-US");
  };

  const selectMarketplace = (marketplaceId: string) => {
    const marketplace = marketplaceGroups[marketRegion].find((item) => item.id === marketplaceId);
    setMarketplaceId(marketplaceId);
    setImageSize(marketRegion === "international" ? marketplace?.sizePresets?.[0]?.value ?? DEFAULT_DETAIL_SIZE : DEFAULT_DETAIL_SIZE);
  };

  const addFiles = async (files: FileList | null) => {
    if (!files) return;
    for (const file of Array.from(files).slice(0, 8 - sources.length)) {
      const previewUrl = URL.createObjectURL(file);
      try {
        const asset = await upload.mutateAsync({ file, mediaKind: "image" });
        setSources((items) => [...items, { asset, previewUrl }]);
      } catch {
        URL.revokeObjectURL(previewUrl);
        break;
      }
    }
    if (fileInput.current) fileInput.current.value = "";
  };

  const removeSource = (assetId: string) => {
    setSources((items) => {
      const removed = items.find((item) => item.asset.id === assetId);
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      return items.filter((item) => item.asset.id !== assetId);
    });
  };

  const createPlanningJob = async () => {
    if (!sources.length || !productName.trim() || !workspace) return;
    const configuration = {
      product_name: productName.trim(),
      platform_code: marketplaceId,
      page_count: pageCount,
      language,
      market_region: marketRegion,
      auto_start_after_plan: marketRegion === "domestic",
      selling_points: sellingPoints.split(/[；;\n]/).map((item) => item.trim()).filter(Boolean).slice(0, 12),
      size: imageSize,
    };
    const created = await createJob.mutateAsync({
      type: "detail_pack",
      intent: "submit",
      display_name: `详情套图 · ${productName.trim()}`,
      input: { product_groups: [{ group_key: "primary-product", asset_ids: sources.map((source) => source.asset.id) }] },
      configuration,
    });
    setJobId(created.id);
  };

  const retry = async () => {
    if (!job.data || !allowsJobAction(job.data.allowed_actions, "retry")) return;
    const retried = await retryJob.mutateAsync({
      jobId: job.data.id,
      allowedActions: job.data.allowed_actions,
      scope: "failed",
    });
    setJobId(retried.id);
  };

  const step = !sources.length ? 0 : !productName.trim() ? 1 : !jobId ? 2 : job.data?.status === "awaiting_confirmation" ? 3 : 4;

  return (
    <AppShell flush>
      <div className="workspace-page">
        <div className="workspace-main">
          <WorkspaceHeader
            eyebrow={workflow.mode === "provider" ? "电商套图 · Provider" : workflow.mode === "mock" ? "电商套图 · 内部 mock" : "电商套图 · 能力未知"}
            title="商品详情图"
            description={workflow.mode === "provider" ? "runtime 已报告 Provider 执行；前端仅经后端任务 API 提交，确认后可能生成真实图片并产生费用。" : workflow.mode === "mock" ? "上传、规划与确认真实写入 API；mock 模式不会调用图片 Provider，也没有真实产物。" : "runtime 能力状态未知，按 fail-closed 处理；规划与图片生成入口保持关闭。"}
            meta={<span className="autosave-state"><ShieldCheck size={15} />{workflow.mode === "provider" ? "Provider 已报告启用" : "真实生成未启用"}</span>}
          />

          <section className="marketplace-selector">
            <div className="marketplace-selector__head"><span className="number-chip">0</span><div><h2>选择目标电商渠道</h2><p>平台信息会写入详情图任务配置。</p></div><span className="platform-selected-state"><CheckCircle2 size={15} />{selectedMarketplace.name}</span></div>
            <div className="market-region-switch" aria-label="电商地区">
              <button className={marketRegion === "domestic" ? "active" : ""} onClick={() => selectRegion("domestic")} disabled={Boolean(jobId)}><MapPin size={17} /><span><strong>国内电商</strong><small>中国大陆平台</small></span></button>
              <button className={marketRegion === "international" ? "active" : ""} onClick={() => selectRegion("international")} disabled={Boolean(jobId)}><Globe2 size={17} /><span><strong>国际电商</strong><small>跨境与海外市场</small></span></button>
            </div>
            <div className="marketplace-grid">
              {marketplaceGroups[marketRegion].map((marketplace) => <button key={marketplace.id} className={marketplaceId === marketplace.id ? "active" : ""} onClick={() => selectMarketplace(marketplace.id)} disabled={Boolean(jobId)}><span className="marketplace-mark">{marketplace.shortName}</span><span><strong>{marketplace.name}</strong><small>{marketplace.format}</small></span><i>{marketplaceId === marketplace.id && <Check size={12} />}</i></button>)}
            </div>
          </section>

          <div className="workflow-steps detail-steps">
            {["商品素材", "商品信息", "输出设置", "确认规划", workflow.mode === "provider" ? "Provider 生成" : workflow.mode === "mock" ? "mock 流转" : "等待能力"].map((label, index) => <div key={label} className={index < step ? "done" : index === step ? "active" : ""}><i>{index < step ? <Check size={14} /> : index + 1}</i><span>{label}</span>{index < 4 && <em />}</div>)}
          </div>

          <section className="detail-form-card">
            <div className="form-section-head"><span className="number-chip">1</span><div><h2>商品素材</h2><p>每张图片都会先通过资产上传 API 持久化。</p></div>{sources.length > 0 && <span className="validation-chip"><CheckCircle2 size={15} />已上传 {sources.length} 张</span>}</div>
            <div className="multi-uploader">
              {sources.map((source, index) => <div key={source.asset.id} className="upload-thumb"><img src={source.previewUrl} alt={`商品角度 ${index + 1}`} /><span>角度 {index + 1}</span><button aria-label={`移除第 ${index + 1} 张图片`} onClick={() => removeSource(source.asset.id)}><X size={13} /></button><i><GripVertical size={14} /></i></div>)}
              {sources.length < 8 && <button className="upload-more" onClick={() => fileInput.current?.click()} disabled={!workspace || upload.isPending}>{upload.isPending ? <LoaderCircle className="spin" size={23} /> : <ImagePlus size={23} />}<strong>{upload.isPending ? "上传中" : "添加素材"}</strong><small>最多 8 张</small></button>}
              <input ref={fileInput} className="visually-hidden" type="file" multiple accept="image/*" onChange={(event) => void addFiles(event.target.files)} />
            </div>
          </section>

          <section className="detail-form-card">
            <div className="form-section-head"><span className="number-chip">2</span><div><h2>商品信息</h2><p>内容按 typed contract 写入任务配置。</p></div></div>
            <div className="form-grid">
              <label><span>商品名称 <i>*</i></span><input value={productName} onChange={(event) => setProductName(event.target.value)} placeholder="例如：鎏金焕亮精华液" /></label>
              <label><span>平台规格</span><div className="selected-output-platform"><Store size={16} /><strong>{selectedMarketplace.name}</strong></div></label>
              <label className="full"><span>核心卖点</span><textarea value={sellingPoints} onChange={(event) => setSellingPoints(event.target.value)} placeholder="用分号或换行分隔，最多 12 条" /></label>
            </div>
          </section>

          <section className="detail-form-card">
            <div className="form-section-head"><span className="number-chip">3</span><div><h2>输出设置</h2><p>{workflow.mode === "provider" ? "将进入真实生成，确认前请核对可能费用。" : "仅用于 mock 规划和状态流转，不代表会生成图片。"}</p></div></div>
            <div className="output-options">
              <div className="option-field"><span><Languages size={16} />内容语言</span><div className="segmented-control"><button className={language === "zh-CN" ? "active" : ""} onClick={() => setLanguage("zh-CN")}>简体中文</button><button className={language === "en-US" ? "active" : ""} onClick={() => setLanguage("en-US")}>English</button></div></div>
              <div className="option-field"><span><FileCheck2 size={16} />详情页数</span><div className="page-count-control">{[4, 6, 8].map((count) => <button key={count} className={pageCount === count ? "active" : ""} onClick={() => setPageCount(count)}>{count} 页</button>)}</div></div>
              {marketRegion === "international" && <div className="option-field"><span><Globe2 size={16} />图片尺寸</span><div className="page-count-control">{selectedMarketplace.sizePresets?.map((preset) => <button key={preset.value} className={imageSize === preset.value ? "active" : ""} onClick={() => setImageSize(preset.value)}>{preset.label}</button>)}</div></div>}
            </div>
          </section>

          {requestError && <div className="api-state api-state--error" role="alert"><AlertCircle size={24} /><div><strong>API 请求未完成</strong><p>{errorMessage(requestError)}</p></div></div>}

          <section className="planning-card" aria-busy={job.isFetching}>
            <div className="planning-head"><div><span className="number-chip number-chip--violet">4</span><div><h2>页面规划</h2><p>{jobId ? "正在从任务详情 API 读取结构化 plan。" : "创建任务后，planner 会返回待确认计划。"}</p></div></div>{job.data && <StatusBadge status={job.data.status} />}</div>
            {!jobId && <div className="api-state"><Info size={22} /><p>尚未创建规划任务。</p></div>}
            {jobId && job.isPending && <div className="api-state"><LoaderCircle className="spin" /><p>planner 处理中，正在轮询…</p></div>}
            {job.data && planPages.length === 0 && <div className="api-state"><Clock3 size={22} /><p>{jobNote(job.data)}</p></div>}
            {planPages.length > 0 && <div className="plan-list">
              {planPages.map((page, index) => {
                const item = job.data?.items.find((candidate) => candidate.ordinal === index + 1);
                const presentation = planItemPresentation(item?.status, job.data?.status, workflow);
                return <article key={`${page.title}-${index}`}><span className="plan-drag"><GripVertical size={15} /></span><i>{String(index + 1).padStart(2, "0")}</i><div><strong>{page.title}</strong><p>{page.description ?? "规划内容已由任务详情 API 返回。"}</p></div><span className="quality-chip">{page.quality ?? "mock"}</span><span className={`page-status ${presentation.className}`}>{presentation.icon === "done" ? <CheckCircle2 size={14} /> : presentation.icon === "failed" ? <AlertCircle size={14} /> : <Clock3 size={14} />}{presentation.label}</span></article>;
              })}
            </div>}
          </section>

          {resultAssets.length > 0 && <section className="detail-form-card">
            <div className="form-section-head"><span className="number-chip number-chip--violet">5</span><div><h2>生成结果</h2><p>结果来自任务详情的可交付 output Asset，并通过 access-url API 访问。</p></div><span className="validation-chip"><CheckCircle2 size={15} />共 {resultAssets.length} 张</span></div>
            <div className="job-results-grid">{resultAssets.map((asset, index) => <JobResultImage key={`${asset.asset_id}-${asset.ordinal}`} workspaceId={workspace?.id} assetId={asset.asset_id} alt={`详情页生成结果 ${index + 1}`} label={`详情页 ${asset.ordinal + 1}`} />)}</div>
          </section>}
          {job.data?.status === "completed" && workflow.mode === "mock" && resultAssets.length === 0 && <div className="api-state"><ImagePlus size={22} /><p>mock 流程已完成，但不会产生真实图片产物。</p></div>}

          <section className="generation-footer">
            <div className="estimate-grid">
              <span><CircleDollarSign size={18} /><div><p>本轮模式</p><strong>{workflow.mode === "provider" ? "Provider 执行 · 可能计费" : workflow.mode === "mock" ? "零付费 mock" : "能力未知 · fail-closed"}</strong></div></span>
              <span><Clock3 size={18} /><div><p>状态更新</p><strong>约每 1.5 秒轮询</strong></div></span>
              <span><ShieldCheck size={18} /><div><p>图片产物</p><strong>{workflow.canDeliverImages ? "真实生成" : "mock 无真实产物"}</strong></div></span>
            </div>
            <div className="generation-actions">
              <p><Info size={14} />{workflow.mode === "provider" ? "确认后由后端执行器调用 Provider，可能产生真实图片与费用。" : workflow.mode === "mock" ? "确认计划只推进模拟状态，不会产生可交付图片。" : "能力状态未知，确认入口保持关闭且不会进入图片生成。"}</p>
              {job.data && allowsJobAction(job.data.allowed_actions, "retry") ? (
                <button className="primary-button" onClick={() => void retry()} disabled={retryJob.isPending}>{retryJob.isPending ? <LoaderCircle className="spin" size={17} /> : <RotateCcw size={17} />}重试失败项目</button>
              ) : !jobId ? (
                <button className="primary-button" onClick={() => void createPlanningJob()} disabled={!workflowAvailable || !sources.length || !productName.trim() || createJob.isPending}>{createJob.isPending ? <LoaderCircle className="spin" size={17} /> : <Upload size={17} />}{workflowAvailable ? workflow.mode === "provider" ? "创建 Provider 规划任务" : "创建 mock 规划任务" : "能力未知，暂不可创建"}<ArrowRight size={17} /></button>
              ) : job.data?.plan && workflowAvailable && allowsJobAction(job.data.allowed_actions, "confirm_plan") ? (
                <button className="primary-button" onClick={() => confirmPlan.mutate({ jobId: job.data!.id, revision: job.data!.plan!.revision, allowedActions: job.data!.allowed_actions })} disabled={confirmPlan.isPending}>{confirmPlan.isPending ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}{workflow.mode === "provider" ? "确认并进入 Provider 生成" : "确认计划并进入 mock 流转"}<ArrowRight size={17} /></button>
              ) : (
                <button className="primary-button" disabled><LoaderCircle className={job.data && ["queued", "planning", "processing"].includes(job.data.status) ? "spin" : ""} size={17} />{job.data ? jobNote(job.data) : "正在读取任务"}</button>
              )}
            </div>
          </section>
        </div>
        <HelpPanel mode="detail-pack" />
      </div>
    </AppShell>
  );
}
