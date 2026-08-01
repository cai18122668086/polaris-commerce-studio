"use client";

import { ArrowRight, Search, Sparkles, WandSparkles, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { AppShell } from "@/components/app-shell";
import {
  FEATURE_CATEGORY_LABELS,
  FEATURE_REGISTRY,
  type FeatureCategory,
} from "@/lib/feature-registry";
import styles from "./tools.module.css";

const categoryOrder: FeatureCategory[] = [
  "quick_edit",
  "product_image",
  "commerce_pack",
];

export default function ToolsPage() {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const visibleFeatures = useMemo(
    () =>
      FEATURE_REGISTRY.filter((feature) => {
        if (!normalizedQuery) return true;
        return [
          feature.title,
          feature.shortTitle,
          feature.description,
          feature.inputHint,
          feature.outputHint,
          ...feature.searchKeywords,
        ]
          .join(" ")
          .toLowerCase()
          .includes(normalizedQuery);
      }),
    [normalizedQuery],
  );

  return (
    <AppShell sidebar={false}>
      <div className={styles.page}>
        <header className={styles.hero}>
          <div className={styles.heroCopy}>
            <span className={styles.eyebrow}>
              <WandSparkles size={16} /> AI 创作能力中心
            </span>
            <h1>功能大全</h1>
            <p>
              从一次精确改图到完整电商套图，所有功能共享素材、任务和结果交付链路。
            </p>
            <div className={styles.metrics} aria-label="功能统计">
              <span><strong>{FEATURE_REGISTRY.length}</strong> 项创作功能</span>
              <span><strong>8</strong> 个万能生图入口</span>
              <span><strong>1</strong> 个统一任务中心</span>
            </div>
          </div>
          <div className={styles.heroArt} aria-hidden="true">
            <span><Sparkles size={30} /></span>
            <div><i /><i /><i /><i /></div>
          </div>
        </header>

        <label className={styles.searchBox}>
          <Search size={20} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索功能，例如：换背景、白底图、Amazon A+"
            aria-label="搜索 AI 创作功能"
          />
          {query ? (
            <button type="button" onClick={() => setQuery("")} aria-label="清空搜索">
              <X size={17} />
            </button>
          ) : (
            <kbd>{FEATURE_REGISTRY.length} 项</kbd>
          )}
        </label>

        {visibleFeatures.length ? (
          <div className={styles.directory}>
            {categoryOrder.map((category) => {
              const features = visibleFeatures.filter(
                (feature) => feature.category === category,
              );
              if (!features.length) return null;
              return (
                <section className={styles.group} key={category}>
                  <div className={styles.groupHeading}>
                    <div>
                      <span>{String(categoryOrder.indexOf(category) + 1).padStart(2, "0")}</span>
                      <h2>{FEATURE_CATEGORY_LABELS[category]}</h2>
                    </div>
                    <p>{features.length} 项能力</p>
                  </div>
                  <div className={styles.grid}>
                    {features.map((feature) => {
                      const Icon = feature.icon;
                      const badge = "badge" in feature ? feature.badge : undefined;
                      return (
                        <article
                          className={styles.card}
                          data-tone={feature.tone}
                          key={feature.id}
                        >
                          <div className={styles.cardArt} aria-hidden="true">
                            <span><Icon size={30} /></span>
                            <i>{feature.outputHint}</i>
                          </div>
                          <div className={styles.cardBody}>
                            <div className={styles.cardTitleRow}>
                              <h3>{feature.title}</h3>
                              {badge ? <span>{badge}</span> : null}
                            </div>
                            <p>{feature.description}</p>
                            <dl>
                              <div>
                                <dt>输入</dt>
                                <dd>{feature.inputHint}</dd>
                              </div>
                              <div>
                                <dt>输出</dt>
                                <dd>{feature.outputHint}</dd>
                              </div>
                            </dl>
                            <Link href={feature.route} className={styles.primaryAction}>
                              立即制作 <ArrowRight size={17} />
                            </Link>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        ) : (
          <section className={styles.emptyState}>
            <Search size={28} />
            <h2>没有找到匹配的功能</h2>
            <p>换一个商品、场景或平台关键词试试。</p>
            <button type="button" onClick={() => setQuery("")}>查看全部功能</button>
          </section>
        )}
      </div>
    </AppShell>
  );
}
