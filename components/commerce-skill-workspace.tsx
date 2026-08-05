"use client";

import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  ImagePlus,
  Info,
  LoaderCircle,
  RefreshCcw,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { AssetLibraryPicker } from "@/components/asset-library-picker";
import { ResultGrid } from "@/components/result-grid";
import { StatusBadge } from "@/components/status-badge";
import { WorkspaceHeader } from "@/components/workspace-header";
import { useUploadAsset } from "@/features/assets/api/assets";
import { useConfirmPlan, useCreateJob, useJob } from "@/features/jobs/api/jobs";
import {
  presentWorkflow,
  resolveRuntimeCapability,
  useRuntimeStatus,
} from "@/features/runtime/api/runtime";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { errorMessage } from "@/lib/api/request";
import type {
  AmazonVisualSuiteJobCreate,
  CreativeImageJobCreate,
  ReferenceRemixJobCreate,
} from "@/lib/api/types";
import { getFeatureById } from "@/lib/feature-registry";
import { allowsJobAction } from "@/lib/jobs/actions";
import { selectJobResultAssets } from "@/lib/jobs/results";
import styles from "./product-image-workspace.module.css";

type WorkspaceFeatureId =
  | "reference-remix"
  | "creative-image"
  | "amazon-visual-suite";
type AspectRatio = "follow-reference" | "1:1" | "3:4" | "4:5" | "4:3" | "9:16" | "16:9";
type CreativeDirection =
  | "selling_point"
  | "pain_point"
  | "scenario"
  | "promotion"
  | "premium"
  | "social";
type RoleKey =
  | "product"
  | "reference"
  | "competitor"
  | "whiteBackground"
  | "detail"
  | "package"
  | "scene"
  | "brand";
type JobBody =
  | ReferenceRemixJobCreate
  | CreativeImageJobCreate
  | AmazonVisualSuiteJobCreate;

type RoleDefinition = {
  key: RoleKey;
  title: string;
  description: string;
  required: boolean;
};

type AmazonPlanPage = {
  itemKey: string;
  finalSize?: string;
  headline?: string;
  sellingPoint?: string;
  visualProof?: string;
  layoutDirection?: string;
};

const aspectRatios: { value: AspectRatio; label: string; note: string }[] = [
  { value: "1:1", label: "1:1", note: "1024 × 1024" },
  { value: "3:4", label: "3:4", note: "768 × 1024" },
  { value: "4:5", label: "4:5", note: "1024 × 1280" },
  { value: "4:3", label: "4:3", note: "1024 × 768" },
  { value: "9:16", label: "9:16", note: "576 × 1024" },
  { value: "16:9", label: "16:9", note: "1024 × 576" },
];

const referenceAspectRatios: { value: AspectRatio; label: string; note: string }[] = [
  { value: "follow-reference", label: "跟随参考图", note: "首张参考图实际尺寸" },
  ...aspectRatios,
];

const imageCountOptions = Array.from({ length: 12 }, (_, index) => index + 1);

const platforms = [
  { value: "tmall", label: "天猫 / 淘宝" },
  { value: "jd", label: "京东" },
  { value: "douyin", label: "抖音电商" },
  { value: "xiaohongshu", label: "小红书" },
  { value: "amazon-us", label: "Amazon US" },
  { value: "generic", label: "通用渠道" },
];

const amazonPlatforms = [
  { value: "amazon-us", label: "Amazon US" },
] as const;

const creativeDirections: { value: CreativeDirection; label: string }[] = [
  { value: "selling_point", label: "核心卖点" },
  { value: "pain_point", label: "用户痛点" },
  { value: "scenario", label: "使用场景" },
  { value: "promotion", label: "活动促销" },
  { value: "premium", label: "高端质感" },
  { value: "social", label: "社媒传播" },
];

const emptySelections: Record<RoleKey, string[]> = {
  product: [],
  reference: [],
  competitor: [],
  whiteBackground: [],
  detail: [],
  package: [],
  scene: [],
  brand: [],
};

