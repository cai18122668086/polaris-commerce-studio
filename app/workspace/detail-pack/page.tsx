"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  AlertCircle, ArrowRight, Check, CheckCircle2, CircleDollarSign, Clock3,
  FileCheck2, Globe2, GripVertical, ImagePlus, Info, Languages, LoaderCircle,
  MapPin, RotateCcw, ShieldCheck, Sparkles, Store, Upload, X,
} from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { HelpPanel } from "@/components/help-panel";
import { BRANDLESS_CONFIRMATION, DomesticDetailIntakeQuestion } from "@/components/domestic-detail-intake-question";
import { DomesticDetailApproval, NATIVE_DETAIL_APPROVAL_TEXT } from "@/components/domestic-detail-approval";
import { DomesticDetailCampaignReview } from "@/components/domestic-detail-campaign-review";
import type { CampaignSelection } from "@/features/jobs/api/campaign-reviews";
import { AutomaticDeliveryChoice, AutomaticDeliveryRecovery } from "@/components/domestic-detail-automatic-delivery";
import { automaticAuthorityForJob, useAutomaticDeliveryAuthorization, type AutomaticDeliveryAuthorization } from "@/features/jobs/api/automatic-delivery";
import { DomesticDetailFinalReview, isCurrentFinalReview, NATIVE_DETAIL_FINAL_REVIEW_TEXT } from "@/components/domestic-detail-final-review";
import { DomesticDetailLocalRevision } from "@/components/domestic-detail-local-revision";
import { JobDeliverablesDownload } from "@/components/job-deliverables-download";
import { JobResultImage } from "@/components/job-result-image";
import { StatusBadge } from "@/components/status-badge";
import { WorkspaceHeader } from "@/components/workspace-header";
import { useUploadAsset } from "@/features/assets/api/assets";
import { useConfirmPlan, useCreateJob, useDomesticDetailFinalReview, useFinalizeJob, useJob, useRetryJob } from "@/features/jobs/api/jobs";
import { presentWorkflow, resolveRuntimeCapability, useRuntimeStatus, type WorkflowPresentation } from "@/features/runtime/api/runtime";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { errorMessage } from "@/lib/api/request";
import { IMAGE_UPLOAD_ACCEPT } from "@/lib/image-upload";
import type { Asset } from "@/lib/api/types";
import { allowsJobAction } from "@/lib/jobs/actions";
import { jobNote } from "@/lib/jobs/presentation";
import { selectJobResultAssets } from "@/lib/jobs/results";
import {
  marketplaceGroups,
  type MarketplaceImageSize,
  type MarketRegion,
} from "@/lib/marketplaces";

type UploadedSource = { asset: Asset; previewUrl: string; role: "product_reference" | "style_reference" };
type PlanPage = { title: string; description?: string; quality?: string };

const DOMESTIC_DETAIL_SIZE: MarketplaceImageSize = "1440x1920";
const INTERNATIONAL_FALLBACK_SIZE: MarketplaceImageSize = "1024x1536";

