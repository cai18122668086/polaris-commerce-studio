"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, Flame, Search, Sparkles, type LucideIcon } from "lucide-react";

import { HomeAiToolbox } from "@/components/home-ai-toolbox";
import { HomeBannerCarousel } from "@/components/home-banner-carousel";
import {
  resolveRuntimeCapability,
  useRuntimeStatus,
} from "@/features/runtime/api/runtime";
import { FEATURE_REGISTRY } from "@/lib/feature-registry";
import { searchFeatures } from "@/lib/feature-search";
import {
  HOME_FEATURE_VISUALS,
  type HomeFeatureImage,
} from "@/lib/home-feature-visuals";
import { HOT_FEATURE_IDS } from "@/lib/feature-priorities";

const FEATURE_PRESENTATION_OVERRIDES: Record<
  string,
  { description?: string }
> = {
  "local-edit": {
    description: "用一句话完成局部精修，让你的出图更加精美",
  },

  "detail-pack": {
    description: "一键生成国内、国际全平台详情图",
  },

};

const searchableTools = FEATURE_REGISTRY.map((feature) => {
  const presentation = FEATURE_PRESENTATION_OVERRIDES[feature.id];
  return {
    id: feature.id,
    title: feature.title,
    description: presentation?.description ?? feature.description,
    href: feature.route,
    icon: feature.icon,
    className:
      feature.workspaceTemplate === "masked_edit"
        ? "home-feature--edit"
        : "home-feature--pack",
    keywords: feature.searchKeywords,
    runtimeCapability: feature.runtimeCapability,
    featured: feature.featured,
  };
});

const featuredTools = [
  ...searchableTools.filter((tool) => tool.featured && HOT_FEATURE_IDS.has(tool.id)),
  ...searchableTools.filter((tool) => tool.featured && !HOT_FEATURE_IDS.has(tool.id)),
];

const RELATED_SCENARIO_RECOMMENDATIONS = [
  {
    pattern: /亚马逊|amazon|跨境|a\+/iu,
    featureIds: ["amazon-visual-suite", "detail-pack", "white-background"],
  },
  {
    pattern: /主图|淘宝|天猫|京东|轮播/iu,
    featureIds: ["domestic-main-image", "scene-main", "white-background"],
  },
  {
    pattern: /背景|场景|环境|光影/iu,
    featureIds: ["change-background", "change-scene", "scene-main"],
  },
  {
    pattern: /模特|服装|穿搭|姿势|试穿/iu,
    featureIds: ["model-pose-transfer", "try-on", "change-model"],
  },
  {
    pattern: /颜色|换色|配色/iu,
    featureIds: ["change-color", "local-edit", "creative-image"],
  },
  {
    pattern: /详情|套图|整套/iu,
    featureIds: ["detail-pack", "domestic-main-image", "amazon-visual-suite"],
  },
] as const;

function getRelatedScenarioTools(query: string) {
  const recommendation = RELATED_SCENARIO_RECOMMENDATIONS.find(({ pattern }) =>
    pattern.test(query),
  );
  const featureIds = recommendation?.featureIds ?? [
    "local-edit",
    "change-background",
    "detail-pack",
  ];

  return featureIds.flatMap((featureId) => {
    const tool = searchableTools.find((item) => item.id === featureId);
    return tool ? [tool] : [];
  });
}

const HOME_FEATURE_FLOW_COPY: Record<string, [string, string]> = {
  "local-edit": ["原图", "局部精修"],
  "change-background": ["商品不变", "场景升级"],
  "reference-remix": ["我的商品", "参考构图"],
  "detail-pack": ["商品素材", "详情页规划"],
  "amazon-visual-suite": ["商品素材", "21 张套图"],
};


function FeatureVisualImage({
  image,
  className,
}: {
  image: HomeFeatureImage;
  className: string;
}) {
  return (
    <img
      src={image.src}
      width={image.width}
      height={image.height}
      className={className}
      alt=""
      loading="eager"
      decoding="async"
      draggable={false}
    />
  );
}

