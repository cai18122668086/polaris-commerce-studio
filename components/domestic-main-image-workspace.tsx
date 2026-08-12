"use client";

import { ArrowRight, Check, ImagePlus, LoaderCircle, ShieldCheck, Sparkles, X } from "lucide-react";
import { useRef, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { JobDeliverablesDownload } from "@/components/job-deliverables-download";
import { JobResultImage } from "@/components/job-result-image";
import { StatusBadge } from "@/components/status-badge";
import { WorkspaceHeader } from "@/components/workspace-header";
import { useUploadAsset } from "@/features/assets/api/assets";
import { useConfirmPlan, useCreateJob, useJob } from "@/features/jobs/api/jobs";
import { presentWorkflow, useRuntimeStatus } from "@/features/runtime/api/runtime";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import type { Asset, DomesticMainImageJobCreate } from "@/lib/api/types";
import { errorMessage } from "@/lib/api/request";
import { IMAGE_UPLOAD_ACCEPT } from "@/lib/image-upload";
import { allowsJobAction } from "@/lib/jobs/actions";
import { selectJobResultAssets } from "@/lib/jobs/results";
import styles from "./domestic-main-image-workspace.module.css";

type Source = { asset: Asset; previewUrl: string };
type PlanPage = {
  page_index: number;
  page_role: string;
  headline: string;
  visual_duty: string;
  objective?: string;
  composition?: string;
  copy_direction?: string;
  evidence?: string[];
};

const roleNames: Record<string, string> = {
  SEARCH_MAIN_IMAGE_LISTING_COVER: "搜索主图",
  CAROUSEL_IDENTITY_HERO: "身份英雄图",
  CAROUSEL_CORE_FEATURE_PROOF: "核心卖点证据",
  CAROUSEL_SCENE_OR_OPERATION: "场景 / 操作",
  CAROUSEL_DETAIL_OR_TRUST: "细节 / 信任",
  CAROUSEL_OFFER_OR_SPEC_CLOSURE: "权益 / 规格收口",
};

function lines(value: string, limit: number) {
  return value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean).slice(0, limit);
}

function readPlan(payload?: Record<string, unknown>): PlanPage[] {
  if (!payload || !Array.isArray(payload.pages)) return [];
  return payload.pages.filter((page): page is PlanPage => Boolean(page && typeof page === "object"));
}

