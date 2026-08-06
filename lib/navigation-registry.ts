import { getFeatureById } from "@/lib/feature-registry";

function navigationFeature(
  featureId: string,
  options: {
    description: string;
  },
) {
  const feature = getFeatureById(featureId);

  if (!feature) {
    throw new Error(`Navigation feature is missing from feature registry: ${featureId}`);
  }

  return {
    featureId: feature.id,
    href: feature.route,
    label: feature.title,
    description: options.description,
    icon: feature.icon,
    tone: feature.tone,
  };
}

export type NavigationFeatureItem = ReturnType<typeof navigationFeature>;

export type NavigationFeatureGroup = {
  label: string;
  items: readonly NavigationFeatureItem[];
};

export type NavigationMenuDefinition = {
  key: "all-features" | "toolbox";
  label: string;
  href: string;
  groups: readonly NavigationFeatureGroup[];
  footer?: {
    label: string;
    href: string;
  };
};

export const PRIMARY_NAVIGATION_LINKS = [
  { label: "首页", href: "/" },
  { label: "素材中心", href: "/assets" },
  { label: "生成记录", href: "/jobs" },
] as const;

export const AI_FEATURES_MENU = {
  key: "all-features",
  label: "AI功能大全",
  href: "/tools",
  groups: [
    {
      label: "热门创作",
      items: [
        navigationFeature("local-edit", {
          description: "用自然语言完成局部精修",
        }),
        navigationFeature("change-background", {
          description: "快速替换商品背景，适配不同展示需求",
        }),
        navigationFeature("reference-remix", {
          description: "快速复刻参考图的构图与氛围",
        }),
      ],
    },
    {
      label: "电商套图",
      items: [
        navigationFeature("detail-pack", {
          description: "生成国内、国际全平台详情图",
        }),
        navigationFeature("amazon-visual-suite", {
          description: "生成亚马逊主图、副图与 A+ 内容",
        }),
      ],
    },
  ],
  footer: {
    label: "查看全部 AI 功能",
    href: "/tools",
  },
} as const satisfies NavigationMenuDefinition;

export const AI_TOOLBOX_MENU = {
  key: "toolbox",
  label: "AI工具箱",
  href: "/#ai-toolbox",
  groups: [
    {
      label: "常用工具",
      items: [
        navigationFeature("change-color", {
          description: "保留商品纹理，快速生成目标配色",
        }),
        navigationFeature("change-scene", {
          description: "重建商品场景与光影氛围",
        }),
        navigationFeature("change-model", {
          description: "替换符合目标人群的模特",
        }),
        navigationFeature("scene-main", {
          description: "生成商业场景主视觉",
        }),
        navigationFeature("white-background", {
          description: "生成符合平台规范的白底图",
        }),
        navigationFeature("model-image", {
          description: "生成模特展示商品图",
        }),
        navigationFeature("try-on", {
          description: "让服饰商品自然适配模特",
        }),
        navigationFeature("creative-image", {
          description: "生成卖点、活动与营销创意素材",
        }),
      ],
    },
  ],
} as const satisfies NavigationMenuDefinition;

export const AI_NAVIGATION_MENUS = [AI_FEATURES_MENU, AI_TOOLBOX_MENU] as const;