function splitList(value: string, maxItems = 12): string[] {
  return value
    .split(/[\n,，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, maxItems);
}

function readAmazonPlanPages(payload: Record<string, unknown> | undefined): AmazonPlanPage[] {
  if (!payload || !Array.isArray(payload.pages)) return [];
  return payload.pages.flatMap((value) => {
    if (!value || typeof value !== "object") return [];
    const page = value as Record<string, unknown>;
    if (typeof page.item_key !== "string" || !page.item_key.trim()) return [];
    const optionalText = (key: string) =>
      typeof page[key] === "string" && page[key].trim() ? page[key].trim() : undefined;
    return [{
      itemKey: page.item_key.trim(),
      finalSize: optionalText("final_size"),
      headline: optionalText("headline"),
      sellingPoint: optionalText("selling_point"),
      visualProof: optionalText("visual_proof"),
      layoutDirection: optionalText("layout_direction"),
    }];
  });
}

function readAmazonBusinessQuality(payload: Record<string, unknown> | undefined) {
  if (!payload || !payload.business_quality || typeof payload.business_quality !== "object") return undefined;
  const quality = payload.business_quality as Record<string, unknown>;
  const status = quality.status;
  if (status !== "needs_review" && status !== "passed" && status !== "failed") return undefined;
  return { status };
}

function rolesFor(featureId: WorkspaceFeatureId): RoleDefinition[] {
  if (featureId === "reference-remix") {
    return [
      {
        key: "product",
        title: "我的商品图",
        description: "至少 1 张，作为二创后必须保留的商品主体。",
        required: true,
      },
      {
        key: "reference",
        title: "参考图",
        description: "至少 1 张，用于提供构图、景别、光影和视觉节奏。",
        required: true,
      },
    ];
  }
  if (featureId === "creative-image") {
    return [
      {
        key: "product",
        title: "商品图",
        description: "至少 1 张，建议包含正面和关键细节。",
        required: true,
      },
      {
        key: "competitor",
        title: "竞品参考",
        description: "可选，仅用于辅助理解赛道表达，不直接复制。",
        required: false,
      },
    ];
  }
  return [
    {
      key: "whiteBackground",
      title: "白底商品图",
      description: "必填，至少 1 张清晰白底商品图。",
      required: true,
    },
    {
      key: "detail",
      title: "商品细节图",
      description: "可选，用于材质、结构和功能特写。",
      required: false,
    },
    {
      key: "package",
      title: "包装参考",
      description: "可选，用于包装、配件和清单表达。",
      required: false,
    },
    {
      key: "scene",
      title: "场景参考",
      description: "可选，用于使用场景和生活方式画面。",
      required: false,
    },
    {
      key: "brand",
      title: "品牌参考",
      description: "可选，用于 Logo、品牌色和视觉规范。",
      required: false,
    },
  ];
}

function UploadPanel({
  title,
  description,
  count,
  required,
  uploading,
  disabled,
  onFiles,
}: {
  title: string;
  description: string;
  count: number;
  required: boolean;
  uploading: boolean;
  disabled: boolean;
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
        disabled={uploading || disabled}
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
        disabled={disabled}
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files ?? []);
          event.currentTarget.value = "";
          if (files.length) onFiles(files);
        }}
      />
    </div>
  );
}