function HomeFeatureCardArt({
  featureId,
  FallbackIcon,
}: {
  featureId: string;
  FallbackIcon: LucideIcon;
}) {
  const visual = HOME_FEATURE_VISUALS[featureId];

  if (!visual) {
    return (
      <span
        className="home-feature-card__art home-feature-card__art--fallback"
        aria-hidden="true"
      >
        <FallbackIcon size={68} />
      </span>
    );
  }

  const heroImage = visual.kind === "detail-scroll" ? visual.before : visual.after;
  const flowCopy = HOME_FEATURE_FLOW_COPY[featureId] ?? ["输入", "生成结果"];

  return (
    <span
      className={`home-feature-card__art home-feature-card__art--${visual.kind}`}
      aria-hidden="true"
    >
      <span className="home-feature-card__visual-stage">
        <FeatureVisualImage
          image={heroImage}
          className="home-feature-card__image home-feature-card__image--hero"
        />
        <span className="home-feature-card__flow">
          <span>{flowCopy[0]}</span>
          <ArrowRight size={13} />
          <span>{flowCopy[1]}</span>
        </span>
        {visual.kind === "amazon" ? (
          <span className="home-feature-card__count-badge">{"21 \u5f20"}</span>
        ) : null}
        {visual.kind === "detail-scroll" ? (
          <span className="home-feature-card__detail-hint">结构 · 场景 · 卖点</span>
        ) : null}
      </span>
    </span>
  );
}

