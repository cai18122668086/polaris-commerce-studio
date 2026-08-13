"use client";

import { ArrowRight, Check, ImagePlus, LoaderCircle, ShieldCheck, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { DevelopmentProviderSettings } from "@/components/development-provider-settings";
import { JobDeliverablesDownload } from "@/components/job-deliverables-download";
import { JobResultImage } from "@/components/job-result-image";
import { StatusBadge } from "@/components/status-badge";
import { WorkspaceHeader } from "@/components/workspace-header";
import { useAssetAccessUrl, useUploadAsset } from "@/features/assets/api/assets";
import { useCloneJob, useConfirmPlan, useCreateJob, useJob } from "@/features/jobs/api/jobs";
import { presentWorkflow, useRuntimeStatus } from "@/features/runtime/api/runtime";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import type { Asset, DomesticMainImageJobCreate } from "@/lib/api/types";
import { errorMessage } from "@/lib/api/request";
import { IMAGE_UPLOAD_ACCEPT, IMAGE_UPLOAD_EXTENSIONS, IMAGE_UPLOAD_FORMAT_HINT, IMAGE_UPLOAD_MIME_TYPES } from "@/lib/image-upload";
import { allowsJobAction } from "@/lib/jobs/actions";
import { selectJobResultAssets } from "@/lib/jobs/results";
import styles from "./domestic-main-image-workspace.module.css";

type Source = { asset: Asset; previewUrl: string; fileKey: string };
type PlanPage = {
  page_index: number;
  page_role: string;
  main_selling_point: string;
  supporting_selling_points: string[];
  visual_proof: string;
  composition_and_subject: string;
  reading_path_and_type_hierarchy: string;
  non_repetition_reason: string;
  commercial_closure: string;
  buyer_question?: string;
};

type CampaignStyle = {
  palette_roles?: Record<string, string>;
  typography?: Record<string, string>;
  graphic_language?: string;
  information_surface_geometry?: string;
  photography_finish?: string;
  light_direction?: string;
  color_temperature?: string;
  density_band?: string;
};

type IdentityLock = {
  product_form?: string;
  identity_summary?: string;
  must_preserve?: string[];
  must_not_change?: string[];
};

const roleNames: Record<string, string> = {
  SEARCH_MAIN_IMAGE_LISTING_COVER: "搜索主图",
  CAROUSEL_IDENTITY_HERO: "身份英雄图",
  CAROUSEL_CORE_FEATURE_PROOF: "核心卖点证据",
  CAROUSEL_SCENE_OR_OPERATION: "场景 / 操作",
  CAROUSEL_DETAIL_OR_TRUST: "细节 / 信任",
  CAROUSEL_OFFER_OR_SPEC_CLOSURE: "权益 / 规格收口",
};

const MAX_SOURCE_IMAGES = 8;

function fileKey(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function isSupportedImage(file: File) {
  const lowerName = file.name.toLowerCase();
  return IMAGE_UPLOAD_MIME_TYPES.some((mimeType) => mimeType === file.type)
    || IMAGE_UPLOAD_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
}

function lines(value: string, limit: number) {
  return value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean).slice(0, limit);
}

function readPlan(payload?: Record<string, unknown>): PlanPage[] {
  if (!payload || !Array.isArray(payload.pages)) return [];
  return payload.pages.filter((page): page is PlanPage => Boolean(page && typeof page === "object"));
}

function recordValue<T>(payload: Record<string, unknown> | undefined, key: string): T | undefined {
  const value = payload?.[key];
  return value && typeof value === "object" && !Array.isArray(value) ? value as T : undefined;
}

function styleSummary(value?: Record<string, string>) {
  return value ? Object.values(value).filter(Boolean).join("；") : "由当前商品身份颜色与用户偏好共同推导";
}

function RestoredSource({ workspaceId, assetId, index }: { workspaceId?: string; assetId: string; index: number }) {
  const access = useAssetAccessUrl(workspaceId, assetId);
  return <figure>{access.data?.url ? <img src={access.data.url} alt={`商品素材 ${index + 1}`} /> : <LoaderCircle className="spin" size={20} />}<figcaption>证据 {String(index + 1).padStart(2, "0")}</figcaption></figure>;
}

export function DomesticMainImageWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedJobId = searchParams.get("jobId")?.trim() || undefined;
  const fileInput = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const sourcesRef = useRef<Source[]>([]);
  const { workspace } = useWorkspace();
  const upload = useUploadAsset(workspace?.id);
  const createJob = useCreateJob(workspace?.id);
  const confirmPlan = useConfirmPlan(workspace?.id);
  const cloneJob = useCloneJob(workspace?.id);
  const runtime = useRuntimeStatus();
  const workflow = presentWorkflow(
    runtime.data?.capabilities.features?.domestic_main_image,
  );
  const [sources, setSources] = useState<Source[]>([]);
  const [isDraggingFiles, setIsDraggingFiles] = useState(false);
  const [productName, setProductName] = useState("");
  const [category, setCategory] = useState("");
  const [sellingPoints, setSellingPoints] = useState("");
  const [scenes, setScenes] = useState("");
  const [trustFacts, setTrustFacts] = useState("");
  const [style, setStyle] = useState("");
  const [instruction, setInstruction] = useState("");
  const [createdJobId, setCreatedJobId] = useState<string>();
  const jobId = requestedJobId ?? createdJobId;
  const [localError, setLocalError] = useState<string>();
  const job = useJob(workspace?.id, jobId);
  const planPayload = job.data?.plan?.payload;
  const plan = readPlan(planPayload);
  const campaignStyle = recordValue<CampaignStyle>(planPayload, "campaign_style");
  const identityLock = recordValue<IdentityLock>(planPayload, "product_identity_lock");
  const restoredAssetIds = job.data?.assets.filter((asset) => asset.direction === "input" && asset.role === "product_identity_authority").sort((left, right) => left.ordinal - right.ordinal).map((asset) => asset.asset_id) ?? [];
  const restoredSettings = job.data?.configuration.settings && typeof job.data.configuration.settings === "object" ? job.data.configuration.settings as Record<string, unknown> : undefined;
  const restoredString = (key: string) => typeof restoredSettings?.[key] === "string" ? restoredSettings[key] as string : "";
  const restoredLines = (key: string) => Array.isArray(restoredSettings?.[key]) ? (restoredSettings[key] as unknown[]).map(String).join("\n") : "";
  const results = selectJobResultAssets(job.data);
  const providerReady = workflow.mode === "provider";
  const hasCompleteSet = results.length === 6;
  const showGeneration = Boolean(
    job.data && ["processing", "completed", "partial", "failed"].includes(job.data.status),
  );
  const busy = upload.isPending || createJob.isPending || confirmPlan.isPending || cloneJob.isPending;
  const canCreate = Boolean(
    !jobId && workspace && sources.length && productName.trim() && category.trim() && lines(sellingPoints, 24).length && workflow.canSubmit,
  );

  useEffect(() => {
    sourcesRef.current = sources;
  }, [sources]);

  useEffect(() => () => {
    sourcesRef.current.forEach((source) => URL.revokeObjectURL(source.previewUrl));
  }, []);

  async function addFiles(files: File[]) {
    setLocalError(undefined);
    const existingKeys = new Set(sources.map((source) => source.fileKey));
    const uniqueFiles = files.filter((file, index, batch) => (
      isSupportedImage(file)
      && !existingKeys.has(fileKey(file))
      && batch.findIndex((candidate) => fileKey(candidate) === fileKey(file)) === index
    ));
    const availableSlots = MAX_SOURCE_IMAGES - sources.length;
    const acceptedFiles = uniqueFiles.slice(0, availableSlots);
    const unsupportedCount = files.filter((file) => !isSupportedImage(file)).length;
    const duplicateCount = files.length - unsupportedCount - uniqueFiles.length;
    const overflowCount = Math.max(0, uniqueFiles.length - availableSlots);

    if (!acceptedFiles.length) {
      if (availableSlots <= 0) setLocalError(`最多只能上传 ${MAX_SOURCE_IMAGES} 张商品原图。`);
      else if (unsupportedCount) setLocalError(`${IMAGE_UPLOAD_FORMAT_HINT}。`);
      else if (duplicateCount) setLocalError("这些照片已经添加过了，无需重复上传。");
      return;
    }

    if (unsupportedCount || duplicateCount || overflowCount) {
      const skipped = [
        unsupportedCount ? `${unsupportedCount} 张格式不支持` : "",
        duplicateCount ? `${duplicateCount} 张重复照片` : "",
        overflowCount ? `${overflowCount} 张超过数量上限` : "",
      ].filter(Boolean).join("、");
      setLocalError(`已开始上传 ${acceptedFiles.length} 张；另有${skipped}，已跳过。`);
    }

    for (const file of acceptedFiles) {
      const previewUrl = URL.createObjectURL(file);
      try {
        const asset = await upload.mutateAsync({ file, mediaKind: "image" });
        setSources((current) => [...current, { asset, previewUrl, fileKey: fileKey(file) }]);
      } catch (error) {
        URL.revokeObjectURL(previewUrl);
        setLocalError(errorMessage(error));
      }
    }
  }

  function handleDragEnter(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (busy || !event.dataTransfer.types.includes("Files")) return;
    dragDepth.current += 1;
    setIsDraggingFiles(true);
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setIsDraggingFiles(false);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    dragDepth.current = 0;
    setIsDraggingFiles(false);
    if (busy) return;
    void addFiles(Array.from(event.dataTransfer.files));
  }

  function removeSource(id: string) {
    setSources((current) => {
      const removed = current.find((source) => source.asset.id === id);
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      return current.filter((source) => source.asset.id !== id);
    });
  }

  async function createPlan() {
    if (!canCreate) return;
    const body: DomesticMainImageJobCreate = {
      type: "domestic_main_image",
      intent: "submit",
      display_name: `国内主图六件套 · ${productName.trim()}`,
      input: { product_asset_ids: sources.map((source) => source.asset.id) },
      configuration: {
        product_name: productName.trim(),
        category: category.trim(),
        selling_points: lines(sellingPoints, 24),
        product_attributes: [],
        scenes: lines(scenes, 12),
        offers: [],
        service_or_trust_facts: lines(trustFacts, 12),
        style_preferences: lines(style, 12),
        instruction: instruction.trim(),
        language: "zh-CN",
      },
    };
    try {
      const created = await createJob.mutateAsync(body);
      setCreatedJobId(created.id);
      router.replace(`/workspace/domestic-main-image?jobId=${encodeURIComponent(created.id)}`);
    } catch (error) {
      setLocalError(errorMessage(error));
    }
  }

  async function rerunWithProvider() {
    if (!job.data || !allowsJobAction(job.data.allowed_actions, "clone")) return;
    try {
      const cloned = await cloneJob.mutateAsync({
        jobId: job.data.id,
        allowedActions: job.data.allowed_actions,
      });
      router.replace(`/workspace/domestic-main-image?jobId=${encodeURIComponent(cloned.id)}`);
    } catch (error) {
      setLocalError(errorMessage(error));
    }
  }

  return (
    <AppShell flush>
      <div className={styles.page}>
        <WorkspaceHeader
          eyebrow="AURORA · 国内电商六图连续创作"
          title="国内电商主图"
          description="先核实商品，再确认六图叙事。生成时严格逐张推进，每张最多自动修复一次。"
          meta={<span className={styles.secure}><ShieldCheck size={15} />Harness 全程接管</span>}
        />

        <div className={styles.rail} aria-label="工作流程">
          {["商品证据", "六图方案", "顺序生成", "整组确认"].map((label, index) => (
            <span key={label} data-active={(index === 0 && !jobId) || (index === 1 && job.data?.status === "awaiting_confirmation") || (index === 2 && job.data?.status === "processing") || (index === 3 && job.data?.status === "completed" && hasCompleteSet) || undefined}>
              <i>{index + 1}</i>{label}
            </span>
          ))}
        </div>

        <div className={styles.grid}>
          <main>
            <section className={styles.card}>
              <div className={styles.heading}><span>01</span><div><h2>商品身份权威素材</h2><p>上传真实商品多角度图。生成图不会被反过来当作身份依据。</p></div></div>
              {jobId ? <div className={styles.uploads}>{restoredAssetIds.map((assetId, index) => <RestoredSource key={assetId} workspaceId={workspace?.id} assetId={assetId} index={index} />)}</div> : <>
                {sources.length < MAX_SOURCE_IMAGES && <div
                  className={styles.dropZone}
                  data-dragging={isDraggingFiles || undefined}
                  data-uploading={upload.isPending || undefined}
                  onDragEnter={handleDragEnter}
                  onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                >
                  <input ref={fileInput} className={styles.fileInput} type="file" multiple accept={IMAGE_UPLOAD_ACCEPT} onChange={(event) => { const files = Array.from(event.currentTarget.files ?? []); event.currentTarget.value = ""; void addFiles(files); }} />
                  <button type="button" className={styles.dropAction} onClick={() => fileInput.current?.click()} disabled={busy}>
                    <span className={styles.dropIcon}>{upload.isPending ? <LoaderCircle className="spin" size={27} /> : <ImagePlus size={27} />}</span>
                    <span><strong>{upload.isPending ? "正在上传商品原图" : isDraggingFiles ? "松开即可加入这些照片" : "把多张商品原图拖到这里"}</strong><small>也可以点击选择 · {IMAGE_UPLOAD_FORMAT_HINT} · 最多 {MAX_SOURCE_IMAGES} 张</small></span>
                    <em>{sources.length} / {MAX_SOURCE_IMAGES}</em>
                  </button>
                </div>}
                {sources.length > 0 && <div className={styles.uploads} aria-live="polite">{sources.map((source, index) => <figure key={source.asset.id}><img src={source.previewUrl} alt={`商品素材 ${index + 1}`} /><figcaption>证据 {String(index + 1).padStart(2, "0")}</figcaption><button type="button" onClick={() => removeSource(source.asset.id)} aria-label={`移除商品素材 ${index + 1}`}><X size={14} /></button></figure>)}</div>}
              </>}
            </section>

            <section className={styles.card}>
              <div className={styles.heading}><span>02</span><div><h2>已核实的商品事实</h2><p>这里只写能够从素材或业务资料确认的内容，避免不实参数与承诺。</p></div></div>
              <div className={styles.form}>
                <label><span>商品名称 *</span><input disabled={Boolean(jobId)} value={jobId ? restoredString("product_name") : productName} onChange={(event) => setProductName(event.target.value)} placeholder="例如：轻量保温随行杯" /></label>
                <label><span>商品类目 *</span><input disabled={Boolean(jobId)} value={jobId ? restoredString("category") : category} onChange={(event) => setCategory(event.target.value)} placeholder="例如：杯壶 / 保温杯" /></label>
                <label className={styles.full}><span>核心卖点 * <small>换行分隔</small></span><textarea disabled={Boolean(jobId)} value={jobId ? restoredLines("selling_points") : sellingPoints} onChange={(event) => setSellingPoints(event.target.value)} placeholder={'轻量便携\n杯盖防误开\n食品接触级内胆'} /></label>
                <label><span>真实使用场景</span><textarea disabled={Boolean(jobId)} value={jobId ? restoredLines("scenes") : scenes} onChange={(event) => setScenes(event.target.value)} placeholder="通勤、办公室、短途出行" /></label>
                <label><span>服务或信任事实</span><textarea disabled={Boolean(jobId)} value={jobId ? restoredLines("service_or_trust_facts") : trustFacts} onChange={(event) => setTrustFacts(event.target.value)} placeholder="仅填写能够证实的检测、质保或服务" /></label>
                <label><span>视觉偏好</span><textarea disabled={Boolean(jobId)} value={jobId ? restoredLines("style_preferences") : style} onChange={(event) => setStyle(event.target.value)} placeholder="克制、高级、暖灰背景、清晰商品轮廓" /></label>
                <label><span>补充要求</span><textarea disabled={Boolean(jobId)} value={jobId ? restoredString("instruction") : instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="不能改变的结构、Logo、颜色或包装信息" /></label>
              </div>
            </section>

            <section className={styles.card}>
              <div className={styles.heading}><span>03</span><div><h2>六图方案确认</h2><p>确认后锁定商品身份、事实边界和整套视觉世界。</p></div>{job.data && <StatusBadge status={job.data.status} />}</div>
              {!plan.length ? <div className={styles.empty}>创建任务后，Aurora 会先分析商品并锁定身份，再编译 1 张搜索主图与 5 张轮播图的完整方案。</div> : <>
                <div className={styles.identityLock}>
                  <span>PRODUCT IDENTITY LOCK</span>
                  <h3>{identityLock?.product_form ?? "当前商品身份已锁定"}</h3>
                  <p>{identityLock?.identity_summary}</p>
                  <div><strong>必须保持</strong><p>{identityLock?.must_preserve?.join("；")}</p></div>
                  <div><strong>禁止改变</strong><p>{identityLock?.must_not_change?.join("；")}</p></div>
                </div>

                <div className={styles.campaignWorld}>
                  <div className={styles.worldTitle}><span>整组视觉世界</span><strong>六张图共享一套美术方向，版式与镜头按页面职责变化</strong></div>
                  <dl>
                    <div><dt>色彩角色</dt><dd>{styleSummary(campaignStyle?.palette_roles)}</dd></div>
                    <div><dt>字体气质</dt><dd>{styleSummary(campaignStyle?.typography)}</dd></div>
                    <div><dt>图形 / 信息面</dt><dd>{campaignStyle?.graphic_language}；{campaignStyle?.information_surface_geometry}</dd></div>
                    <div><dt>摄影完成度</dt><dd>{campaignStyle?.photography_finish}</dd></div>
                    <div><dt>光线与色温</dt><dd>{campaignStyle?.light_direction}；{campaignStyle?.color_temperature}</dd></div>
                    <div><dt>整组密度节奏</dt><dd>{campaignStyle?.density_band}</dd></div>
                  </dl>
                </div>

                <div className={styles.contractLegend} aria-label="六页执行契约字段">
                  <span>主卖点</span><span>辅助卖点</span><span>画面证明</span><span>构图与主体</span><span>阅读路径</span><span>不重复理由</span><span>商业闭合</span>
                </div>
                <div className={styles.plan}>{plan.map((page) => <article key={page.page_index}><i>{String(page.page_index + 1).padStart(2, "0")}</i><div><span>{roleNames[page.page_role] ?? page.page_role}</span><strong>{page.main_selling_point}</strong>{page.buyer_question && <p>{page.buyer_question}</p>}<dl>
                  <div><dt>主卖点</dt><dd>{page.main_selling_point}</dd></div>
                  <div><dt>辅助卖点</dt><dd>{page.supporting_selling_points?.length ? page.supporting_selling_points.join(" · ") : "无强制辅助卖点，按画面需要取舍"}</dd></div>
                  <div><dt>画面证明</dt><dd>{page.visual_proof}</dd></div>
                  <div><dt>构图主体</dt><dd>{page.composition_and_subject}</dd></div>
                  <div><dt>阅读路径</dt><dd>{page.reading_path_and_type_hierarchy}</dd></div>
                  <div><dt>不重复</dt><dd>{page.non_repetition_reason}</dd></div>
                  <div><dt>商业闭合</dt><dd>{page.commercial_closure}</dd></div>
                </dl></div>{page.page_index === 0 ? <em>搜索入口</em> : <em>轮播</em>}</article>)}</div>
              </>}
            </section>

            {showGeneration && <section className={styles.card}><div className={styles.heading}><span>04</span><div><h2>逐张生成进度</h2><p>严格按页顺序生成与审图，六张全部完成后才进入整组确认。</p></div></div><div className={styles.generationProgress}><strong>{results.length} / 6 张真实图片</strong><div>{job.data!.items.map((item) => <span key={item.id} data-status={item.status}><i>{String(item.ordinal + 1).padStart(2, "0")}</i>{roleNames[plan[item.ordinal]?.page_role] ?? `图 ${item.ordinal + 1}`}<em>{item.result_source === "generated" ? "已生成" : item.status === "running" ? "生成中" : item.status === "failed" ? "失败" : item.status === "succeeded" ? "无图片结果" : "等待"}</em></span>)}</div></div>{job.data?.status === "completed" && !hasCompleteSet && <div className={styles.mockWarning}><strong>没有生成真实图片</strong><p>这条任务由安全 Mock 执行，只模拟了六页状态，不能进入整组图片确认。启用真实 Provider 后请重新运行任务。</p></div>}</section>}

            {results.length > 0 && <section className={styles.card}><div className={styles.heading}><span>05</span><div><h2>六图交付</h2><p>单张可查看与下载，全部完成后可下载整套文件。</p></div></div><div className={styles.results}>{results.map((asset, index) => <JobResultImage key={asset.asset_id} workspaceId={workspace?.id} assetId={asset.asset_id} alt={`国内电商主图 ${index + 1}`} label={roleNames[plan[index]?.page_role] ?? `图 ${index + 1}`} />)}</div>{job.data?.status === "completed" && hasCompleteSet && <JobDeliverablesDownload workspaceId={workspace?.id} jobId={job.data.id} />}</section>}
          </main>

          <aside className={styles.side}>
            <div><span>AURORA / 06</span><h3>连续创作约束</h3><ul><li><Check size={15} />固定六张，不增不减</li><li><Check size={15} />严格按页顺序生成</li><li><Check size={15} />每页最多自动修复一次</li><li><Check size={15} />最终整组等待人工确认</li></ul></div>
            {localError || createJob.error || confirmPlan.error || cloneJob.error ? <p className={styles.error}>{localError ?? errorMessage(createJob.error ?? confirmPlan.error ?? cloneJob.error)}</p> : null}
            {runtime.data?.environment === "development" && <DevelopmentProviderSettings />}
            {!jobId ? <button className={styles.primary} disabled={!canCreate || busy} onClick={() => void createPlan()}>{busy ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}生成六图方案<ArrowRight size={17} /></button> : job.data?.status === "completed" && !hasCompleteSet && providerReady && allowsJobAction(job.data.allowed_actions, "clone") ? <button className={styles.primary} disabled={cloneJob.isPending} onClick={() => void rerunWithProvider()}>{cloneJob.isPending ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}使用真实服务重新运行<ArrowRight size={17} /></button> : job.data?.plan && allowsJobAction(job.data.allowed_actions, "confirm_plan") && providerReady ? <button className={styles.primary} disabled={confirmPlan.isPending} onClick={() => confirmPlan.mutate({ jobId: job.data!.id, revision: job.data!.plan!.revision, allowedActions: job.data!.allowed_actions, approvalText: "我确认当前六图规划，并授权按 Aurora Skill 逐张生成、审图及执行每页至多一次自动修复。" })}>{confirmPlan.isPending ? <LoaderCircle className="spin" size={17} /> : <ShieldCheck size={17} />}确认方案并开始<ArrowRight size={17} /></button> : <button className={styles.primary} disabled><LoaderCircle className={job.data && ["queued", "planning", "processing"].includes(job.data.status) ? "spin" : ""} size={17} />{job.data?.status === "completed" && hasCompleteSet ? "等待整组确认" : job.data?.status === "completed" ? "未生成真实图片" : workflow.mode === "mock" && job.data?.status === "awaiting_confirmation" ? "真实生成服务未启用" : "任务处理中"}</button>}
            <small className={styles.note}>{providerReady ? "在线生成已启用；确认后将按 Skill 逐张生成与审图" : "当前为安全 Mock：只允许编译和查看规划，不会授权生图或产生图片费用"}</small>
          </aside>
        </div>
      </div>
    </AppShell>
  );
}
