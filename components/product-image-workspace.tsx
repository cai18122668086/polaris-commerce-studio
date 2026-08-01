"use client";

import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  ImagePlus,
  Info,
  LoaderCircle,
  Palette,
  RefreshCcw,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { AssetLibraryPicker } from "@/components/asset-library-picker";
import { ResultGrid } from "@/components/result-grid";
import { StatusBadge } from "@/components/status-badge";
import { WorkspaceHeader } from "@/components/workspace-header";
import { useUploadAsset } from "@/features/assets/api/assets";
import { useCreateJob, useJob } from "@/features/jobs/api/jobs";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { errorMessage } from "@/lib/api/request";
import type { ProductImageJobCreate } from "@/lib/api/types";
import {
  PRODUCT_IMAGE_FEATURES,
  getProductImageFeatureByPresetSlug
} from "@/lib/feature-registry";
import { selectJobResultAssets } from "@/lib/jobs/results";
import {
  presentWorkflow,
  resolveRuntimeCapability,
  useRuntimeStatus,
} from "@/features/runtime/api/runtime";
import styles from "./product-image-workspace.module.css";

type AspectRatio = "1:1" | "3:4" | "4:3" | "9:16" | "16:9";

const aspectRatios: { value: AspectRatio; label: string; note: string }[] = [
  { value: "1:1", label: "1:1", note: "方形主图" },
  { value: "3:4", label: "3:4", note: "电商竖图" },
  { value: "4:3", label: "4:3", note: "横向展示" },
  { value: "9:16", label: "9:16", note: "短视频封面" },
  { value: "16:9", label: "16:9", note: "横屏视觉" },
];

const platforms = [
  { value: "tmall", label: "天猫 / 淘宝" },
  { value: "jd", label: "京东" },
  { value: "douyin", label: "抖音电商" },
  { value: "xiaohongshu", label: "小红书" },
  { value: "amazon-us", label: "Amazon US" },
  { value: "generic", label: "通用渠道" },
];

function UploadPanel({
  title,
  description,
  count,
  required,
  uploading,
  onFiles,
}: {
  title: string;
  description: string;
  count: number;
  required?: boolean;
  uploading: boolean;
  onFiles: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className={styles.uploadPanel}>
      <div className={styles.uploadIcon}><ImagePlus size={22} /></div>
      <div className={styles.uploadCopy}>
        <div>
          <strong>{title}</strong>
          {required ? <span>必填</span> : <span data-optional>可选</span>}
        </div>
        <p>{description}</p>
        <small>{count ? `已选择 ${count} 张素材` : "支持 JPG、PNG、WebP"}</small>
      </div>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
      >
        {uploading ? <LoaderCircle className="spin" size={16} /> : <Upload size={16} />}
        本地上传
      </button>
      <input
        ref={inputRef}
        className={styles.hiddenInput}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        multiple
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files ?? []);
          event.currentTarget.value = "";
          if (files.length) onFiles(files);
        }}
      />
    </div>
  );
}

