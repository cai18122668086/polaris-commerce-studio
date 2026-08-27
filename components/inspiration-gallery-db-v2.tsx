"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Copy, ImagePlus, Layers3, Loader2, Sparkles, X } from "lucide-react";
import { getAssetAccessUrl, useAssetAccessUrl, useAssets, useUploadAsset } from "@/features/assets/api/assets";
import { useCreateJob, useJob } from "@/features/jobs/api/jobs";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import type { Asset as ApiAsset } from "@/lib/api/types";
import styles from "./inspiration-gallery.module.css";

type Asset = { asset_id: string; role: "result" | "user_upload" | "reference"; ordinal: number; url: string };
type Case = { id: string; title: string; description: string; role: string; type: string; category: string; platform: string; ratio: string; intent?: string; prompt: string; gallery: Asset[]; cover_image: Asset | null };
type RemixAspectRatio = "follow-reference" | "1:1" | "3:4" | "4:3" | "4:5" | "9:16" | "16:9";
type InspirationAspectRatio = "自动" | "16:9" | "4:3" | "4:5" | "3:2" | "1:1" | "2:3" | "3:4" | "5:4" | "9:16" | "21:9";
const IMAGE_COUNT_OPTIONS = [1, 2, 3, 4] as const;
const ASPECT_OPTIONS: Array<{ value: InspirationAspectRatio; label: string }> = [
  { value: "16:9", label: "16:9" }, { value: "4:3", label: "4:3" }, { value: "4:5", label: "4:5" },
  { value: "3:2", label: "3:2" }, { value: "1:1", label: "1:1" }, { value: "2:3", label: "2:3" },
  { value: "3:4", label: "3:4" }, { value: "5:4", label: "5:4" }, { value: "9:16", label: "9:16" },
  { value: "21:9", label: "21:9" }, { value: "自动", label: "自动" },
];

// Case metadata may contain a legacy ratio such as 2:3 that is not accepted
// by the jobs API. In that situation the reference image is the authoritative
// canvas, so ask the backend to follow its actual dimensions instead of
// coercing it to a different crop or changing the case prompt.
function jobAspectRatio(ratio: string): RemixAspectRatio {
  return ["1:1", "3:4", "4:3", "4:5", "9:16", "16:9"].includes(ratio)
    ? ratio as RemixAspectRatio
    : "follow-reference";
}

function inspirationAspectToApi(value: InspirationAspectRatio): Exclude<RemixAspectRatio, "follow-reference"> {
  // Keep the Focus-style menu while adapting choices to the provider's
  // current canonical canvases.
  if (value === "自动" || value === "1:1") return "1:1";
  if (value === "16:9" || value === "21:9") return "16:9";
  if (value === "4:3" || value === "3:2") return "4:3";
  if (value === "4:5" || value === "5:4") return "4:5";
  if (value === "2:3" || value === "9:16") return "9:16";
  return value;
}

// Case prompts describe the case's original product. They remain useful as
// visual strategy, but must not remain product identity instructions after a
// user replaces the product image.
function runtimeRemixPrompt(casePrompt: string): string {
  const identityStart = casePrompt.indexOf("[Product Identity Lock]");
  const visualStart = casePrompt.indexOf("[Visual Strategy Lock]");
  let prompt = casePrompt;
  if (identityStart >= 0 && visualStart > identityStart) {
    prompt = `${casePrompt.slice(0, identityStart)}[Product Identity Lock]\nThe uploaded user product image is the only product identity authority. Preserve its visible silhouette, geometry, materials, colors, packaging, logo, printed text, parts and accessories exactly. Do not use the original case product or invent a replacement.\n${casePrompt.slice(visualStart)}`;
  }
  // The provider sends multipart files as Image 1 = style reference and
  // Image 2 = product reference. Normalize any legacy case wording so the
  // model sees the same role contract that the gateway actually receives.
  const roleHeader = `[Input Roles]\nImage 1 is the visual strategy reference only. Image 2 is the uploaded product identity reference and the sole source of product identity. This order matches the multipart image order.`;
  prompt = /^\[Input Roles\][\s\S]*?(?=\[Product Identity Lock\])/m.test(prompt)
    ? prompt.replace(/^\[Input Roles\][\s\S]*?(?=\[Product Identity Lock\])/m, `${roleHeader}\n`)
    : `${roleHeader}\n${prompt}`;
  const productPresence = `[Product Presence Requirement]\nThe uploaded user product must visibly appear as the primary hero subject in the final image. Use the uploaded product image to preserve its visible silhouette, geometry, materials, colors, packaging, logo and printed details. Do not omit it, replace it with a reference-image product, or invent an alternate product. The reference image may influence composition, lighting, atmosphere, typography zones and prop relationships only.`;
  if (!prompt.includes("[Product Presence Requirement]")) {
    prompt = prompt.replace("[Visual Strategy Lock]", `${productPresence}\n[Visual Strategy Lock]`);
  }
  return prompt
    .replace(/perfume bottle/gi, "uploaded user product")
    .replace(/perfume/gi, "uploaded user product")
    .replace(/香水瓶/g, "用户上传的商品")
    .replace(/香水/g, "用户上传的商品")
    .replace(/护肤品/g, "用户上传的商品")
    .replace(/清扬产品图/g, "用户上传的商品图")
    .replace(/电动扳手产品图/g, "用户上传的商品图");
}