function readPlanPages(payload: Record<string, unknown> | undefined): PlanPage[] {
  if (!payload) return [];
  const nested = payload.plan && typeof payload.plan === "object"
    ? (payload.plan as Record<string, unknown>).screens
    : undefined;
  const auroraModules = Array.isArray(payload.modules)
    ? payload.modules
    : payload.aurora_plan && typeof payload.aurora_plan === "object" && Array.isArray((payload.aurora_plan as Record<string, unknown>).modules)
      ? ((payload.aurora_plan as Record<string, unknown>).modules as unknown[])
      : [];
  const pages = Array.isArray(payload.pages) ? payload.pages : auroraModules.length > 0 ? auroraModules : Array.isArray(nested) ? nested : [];
  return pages.flatMap((item, index) => {
    if (!item || typeof item !== "object") return [];
    const page = item as Record<string, unknown>;
    const planDetails = [page.role, page.structure, page.subject_scale, page.composition, page.device]
      .filter((value): value is string => typeof value === "string" && Boolean(value.trim()));
    return [{
      title: typeof page.title === "string" ? page.title : typeof page.lead_conclusion === "string" ? page.lead_conclusion : `页面 ${index + 1}`,
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
    label: workflow.mode === "provider" ? "图片生成完成" : workflow.mode === "mock" ? "任务已完成 · 暂无图片结果" : "任务已完成 · 暂无图片结果",
    icon: "done",
  };
  if (failed) return {
    className: "failed",
    label: workflow.mode === "provider" ? "图片生成未完成" : workflow.mode === "mock" ? "任务已结束 · 暂无图片结果" : "任务已结束 · 暂无图片结果",
    icon: "failed",
  };
  if (jobStatus === "awaiting_confirmation") return { className: "queued", label: "等待方案确认", icon: "waiting" };
  if (jobStatus === "planning") return { className: "queued", label: "规划中", icon: "waiting" };
  return {
    className: "queued",
    label: workflow.mode === "provider" ? "图片生成处理中" : workflow.mode === "mock" ? "任务处理中" : "服务状态确认中 · 生成服务暂不可用",
    icon: "waiting",
  };
}

export default function DetailPackPage() {
  const fileInput = useRef<HTMLInputElement>(null);
  const searchParams = useSearchParams();
  const [pageCount, setPageCount] = useState(8);
  const [marketRegion, setMarketRegion] = useState<MarketRegion>("domestic");
  const [marketplaceId, setMarketplaceId] = useState("tmall");
  const [imageSize, setImageSize] = useState<MarketplaceImageSize>(DOMESTIC_DETAIL_SIZE);
  const [language, setLanguage] = useState<"zh-CN" | "en-US">("zh-CN");
  const [productName, setProductName] = useState("");
  const [category, setCategory] = useState("");
  const [targetBuyer, setTargetBuyer] = useState("");
  const [sellingPoints, setSellingPoints] = useState("");
  const [brandlessConfirmed, setBrandlessConfirmed] = useState(false);
  const [reviewedApprovalKey, setReviewedApprovalKey] = useState("");
  const [automaticChoice, setAutomaticChoice] = useState<{ scope: string; requested: boolean; authorization?: AutomaticDeliveryAuthorization }>();
  const [reviewedFinalKey, setReviewedFinalKey] = useState("");
  const [campaignChoice, setCampaignChoice] = useState<{ workspaceId?: string; sourceId: string; selection: CampaignSelection }>();
  const [sources, setSources] = useState<UploadedSource[]>([]);
  const [uploadError, setUploadError] = useState<string>();
  // Prefer the task-center URL when present; the local value covers jobs
  // created or retried from this form. Deriving this value also handles SPA
  // navigation between task links without an effect-driven state update.
  const [localJobId, setLocalJobId] = useState<string>();
  const jobId = searchParams.get("jobId") ?? localJobId ?? "";
  const { workspace } = useWorkspace();
  const upload = useUploadAsset(workspace?.id);
  const createJob = useCreateJob(workspace?.id);
  const confirmPlan = useConfirmPlan(workspace?.id);
  const retryJob = useRetryJob(workspace?.id);
  const finalizeJob = useFinalizeJob(workspace?.id);
  const job = useJob(workspace?.id, jobId);
  const isNativeDetail = job.data?.configuration.domestic_detail_pipeline === "aurora-domestic-detail-v4.3.1";
  const activeCampaignChoice = campaignChoice?.workspaceId === workspace?.id && campaignChoice?.sourceId === jobId && job.data?.status !== "completed" ? campaignChoice.selection : undefined;
  const finalReview = useDomesticDetailFinalReview(workspace?.id, job.data, activeCampaignChoice);
  const currentFinalReview = isCurrentFinalReview(finalReview.data, jobId, job.data?.expected_item_count ?? 0) ? finalReview.data : undefined;
  const finalKey = currentFinalReview ? `${jobId}:${currentFinalReview.sha256}` : "";
  const finalReviewed = Boolean(finalKey && reviewedFinalKey === finalKey && !finalReview.isError);

  const runtime = useRuntimeStatus();
  const workflow = presentWorkflow(
    marketRegion === "international"
      ? resolveRuntimeCapability(runtime.data, "crossborder_detail")
      : runtime.data?.capabilities.detail_pack,
  );
  const workflowAvailable = workflow.mode === "mock" || workflow.mode === "provider";
  const selectedMarketplace = marketplaceGroups[marketRegion].find((item) => item.id === marketplaceId) ?? marketplaceGroups[marketRegion][0];
  const planPages = readPlanPages(job.data?.plan?.payload);
  const auroraApproval = job.data?.plan?.payload.aurora_v4_3 as Record<string, unknown> | undefined;
  const nativeApproval = job.data?.plan?.payload.native_approval as Record<string, unknown> | undefined;
  const approvalDocument = typeof auroraApproval?.approval_document_markdown === "string" ? auroraApproval.approval_document_markdown : "";
  const approvalFingerprint = typeof auroraApproval?.approval_document_sha256 === "string" ? auroraApproval.approval_document_sha256 : "";
  const approvalKey = `${job.data?.id}:${job.data?.plan?.revision}:${approvalFingerprint}`;
  const nativeReviewed = job.data?.id === jobId && nativeApproval?.version === "domestic-native-approval-v1" && Boolean(nativeApproval?.artifact_id) && Boolean(approvalDocument) && reviewedApprovalKey === approvalKey && job.data?.plan?.validation_status === "valid";
  const automaticScope = `${workspace?.id}:${jobId}:${job.data?.plan?.revision}:${nativeApproval?.document_sha256}`;
  const automaticRequested = automaticChoice?.scope === automaticScope && automaticChoice.requested;
  const automaticQuote = useAutomaticDeliveryAuthorization(workspace?.id, job.data, Boolean(automaticRequested));
  const automaticConsent = automaticChoice?.scope === automaticScope ? automaticChoice.authorization : undefined;
  const automaticReady = !automaticRequested || Boolean(automaticConsent && automaticQuote.data && !automaticQuote.isError && !automaticQuote.isFetching && automaticConsent.sha256 === automaticQuote.data.sha256 && automaticQuote.data.native_approval_document_sha256 === nativeApproval?.document_sha256 && automaticQuote.data.plan_revision === job.data?.plan?.revision);
  const originalAutomaticAuthority = automaticAuthorityForJob(job.data);
  const resultAssets = selectJobResultAssets(job.data);
  const requestError = createJob.error ?? confirmPlan.error ?? retryJob.error ?? finalizeJob.error ?? job.error;

  const productSources = marketRegion === "domestic" ? sources.filter(source => source.role === "product_reference") : sources;
  const sourcesRef = useRef(sources);
  useEffect(() => { sourcesRef.current = sources; }, [sources]);
  useEffect(() => () => {
    sourcesRef.current.forEach((source) => URL.revokeObjectURL(source.previewUrl));
  }, []);

  const selectRegion = (region: MarketRegion) => {
    const marketplace = marketplaceGroups[region][0];
    setMarketRegion(region);
    setMarketplaceId(marketplace.id);
    setImageSize(
      region === "international"
        ? marketplace.sizePresets?.[0]?.value ?? INTERNATIONAL_FALLBACK_SIZE
        : DOMESTIC_DETAIL_SIZE,
    );
    setLanguage(region === "domestic" ? "zh-CN" : "en-US");
  };

  const selectMarketplace = (marketplaceId: string) => {
    const marketplace = marketplaceGroups[marketRegion].find((item) => item.id === marketplaceId);
    setMarketplaceId(marketplaceId);
    setImageSize(
      marketRegion === "international"
        ? marketplace?.sizePresets?.[0]?.value ?? INTERNATIONAL_FALLBACK_SIZE
        : DOMESTIC_DETAIL_SIZE,
    );
  };

  const addFiles = async (files: File[]) => {
    if (!files.length) return;
    setUploadError(undefined);
    const failures: string[] = [];
    for (const file of files.slice(0, 8 - sources.length)) {
      const previewUrl = URL.createObjectURL(file);
      try {
        const asset = await upload.mutateAsync({ file, mediaKind: "image" });
        setBrandlessConfirmed(false);
        setSources((items) => [...items, { asset, previewUrl, role: "product_reference" }]);
      } catch (error) {
        URL.revokeObjectURL(previewUrl);
        failures.push(`${file.name || "所选图片"}：${errorMessage(error)}`);
      }
    }
    if (failures.length) {
      const remaining = failures.length > 1 ? `，另有 ${failures.length - 1} 张上传失败` : "";
      setUploadError(`${failures[0]}${remaining}`);
    }
  };

  const removeSource = (assetId: string) => {
    setBrandlessConfirmed(false);
    setSources((items) => {
      const removed = items.find((item) => item.asset.id === assetId);
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      return items.filter((item) => item.asset.id !== assetId);
    });
  };

  const createPlanningJob = async () => {
    if (!workflowAvailable || !productSources.length || !productName.trim() || !workspace) return;
    const configuration = {
      product_name: productName.trim(),
      platform_code: marketplaceId,
      page_count: pageCount,
      language,
      market_region: marketRegion,
      category: category.trim() || undefined,
      target_buyer: targetBuyer.trim() || undefined,
      // Aurora v4.3 requires explicit approval of the complete campaign
      // group→screen packet before any pair generation can start.
      auto_start_after_plan: false,
      selling_points: sellingPoints.split(/[；;\n]/).map((item) => item.trim()).filter(Boolean).slice(0, 12),
      verified_facts: marketRegion === "domestic" ? [] : sellingPoints.split(/[；;\n]/).map((item) => item.trim()).filter(Boolean).slice(0, 24),
      brandless_confirmation: marketRegion === "domestic" && brandlessConfirmed ? BRANDLESS_CONFIRMATION : undefined,
      conflict_scan: marketRegion === "domestic" ? {} : { status: "NO_MATERIAL_CONFLICTS_REPORTED" },
      source_conflicts: [],
      reference_materials: [],
      platform_profile: {
        marketplace: marketplaceId,
        region: marketRegion,
        screen_size: imageSize,
        pair_canvas_aspect_ratio: marketRegion === "domestic" ? "3:8" : undefined,
      },
      size: imageSize,
    };
    const created = await createJob.mutateAsync({
      type: "detail_pack",
      intent: "submit",
      display_name: `商品详情图 · ${productName.trim()}`,
      input: { product_groups: [{ group_key: "primary-product", asset_ids: productSources.map((source) => source.asset.id) }],
        reference_asset_ids: marketRegion === "domestic" ? sources.filter(source => source.role === "style_reference").map(source => source.asset.id) : [] },
      configuration,
    });
    setLocalJobId(created.id);
  };

  const retry = async () => {
    if (!job.data || !allowsJobAction(job.data.allowed_actions, "retry")) return;
    const retried = await retryJob.mutateAsync({
      jobId: job.data.id,
      allowedActions: job.data.allowed_actions,
      scope: "failed",
    });
    setLocalJobId(retried.id);
  };

  const step = !productSources.length ? 0 : !productName.trim() ? 1 : !jobId ? 2 : job.data?.status === "awaiting_confirmation" ? 3 : 4;

  return (
    <AppShell flush>
      <div className="workspace-page">
        <div className="workspace-main">
          <WorkspaceHeader
            eyebrow={workflow.mode === "provider" ? "电商套图 · 在线生成" : workflow.mode === "mock" ? "电商套图 · 基础流程" : "电商套图 · 服务状态确认中"}
            title="商品详情图"
            description={workflow.mode === "provider" ? "当前生成服务可用；确认方案后将开始生成整套图片。" : workflow.mode === "mock" ? "当前支持素材上传、方案规划和任务保存，图片生成服务暂不可用。" : "当前无法确认生成服务状态，方案规划与图片生成入口暂时关闭。"}
            meta={<span className="autosave-state"><ShieldCheck size={15} />{workflow.mode === "provider" ? "生成服务可用" : "生成服务暂不可用"}</span>}
          />

          <section className="marketplace-selector">
            <div className="marketplace-selector__head"><span className="number-chip">0</span><div><h2>选择目标电商渠道</h2><p>所选渠道会影响图片尺寸、构图和文案规范。</p></div><span className="platform-selected-state"><CheckCircle2 size={15} />{selectedMarketplace.name} · 严格交付 {imageSize}</span></div>
            <div className="market-region-switch" aria-label="电商地区">
              <button className={marketRegion === "domestic" ? "active" : ""} onClick={() => selectRegion("domestic")} disabled={Boolean(jobId)}><MapPin size={17} /><span><strong>国内电商</strong><small>中国大陆平台</small></span></button>
              <button className={marketRegion === "international" ? "active" : ""} onClick={() => selectRegion("international")} disabled={Boolean(jobId)}><Globe2 size={17} /><span><strong>国际电商</strong><small>跨境与海外市场</small></span></button>
            </div>
            <div className="marketplace-grid">
              {marketplaceGroups[marketRegion].map((marketplace) => <button key={marketplace.id} className={marketplaceId === marketplace.id ? "active" : ""} onClick={() => selectMarketplace(marketplace.id)} disabled={Boolean(jobId)}><span className="marketplace-mark">{marketplace.shortName}</span><span><strong>{marketplace.name}</strong><small>{marketplace.format}</small></span><i>{marketplaceId === marketplace.id && <Check size={12} />}</i></button>)}
            </div>
          </section>

          <div className="workflow-steps detail-steps">
            {["商品素材", "商品信息", "输出设置", "确认规划", workflow.mode === "provider" ? "图片生成" : workflow.mode === "mock" ? "保存任务" : "服务确认中"].map((label, index) => <div key={label} className={index < step ? "done" : index === step ? "active" : ""}><i>{index < step ? <Check size={14} /> : index + 1}</i><span>{label}</span>{index < 4 && <em />}</div>)}
          </div>

          <section className="detail-form-card">
            <div className="form-section-head"><span className="number-chip">1</span><div><h2>商品素材</h2><p>每张图片都会先保存到当前工作区。</p></div>{sources.length > 0 && <span className="validation-chip"><CheckCircle2 size={15} />已上传 {sources.length} 张</span>}</div>
            <div className="multi-uploader">
              {sources.map((source, index) => <div key={source.asset.id} className="upload-thumb"><img src={source.previewUrl} alt={`商品角度 ${index + 1}`} /><span>{source.role === "style_reference" ? "风格参考" : `商品图 ${index + 1}`}</span>{marketRegion === "domestic" && <select aria-label={`第 ${index + 1} 张图片用途`} value={source.role} disabled={Boolean(jobId)} onChange={event => {
                const role = event.target.value as UploadedSource["role"]; setBrandlessConfirmed(false); setSources(items => items.map(item => item.asset.id === source.asset.id ? { ...item, role } : item));
              }}><option value="product_reference">商品图</option><option value="style_reference">风格参考</option></select>}<button aria-label={`移除第 ${index + 1} 张图片`} onClick={() => removeSource(source.asset.id)}><X size={13} /></button><i><GripVertical size={14} /></i></div>)}
              {sources.length < 8 && <button className="upload-more" onClick={() => fileInput.current?.click()} disabled={!workspace || upload.isPending}>{upload.isPending ? <LoaderCircle className="spin" size={23} /> : <ImagePlus size={23} />}<strong>{upload.isPending ? "上传中" : "添加素材"}</strong><small>最多 8 张</small></button>}
              <input ref={fileInput} className="visually-hidden" type="file" multiple accept={IMAGE_UPLOAD_ACCEPT} onChange={(event) => { const files = Array.from(event.currentTarget.files ?? []); event.currentTarget.value = ""; void addFiles(files); }} />
            </div>
            {uploadError && <div className="api-state api-state--error" role="alert"><AlertCircle size={20} /><div><strong>部分素材未能上传</strong><p>{uploadError}</p></div></div>}
          </section>

          <section className="detail-form-card">
            <div className="form-section-head"><span className="number-chip">2</span><div><h2>商品信息</h2><p>请填写商品名称与核心卖点，用于生成页面方案。</p></div></div>
            <div className="form-grid">
              <label><span>商品名称 <i>*</i></span><input value={productName} onChange={(event) => setProductName(event.target.value)} placeholder="例如：鎏金焕亮精华液" /></label>
              <label><span>商品类目</span><input value={category} onChange={(event) => setCategory(event.target.value)} placeholder="例如：护肤 / 家居 / 3C" /></label>
              <label><span>目标买家</span><input value={targetBuyer} onChange={(event) => setTargetBuyer(event.target.value)} placeholder="例如：关注成分与肤感的通勤人群" /></label>
              <label><span>平台规格</span><div className="selected-output-platform"><Store size={16} /><strong>{selectedMarketplace.name} · {imageSize}</strong></div></label>
              {marketRegion === "domestic" && <label className="full"><span><input style={{ width: "auto", marginRight: 8 }} type="checkbox" checked={brandlessConfirmed} onChange={event => setBrandlessConfirmed(event.target.checked)} />{BRANDLESS_CONFIRMATION}</span><small>有品牌的商品请上传能清楚辨认标识的本商品图片。</small></label>}
              <label className="full"><span>核心卖点</span><textarea value={sellingPoints} onChange={(event) => setSellingPoints(event.target.value)} placeholder="用分号或换行分隔，最多 12 条" /></label>
            </div>
          </section>

          <section className="detail-form-card">
            <div className="form-section-head"><span className="number-chip">3</span><div><h2>输出设置</h2><p>{workflow.mode === "provider" ? "确认后将开始生成，请先核对输出设置。" : "当前仅保存规划和任务状态，暂不生成图片。"}</p></div></div>
            <div className="output-options">
              <div className="option-field"><span><Languages size={16} />内容语言</span><div className="segmented-control"><button className={language === "zh-CN" ? "active" : ""} onClick={() => setLanguage("zh-CN")}>简体中文</button><button className={language === "en-US" ? "active" : ""} onClick={() => setLanguage("en-US")}>English</button></div></div>
              <div className="option-field"><span><FileCheck2 size={16} />详情页数</span><div className="page-count-control">{[8, 10, 12].map((count) => <button key={count} className={pageCount === count ? "active" : ""} onClick={() => setPageCount(count)}>{count} 页</button>)}</div></div>
              {marketRegion === "international" && <div className="option-field"><span><Globe2 size={16} />图片尺寸</span><div className="page-count-control">{selectedMarketplace.sizePresets?.map((preset) => <button key={preset.value} className={imageSize === preset.value ? "active" : ""} onClick={() => setImageSize(preset.value)}>{preset.label}</button>)}</div></div>}
            </div>
          </section>

          {requestError && <div className="api-state api-state--error" role="alert"><AlertCircle size={24} /><div><strong>请求未完成</strong><p>{errorMessage(requestError)}</p></div></div>}

          {job.data?.stage === "intake_confirmation_required" && <DomesticDetailIntakeQuestion key={`${job.data.id}:${job.data.plan?.revision}`} workspaceId={workspace?.id} job={job.data} />}

          <section className="planning-card" aria-busy={job.isFetching}>
            <div className="planning-head"><div><span className="number-chip number-chip--violet">4</span><div><h2>页面规划</h2><p>{jobId ? "正在读取页面规划。" : "创建任务后将生成待确认的页面方案。"}</p><small>{marketRegion === "domestic" ? "国内详情按相邻两屏生成一个 3:8 连续画布，固定切成两张 3:4 图片并审核。" : "跨境详情按平台尺寸分别生成独立模块，生成完成后需完成人工 QA 审阅再交付。"}</small></div></div>{job.data && <StatusBadge status={job.data.status} />}</div>
            {!jobId && <div className="api-state"><Info size={22} /><p>尚未创建规划任务。</p></div>}
            {jobId && job.isPending && <div className="api-state"><LoaderCircle className="spin" /><p>正在准备页面规划，请稍候…</p></div>}
            {job.data && planPages.length === 0 && <div className="api-state"><Clock3 size={22} /><p>{jobNote(job.data)}</p></div>}
            {planPages.length > 0 && <div className="plan-list">
              {planPages.map((page, index) => {
                const item = job.data?.items.find((candidate) => candidate.ordinal === (isNativeDetail ? index : index + 1));
                const presentation = planItemPresentation(item?.status, job.data?.status, workflow);
                return <article key={`${page.title}-${index}`}><span className="plan-drag"><GripVertical size={15} /></span><i>{String(index + 1).padStart(2, "0")}</i><div><strong>{page.title}</strong><p>{page.description ?? "页面规划内容已生成。"}</p></div><span className="quality-chip">{page.quality ?? "默认"}</span><span className={`page-status ${presentation.className}`}>{presentation.icon === "done" ? <CheckCircle2 size={14} /> : presentation.icon === "failed" ? <AlertCircle size={14} /> : <Clock3 size={14} />}{presentation.label}</span></article>;
              })}
            </div>}
          </section>

          {job.data?.id === jobId && job.data.plan?.validation_status === "valid" && auroraApproval && nativeApproval && approvalDocument && <DomesticDetailApproval key={approvalKey} document={approvalDocument} fingerprint={approvalFingerprint} reviewed={nativeReviewed} onReviewed={checked => setReviewedApprovalKey(checked ? approvalKey : "")} />}

          {job.data?.id === jobId && isNativeDetail && job.data.status === "awaiting_confirmation" && job.data.plan?.validation_status === "valid" && <AutomaticDeliveryChoice requested={Boolean(automaticRequested)} quote={automaticQuote.data} selected={automaticConsent} busy={automaticQuote.isFetching} error={automaticQuote.error ?? undefined} onChange={(requested, authorization) => {
            setReviewedApprovalKey("");
            setAutomaticChoice({ scope: automaticScope, requested, authorization });
          }} />}

          {job.data?.id === jobId && auroraApproval && job.data.plan?.validation_status === "invalid" && <div className="api-state api-state--error" role="alert"><p>当前方案尚未通过校验。请修正后重新审阅完整方案；旧审批内容不能用于此次修改。</p></div>}

          {resultAssets.length > 0 && <section className="detail-form-card">
            <div className="form-section-head"><span className="number-chip number-chip--violet">5</span><div><h2>生成结果</h2><p>所有已完成的图片会展示在这里，并支持后续下载。</p></div><span className="validation-chip"><CheckCircle2 size={15} />共 {resultAssets.length} 张</span></div>
            <div className="job-results-grid">{resultAssets.map((asset, index) => <JobResultImage key={`${asset.asset_id}-${asset.ordinal}`} workspaceId={workspace?.id} assetId={asset.asset_id} alt={`详情页生成结果 ${index + 1}`} label={`详情页 ${asset.ordinal + 1}`} />)}</div>
            {job.data?.status === "completed" && resultAssets.length === job.data.expected_item_count ? <JobDeliverablesDownload workspaceId={workspace?.id} jobId={job.data.id} /> : null}
          </section>}
          {isNativeDetail && ["awaiting_final_review", "completed"].includes(job.data?.status ?? "") && <>
            {finalReview.isPending && <div className="api-state"><LoaderCircle className="spin" /><p>正在核对当前成图和审核记录…</p></div>}
            {finalReview.error && <div className="api-state api-state--error" role="alert"><p>{errorMessage(finalReview.error)}</p><button onClick={() => void finalReview.refetch()}>重新核对审阅内容</button></div>}
            {job.data && <DomesticDetailCampaignReview key={`${workspace?.id}:${jobId}`} workspaceId={workspace?.id} source={job.data} fingerprint={currentFinalReview?.sha256} selected={activeCampaignChoice} canAttach={!originalAutomaticAuthority} onSelection={selection => {
              setReviewedFinalKey("");
              setCampaignChoice(selection ? { workspaceId: workspace?.id, sourceId: jobId, selection } : undefined);
            }} />}
            {currentFinalReview && <DomesticDetailFinalReview key={finalKey} review={currentFinalReview} workspaceId={workspace?.id} reviewed={finalReviewed} onReviewed={checked => setReviewedFinalKey(checked ? finalKey : "")} completed={job.data?.status === "completed"} />}
            {currentFinalReview && workspace?.id && <DomesticDetailLocalRevision key={`revision:${finalKey}`} workspaceId={workspace.id} review={currentFinalReview} />}
          </>}
          {job.data?.status === "completed" && workflow.mode === "mock" && resultAssets.length === 0 && <div className="api-state"><ImagePlus size={22} /><p>任务流程已完成，当前生成服务未返回图片结果。</p></div>}

          <section className="generation-footer">
            <div className="estimate-grid">
              <span><CircleDollarSign size={18} /><div><p>本次服务</p><strong>{workflow.mode === "provider" ? "在线生成 · 按套餐计费" : workflow.mode === "mock" ? "任务保存 · 暂不生成图片" : "服务暂不可用"}</strong></div></span>
              <span><Clock3 size={18} /><div><p>状态更新</p><strong>状态自动同步</strong></div></span>
              <span><ShieldCheck size={18} /><div><p>图片产物</p><strong>{workflow.canDeliverImages ? "已生成图片" : "暂无图片结果"}</strong></div></span>
            </div>
            <div className="generation-actions">
              <p><Info size={14} />{workflow.mode === "provider" ? "确认后将开始整套图片生成。" : workflow.mode === "mock" ? "确认后将保存任务计划，当前暂不生成图片。" : "生成服务状态确认中，确认入口暂时关闭。"}</p>
              {job.data && allowsJobAction(job.data.allowed_actions, "retry") ? (
                <button className="primary-button" onClick={() => void retry()} disabled={retryJob.isPending}>{retryJob.isPending ? <LoaderCircle className="spin" size={17} /> : <RotateCcw size={17} />}重试失败项目</button>
              ) : !jobId ? (
                <button className="primary-button" onClick={() => void createPlanningJob()} disabled={!workflowAvailable || !productSources.length || !productName.trim() || createJob.isPending}>{createJob.isPending ? <LoaderCircle className="spin" size={17} /> : <Upload size={17} />}{workflowAvailable ? workflow.mode === "provider" ? "创建套图规划" : "保存套图规划" : "服务状态确认中，暂不可创建"}<ArrowRight size={17} /></button>
              ) : job.data?.status === "awaiting_final_review" && originalAutomaticAuthority ? (
                <AutomaticDeliveryRecovery workspaceId={workspace?.id} job={job.data} authorization={originalAutomaticAuthority} />
              ) : job.data?.status === "awaiting_final_review" && allowsJobAction(job.data.allowed_actions, "finalize") ? (
                <button className="primary-button" onClick={() => { if (isNativeDetail && !finalReviewed) return; finalizeJob.mutate({ jobId: job.data!.id, allowedActions: job.data!.allowed_actions, approvalText: isNativeDetail ? NATIVE_DETAIL_FINAL_REVIEW_TEXT : "我已完成详情图逐 pair 最终审核并确认交付", finalReviewSha256: isNativeDetail ? currentFinalReview?.sha256 : undefined }); }} disabled={finalizeJob.isPending || (isNativeDetail && !finalReviewed)}>{finalizeJob.isPending ? <LoaderCircle className="spin" size={17} /> : <CheckCircle2 size={17} />}确认最终审核并交付<ArrowRight size={17} /></button>
              ) : job.data?.plan && workflowAvailable && allowsJobAction(job.data.allowed_actions, "confirm_plan") ? (
                <button className="primary-button" onClick={() => {
                  const aurora = job.data!.plan!.payload.aurora_v4_3 as Record<string, unknown> | undefined;
                  if (aurora && (!nativeReviewed || !automaticReady)) return;
                  confirmPlan.mutate({
                    ...(isNativeDetail && automaticRequested && automaticReady && automaticConsent ? { automaticDeliveryAuthorization: automaticConsent } : {}),
                    jobId: job.data!.id,
                    revision: job.data!.plan!.revision,
                    allowedActions: job.data!.allowed_actions,
                    approvalProtocol: nativeApproval?.version === "domestic-native-approval-v1" ? "domestic-native-approval-v1" : undefined,
                    nativeApprovalDocumentSha256: typeof nativeApproval?.document_sha256 === "string" ? nativeApproval.document_sha256 : undefined,
                    approvalText: aurora ? NATIVE_DETAIL_APPROVAL_TEXT : "我确认完整详情图审批包，并授权按 pair 逐组生成",
                    approvalDocumentSha256: typeof aurora?.approval_document_sha256 === "string" ? aurora.approval_document_sha256 : undefined,
                    approvedModuleCount: typeof aurora?.approved_module_count === "number" ? aurora.approved_module_count : undefined,
                    approvedPairCanvasAspectRatio: aurora?.approved_pair_canvas_aspect_ratio === "3:8" ? "3:8" : undefined,
                  });
                }} disabled={confirmPlan.isPending || Boolean(auroraApproval && (!nativeReviewed || !automaticReady))}>{confirmPlan.isPending ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}{workflow.mode === "provider" ? "确认并开始生成" : "确认并保存任务"}<ArrowRight size={17} /></button>
              ) : (
                <button className="primary-button" disabled><LoaderCircle className={job.data && ["queued", "planning", "processing"].includes(job.data.status) ? "spin" : ""} size={17} />{job.data ? jobNote(job.data) : "正在读取任务"}</button>
              )}
            </div>
          </section>
        </div>
        <HelpPanel
          mode="detail-pack"
          taskTitle={productName.trim() ? `${productName.trim()}详情套图` : "等待填写商品名称"}
          assetSummary={sources.length ? `${sources.length} 张 · 同一分组` : "尚未上传"}
          outputSummary={`${selectedMarketplace.name} · ${language === "zh-CN" ? "中文" : "English"} · ${pageCount} 页`}
        />
      </div>
    </AppShell>
  );
}