export function ProductImageWorkspace({ preset }: { preset: string }) {
  const router = useRouter();
  const feature = getProductImageFeatureByPresetSlug(preset);
  const { workspace, isPending: workspacePending, error: workspaceError } = useWorkspace();
  const upload = useUploadAsset(workspace?.id);
  const [productAssetIds, setProductAssetIds] = useState<string[]>([]);
  const [referenceAssetIds, setReferenceAssetIds] = useState<string[]>([]);
  const [platformCode, setPlatformCode] = useState("tmall");
  const [aspectRatio, setAspectRatio] = useState<AspectRatio>("1:1");
  const [imageCount, setImageCount] = useState(1);
  const [instruction, setInstruction] = useState("");
  const [targetColor, setTargetColor] = useState("");
  const [jobId, setJobId] = useState<string>();
  const [uiError, setUiError] = useState<string>();
  const runtime = useRuntimeStatus();
  const capability = resolveRuntimeCapability(runtime.data, feature?.runtimeCapability ?? "product_image");
  const workflow = presentWorkflow(capability);
  const createJob = useCreateJob(workspace?.id);
  const job = useJob(workspace?.id, jobId);
  const resultAssets = selectJobResultAssets(job.data);
  const requestError = workspaceError ?? upload.error ?? job.error;

  const progressText = useMemo(() => {
    if (!job.data) return "任务创建后将自动轮询状态";
    return `${job.data.succeeded_item_count} / ${job.data.expected_item_count} 项完成`;
  }, [job.data]);

  if (!feature) return null;
  const FeatureIcon = feature.icon;

  const addUploadedAssets = async (files: File[], role: "product" | "reference") => {
    setUiError(undefined);
    try {
      const uploadedIds: string[] = [];
      for (const file of files.slice(0, 8)) {
        const asset = await upload.mutateAsync({ file, mediaKind: "image" });
        uploadedIds.push(asset.id);
      }
      if (role === "product") {
        setProductAssetIds((current) =>
          [...new Set([...current, ...uploadedIds])].slice(0, 8),
        );
        setReferenceAssetIds((current) =>
          current.filter((id) => !uploadedIds.includes(id)),
        );
      } else {
        setReferenceAssetIds((current) =>
          [...new Set([...current, ...uploadedIds])].slice(0, 8),
        );
        setProductAssetIds((current) =>
          current.filter((id) => !uploadedIds.includes(id)),
        );
      }
    } catch (error) {
      setUiError(errorMessage(error));
    }
  };

  const targetColorMissing = feature.taskPreset === "change_color" && !targetColor.trim();
  const canSubmit = Boolean(
    workspace &&
    productAssetIds.length &&
    !targetColorMissing &&
    workflow.canSubmit &&
    !runtime.isPending &&
    !upload.isPending &&
    !createJob.isPending,
  );

  const submit = async () => {
    if (!canSubmit) return;
    setUiError(undefined);
    const body: ProductImageJobCreate = {
      type: "product_image",
      intent: "submit",
      display_name: feature.title,
      input: {
        product_asset_ids: productAssetIds,
        reference_asset_ids: referenceAssetIds,
      },
      configuration: {
        task_type: feature.taskPreset,
        platform_code: platformCode,
        aspect_ratio: aspectRatio,
        image_count: imageCount,
        instruction: instruction.trim(),
        ...(feature.taskPreset === "change_color"
          ? { target_color: targetColor.trim() }
          : {}),
      },
    };
    try {
      const created = await createJob.mutateAsync(body);
      setJobId(created.id);
    } catch (error) {
      setUiError(errorMessage(error));
    }
  };

  const resetTask = () => {
    setJobId(undefined);
    setUiError(undefined);
    createJob.reset();
  };

  return (
    <AppShell flush sidebar={false}>
      <div className={styles.workspacePage}>
        <WorkspaceHeader
          eyebrow="万能生图 · 统一工作台"
          title={feature.title}
          description={feature.description}
          meta={
            <span className={styles.safetyBadge}>
              <ShieldCheck size={15} /> 素材与任务 API 隔离
            </span>
          }
        />

        <nav className={styles.stepBar} aria-label="创作步骤">
          {[
            ["01", "选择素材"],
            ["02", "生成设置"],
            ["03", "创建任务"],
            ["04", "交付结果"],
          ].map(([number, label], index) => (
            <span
              key={number}
              data-active={
                index === 0 ||
                (index === 1 && productAssetIds.length > 0) ||
                (index >= 2 && Boolean(jobId)) ||
                undefined
              }
            >
              <i>{number}</i>{label}
            </span>
          ))}
        </nav>

        <div className={styles.workspaceGrid}>
          <main className={styles.mainColumn}>
            <section className={styles.card}>
              <div className={styles.sectionHeading}>
                <div>
                  <span>01</span>
                  <div><h2>选择创作素材</h2><p>支持本地上传和当前工作区素材库。</p></div>
                </div>
                <strong>{productAssetIds.length + referenceAssetIds.length} 张已选</strong>
              </div>

              <div className={styles.uploadGrid}>
                <UploadPanel
                  title="商品图"
                  description="上传清晰、主体完整的商品参考图，可提供多个角度。"
                  count={productAssetIds.length}
                  required
                  uploading={upload.isPending}
                  onFiles={(files) => void addUploadedAssets(files, "product")}
                />
                <UploadPanel
                  title="参考图"
                  description="可选场景、背景、模特或颜色参考，不会替代商品主体。"
                  count={referenceAssetIds.length}
                  uploading={upload.isPending}
                  onFiles={(files) => void addUploadedAssets(files, "reference")}
                />
              </div>

              <AssetLibraryPicker
                workspaceId={workspace?.id}
                title="从素材库选择商品图"
                description="至少选择 1 张，最多 8 张。"
                selectedIds={productAssetIds}
                excludedIds={referenceAssetIds}
                onChange={setProductAssetIds}
                disabled={Boolean(jobId)}
              />
              <AssetLibraryPicker
                workspaceId={workspace?.id}
                title="从素材库选择可选参考图"
                description="用于提供场景、风格、模特或颜色线索。"
                selectedIds={referenceAssetIds}
                excludedIds={productAssetIds}
                onChange={setReferenceAssetIds}
                disabled={Boolean(jobId)}
              />
            </section>

            <section className={styles.card}>
              <div className={styles.sectionHeading}>
                <div>
                  <span>02</span>
                  <div><h2>配置生成任务</h2><p>8 个入口共用同一个 product_image Job contract。</p></div>
                </div>
                <strong>{feature.shortTitle}</strong>
              </div>

              <div className={styles.formGrid}>
                <label>
                  <span>功能 preset</span>
                  <select
                    value={feature.presetSlug}
                    onChange={(event) =>
                      router.push(`/workspace/product-image/${event.target.value}`)
                    }
                    disabled={Boolean(jobId)}
                  >
                    {PRODUCT_IMAGE_FEATURES.map((item) => (
                      <option key={item.taskPreset} value={item.presetSlug}>{item.title}</option>
                    ))}
                  </select>
                  <small>路由会映射为后端 task_type：{feature.taskPreset}</small>
                </label>
                <label>
                  <span>目标平台</span>
                  <select
                    value={platformCode}
                    onChange={(event) => setPlatformCode(event.target.value)}
                    disabled={Boolean(jobId)}
                  >
                    {platforms.map((platform) => (
                      <option key={platform.value} value={platform.value}>{platform.label}</option>
                    ))}
                  </select>
                  <small>用于约束构图、留白和渠道风格。</small>
                </label>
              </div>

              <fieldset className={styles.optionGroup} disabled={Boolean(jobId)}>
                <legend>画面比例</legend>
                <div className={styles.ratioGrid}>
                  {aspectRatios.map((ratio) => (
                    <label key={ratio.value} data-selected={aspectRatio === ratio.value || undefined}>
                      <input
                        type="radio"
                        name="aspect-ratio"
                        value={ratio.value}
                        checked={aspectRatio === ratio.value}
                        onChange={() => setAspectRatio(ratio.value)}
                      />
                      <strong>{ratio.label}</strong>
                      <small>{ratio.note}</small>
                    </label>
                  ))}
                </div>
              </fieldset>

              <fieldset className={styles.optionGroup} disabled={Boolean(jobId)}>
                <legend>生成数量</legend>
                <div className={styles.countOptions}>
                  {[1, 2, 3, 4].map((count) => (
                    <label key={count} data-selected={imageCount === count || undefined}>
                      <input
                        type="radio"
                        name="image-count"
                        value={count}
                        checked={imageCount === count}
                        onChange={() => setImageCount(count)}
                      />
                      <strong>{count}</strong><span>张</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              {feature.taskPreset === "change_color" ? (
                <label className={styles.colorField}>
                  <span><Palette size={16} />目标颜色 <i>必填</i></span>
                  <input
                    value={targetColor}
                    onChange={(event) => setTargetColor(event.target.value)}
                    placeholder="例如：Pantone 186 C、哑光酒红色、#B31942"
                    disabled={Boolean(jobId)}
                    aria-invalid={targetColorMissing}
                  />
                  <small>可输入色名、色号或颜色描述；为空时不会创建任务。</small>
                </label>
              ) : null}

              <label className={styles.instructionField}>
                <span>补充要求</span>
                <textarea
                  value={instruction}
                  onChange={(event) => setInstruction(event.target.value)}
                  placeholder={feature.guidance}
                  rows={5}
                  maxLength={4000}
                  disabled={Boolean(jobId)}
                />
                <small>{instruction.length} / 4000 · {feature.guidance}</small>
              </label>
            </section>

            {jobId ? (
              <section className={styles.card}>
                <div className={styles.sectionHeading}>
                  <div>
                    <span>03</span>
                    <div><h2>任务状态</h2><p>任务详情约每 1.5 秒自动轮询。</p></div>
                  </div>
                  {job.data ? <StatusBadge status={job.data.status} /> : null}
                </div>
                {job.isPending ? (
                  <div className={styles.jobState}><LoaderCircle className="spin" />正在读取任务…</div>
                ) : job.error ? (
                  <div className={styles.jobError} role="alert">{errorMessage(job.error)}</div>
                ) : job.data ? (
                  <div className={styles.jobPanel}>
                    <div className={styles.progressRow}>
                      <div>
                        <strong>{progressText}</strong>
                        <span>{job.data.stage ? `当前阶段：${job.data.stage}` : "等待执行器更新阶段"}</span>
                      </div>
                      <em>{Math.round(job.data.progress)}%</em>
                    </div>
                    <div className={styles.progressTrack} aria-label={`任务进度 ${Math.round(job.data.progress)}%`}>
                      <i style={{ width: `${Math.max(0, Math.min(100, job.data.progress))}%` }} />
                    </div>
                    <div className={styles.itemGrid}>
                      {job.data.items.map((item) => (
                        <span key={item.id} data-status={item.status}>
                          <i /> {item.item_key}
                        </span>
                      ))}
                    </div>
                    {job.data.error_message ? (
                      <div className={styles.jobError} role="alert">{job.data.error_message}</div>
                    ) : null}
                  </div>
                ) : null}
              </section>
            ) : null}

            <ResultGrid
              workspaceId={workspace?.id}
              assets={resultAssets}
              expectedCount={job.data?.expected_item_count ?? imageCount}
              title={`${feature.title}结果`}
            />
          </main>

          <aside className={styles.sideColumn}>
            <section className={styles.summaryCard}>
              <span className={styles.summaryIcon}><FeatureIcon size={24} /></span>
              <p>当前功能</p>
              <h2>{feature.title}</h2>
              <small>{feature.guidance}</small>
              <dl>
                <div><dt>输入</dt><dd>{feature.inputHint}</dd></div>
                <div><dt>输出</dt><dd>{feature.outputHint}</dd></div>
                <div><dt>Skill</dt><dd>{feature.skillId}</dd></div>
              </dl>
            </section>

            <section className={styles.guardrailCard} data-runtime-mode={workflow.mode}>
              <div><ShieldCheck size={19} /><strong>{workflow.badge}</strong></div>
              <p>{workflow.message}</p>
              {workflow.reasonCode ? <small>{workflow.reasonCode}</small> : null}
            </section>

            <section className={styles.guardrailCard}>
              <div><ShieldCheck size={19} /><strong>执行边界</strong></div>
              <p>前端只经工作区 API 上传素材、创建 Job 和读取 deliverable output。</p>
              <ul>
                <li>不在浏览器直连图片 Provider</li>
                <li>每张结果必须是独立 output Asset</li>
                <li>失败项不会用拼图或占位图替代</li>
              </ul>
            </section>
          </aside>
        </div>

        <footer className={styles.stickyBar}>
          <div>
            <span>{workspacePending ? <LoaderCircle className="spin" size={17} /> : <Clock3 size={17} />}</span>
            <p>
              <strong>{workspace?.name ?? "正在连接工作区"}</strong>
              <small>{jobId ? progressText : `将创建 ${imageCount} 个独立 JobItem`}</small>
            </p>
          </div>
          <div className={styles.stickyActions}>
            {(uiError || requestError || createJob.error) ? (
              <p role="alert"><Info size={15} />{uiError ?? errorMessage(requestError ?? createJob.error)}</p>
            ) : !workflow.canSubmit ? (
              <p role="alert"><Info size={15} />{workflow.message}</p>
            ) : !productAssetIds.length ? (
              <p><Info size={15} />请至少选择 1 张商品图。</p>
            ) : targetColorMissing ? (
              <p><Info size={15} />商品换色必须填写目标颜色。</p>
            ) : (
              <p><CheckCircle2 size={15} />素材与参数已就绪。</p>
            )}
            {jobId ? (
              <button type="button" className={styles.secondaryAction} onClick={resetTask}>
                <RefreshCcw size={16} />新建任务
              </button>
            ) : (
              <button
                type="button"
                className={styles.primaryAction}
                disabled={!canSubmit}
                onClick={() => void submit()}
              >
                {createJob.isPending ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}
                {createJob.isPending ? "正在创建" : `生成 ${imageCount} 张`}
                <ArrowRight size={17} />
              </button>
            )}
          </div>
        </footer>
      </div>
    </AppShell>
  );
}