function PersonalRepositoryThumbnail({
  asset,
  workspaceId,
  selected,
  onToggle,
}: {
  asset: ApiAsset;
  workspaceId: string;
  selected: boolean;
  onToggle: () => void;
}) {
  const access = useAssetAccessUrl(workspaceId, asset.id);
  return (
    <button
      type="button"
      className={styles.repositoryTile}
      data-selected={selected || undefined}
      onClick={onToggle}
      aria-pressed={selected}
      aria-label={`${selected ? "取消选择" : "选择"} ${asset.original_filename}`}
    >
      {access.data?.url ? <img src={access.data.url} alt={asset.original_filename} /> : <Loader2 className="spin" size={22} />}
      {selected && <span className={styles.repositoryCheck}>✓</span>}
    </button>
  );
}

const HANDOFF_KEY = "polaris-inspiration-strategy";

export function InspirationGalleryDb() {
  const [items, setItems] = useState<Case[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [type, setType] = useState("全部");
  const [category, setCategory] = useState("全部");
  const [platform, setPlatform] = useState("全部");
  const [selected, setSelected] = useState<Case | null>(null);
  const [activeCase, setActiveCase] = useState<Case | null>(null);
  const [composerAssets, setComposerAssets] = useState<Asset[]>([]);
  const [uploadingAssetId, setUploadingAssetId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string>();
  const [generating, setGenerating] = useState(false);
  const [composeError, setComposeError] = useState<string>();
  const [instruction, setInstruction] = useState("");
  const [copied, setCopied] = useState(false);
  const [previewAsset, setPreviewAsset] = useState<Asset | null>(null);
  const [repositoryOpen, setRepositoryOpen] = useState(false);
  const [repositoryPage, setRepositoryPage] = useState(1);
  const [repositorySelected, setRepositorySelected] = useState<string[]>([]);
  const [imageCount, setImageCount] = useState(1);
  const [imageCountOpen, setImageCountOpen] = useState(false);
  const [aspectRatio, setAspectRatio] = useState<InspirationAspectRatio>("自动");
  const [aspectOpen, setAspectOpen] = useState(false);
  const composerRef = useRef<HTMLDivElement>(null);
  const { workspace, workspaceState } = useWorkspace();
  const upload = useUploadAsset(workspace?.id);
  const createJob = useCreateJob(workspace?.id);
  const repositoryQuery = useAssets(workspace?.id, { originKind: "upload", limit: 100 });
  const repositoryAssets = repositoryQuery.data?.items ?? [];
  const repositoryPageSize = 10;
  const repositoryPageCount = Math.max(1, Math.ceil(repositoryAssets.length / repositoryPageSize));
  const repositoryPageAssets = repositoryAssets.slice(
    (repositoryPage - 1) * repositoryPageSize,
    repositoryPage * repositoryPageSize,
  );
  const job = useJob(workspace?.id, jobId);

  useEffect(() => {
    const detail = job.data;
    if (!detail || !jobId) return;

    if (["failed", "cancelled"].includes(detail.status)) {
      // The job polling hook is an external subscription; synchronize the
      // local composer state when its status changes.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setGenerating(false);
      setComposeError(detail.error_message || "生成未完成，请稍后重试。");
      return;
    }

    const partial = detail.status === "partial";
    const outputAssets = detail.assets
      .filter((asset) => asset.direction === "output" && asset.is_deliverable)
      .sort((left, right) => left.ordinal - right.ordinal);
    if ((!partial && detail.status !== "completed") || !outputAssets.length || !workspace?.id) {
      if (partial) {
        setGenerating(false);
        setComposeError("部分图片已生成，失败项可在生成记录中重试。");
      }
      return;
    }

    let cancelled = false;
    void Promise.all(outputAssets.map(async (asset) => ({
      asset_id: asset.asset_id,
      role: "result" as const,
      ordinal: asset.ordinal,
      url: (await getAssetAccessUrl(workspace.id, asset.asset_id)).url,
    })))
      .then((results) => {
        if (cancelled) return;
        setComposerAssets((current) => [
          ...current.filter((asset) => asset.role !== "result"),
          ...results,
        ]);
        setGenerating(false);
        setComposeError(
          partial
            ? "部分图片已生成，失败项可在生成记录中重试。"
            : undefined,
        );
      })
      .catch(() => {
        if (cancelled) return;
        setGenerating(false);
        setComposeError("生成已完成，但结果图片暂时无法加载，请稍后重试。");
      });

    return () => {
      cancelled = true;
    };
  // The selected fields above are the stable polling signals; depending on the
  // whole response object would rerun this effect for unrelated query updates.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.data?.status, job.data?.error_message, job.data?.primary_output_asset_id, jobId, workspace?.id]);

  useEffect(() => {
    fetch("/api/v1/inspiration/cases")
      .then(async (response) => { if (!response.ok) throw new Error("灵感案例加载失败，请稍后重试。"); return response.json(); })
      .then((value) => setItems(value.items ?? []))
      .catch((reason) => setError(reason instanceof Error ? reason.message : "灵感案例加载失败，请稍后重试。"))
      .finally(() => setLoading(false));
  }, []);

  const types = useMemo(() => ["全部", ...new Set(items.map((item) => item.type))], [items]);
  const categories = useMemo(() => ["全部", ...new Set(items.map((item) => item.category))], [items]);
  const filtered = items.filter((item) => (type === "全部" || item.type === type) && (category === "全部" || item.category === category) && (platform === "全部" || item.platform === platform));

  const selectCase = (item: Case) => {
    setActiveCase(item);
    setSelected(null);
    setComposerAssets(item.gallery.filter((asset) => asset.role !== "result"));
    // Keep the confirmed case prompt visible in the composer. Any text the
    // user edits or appends remains a local override when the job is sent.
    setInstruction(runtimeRemixPrompt(item.prompt));
    const caseRatio = jobAspectRatio(item.ratio);
    setAspectRatio(caseRatio === "follow-reference" ? "自动" : caseRatio);
    composerRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  useEffect(() => {
    if (activeCase) {
      // Reset the composer inputs when the user selects a different case.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setComposerAssets(activeCase.gallery.filter((asset) => asset.role !== "result"));
    }
  }, [activeCase]);

  const replaceComposerAsset = async (asset: Asset, file: File) => {
    if (!workspace?.id) return;
    setUploadingAssetId(asset.asset_id);
    try {
      const uploaded = await upload.mutateAsync({ file, mediaKind: "image" });
      const access = await getAssetAccessUrl(workspace.id, uploaded.id);
      setComposerAssets((current) => current.map((entry) => entry.asset_id === asset.asset_id
        ? { ...entry, asset_id: uploaded.id, url: access.url }
        : entry));
      setComposeError(undefined);
    } catch (reason) {
      setComposeError(reason instanceof Error ? reason.message : "图片上传失败，请稍后重试。");
    } finally {
      setUploadingAssetId(null);
    }
  };

  const addComposerAssets = async (files: File[], role: "reference" | "user_upload") => {
    if (!workspace?.id || files.length === 0) return;
    const availableSlots = 8 - composerAssets.filter((asset) => asset.role !== "result").length;
    if (files.length > availableSlots) {
      setComposeError(`最多同时添加 ${availableSlots} 张图片。`);
      return;
    }
    setUploadingAssetId("new");
    try {
      const nextAssets = await Promise.all(files.map(async (file, index) => {
        const uploaded = await upload.mutateAsync({ file, mediaKind: "image" });
        const access = await getAssetAccessUrl(workspace.id!, uploaded.id);
        return { asset_id: uploaded.id, role, ordinal: index, url: access.url } satisfies Asset;
      }));
      setComposerAssets((current) => {
        const roleOffset = current.filter((entry) => entry.role === role).length;
        return [...current, ...nextAssets.map((asset, index) => ({ ...asset, ordinal: roleOffset + index }))];
      });
      setComposeError(undefined);
    } catch (reason) {
      setComposeError(reason instanceof Error ? reason.message : "图片上传失败，请稍后重试。");
    } finally {
      setUploadingAssetId(null);
    }
  };

  const removeComposerAsset = (asset: Asset) => {
    setComposerAssets((current) => current.filter((entry) => entry.asset_id !== asset.asset_id));
    setComposeError(undefined);
  };

  const openRepository = () => {
    setRepositorySelected(composerAssets.filter((asset) => asset.role === "user_upload").map((asset) => asset.asset_id));
    setRepositoryPage(1);
    setRepositoryOpen(true);
  };

  const confirmRepository = async () => {
    if (!workspace?.id) return;
    try {
      const selectedAssets = repositoryAssets.filter((asset) => repositorySelected.includes(asset.id));
      const resolved = await Promise.all(
        selectedAssets.map(async (asset, ordinal) => ({
          asset_id: asset.id,
          role: "user_upload" as const,
          ordinal,
          url: (await getAssetAccessUrl(workspace.id, asset.id)).url,
        })),
      );
      setComposerAssets((current) => [
        ...current.filter((asset) => asset.role !== "user_upload" && asset.role !== "result"),
        ...resolved,
      ]);
      setComposeError(undefined);
      setRepositoryOpen(false);
    } catch {
      setComposeError("个人仓库素材暂时无法读取，请稍后重试。");
    }
  };

  const casePromptWithOverride = (basePrompt: string, override: string) => {
    const normalizedOverride = override.trim();
    if (!normalizedOverride) return basePrompt;
    return `${basePrompt}\n\nUSER OVERRIDE — HIGHEST PRIORITY\nApply the following user-requested local changes exactly. These requirements override any conflicting wording in the case prompt and must not be paraphrased, weakened, or replaced. Keep every other case composition, product role, prop position, crop, scale, typography zone, and layout constraint unchanged:\n${normalizedOverride}`;
  };

  const launchRemix = async () => {
    const remixCase = activeCase;
    if (!remixCase) {
      if (!instruction.trim()) return;
      if (!workspace?.id) {
        setComposeError(workspaceState === "loading" ? "工作区正在准备，请稍后再试。" : "工作区不可用，请稍后再试。");
        return;
      }
      const productAssetIds = composerAssets.filter((asset) => asset.role === "user_upload").map((asset) => asset.asset_id);
      if (productAssetIds.length === 0) {
        setComposeError("请先上传一张商品图，再开始生成。");
        return;
      }
      setComposeError(undefined);
      setJobId(undefined);
      setGenerating(true);
      createJob.mutate({
        intent: "submit",
        type: "creative_image",
        display_name: "灵感创作",
        input: {
          product_asset_ids: productAssetIds,
          competitor_asset_ids: composerAssets.filter((asset) => asset.role === "reference").map((asset) => asset.asset_id),
        },
        configuration: {
          creative_direction: "selling_point",
          platform_code: "generic",
          language: "zh-CN",
          selling_points: [],
          aspect_ratio: inspirationAspectToApi(aspectRatio),
          image_count: imageCount,
          // Opt in only for this Inspiration tab's freeform mode. Other
          // creative-image surfaces keep their existing direct contract.
          inspiration_planning: true,
          inspiration_reference_planning: composerAssets.some((asset) => asset.role === "reference"),
          instruction: instruction.trim(),
        },
      }, {
        onSuccess: (created) => setJobId(created.id),
        onError: (reason) => {
          setGenerating(false);
          setComposeError(reason instanceof Error ? reason.message : "生成请求提交失败，请稍后重试。");
        },
      });
      return;
    }
    const compiledPrompt = runtimeRemixPrompt(remixCase.prompt);
    const normalizedInstruction = instruction.trim();
    // The composer is prefilled with the complete confirmed case prompt. When
    // the user appends a description, only the suffix is the override; sending
    // the whole textarea value as an override would duplicate the case prompt
    // and can exceed the API's 4,000-character validation limit.
    const hasCanonicalPrefix = normalizedInstruction.startsWith(compiledPrompt);
    const userOverride = hasCanonicalPrefix
      ? normalizedInstruction.slice(compiledPrompt.length).trim()
      : "";
    // If the user edited the prefilled prompt itself rather than appending to
    // it, respect that explicit full-text edit instead of duplicating it.
    const finalPrompt = hasCanonicalPrefix
      ? casePromptWithOverride(compiledPrompt, userOverride)
      : normalizedInstruction;
    const handoff = {
      source: "inspiration",
      id: remixCase.id,
      title: remixCase.title,
      visualStrategyLock: compiledPrompt,
      originalRemixPrompt: finalPrompt,
      forbiddenTransfer: "不得迁移参考图中的品牌、logo、水印、原文案与不受支持的产品声明。",
      imageRole: remixCase.role,
      ratio: remixCase.ratio,
      productAssetIds: composerAssets.filter((asset) => asset.role === "user_upload").map((asset) => asset.asset_id),
      referenceAssetIds: composerAssets.filter((asset) => asset.role === "reference").map((asset) => asset.asset_id),
      intent: finalPrompt,
      userInstruction: userOverride,
      autoStart: true,
      plannerModel: "gpt-5.6-terra",
      imageModel: "gpt-image-2",
    };
    localStorage.setItem(HANDOFF_KEY, JSON.stringify(handoff));
    const productAssetIds = composerAssets.filter((asset) => asset.role === "user_upload").map((asset) => asset.asset_id);
    const referenceAssetIds = composerAssets.filter((asset) => asset.role === "reference").map((asset) => asset.asset_id);
    if (!workspace?.id) {
      setComposeError(workspaceState === "loading" ? "工作区正在准备，请稍后再试。" : "工作区不可用，请稍后再试。");
      return;
    }
    if (productAssetIds.length === 0 || referenceAssetIds.length === 0) {
      setComposeError("案例素材尚未准备好，请重新选择案例后再试。");
      return;
    }
    try {
      await Promise.all([...productAssetIds, ...referenceAssetIds].map((assetId) => getAssetAccessUrl(workspace.id, assetId)));
    } catch {
      setComposeError("替换后的图片已失效，请在当前页面重新上传后再生成。");
      return;
    }
    // Clear a previous failed attempt before starting a new remix. Otherwise a
    // later successful result leaves the stale generic failure message visible
    // because composeError is rendered whenever generating becomes false.
    setComposeError(undefined);
    // Do not let the previous job detail (especially a failed job) terminate
    // this attempt before the create request returns a new job id.
    setJobId(undefined);
    setGenerating(true);
    createJob.mutate({
      intent: "submit",
      type: "reference_remix",
      display_name: "灵感同款创作",
      input: {
        product_asset_ids: productAssetIds,
        reference_asset_ids: referenceAssetIds,
      },
      configuration: {
        reference_skill: "reference-visual-reverse-remix",
        platform_code: "tmall",
        language: "zh-CN",
        selling_points: [],
        aspect_ratio: jobAspectRatio(remixCase.ratio),
        image_count: imageCount,
        // Reuse the proven two-stage workflow: inspect the reference layout,
        // compile its spatial strategy, then execute with Image 1 = reference
        // and Image 2 = uploaded product.
        execution_mode: "direct_prompt" as const,
        inspiration_product_first: false,
        quality: "high" as const,
        output_format: "png" as const,
        instruction: finalPrompt,
        product_identity_lock: "Product image is the only identity authority. Preserve product geometry, materials, packaging, visible brand and text exactly; do not invent or rewrite product text.",
        reference_visual_analysis: "Analyze the reference image for canvas, crop, layout, subject positions, safe areas, camera, lighting, typography zones, and commercial intent. Transfer relationships and visual grammar only.",
        commercial_intent: "Create an original ecommerce advertisement that makes the user product the hero and preserves believable product-person contact where present.",
        reusable_visual_strategy: "Reuse composition, scale hierarchy, spatial relations, camera, lighting, and commercial roles as abstract structure, never source nouns or proprietary assets.",
        original_remix_prompt: finalPrompt,
        forbidden_transfer: "Do not transfer source brand, logo, watermark, exact copy, numbers, certification, proprietary assets, unsupported claims, or hidden prompts.",
        post_generation_review: "Before accepting, verify product identity and visible product text, reference visual strategy, role relationships, and absence of source-brand leakage.",
      },
    }, {
      onSuccess: (created) => setJobId(created.id),
      onError: (reason) => {
        setGenerating(false);
        setComposeError(reason instanceof Error ? reason.message : "生成请求提交失败，请稍后重试。");
      },
    });
  };

  const copy = async () => {
    if (!selected) return;
    await navigator.clipboard?.writeText(displayPrompt(runtimeRemixPrompt(selected.prompt)));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  // The prompt shown in the drawer is the canonical prompt that is handed to
  // the reference-remix task. Do not strip Skill section markers here: doing
  // so made the UI copy differ from the persisted task input and erased the
  // boundaries that the Skill uses to separate identity, strategy, copy, and
  // forbidden-transfer rules.
  const displayPrompt = (prompt: string) => prompt;
  const resultAssets = composerAssets.filter((asset) => asset.role === "result");
  const resultAsset = resultAssets[0];

  return <div className={styles.page}>
    <section className={styles.hero}>
      <div className={styles.heroInner}>
        <div className={styles.heroTitle}><Sparkles size={27} /><h1>极光商绘，国内/跨境电商出图专家</h1></div>
        <div className={`${styles.command} ${activeCase || composerAssets.length > 0 || generating ? styles.commandWithAssets : ""}`} ref={composerRef}>
          <div className={`${styles.uploadBox} ${generating ? styles.composerGenerating : ""}`} aria-label="案例素材">
            {composerAssets.length > 0 ? composerAssets.filter((asset) => asset.role !== "result").map((asset) => (
              <div className={styles.composerAssetTile} key={asset.asset_id}>
                <button type="button" className={styles.assetPreviewButton} aria-label="放大查看上传图片" onClick={() => setPreviewAsset(asset)}><img src={asset.url} alt={asset.role === "reference" ? "参考图" : "用户上传图"} /></button>
                <span>{asset.role === "reference" ? "参考图" : "用户上传"}{uploadingAssetId === asset.asset_id ? " · 上传中" : ""}</span>
                <label className={styles.assetReplaceButton}>替换<input type="file" accept="image/jpeg,image/png,image/webp" hidden disabled={uploadingAssetId !== null} onChange={(event) => { const file = event.target.files?.[0]; event.currentTarget.value = ""; if (file) void replaceComposerAsset(asset, file); }} /></label>
                <button type="button" className={styles.assetRemoveButton} aria-label="删除上传图片" onClick={() => removeComposerAsset(asset)}><X size={13} /></button>
              </div>
            )) : generating ? <Loader2 className="spin" size={24} /> : null}
            <label className={styles.composerAddTile} aria-label="添加商品图">
              <ImagePlus size={22} />
              <span>添加商品图</span>
              <input type="file" accept="image/jpeg,image/png,image/webp" multiple hidden disabled={uploadingAssetId !== null} onChange={(event) => { const files = Array.from(event.target.files ?? []); event.currentTarget.value = ""; if (files.length) void addComposerAssets(files, "user_upload"); }} />
            </label>
          </div>
          <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="万能出图，写什么就出什么，大白话，具体讲清楚要求" />
          <div className={styles.commandBar}>
            <button type="button" onClick={openRepository}><Layers3 size={15} /> 个人仓库</button>
            <div className={styles.aspectControl}>
              <button type="button" className={styles.aspectTrigger} aria-label="选择生成图片比例" aria-expanded={aspectOpen} disabled={Boolean(activeCase)} onClick={() => setAspectOpen((open) => !open)}>▣ 比例: {activeCase ? (activeCase.ratio || "自动") : aspectRatio} <ChevronDown size={13} /></button>
              {aspectOpen && !activeCase && <div className={styles.aspectMenu} role="menu"><strong>生成比例</strong><div className={styles.aspectGrid}>{ASPECT_OPTIONS.map((option) => <button type="button" role="menuitem" key={option.value} className={aspectRatio === option.value ? styles.aspectSelected : ""} onClick={() => { setAspectRatio(option.value); setAspectOpen(false); }}>{option.label}</button>)}</div></div>}
            </div>
            <div className={styles.countControl}>
              <button type="button" className={styles.countButton} aria-label="选择生成张数" aria-expanded={imageCountOpen} onClick={() => setImageCountOpen((open) => !open)}>{imageCount} 张 <ChevronDown size={13} /></button>
              {imageCountOpen && <div className={styles.countMenu} role="menu" aria-label="生成张数">{IMAGE_COUNT_OPTIONS.map((count) => <button type="button" role="menuitem" key={count} className={imageCount === count ? styles.countSelected : ""} onClick={() => { setImageCount(count); setImageCountOpen(false); }}>{count} 张</button>)}</div>}
            </div>
            <small>消耗 {imageCount} 次</small>
            <button className={styles.commandSubmit} aria-label={activeCase ? "开始生成" : "开始创作"} onClick={launchRemix} disabled={generating || createJob.isPending || !workspace?.id || (activeCase ? composerAssets.every((asset) => asset.role !== "user_upload" || !asset.asset_id) || composerAssets.every((asset) => asset.role !== "reference" || !asset.asset_id) : !instruction.trim())} style={{ opacity: generating || activeCase || instruction.trim() ? 1 : .42 }}>{generating ? <Loader2 className="spin" size={17} /> : <ChevronRight size={18} />}</button>
          </div>
        </div>
        {resultAsset && <div className={styles.resultShowcase}><div className={styles.resultShowcaseMeta}><strong>本次生成结果 · {resultAssets.length} 张</strong><span>点击图片查看大图</span></div><div className={styles.resultShowcaseGrid}>{resultAssets.map((asset) => <button type="button" key={asset.asset_id} aria-label={`查看第 ${asset.ordinal + 1} 张生成结果`} onClick={() => setPreviewAsset(asset)}><img src={asset.url} alt={`生成结果 ${asset.ordinal + 1}`} /></button>)}</div></div>}
        {generating ? <div className={styles.generationStatus} role="status"><Loader2 className="spin" size={15} /><span>{job.data?.status === "completed" ? "生成完成，正在加载结果" : job.data?.stage ? `正在${job.data.stage}` : "正在准备生成"}</span><b>{job.data ? `${Math.round(job.data.progress)}%` : "排队中"}</b></div> : null}
        {composeError && !generating ? <div className={styles.composeError} role="alert">{composeError}</div> : null}
      </div>
    </section>
    <main className={styles.content}><section className={styles.materialPanel}><div className={styles.sectionHead}><div><p className={styles.eyebrow}>CURATED VISUAL LIBRARY</p><h2>灵感素材</h2></div><span className={styles.count}>{filtered.length} 个方案</span></div><div className={styles.filters}><div className={styles.filterRow}><b>类型:</b><div>{types.map((value) => <button key={value} className={type === value ? styles.active : ""} onClick={() => setType(value)}>{value}</button>)}</div></div><div className={styles.filterRow}><b>品类:</b><div>{categories.map((value) => <button key={value} className={category === value ? styles.active : ""} onClick={() => setCategory(value)}>{value}</button>)}</div></div><div className={styles.filterRow}><b>分类:</b><div>{["全部", "国内", "跨境"].map((value) => <button key={value} className={platform === value ? styles.active : ""} onClick={() => setPlatform(value)}>{value}</button>)}</div></div></div>{loading ? <div className={styles.emptyInput}><Loader2 /> 正在加载灵感案例…</div> : error ? <div className={styles.emptyInput}>{error}</div> : <div className={styles.grid}>{filtered.map((item) => <article className={styles.card} key={item.id}><div className={styles.imageWrap}><img src={item.cover_image?.url} alt={item.title} /><span>{item.platform}</span><div className={styles.imageHover}><button onClick={() => setSelected(item)}>查看指令</button></div></div><div className={styles.cardBody}><div className={styles.cardTags}><span>{item.type}</span><span>{item.category}</span></div><h3>{item.title}</h3><p>{item.description}</p><div className={styles.cardFooter}><small>{item.role} · {item.ratio}</small><button onClick={() => selectCase(item)}>一键做同款 <ChevronRight size={15} /></button></div></div></article>)}</div>}</section></main>
    {repositoryOpen && <div className={styles.repositoryOverlay} role="dialog" aria-modal="true" aria-labelledby="personal-repository-title" onMouseDown={(event) => { if (event.target === event.currentTarget) setRepositoryOpen(false); }}><section className={styles.repositoryModal} onMouseDown={(event) => event.stopPropagation()}><header className={styles.repositoryHeader}><h2 id="personal-repository-title">个人仓库</h2><button type="button" className={styles.repositoryClose} aria-label="关闭个人仓库" onClick={() => setRepositoryOpen(false)}><X size={21} /></button></header><div className={styles.repositoryBody}>{repositoryQuery.isPending ? <div className={styles.repositoryState}><Loader2 className="spin" size={22} /> 正在加载个人素材…</div> : repositoryQuery.isError ? <div className={styles.repositoryState}>个人素材暂时无法读取，请稍后重试。</div> : repositoryPageAssets.length ? <div className={styles.repositoryGrid}>{repositoryPageAssets.map((asset) => <PersonalRepositoryThumbnail key={asset.id} asset={asset} workspaceId={workspace!.id} selected={repositorySelected.includes(asset.id)} onToggle={() => setRepositorySelected((current) => current.includes(asset.id) ? current.filter((id) => id !== asset.id) : [...current, asset.id])} />)}</div> : <div className={styles.repositoryState}>还没有用户上传素材，请先上传图片。</div>}</div><footer className={styles.repositoryFooter}><div className={styles.repositoryPager}><button type="button" aria-label="上一页" disabled={repositoryPage <= 1} onClick={() => setRepositoryPage((page) => Math.max(1, page - 1))}>‹</button>{Array.from({ length: repositoryPageCount }, (_, index) => index + 1).slice(0, 5).map((page) => <button type="button" key={page} className={repositoryPage === page ? styles.repositoryPageSelected : ""} onClick={() => setRepositoryPage(page)}>{page}</button>)}<button type="button" aria-label="下一页" disabled={repositoryPage >= repositoryPageCount} onClick={() => setRepositoryPage((page) => Math.min(repositoryPageCount, page + 1))}>›</button><span>{repositoryAssets.length ? `${repositoryAssets.length} 个上传素材` : "0 个上传素材"}</span></div><div className={styles.repositoryActions}><button type="button" onClick={() => setRepositoryOpen(false)}>取消</button><button type="button" className={styles.repositoryConfirm} onClick={() => void confirmRepository()} disabled={!workspace || repositoryQuery.isPending}>确定</button></div></footer></section></div>}
    {previewAsset && <div className={styles.resultPreviewOverlay} role="dialog" aria-label="生成成品大图" onMouseDown={(event) => { if (event.target === event.currentTarget) setPreviewAsset(null); }}><button type="button" className={styles.resultPreviewClose} aria-label="关闭大图预览" onClick={() => setPreviewAsset(null)}><X size={22} /></button><img src={previewAsset.url} alt="生成成品大图" /></div>}
    {selected && <div className={styles.overlay} onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}><aside className={styles.focusModal}><button className={styles.close} onClick={() => setSelected(null)}><X size={20} /></button><div className={styles.modalGallery}><div className={styles.inputGrid}>{selected.gallery.filter((asset) => asset.role !== "result").map((asset) => <div className={styles.inputTile} key={asset.asset_id}><span>{asset.role === "user_upload" ? "用户上传" : "参考图"}</span><img src={asset.url} alt="案例输入" /></div>)}</div><div className={styles.resultTile}>{selected.gallery.filter((asset) => asset.role === "result").map((asset) => <img key={asset.asset_id} src={asset.url} alt="案例结果" />)}</div></div><div className={styles.modalInfo}><h2>{selected.title}</h2><h3>创作指令</h3><p>{displayPrompt(selected.prompt)}</p><button className={styles.modalApply} onClick={copy}>{copied ? "已复制" : <><Copy size={15} /> 复制指令</>}</button><button className={styles.modalApply} onClick={() => selectCase(selected)}>一键做同款</button></div></aside></div>}
  </div>;
}