export function DomesticMainImageWorkspace() {
  const fileInput = useRef<HTMLInputElement>(null);
  const { workspace } = useWorkspace();
  const upload = useUploadAsset(workspace?.id);
  const createJob = useCreateJob(workspace?.id);
  const confirmPlan = useConfirmPlan(workspace?.id);
  const runtime = useRuntimeStatus();
  const workflow = presentWorkflow(
    runtime.data?.capabilities.features?.domestic_main_image,
  );
  const [sources, setSources] = useState<Source[]>([]);
  const [productName, setProductName] = useState("");
  const [category, setCategory] = useState("");
  const [sellingPoints, setSellingPoints] = useState("");
  const [scenes, setScenes] = useState("");
  const [trustFacts, setTrustFacts] = useState("");
  const [style, setStyle] = useState("");
  const [instruction, setInstruction] = useState("");
  const [jobId, setJobId] = useState<string>();
  const [localError, setLocalError] = useState<string>();
  const job = useJob(workspace?.id, jobId);
  const plan = readPlan(job.data?.plan?.payload);
  const results = selectJobResultAssets(job.data);
  const busy = upload.isPending || createJob.isPending || confirmPlan.isPending;
  const canCreate = Boolean(
    workspace && sources.length && productName.trim() && category.trim() && lines(sellingPoints, 24).length && workflow.canSubmit,
  );

  async function addFiles(files: File[]) {
    setLocalError(undefined);
    for (const file of files.slice(0, 8 - sources.length)) {
      const previewUrl = URL.createObjectURL(file);
      try {
        const asset = await upload.mutateAsync({ file, mediaKind: "image" });
        setSources((current) => [...current, { asset, previewUrl }]);
      } catch (error) {
        URL.revokeObjectURL(previewUrl);
        setLocalError(errorMessage(error));
      }
    }
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
      setJobId(created.id);
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
            <span key={label} data-active={(index === 0 && !jobId) || (index === 1 && job.data?.status === "awaiting_confirmation") || (index === 2 && job.data?.status === "processing") || (index === 3 && job.data?.status === "completed") || undefined}>
              <i>{index + 1}</i>{label}
            </span>
          ))}
        </div>

        <div className={styles.grid}>
          <main>
            <section className={styles.card}>
              <div className={styles.heading}><span>01</span><div><h2>商品身份权威素材</h2><p>上传真实商品多角度图。生成图不会被反过来当作身份依据。</p></div></div>
              <div className={styles.uploads}>
                {sources.map((source, index) => <figure key={source.asset.id}><img src={source.previewUrl} alt={`商品素材 ${index + 1}`} /><figcaption>证据 {String(index + 1).padStart(2, "0")}</figcaption><button onClick={() => removeSource(source.asset.id)} aria-label="移除素材"><X size={14} /></button></figure>)}
                {sources.length < 8 && <button className={styles.add} onClick={() => fileInput.current?.click()} disabled={busy}><ImagePlus size={25} /><strong>添加真实商品图</strong><small>最多 8 张</small></button>}
                <input ref={fileInput} hidden type="file" multiple accept={IMAGE_UPLOAD_ACCEPT} onChange={(event) => { const files = Array.from(event.currentTarget.files ?? []); event.currentTarget.value = ""; void addFiles(files); }} />
              </div>
            </section>

            <section className={styles.card}>
              <div className={styles.heading}><span>02</span><div><h2>已核实的商品事实</h2><p>这里只写能够从素材或业务资料确认的内容，避免不实参数与承诺。</p></div></div>
              <div className={styles.form}>
                <label><span>商品名称 *</span><input value={productName} onChange={(event) => setProductName(event.target.value)} placeholder="例如：轻量保温随行杯" /></label>
                <label><span>商品类目 *</span><input value={category} onChange={(event) => setCategory(event.target.value)} placeholder="例如：杯壶 / 保温杯" /></label>
                <label className={styles.full}><span>核心卖点 * <small>换行分隔</small></span><textarea value={sellingPoints} onChange={(event) => setSellingPoints(event.target.value)} placeholder={'轻量便携\n杯盖防误开\n食品接触级内胆'} /></label>
                <label><span>真实使用场景</span><textarea value={scenes} onChange={(event) => setScenes(event.target.value)} placeholder="通勤、办公室、短途出行" /></label>
                <label><span>服务或信任事实</span><textarea value={trustFacts} onChange={(event) => setTrustFacts(event.target.value)} placeholder="仅填写能够证实的检测、质保或服务" /></label>
                <label><span>视觉偏好</span><textarea value={style} onChange={(event) => setStyle(event.target.value)} placeholder="克制、高级、暖灰背景、清晰商品轮廓" /></label>
                <label><span>补充要求</span><textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="不能改变的结构、Logo、颜色或包装信息" /></label>
              </div>
            </section>

            <section className={styles.card}>
              <div className={styles.heading}><span>03</span><div><h2>六图方案确认</h2><p>确认后锁定商品身份、事实边界和整套视觉世界。</p></div>{job.data && <StatusBadge status={job.data.status} />}</div>
              {!plan.length ? <div className={styles.empty}>创建任务后，这里会出现 1 张搜索主图与 5 张轮播图方案。</div> : <div className={styles.plan}>{plan.map((page) => <article key={page.page_index}><i>{String(page.page_index + 1).padStart(2, "0")}</i><div><span>{roleNames[page.page_role] ?? page.page_role}</span><strong>{page.headline}</strong><p>{page.objective ?? page.visual_duty}</p>{page.composition && <dl><div><dt>画面</dt><dd>{page.composition}</dd></div>{page.copy_direction && <div><dt>文案</dt><dd>{page.copy_direction}</dd></div>}{page.evidence?.length ? <div><dt>依据</dt><dd>{page.evidence.join(" · ")}</dd></div> : null}</dl>}</div>{page.page_index === 0 ? <em>搜索入口</em> : <em>轮播</em>}</article>)}</div>}
            </section>

            {results.length > 0 && <section className={styles.card}><div className={styles.heading}><span>04</span><div><h2>六图交付</h2><p>单张可查看与下载，全部完成后可下载整套文件。</p></div></div><div className={styles.results}>{results.map((asset, index) => <JobResultImage key={asset.asset_id} workspaceId={workspace?.id} assetId={asset.asset_id} alt={`国内电商主图 ${index + 1}`} label={roleNames[plan[index]?.page_role] ?? `图 ${index + 1}`} />)}</div>{job.data?.status === "completed" && results.length === 6 && <JobDeliverablesDownload workspaceId={workspace?.id} jobId={job.data.id} />}</section>}
          </main>

          <aside className={styles.side}>
            <div><span>AURORA / 06</span><h3>连续创作约束</h3><ul><li><Check size={15} />固定六张，不增不减</li><li><Check size={15} />严格按页顺序生成</li><li><Check size={15} />每页最多自动修复一次</li><li><Check size={15} />最终整组等待人工确认</li></ul></div>
            {localError || createJob.error || confirmPlan.error ? <p className={styles.error}>{localError ?? errorMessage(createJob.error ?? confirmPlan.error)}</p> : null}
            {!jobId ? <button className={styles.primary} disabled={!canCreate || busy} onClick={() => void createPlan()}>{busy ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}生成六图方案<ArrowRight size={17} /></button> : job.data?.plan && allowsJobAction(job.data.allowed_actions, "confirm_plan") ? <button className={styles.primary} disabled={confirmPlan.isPending} onClick={() => confirmPlan.mutate({ jobId: job.data!.id, revision: job.data!.plan!.revision, allowedActions: job.data!.allowed_actions })}>{confirmPlan.isPending ? <LoaderCircle className="spin" size={17} /> : <ShieldCheck size={17} />}确认方案并开始<ArrowRight size={17} /></button> : <button className={styles.primary} disabled><LoaderCircle className={job.data && ["queued", "planning", "processing"].includes(job.data.status) ? "spin" : ""} size={17} />{job.data?.status === "completed" ? "等待整组确认" : "任务处理中"}</button>}
            <small className={styles.note}>{workflow.mode === "provider" ? "在线生成已启用" : "当前为安全 Mock：可验证完整规划与状态流程，不会产生图片费用"}</small>
          </aside>
        </div>
      </div>
    </AppShell>
  );
}
