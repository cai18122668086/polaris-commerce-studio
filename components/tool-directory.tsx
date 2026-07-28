"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  BriefcaseBusiness,
  Check,
  Footprints,
  Headphones,
  PackageOpen,
  Search,
  Sparkles,
  Watch,
} from "lucide-react";

const featuredTools = [
  {
    title: "局部修改",
    description: "一句话精修，只改变选中的区域",
    href: "/workspace/local-edit",
    icon: Headphones,
    className: "home-feature--edit",
  },
  {
    title: "商品详情图",
    description: "从商品素材到完整电商套图",
    href: "/workspace/detail-pack",
    icon: PackageOpen,
    className: "home-feature--pack",
  },
];

const categoryCards = [
  {
    title: "箱包手袋",
    description: "快速统一商品氛围",
    icon: BriefcaseBusiness,
  },
  {
    title: "腕表饰品",
    description: "突出材质与细节",
    icon: Watch,
  },
  {
    title: "鞋服商品",
    description: "减少重复修图工作",
    icon: Footprints,
  },
];

export function ToolDirectory() {
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const keyword = query.trim().toLowerCase();
  const visibleTools = featuredTools.filter((tool) =>
    `${tool.title} ${tool.description}`.toLowerCase().includes(keyword),
  );

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

  return (
    <section className="focus-home" id="tools">
      <div className="focus-home__hero">
        <div className="focus-home__hero-inner">
          <div className="focus-home__headline">
            <span>极光商绘</span>
            <h1>懂电商的全品类出图工作台</h1>
          </div>
          <div className="focus-home__hero-art" aria-hidden="true">
            <span className="hero-art__tile">
              <Headphones size={28} />
            </span>
            <span className="hero-art__product">
              <BriefcaseBusiness size={58} />
            </span>
            <span className="hero-art__spark">
              <Sparkles size={26} />
            </span>
          </div>
          <Link href="/help" className="focus-home__notice">
            <span>◔</span>
            公告与使用指南
          </Link>
        </div>
      </div>

      <div className="focus-home__content">
        <header className="focus-home__section-head">
          <h2>一键直达创作任务</h2>
          <p>快速定位，保留你熟悉的电商工作流程</p>
        </header>

        {visibleTools.length ? (
          <div className="home-feature-grid">
            {visibleTools.map((tool) => (
              <Link
                href={tool.href}
                className={`home-feature-card ${tool.className}`}
                key={tool.href}
              >
                <span className="home-feature-card__art" aria-hidden="true">
                  <tool.icon size={68} />
                </span>
                <div>
                  <strong>{tool.title}</strong>
                  <span>{tool.description}</span>
                  <ArrowRight size={18} />
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="home-search-empty">
            <Search size={22} />
            <strong>没有找到匹配的工作流</strong>
            <button onClick={() => setQuery("")}>查看全部</button>
          </div>
        )}

        <div className="home-category-grid" aria-label="更多商品类别">
          {categoryCards.map((card) => (
            <Link
              href="/workspace/detail-pack"
              className="home-category-card"
              key={card.title}
            >
              <div>
                <strong>{card.title}</strong>
                <span>{card.description}</span>
                <i>
                  <ArrowRight size={16} />
                </i>
              </div>
              <span className="home-category-card__art" aria-hidden="true">
                <card.icon size={46} />
              </span>
            </Link>
          ))}
        </div>

        <div className="home-command">
          <h2>没找到你的类别？用下面这个快速入口</h2>
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
              onChange={(event) => setQuery(event.target.value)}
              placeholder="描述你要处理的商品或任务，例如：耳机局部精修、护肤品详情套图"
              aria-label="搜索创作任务"
            />
            <kbd>⌘ K</kbd>
            <button
              type="button"
              aria-label="搜索"
              onClick={() =>
                document
                  .querySelector(".focus-home__section-head")
                  ?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            >
              <ArrowRight size={18} />
            </button>
          </label>
          <div className="home-command__promises">
            <span>
              <Check size={13} /> 保留原有工作台
            </span>
            <span>
              <Check size={13} /> 不改变任务语义
            </span>
            <span>
              <Check size={13} /> 已接入内部 mock API
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