export function ToolDirectory() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [activeSearchIndex, setActiveSearchIndex] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);
  const featureGridRef = useRef<HTMLDivElement>(null);
  const runtime = useRuntimeStatus();
  const keyword = query.trim();
  const searchResults = keyword
    ? searchFeatures(keyword, FEATURE_REGISTRY)
        .flatMap((match) => {
          const tool = searchableTools.find((item) => item.id === match.feature.id);
          return tool ? [{ ...match, ...tool }] : [];
        })
        .slice(0, 8)
    : [];
  const relatedScenarioTools = keyword && !searchResults.length
    ? getRelatedScenarioTools(keyword)
    : [];

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);

  useEffect(() => {
    const grid = featureGridRef.current;
    if (
      !grid ||
      typeof IntersectionObserver === "undefined" ||
      !window.matchMedia("(hover: none), (pointer: coarse)").matches
    ) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.add("is-mobile-played");
          observer.unobserve(entry.target);
        }
      },
      { threshold: 0.45 },
    );

    const cards = grid.querySelectorAll<HTMLElement>(
      ".home-feature-card[data-feature-visual]",
    );
    cards.forEach((card) => observer.observe(card));

    return () => observer.disconnect();
  }, []);


  const openSearchResult = (index: number) => {
    const result = searchResults[index];
    if (!result) return;
    const capability = resolveRuntimeCapability(runtime.data, result.runtimeCapability);
    if (capability !== undefined && capability.availability !== "available") return;
    router.push(result.href);
  };

  return (
    <section className="focus-home" id="tools">
      <HomeBannerCarousel />

      <div className="focus-home__content">
        <div className="home-command home-command--primary">
          <h2>描述你的商品图需求，快速找到合适功能</h2>
          <p>
            <strong>全品类</strong> 都可以用
          </p>
          <label>
            <span className="home-command__icon">
              <Sparkles size={18} />
            </span>
            <input
              ref={searchRef}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setActiveSearchIndex(0);
              }}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown" && searchResults.length) {
                  event.preventDefault();
                  setActiveSearchIndex((current) =>
                    Math.min(current + 1, searchResults.length - 1),
                  );
                } else if (event.key === "ArrowUp" && searchResults.length) {
                  event.preventDefault();
                  setActiveSearchIndex((current) => Math.max(current - 1, 0));
                } else if (event.key === "Enter" && searchResults.length) {
                  event.preventDefault();
                  openSearchResult(activeSearchIndex);
                } else if (event.key === "Escape") {
                  setQuery("");
                }
              }}
              placeholder="描述你要处理的商品或任务，例如：耳机局部精修、护肤品详情套图"
              aria-label="搜索创作任务"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={Boolean(keyword)}
              aria-controls="home-search-results"
              aria-activedescendant={
                searchResults[activeSearchIndex]
                  ? `home-search-result-${searchResults[activeSearchIndex].id}`
                  : undefined
              }
            />
            <kbd>⌘ K</kbd>
            <button
              type="button"
              aria-label="打开首个搜索结果"
              onClick={() => openSearchResult(activeSearchIndex)}
              disabled={!searchResults.length}
            >
              <ArrowRight size={18} />
            </button>
          </label>
          {keyword ? (
            <div
              className="home-search-results"
              id="home-search-results"
              role={searchResults.length ? "listbox" : "region"}
              aria-label={searchResults.length ? "功能搜索结果" : "相近场景推荐"}
            >
              {searchResults.length ? (
                searchResults.map((tool, index) => {
                  const capability = resolveRuntimeCapability(
                    runtime.data,
                    tool.runtimeCapability,
                  );
                  const unavailable =
                    capability !== undefined &&
                    capability.availability !== "available";
                  const Icon = tool.icon;
                  return (
                    <Link
                      id={`home-search-result-${tool.id}`}
                      href={tool.href}
                      role="option"
                      aria-selected={index === activeSearchIndex}
                      aria-disabled={unavailable || undefined}
                      className={`home-search-result${
                        index === activeSearchIndex ? " is-active" : ""
                      }${unavailable ? " is-unavailable" : ""}`}
                      onMouseEnter={() => setActiveSearchIndex(index)}
                      onClick={
                        unavailable
                          ? (event) => {
                              event.preventDefault();
                            }
                          : undefined
                      }
                      key={tool.id}
                    >
                      <span className="home-search-result__icon" aria-hidden="true">
                        <Icon size={19} />
                      </span>
                      <span>
                        <strong>{tool.title}</strong>
                        <small className="home-search-result__description">{tool.description}</small>
                        <small className="home-search-result__reason">{tool.matchReason}</small>
                      </span>
                      {unavailable ? <em>暂不可用</em> : <ArrowRight size={16} />}
                    </Link>
                  );
                })
              ) : (
                <div className="home-search-empty">
                  <div className="home-search-empty__head">
                    <span className="home-search-empty__icon" aria-hidden="true">
                      <Search size={20} />
                    </span>
                    <div>
                      <strong>没有找到精确匹配</strong>
                      <p>试试下面这些相近场景</p>
                    </div>
                    <button type="button" onClick={() => setQuery("")}>
                      清除搜索
                    </button>
                  </div>
                  <div className="home-search-recommendations">
                    {relatedScenarioTools.map((tool) => {
                      const capability = resolveRuntimeCapability(
                        runtime.data,
                        tool.runtimeCapability,
                      );
                      const unavailable =
                        capability !== undefined &&
                        capability.availability !== "available";
                      const Icon = tool.icon;

                      return (
                        <Link
                          href={tool.href}
                          className={`home-search-recommendation${
                            unavailable ? " is-unavailable" : ""
                          }`}
                          aria-disabled={unavailable || undefined}
                          onClick={
                            unavailable
                              ? (event) => {
                                  event.preventDefault();
                                }
                              : undefined
                          }
                          key={tool.id}
                        >
                          <span aria-hidden="true">
                            <Icon size={18} />
                          </span>
                          <span>
                            <strong>{tool.title}</strong>
                            <small>{tool.description}</small>
                          </span>
                          {unavailable ? <em>暂不可用</em> : <ArrowRight size={15} />}
                        </Link>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          ) : null}
          <div className="home-command__promises">
            <span>
              <Check size={13} /> 保留原有工作台
            </span>
            <span>
              <Check size={13} /> 不改变任务语义
            </span>
            <span>
              <Check size={13} /> 支持生成记录追踪
            </span>
          </div>
        </div>

        <header className="focus-home__section-head">
          <h2>一键直达任务</h2>
          <p>快速定位，保留你熟悉的电商工作流程</p>
        </header>

        <div className="home-feature-grid" ref={featureGridRef}>
          {featuredTools.map((tool) => {
              const capability = resolveRuntimeCapability(
                runtime.data,
                tool.runtimeCapability,
              );
              const unavailable =
                capability !== undefined &&
                capability.availability !== "available";
              const Icon = tool.icon;

              return (
                <Link
                  href={tool.href}
                  className={`home-feature-card ${tool.className}${
                    unavailable ? " is-unavailable" : ""
                  }`}
                  data-feature-id={tool.id}
                  data-feature-visual={HOME_FEATURE_VISUALS[tool.id]?.kind}
                  data-runtime-capability={tool.runtimeCapability}
                  data-capability-state={capability?.availability ?? "unknown"}
                  aria-disabled={unavailable || undefined}
                  tabIndex={unavailable ? -1 : undefined}
                  onClick={
                    unavailable
                      ? (event) => {
                          event.preventDefault();
                        }
                      : undefined
                  }
                  key={tool.id}
                >
                  <HomeFeatureCardArt
                    featureId={tool.id}
                    FallbackIcon={Icon}
                  />
                  {HOT_FEATURE_IDS.has(tool.id) ? (
                    <span
                      className="home-feature-card__hot"
                      aria-label="热门功能"
                      title="热门功能"
                    >
                      <Flame size={16} fill="currentColor" />
                    </span>
                  ) : null}
                  <div>
                    <strong>{tool.title}</strong>
                    <span>{tool.description}</span>
                    <ArrowRight size={18} />
                  </div>
                </Link>
              );
          })}
        </div>

        <HomeAiToolbox />
      </div>
    </section>
  );
}
