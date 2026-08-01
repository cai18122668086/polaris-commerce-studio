import {
  Aperture,
  Blend,
  Boxes,
  Brush,
  Camera,
  Images,
  Layers3,
  PackageCheck,
  PaintBucket,
  PersonStanding,
  ScanFace,
  Shirt,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

export type FeatureCategory = "quick_edit" | "product_image" | "commerce_pack";
export type FeatureJobType =
  | "local_edit"
  | "product_image"
  | "reference_remix"
  | "creative_image"
  | "detail_pack"
  | "amazon_visual_suite";
export type ProductImagePreset =
  | "scene_main"
  | "white_background"
  | "model_image"
  | "change_model"
  | "try_on"
  | "change_scene"
  | "change_background"
  | "change_color";
export type ProductImagePresetSlug =
  | "scene-main"
  | "white-background"
  | "model-image"
  | "change-model"
  | "try-on"
  | "change-scene"
  | "change-background"
  | "change-color";

export type FeatureDefinition = {
  id: string;
  title: string;
  shortTitle: string;
  description: string;
  category: FeatureCategory;
  route: string;
  icon: LucideIcon;
  tone: "coral" | "amber" | "indigo" | "cyan" | "green" | "rose";
  badge?: string;
  skillId: string;
  jobType: FeatureJobType;
  taskPreset?: ProductImagePreset;
  presetSlug?: ProductImagePresetSlug;
  runtimeCapability: string;
  workspaceTemplate: "masked_edit" | "product_image" | "detail_pack" | "fixed_pack";
  inputRoles: string[];
  resultTemplate: "before_after" | "result_grid" | "page_grid" | "grouped_grid";
  completionPolicy: string;
  supportsAssetPicker: boolean;
  supportsMultiSelect: boolean;
  supportsZipDownload: boolean;
  supportsContinueEditing: boolean;
  searchKeywords: string[];
  featured: boolean;
  inputHint: string;
  outputHint: string;
  guidance: string;
};

export const FEATURE_CATEGORY_LABELS: Record<FeatureCategory, string> = {
  quick_edit: "快捷改图",
  product_image: "商品主图",
  commerce_pack: "电商套图",
};

export const FEATURE_REGISTRY = [
  {
    id: "local-edit",
    title: "一句话改图",
    shortTitle: "局部改图",
    description: "涂选允许修改的区域，用一句话完成像素级局部精修。",
    category: "quick_edit",
    route: "/workspace/local-edit",
    icon: Brush,
    tone: "indigo",
    badge: "像素锁定",
    skillId: "masked-image-repair",
    jobType: "local_edit",
    runtimeCapability: "local_edit",
    workspaceTemplate: "masked_edit",
    inputRoles: ["source", "selection_mask"],
    resultTemplate: "before_after",
    completionPolicy: "strict_masked_result",
    supportsAssetPicker: false,
    supportsMultiSelect: false,
    supportsZipDownload: false,
    supportsContinueEditing: true,
    searchKeywords: ["局部修改", "蒙版", "精修", "一句话改图"],
    featured: true,
    inputHint: "1 张商品图 + 授权蒙版",
    outputHint: "1 张严格合成结果",
    guidance: "仅修改你涂选的授权区域，蒙版外像素保持锁定。",
  },
  {
    id: "change-color",
    title: "商品换色",
    shortTitle: "换色",
    description: "保留商品纹理、材质和品牌细节，快速生成目标配色。",
    category: "quick_edit",
    route: "/workspace/product-image/change-color",
    icon: PaintBucket,
    tone: "rose",
    badge: "热门",
    skillId: "xinghe-wanneng-shengtu-3-0",
    jobType: "product_image",
    taskPreset: "change_color",
    presetSlug: "change-color",
    runtimeCapability: "product_image.change_color",
    workspaceTemplate: "product_image",
    inputRoles: ["product_reference", "style_reference"],
    resultTemplate: "result_grid",
    completionPolicy: "independent_images",
    supportsAssetPicker: true,
    supportsMultiSelect: true,
    supportsZipDownload: true,
    supportsContinueEditing: true,
    searchKeywords: ["商品换色", "颜色", "改色", "SKU"],
    featured: false,
    inputHint: "商品图；可选颜色参考",
    outputHint: "1–4 张独立结果",
    guidance: "目标颜色为必填；建议同时描述需保留的材质、纹理与 Logo。",
  },
  {
    id: "change-background",
    title: "更换背景",
    shortTitle: "换背景",
    description: "保留商品主体与边缘细节，替换为更匹配渠道的背景。",
    category: "quick_edit",
    route: "/workspace/product-image/change-background",
    icon: Layers3,
    tone: "cyan",
    badge: "推荐",
    skillId: "xinghe-wanneng-shengtu-3-0",
    jobType: "product_image",
    taskPreset: "change_background",
    presetSlug: "change-background",
    runtimeCapability: "product_image.change_background",
    workspaceTemplate: "product_image",
    inputRoles: ["product_reference", "style_reference"],
    resultTemplate: "result_grid",
    completionPolicy: "independent_images",
    supportsAssetPicker: true,
    supportsMultiSelect: true,
    supportsZipDownload: true,
    supportsContinueEditing: true,
    searchKeywords: ["换背景", "背景替换", "抠图", "场景"],
    featured: true,
    inputHint: "商品图；可选背景参考",
    outputHint: "1–4 张独立结果",
    guidance: "描述背景类型、光线和是否保留原阴影，能获得更稳定的结果。",
  },
  {
    id: "change-scene",
    title: "更换场景",
    shortTitle: "换场景",
    description: "在保留商品构图的前提下，重建光线、反射与环境氛围。",
    category: "quick_edit",
    route: "/workspace/product-image/change-scene",
    icon: Blend,
    tone: "green",
    skillId: "xinghe-wanneng-shengtu-3-0",
    jobType: "product_image",
    taskPreset: "change_scene",
    presetSlug: "change-scene",
    runtimeCapability: "product_image.change_scene",
    workspaceTemplate: "product_image",
    inputRoles: ["product_reference", "style_reference"],
    resultTemplate: "result_grid",
    completionPolicy: "independent_images",
    supportsAssetPicker: true,
    supportsMultiSelect: true,
    supportsZipDownload: true,
    supportsContinueEditing: true,
    searchKeywords: ["换场景", "场景替换", "环境", "光影"],
    featured: false,
    inputHint: "商品图；可选场景参考",
    outputHint: "1–4 张独立结果",
    guidance: "可补充商品位置、构图保持、环境反射和光线匹配要求。",
  },
  {
    id: "change-model",
    title: "更换模特",
    shortTitle: "换模特",
    description: "保留商品、服装和姿态，替换更符合目标人群的模特。",
    category: "quick_edit",
    route: "/workspace/product-image/change-model",
    icon: ScanFace,
    tone: "amber",
    skillId: "xinghe-wanneng-shengtu-3-0",
    jobType: "product_image",
    taskPreset: "change_model",
    presetSlug: "change-model",
    runtimeCapability: "product_image.change_model",
    workspaceTemplate: "product_image",
    inputRoles: ["product_reference", "style_reference"],
    resultTemplate: "result_grid",
    completionPolicy: "independent_images",
    supportsAssetPicker: true,
    supportsMultiSelect: true,
    supportsZipDownload: true,
    supportsContinueEditing: true,
    searchKeywords: ["换模特", "模特替换", "人像", "服装"],
    featured: false,
    inputHint: "原商品模特图；可选目标模特参考",
    outputHint: "1–4 张独立结果",
    guidance: "说明需保留的服装、姿态、面部特征与原场景。",
  },
  {
    id: "scene-main",
    title: "场景主图",
    shortTitle: "场景主图",
    description: "围绕商品卖点生成可直接用于投放的商业场景主视觉。",
    category: "product_image",
    route: "/workspace/product-image/scene-main",
    icon: Camera,
    tone: "coral",
    badge: "主图",
    skillId: "xinghe-wanneng-shengtu-3-0",
    jobType: "product_image",
    taskPreset: "scene_main",
    presetSlug: "scene-main",
    runtimeCapability: "product_image.scene_main",
    workspaceTemplate: "product_image",
    inputRoles: ["product_reference", "style_reference"],
    resultTemplate: "result_grid",
    completionPolicy: "independent_images",
    supportsAssetPicker: true,
    supportsMultiSelect: true,
    supportsZipDownload: true,
    supportsContinueEditing: true,
    searchKeywords: ["场景主图", "商品主图", "棚拍", "商业摄影"],
    featured: false,
    inputHint: "商品图；可选场景参考",
    outputHint: "1–4 张独立结果",
    guidance: "可选择家居、户外、高端棚拍、节日、社媒或科技感方向。",
  },
  {
    id: "white-background",
    title: "电商白底图",
    shortTitle: "白底图",
    description: "生成主体比例稳定、阴影可控、适配平台规范的商品白底图。",
    category: "product_image",
    route: "/workspace/product-image/white-background",
    icon: Aperture,
    tone: "cyan",
    skillId: "xinghe-wanneng-shengtu-3-0",
    jobType: "product_image",
    taskPreset: "white_background",
    presetSlug: "white-background",
    runtimeCapability: "product_image.white_background",
    workspaceTemplate: "product_image",
    inputRoles: ["product_reference"],
    resultTemplate: "result_grid",
    completionPolicy: "independent_images",
    supportsAssetPicker: true,
    supportsMultiSelect: true,
    supportsZipDownload: true,
    supportsContinueEditing: true,
    searchKeywords: ["白底图", "纯白", "主图", "阴影"],
    featured: false,
    inputHint: "1–8 张商品参考图",
    outputHint: "1–4 张独立结果",
    guidance: "可说明主体占比、位置以及无阴影、柔光、悬浮或接地阴影。",
  },
  {
    id: "model-image",
    title: "模特商品图",
    shortTitle: "模特图",
    description: "根据商品类型生成模特、姿态、景别与场景一致的商品图。",
    category: "product_image",
    route: "/workspace/product-image/model-image",
    icon: PersonStanding,
    tone: "indigo",
    skillId: "xinghe-wanneng-shengtu-3-0",
    jobType: "product_image",
    taskPreset: "model_image",
    presetSlug: "model-image",
    runtimeCapability: "product_image.model_image",
    workspaceTemplate: "product_image",
    inputRoles: ["product_reference", "style_reference"],
    resultTemplate: "result_grid",
    completionPolicy: "independent_images",
    supportsAssetPicker: true,
    supportsMultiSelect: true,
    supportsZipDownload: true,
    supportsContinueEditing: true,
    searchKeywords: ["模特商品图", "人像", "服装", "上身"],
    featured: false,
    inputHint: "商品图；可选模特风格参考",
    outputHint: "1–4 张独立结果",
    guidance: "建议在补充要求中写明模特性别、年龄、景别、姿态与场景。",
  },
  {
    id: "try-on",
    title: "商品试穿",
    shortTitle: "试穿",
    description: "将服饰商品自然适配到模特，控制身份、姿态和穿着效果。",
    category: "product_image",
    route: "/workspace/product-image/try-on",
    icon: Shirt,
    tone: "green",
    skillId: "xinghe-wanneng-shengtu-3-0",
    jobType: "product_image",
    taskPreset: "try_on",
    presetSlug: "try-on",
    runtimeCapability: "product_image.try_on",
    workspaceTemplate: "product_image",
    inputRoles: ["product_reference", "style_reference"],
    resultTemplate: "result_grid",
    completionPolicy: "independent_images",
    supportsAssetPicker: true,
    supportsMultiSelect: true,
    supportsZipDownload: true,
    supportsContinueEditing: true,
    searchKeywords: ["试穿", "虚拟试衣", "服饰", "模特"],
    featured: false,
    inputHint: "服饰商品图 + 模特参考图",
    outputHint: "1–4 张独立结果",
    guidance: "参考图用于模特线索；请说明穿着方式、身份保留和适配强度。",
  },
  {
    id: "reference-remix",
    title: "参考图二创",
    shortTitle: "参考二创",
    description: "借鉴参考图的构图与光影，替换为自己的商品、品牌和卖点。",
    category: "product_image",
    route: "/workspace/reference-remix",
    icon: Images,
    tone: "rose",
    badge: "双图输入",
    skillId: "xinghe-reference-image-remix-3",
    jobType: "reference_remix",
    runtimeCapability: "reference_remix",
    workspaceTemplate: "product_image",
    inputRoles: ["product_reference", "style_reference"],
    resultTemplate: "result_grid",
    completionPolicy: "independent_images",
    supportsAssetPicker: true,
    supportsMultiSelect: true,
    supportsZipDownload: true,
    supportsContinueEditing: true,
    searchKeywords: ["参考图二创", "竞品", "构图", "风格迁移"],
    featured: true,
    inputHint: "我的商品图 + 参考图",
    outputHint: "1–4 张独立结果",
    guidance: "锁定参考图的构图、景别与光影，替换商品、品牌和活动信息。",
  },
  {
    id: "creative-image",
    title: "电商创意图",
    shortTitle: "创意图",
    description: "从卖点、痛点、场景和活动方向生成成组电商创意素材。",
    category: "product_image",
    route: "/workspace/creative-image",
    icon: Sparkles,
    tone: "coral",
    skillId: "xinghe-ecommerce-creative-image",
    jobType: "creative_image",
    runtimeCapability: "creative_image",
    workspaceTemplate: "product_image",
    inputRoles: ["product_reference", "competitor_reference"],
    resultTemplate: "result_grid",
    completionPolicy: "independent_images",
    supportsAssetPicker: true,
    supportsMultiSelect: true,
    supportsZipDownload: true,
    supportsContinueEditing: true,
    searchKeywords: ["电商创意图", "卖点", "广告", "活动图"],
    featured: false,
    inputHint: "商品图；竞品图可选",
    outputHint: "默认 4 张，最多 4 张",
    guidance: "每张结果是独立可交付图片，不以拼图或提示词占位。",
  },
  {
    id: "detail-pack",
    title: "商品详情图",
    shortTitle: "详情套图",
    description: "在同一页面选择国内或国际市场，自动规划并逐页生成详情套图。",
    category: "commerce_pack",
    route: "/workspace/detail-pack",
    icon: Boxes,
    tone: "indigo",
    badge: "成套生成",
    skillId: "xinghe-ecommerce-detail",
    jobType: "detail_pack",
    runtimeCapability: "detail_pack",
    workspaceTemplate: "detail_pack",
    inputRoles: ["product_reference", "style_reference"],
    resultTemplate: "page_grid",
    completionPolicy: "validated_plan_and_pages",
    supportsAssetPicker: true,
    supportsMultiSelect: true,
    supportsZipDownload: true,
    supportsContinueEditing: true,
    searchKeywords: ["商品详情图", "详情页", "国内电商", "跨境电商"],
    featured: true,
    inputHint: "多角度商品图；参考图可选",
    outputHint: "按规划逐页交付",
    guidance: "页面内选择国内或国际市场；现有国际稳定链路保持不变。",
  },
  {
    id: "amazon-visual-suite",
    title: "亚马逊主副图 A+",
    shortTitle: "Amazon A+",
    description: "一次生成主图、副图和桌面/移动 A+ 的固定 21 张视觉套图。",
    category: "commerce_pack",
    route: "/workspace/amazon-visual-suite",
    icon: PackageCheck,
    tone: "amber",
    badge: "21 张",
    skillId: "xinghe-amazon-visual-suite",
    jobType: "amazon_visual_suite",
    runtimeCapability: "amazon_visual_suite",
    workspaceTemplate: "fixed_pack",
    inputRoles: [
      "white_background_product",
      "product_detail",
      "package_reference",
      "scene_reference",
      "brand_reference",
    ],
    resultTemplate: "grouped_grid",
    completionPolicy: "amazon_21_of_21",
    supportsAssetPicker: true,
    supportsMultiSelect: true,
    supportsZipDownload: true,
    supportsContinueEditing: false,
    searchKeywords: ["亚马逊", "Amazon", "A+", "主图", "副图", "21 张"],
    featured: true,
    inputHint: "白底商品图 + 多角色参考素材",
    outputHint: "固定 21 张正式结果",
    guidance: "Contact Sheet 不计入 21 张正式交付；完成以 21/21 为准。",
  },
] as const satisfies readonly FeatureDefinition[];

export const FEATURE_GROUPS = (["quick_edit", "product_image", "commerce_pack"] as const).map(
  (category) => ({
    category,
    label: FEATURE_CATEGORY_LABELS[category],
    features: FEATURE_REGISTRY.filter((feature) => feature.category === category),
  }),
);

export const PRODUCT_IMAGE_FEATURES = FEATURE_REGISTRY.filter(
  (feature): feature is (typeof FEATURE_REGISTRY)[number] & {
    jobType: "product_image";
    taskPreset: ProductImagePreset;
    presetSlug: ProductImagePresetSlug;
  } => feature.jobType === "product_image",
);

export function getFeatureById(id: string): FeatureDefinition | undefined {
  return FEATURE_REGISTRY.find((feature) => feature.id === id);
}

export function getFeatureByRoute(pathname: string): FeatureDefinition | undefined {
  const route = pathname.split(/[?#]/, 1)[0].replace(/\/+$/, "") || "/";
  return FEATURE_REGISTRY.find((feature) => feature.route === route);
}

export function getProductImageFeatureByPresetSlug(
  presetSlug: string,
): (typeof PRODUCT_IMAGE_FEATURES)[number] | undefined {
  return PRODUCT_IMAGE_FEATURES.find((feature) => feature.presetSlug === presetSlug);
}
