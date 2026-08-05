"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, Search, Sparkles } from "lucide-react";

import { HomeAiToolbox } from "@/components/home-ai-toolbox";
import { HomeBannerCarousel } from "@/components/home-banner-carousel";
import {
  resolveRuntimeCapability,
  useRuntimeStatus,
} from "@/features/runtime/api/runtime";
import { FEATURE_REGISTRY } from "@/lib/feature-registry";

const FEATURE_PRESENTATION_OVERRIDES: Record<
  string,
  { title?: string; description?: string }
> = {
  "local-edit": {
    description: "局部修改，让你的出图更加精美",
  },
  "reference-remix": {
    title: "一键模仿",
  },
  "detail-pack": {
    description: "一键生成国内、国际全平台详情图",
  },
  "amazon-visual-suite": {
    title: "亚马逊套图",
  },
};

const searchableTools = FEATURE_REGISTRY.map((feature) => {
  const presentation = FEATURE_PRESENTATION_OVERRIDES[feature.id];
  return {
    id: feature.id,
    title: presentation?.title ?? feature.title,
    registryTitle: feature.title,
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

const featuredTools = searchableTools.filter((tool) => tool.featured);

export function ToolDirectory() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [activeSearchIndex, setActiveSearchIndex] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);
  const runtime = useRuntimeStatus();
  const keyword = query.trim().toLowerCase();
  const searchResults = keyword
    ? searchableTools
        .filter((tool) =>
          `${tool.title} ${tool.registryTitle} ${tool.description} ${tool.keywords.join(" ")}`
            .toLowerCase()
            .includes(keyword),
        )
        .slice(0, 8)
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
        <header className="focus-home__section-head">
          <h2>一键直达任务</h2>
          <p>快速定位，保留你熟悉的电商工作流程</p>
        </header>

        <div className="home-feature-grid">
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
                  <span className="home-feature-card__art" aria-hidden="true">
                    <Icon size={68} />
                  </span>
                  <div>
                    <strong>{tool.title}</strong>
                    <span>{tool.description}</span>
                    <ArrowRight size={18} />
                  </div>
                </Link>
              );
          })}
        </div>

        <div className="home-command">
          <h2>没找到你的类目？用下面这个快速入口</h2>
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
                } else if (event.key === "Enter") {
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
              aria-expanded={Boolean(keyword && searchResults.length)}
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
              role="listbox"
              aria-label="功能搜索结果"
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
                        <small>{tool.description}</small>
                      </span>
                      {unavailable ? <em>暂不可用</em> : <ArrowRight size={16} />}
                    </Link>
                  );
                })
              ) : (
                <div className="home-search-empty">
                  <Search size={20} />
                  <strong>没有找到匹配功能</strong>
                  <button type="button" onClick={() => setQuery("")}>
                    清除搜索
                  </button>
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

        <HomeAiToolbox />
      </div>
    </section>
  );
}