export function CommerceSkillWorkspace({
  featureId,
}: {
  featureId: WorkspaceFeatureId;
}) {
  const feature = getFeatureById(featureId);
  const roleDefinitions = useMemo(() => rolesFor(featureId), [featureId]);
  const { workspace, isPending: workspacePending, error: workspaceError } = useWorkspace();
  const upload = useUploadAsset(workspace?.id);
  const runtime = useRuntimeStatus();
  const capability = resolveRuntimeCapability(
    runtime.data,
    feature?.runtimeCapability ?? featureId,
  );
  const workflow = presentWorkflow(capability);
  const createJob = useCreateJob(workspace?.id);
  const confirmPlan = useConfirmPlan(workspace?.id);

  const [selections, setSelections] = useState(emptySelections);
  const [platformCode, setPlatformCode] = useState(
    featureId === "amazon-visual-suite" ? "amazon-us" : "tmall",
  );
  const [language, setLanguage] = useState(
    featureId === "amazon-visual-suite" ? "en-US" : "zh-CN",
  );
  const [aspectRatio, setAspectRatio] = useState<AspectRatio>(
    featureId === "reference-remix" ? "follow-reference" : "1:1",
  );
  const [imageCount, setImageCount] = useState(1);
  const [creativeDirection, setCreativeDirection] =
    useState<CreativeDirection>("selling_point");
  const [instruction, setInstruction] = useState("");
  const [sellingPoints, setSellingPoints] = useState("");
  const [productName, setProductName] = useState("");
  const [listingTitle, setListingTitle] = useState("");
  const [brandColors, setBrandColors] = useState("");
  const [jobId, setJobId] = useState<string>();
  const [uiError, setUiError] = useState<string>();

  const job = useJob(workspace?.id, jobId);
  const resultAssets = selectJobResultAssets(job.data);
  const requestError = workspaceError ?? upload.error ?? confirmPlan.error ?? job.error;
  const isAmazon = featureId === "amazon-visual-suite";
  const isCreative = featureId === "creative-image";
  const selectedSizeLabel = isAmazon
    ? "主图 2000 × 2000；副图 1200 × 1600；桌面 A+ 1464 × 600；移动 A+ 1600 × 1200"
    : aspectRatio === "follow-reference"
      ? "跟随首张参考图实际尺寸"
      : aspectRatios.find((ratio) => ratio.value === aspectRatio)?.note ?? "未选择";
  const expectedCount = job.data?.expected_item_count ?? (isAmazon ? 21 : imageCount);
  const amazonPlanPages = isAmazon
    ? readAmazonPlanPages(job.data?.plan?.payload)
    : [];
  const amazonBusinessQuality = isAmazon
    ? readAmazonBusinessQuality(job.data?.plan?.payload)
    : undefined;
  const canConfirmAmazonPlan = Boolean(
    isAmazon &&
      job.data?.status === "awaiting_confirmation" &&
      job.data.plan &&
      amazonPlanPages.length > 0 &&
      allowsJobAction(job.data.allowed_actions, "confirm_plan"),
  );

  const selectedIds = useMemo(
    () => Object.values(selections).flat(),
    [selections],
  );
  const missingRequiredRole = roleDefinitions.find(
    (role) => role.required && selections[role.key].length === 0,
  );
  const canSubmit = Boolean(
    workspace &&
      workflow.canSubmit &&
      !runtime.isPending &&
      !missingRequiredRole &&
      !upload.isPending &&
      !createJob.isPending,
  );

  const progressText = useMemo(() => {
    if (!job.data) return "任务创建后将自动轮询状态";
    return `${job.data.succeeded_item_count} / ${job.data.expected_item_count} 项完成`;
  }, [job.data]);

  if (!feature) return null;
  const FeatureIcon = feature.icon;

  const replaceRoleSelection = (role: RoleKey, ids: string[]) => {
    const unique = [...new Set(ids)].slice(0, 8);
    setSelections((current) => {
      const next = { ...current, [role]: unique };
      for (const key of Object.keys(next) as RoleKey[]) {
        if (key !== role) {
          next[key] = next[key].filter((id) => !unique.includes(id));
        }
      }
      return next;
    });
  };

  const addUploadedAssets = async (files: File[], role: RoleKey) => {
    setUiError(undefined);
    try {
      const uploadedIds: string[] = [];
      for (const file of files.slice(0, 8)) {
        const asset = await upload.mutateAsync({ file, mediaKind: "image" });
        uploadedIds.push(asset.id);
      }
      replaceRoleSelection(role, [...selections[role], ...uploadedIds]);
    } catch (error) {
      setUiError(errorMessage(error));
    }
  };

  const buildJobBody = (): JobBody => {
    const common = {
      intent: "submit" as const,
      display_name: feature.title,
    };
    if (featureId === "reference-remix") {
      return {
        ...common,
        type: "reference_remix",
        input: {
          product_asset_ids: selections.product,
          reference_asset_ids: selections.reference,
        },
        configuration: {
          platform_code: platformCode,
          language,
          selling_points: splitList(sellingPoints),
          aspect_ratio: aspectRatio,
          image_count: imageCount,
          instruction: instruction.trim(),
        },
      };
    }
    if (featureId === "creative-image") {
      return {
        ...common,
        type: "creative_image",
        input: {
          product_asset_ids: selections.product,
          competitor_asset_ids: selections.competitor,
        },
        configuration: {
          creative_direction: creativeDirection,
          platform_code: platformCode,
          language,
          selling_points: splitList(sellingPoints),
          aspect_ratio: aspectRatio as Exclude<AspectRatio, "follow-reference">,
          image_count: imageCount,
          instruction: instruction.trim(),
        },
      };
    }
    return {
      ...common,
      type: "amazon_visual_suite",
      input: {
        white_background_product_asset_ids: selections.whiteBackground,
        detail_asset_ids: selections.detail,
        package_asset_ids: selections.package,
        scene_asset_ids: selections.scene,
        brand_asset_ids: selections.brand,
      },
      configuration: {
        marketplace:
          amazonPlatforms.find((platform) => platform.value === platformCode)?.value ??
          amazonPlatforms[0].value,
        product_name: productName.trim(),
        listing_title: listingTitle.trim(),
        bullet_points: splitList(sellingPoints),
        brand_colors: splitList(brandColors, 8),
        language,
      },
    };
  };

  const submit = async () => {
    if (!canSubmit) return;
    setUiError(undefined);
    try {
      const created = await createJob.mutateAsync(buildJobBody());
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
          eyebrow={`${feature.shortTitle} · 独立工作台`}
          title={feature.title}
          description={feature.description}
          meta={
            <span className={styles.safetyBadge}>
              <ShieldCheck size={15} /> 任务进度自动保存
            </span>
          }
        />

        <div className={styles.stepBar} aria-label="创作步骤">
          <span data-active={!jobId || undefined}><i>1</i>选择素材</span>
          <span data-active={!jobId || undefined}><i>2</i>配置参数</span>
          <span data-active={Boolean(jobId) || undefined}><i>3</i>任务轮询</span>
          <span data-active={resultAssets.length > 0 || undefined}><i>4</i>结果交付</span>
        </div>

        <div className={styles.workspaceGrid}>
          <main className={styles.mainColumn}>
            <section className={styles.card}>
              <div className={styles.sectionHeading}>
                <div>
                  <span>01</span>
                  <div>
                    <h2>选择角色素材</h2>
                    <p>同一素材不能跨角色重复选择，每个角色最多 8 张。</p>
                  </div>
                </div>
                <strong>{selectedIds.length} 张</strong>
              </div>

              <div className={styles.uploadGrid}>
                {roleDefinitions.map((role) => (
                  <UploadPanel
                    key={role.key}
                    title={role.title}
                    description={role.description}
                    count={selections[role.key].length}
                    required={role.required}
                    uploading={upload.isPending}
                    disabled={Boolean(jobId)}
                    onFiles={(files) => void addUploadedAssets(files, role.key)}
                  />
                ))}
              </div>

              {roleDefinitions.map((role) => (
                <AssetLibraryPicker
                  key={role.key}
                  workspaceId={workspace?.id}
                  title={`从素材库选择：${role.title}`}
                  description={role.description}
                  selectedIds={selections[role.key]}
                  excludedIds={selectedIds.filter(
                    (id) => !selections[role.key].includes(id),
                  )}
                  onChange={(ids) => replaceRoleSelection(role.key, ids)}
                  disabled={Boolean(jobId)}
                />
              ))}
            </section>

            <section className={styles.card}>
              <div className={styles.sectionHeading}>
                <div>
                  <span>02</span>
                  <div>
                    <h2>配置生成任务</h2>
                    <p>
                      {isAmazon
                        ? "前端只提交素材和商品信息，固定 21 个 JobItem 由后端创建。"
                        : "每张结果对应独立 JobItem，不使用拼图或占位输出。"}
                    </p>
                  </div>
                </div>
                <strong>{isAmazon ? "固定 21 项" : `${imageCount} 项`}</strong>
              </div>

              <div className={styles.formGrid}>
                <label>
                  <span>{isAmazon ? "Amazon 站点" : "目标平台"}</span>
                  <select
                    value={platformCode}
                    onChange={(event) => setPlatformCode(event.target.value)}
                    disabled={Boolean(jobId)}
                  >
                    {(isAmazon ? amazonPlatforms : platforms).map((platform) => (
                      <option key={platform.value} value={platform.value}>{platform.label}</option>
                    ))}
                  </select>
                  <small>{isAmazon ? "写入 marketplace。" : "用于渠道构图与视觉约束。"} 严格交付尺寸：{selectedSizeLabel}。</small>
                </label>
                <label>
                  <span>语言</span>
                  <select
                    value={language}
                    onChange={(event) => setLanguage(event.target.value)}
                    disabled={Boolean(jobId)}
                  >
                    <option value="zh-CN">简体中文</option>
                    <option value="en-US">English (US)</option>
                    <option value="ja-JP">日本語</option>
                    <option value="de-DE">Deutsch</option>
                  </select>
                  <small>仅提交后端 contract 支持的语言代码。</small>
                </label>
                {isCreative ? (
                  <label>
                    <span>创意方向</span>
                    <select
                      value={creativeDirection}
                      onChange={(event) =>
                        setCreativeDirection(event.target.value as CreativeDirection)
                      }
                      disabled={Boolean(jobId)}
                    >
                      {creativeDirections.map((direction) => (
                        <option key={direction.value} value={direction.value}>
                          {direction.label}
                        </option>
                      ))}
                    </select>
                    <small>写入 creative_direction。</small>
                  </label>
                ) : null}
              </div>

              {isAmazon ? (
                <>
                  <label className={styles.colorField}>
                    <span>商品名称 <i>可选</i></span>
                    <input
                      value={productName}
                      onChange={(event) => setProductName(event.target.value)}
                      maxLength={160}
                      placeholder="可留空，系统将仅依据上传素材分析"
                      disabled={Boolean(jobId)}
                    />
                    <small>留空不会阻塞提交，也不会虚构商品名称或属性。</small>
                  </label>
                  <label className={styles.colorField}>
                    <span>Listing 标题</span>
                    <input
                      value={listingTitle}
                      onChange={(event) => setListingTitle(event.target.value)}
                      maxLength={240}
                      placeholder="可选，最多 240 字符"
                      disabled={Boolean(jobId)}
                    />
                    <small>用于辅助 21 项套图的信息层级规划。</small>
                  </label>
                  <label className={styles.instructionField}>
                    <span>品牌色</span>
                    <textarea
                      value={brandColors}
                      onChange={(event) => setBrandColors(event.target.value)}
                      rows={3}
                      placeholder="每行一个色名或色号，最多 8 项"
                      disabled={Boolean(jobId)}
                    />
                    <small>将按行拆分为 brand_colors。</small>
                  </label>
                </>
              ) : (
                <>
                  <fieldset className={styles.optionGroup} disabled={Boolean(jobId)}>
                    <legend>画面比例</legend>
                    <div className={styles.ratioGrid}>
                      {(featureId === "reference-remix" ? referenceAspectRatios : aspectRatios).map((ratio) => (
                        <label key={ratio.value} data-selected={aspectRatio === ratio.value || undefined}>
                          <input
                            type="radio"
                            name={`${featureId}-aspect-ratio`}
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
                      {imageCountOptions.map((count) => (
                        <label key={count} data-selected={imageCount === count || undefined}>
                          <input
                            type="radio"
                            name={`${featureId}-image-count`}
                            value={count}
                            checked={imageCount === count}
                            onChange={() => setImageCount(count)}
                          />
                          <strong>{count}</strong><span>张</span>
                        </label>
                      ))}
                    </div>
                  </fieldset>
                </>
              )}

              <label className={styles.instructionField}>
                <span>{isAmazon ? "Bullet Points" : "商品卖点"}</span>
                <textarea
                  value={sellingPoints}
                  onChange={(event) => setSellingPoints(event.target.value)}
                  rows={4}
                  placeholder="每行一项，最多 12 项"
                  disabled={Boolean(jobId)}
                />
                <small>按换行或逗号拆分，最多提交 12 项。</small>
              </label>

              {!isAmazon ? (
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
              ) : null}
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
                  <div className={styles.jobState}><LoaderCircle className="spin" size={18} />正在读取任务…</div>
                ) : job.isError ? (
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

            {isAmazon && job.data?.status === "awaiting_confirmation" && amazonPlanPages.length > 0 ? (
              <section className={styles.card} aria-labelledby="amazon-plan-review-title">
                <div className={styles.sectionHeading}>
                  <div>
                    <span>04</span>
                    <div>
                      <h2 id="amazon-plan-review-title">确认 21 项页面规划</h2>
                      <p>生成开始前，请逐项核对尺寸、卖点、视觉证明与布局方向。</p>
                    </div>
                  </div>
                  <strong>{amazonPlanPages.length} / 21 项</strong>
                </div>
                <div className={styles.planReview}>
                  {amazonPlanPages.map((page, index) => (
                    <article key={`${page.itemKey}-${index}`}>
                      <i>{String(index + 1).padStart(2, "0")}</i>
                      <div>
                        <div className={styles.planRowHeading}>
                          <strong>{page.itemKey}</strong>
                          {page.finalSize ? <span>{page.finalSize}</span> : null}
                        </div>
                        <h3>{page.headline ?? page.sellingPoint ?? "待核对页面规划"}</h3>
                        {page.sellingPoint && page.sellingPoint !== page.headline ? (
                          <p><b>卖点</b>{page.sellingPoint}</p>
                        ) : null}
                        {page.visualProof ? <p><b>视觉证明</b>{page.visualProof}</p> : null}
                        {page.layoutDirection ? <p><b>布局</b>{page.layoutDirection}</p> : null}
                      </div>
                    </article>
                  ))}
                </div>
                <div className={styles.planConfirmation}>
                  <p><Info size={15} />确认后任务将继续处理并进入整套图片生成，请在提交前核对方案。</p>
                  <button
                    type="button"
                    className={styles.primaryAction}
                    disabled={!canConfirmAmazonPlan || confirmPlan.isPending}
                    onClick={() => {
                      if (!job.data?.plan) return;
                      confirmPlan.mutate({
                        jobId: job.data.id,
                        revision: job.data.plan.revision,
                        allowedActions: job.data.allowed_actions,
                      });
                    }}
                  >
                    {confirmPlan.isPending ? <LoaderCircle className="spin" size={17} /> : <CheckCircle2 size={17} />}
                    {confirmPlan.isPending ? "正在确认计划" : "确认计划并开始生成"}
                    <ArrowRight size={17} />
                  </button>
                </div>
              </section>
            ) : null}

            {isAmazon && job.data?.status === "completed" && amazonBusinessQuality ? (
              <section
                className={styles.businessQuality}
                data-status={amazonBusinessQuality.status}
                aria-live="polite"
              >
                <ShieldCheck size={19} />
                <div>
                  <strong>
                    {amazonBusinessQuality.status === "passed"
                      ? "技术交付与业务审核均已通过"
                      : amazonBusinessQuality.status === "failed"
                        ? "技术交付完成，业务质量检查未通过"
                        : "技术交付完成，业务质量等待人工审核"}
                  </strong>
                  <p>
                    {amazonBusinessQuality.status === "failed"
                      ? "系统发现确定性重复等风险；文件仍可下载核对，但不会自动重做。"
                      : amazonBusinessQuality.status === "needs_review"
                        ? "SKU 身份与跨页视觉一致性需要人工确认；文件可下载，重做必须由你明确发起。"
                        : "已确认 Product Master、SKU 一致性和跨页质量。"}
                  </p>
                </div>
              </section>
            ) : null}

            <ResultGrid
              workspaceId={workspace?.id}
              assets={resultAssets}
              expectedCount={expectedCount}
              title={`${feature.title}结果`}
              archiveJobId={
                isAmazon &&
                job.data?.status === "completed" &&
                resultAssets.length === expectedCount
                  ? job.data.id
                  : undefined
              }
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
              <p>浏览器只上传素材、创建后端 Job、轮询状态并读取 deliverable output Asset。</p>
              <ul>
                <li>图片生成与交付均通过安全的任务服务完成</li>
                <li>仅在生成服务可用时提供可交付图片</li>
                <li>{isAmazon ? "21 个固定 JobItem 仅由后端创建" : "按界面选择原样提交 1–12 张"}</li>
              </ul>
            </section>
          </aside>
        </div>

        <footer className={styles.stickyBar}>
          <div>
            <span>{workspacePending ? <LoaderCircle className="spin" size={17} /> : <Clock3 size={17} />}</span>
            <p>
              <strong>{workspace?.name ?? "正在连接工作区"}</strong>
              <small>{jobId ? progressText : isAmazon ? "后端将创建固定 21 个 JobItem" : `将创建 ${imageCount} 个独立 JobItem`}</small>
            </p>
          </div>
          <div className={styles.stickyActions}>
            {(uiError || requestError || createJob.error) ? (
              <p role="alert"><Info size={15} />{uiError ?? errorMessage(requestError ?? createJob.error)}</p>
            ) : !workflow.canSubmit ? (
              <p role="alert"><Info size={15} />{workflow.message}</p>
            ) : missingRequiredRole ? (
              <p><Info size={15} />请先选择：{missingRequiredRole.title}。</p>
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
                {createJob.isPending
                  ? "正在创建"
                  : isAmazon
                    ? "创建 21 项套图任务"
                    : `生成 ${imageCount} 张`}
                <ArrowRight size={17} />
              </button>
            )}
          </div>
        </footer>
      </div>
    </AppShell>
  );
}
