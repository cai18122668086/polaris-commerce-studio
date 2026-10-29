"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, ArrowRight, ArrowUpRight, Check, Globe2, Grid2X2, ImagePlus, Layers3, Lightbulb, PackageCheck, ShoppingBag, Sparkles } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { commerceEntriesFor, commerceEntryHref } from "@/lib/commerce-entrypoints";
import { FEATURE_THUMBNAILS } from "@/lib/creation-entrypoints";
import styles from "./create.module.css";

const visualCopy = {
  "domestic-main-image": { title: "把第一眼做好", caption: "搜索主图 / 连续轮播" },
  "detail-pack": { title: "讲清每个卖点", caption: "卖点 / 场景 / 商品细节" },
  "amazon-visual-suite": { title: "一次备齐整套", caption: "主图 / 副图 / A+" },
  "crossborder-detail": { title: "让商品走更远", caption: "海外店铺 / 商品详情" },
};

export default function CreatePage() {
  const search = useSearchParams();
  const marketValue = search.get("market");
  const market = marketValue === "domestic" || marketValue === "international" ? marketValue : undefined;
  const goal = search.get("goal");
  const hasAssets = search.getAll("assetId").length > 0;
  function marketHref(value?: string, selectedGoal = goal) {
    const params = new URLSearchParams();
    if (selectedGoal === "main" || selectedGoal === "detail") params.set("goal", selectedGoal);
    if (value) params.set("market", value);
    for (const key of ["workspaceId", "assetId", "inspirationCaseId"]) {
      for (const value of search.getAll(key)) params.append(key, value);
    }
    return params.size ? `/create?${params}` : "/create";
  }
  const entries = commerceEntriesFor({ market, goal, hasAssets });
  return <AppShell sidebar={false}><div className={styles.page}>
    <div className={styles.breadcrumb}><Link href="/"><ArrowLeft size={14} aria-hidden="true" /> 创作首页</Link><span>/</span><span>电商套图</span></div>
    <header className={styles.hero}>
      <div className={styles.heroCopy}><span className="commerce-eyebrow">MADE FOR YOUR NEXT LAUNCH</span><h1>为你的商品，选一套好图。</h1><p>从第一眼的主图，到讲清卖点的详情。<br />找到适合销售平台的套图，开始下一次上新。</p></div>
      <div className={styles.heroArt} aria-hidden="true">
        {["domestic-main-image", "detail-pack", "amazon-visual-suite"].map(id => <img key={id} src={FEATURE_THUMBNAILS[id]} alt="" width={1374} height={1145} />)}
        <span><Sparkles size={13} /> 让好商品，一眼出彩</span>
      </div>
    </header>
    <div className={styles.marketBar}>
      <span className={styles.marketLabel}>销售市场</span>
      <nav className={styles.markets} aria-label="选择电商市场">
        <Link href={marketHref()} aria-current={!market ? "page" : undefined}><Grid2X2 size={16} aria-hidden="true" />全部平台</Link>
        <Link href={marketHref("domestic")} aria-current={market === "domestic" ? "page" : undefined}><ShoppingBag size={16} aria-hidden="true" />国内电商</Link>
        <Link href={marketHref("international")} aria-current={market === "international" ? "page" : undefined}><Globe2 size={16} aria-hidden="true" />跨境电商</Link>
      </nav>
    </div>
    <section aria-labelledby="creation-options-title">
      <header className={styles.selectionHeading}><div><h2 id="creation-options-title">{goal === "main" ? "选择主图创作方式" : goal === "detail" ? "选择详情创作方式" : "选择你需要的套图"}</h2><p>{market === "domestic" ? "淘宝 · 天猫 · 京东 · 拼多多等国内平台" : market === "international" ? "Amazon · Shopify · TikTok Shop · Shopee 等海外平台" : "按上架需求选择，主图、详情都能在这里开始。"}</p></div><span>{goal === "main" || goal === "detail" ? <><Check size={13} aria-hidden="true" /> 已按目标筛选</> : `${entries.length} 种创作方式`}</span></header>
      {hasAssets && <div className={styles.assetNotice}><ImagePlus size={18} aria-hidden="true" /><p>已带入 {search.getAll("assetId").length} 张素材，进入详情工作台后继续使用。<Link href="/create">不带素材，查看全部方式 <ArrowRight size={13} aria-hidden="true" /></Link></p></div>}
      <div className={styles.grid} data-single={entries.length === 1 || undefined}>{entries.map(entry => <Link className={styles.card} href={commerceEntryHref(entry, search)} key={entry.id} data-entry={entry.id} data-tone={entry.goal === "detail" ? "lime" : "lilac"}>
        <div className={styles.cardVisual}><div className={styles.visualCopy}><strong>{visualCopy[entry.id].title}</strong><p>{visualCopy[entry.id].caption}</p></div><img src={FEATURE_THUMBNAILS[entry.id === "crossborder-detail" ? "detail-pack" : entry.id]} alt="" width={1374} height={1145} /><span>{entry.market === "domestic" ? "国内电商" : "跨境电商"}</span><small>示例效果</small></div>
        <div className={styles.cardBody}><h3>{entry.title}</h3><p>{entry.description}</p><div className={styles.output}><PackageCheck size={17} aria-hidden="true" /><span><small>你将得到</small><strong>{entry.output}</strong></span></div><div className={styles.cardAction}>进入工作台<span><ArrowUpRight size={18} aria-hidden="true" /></span></div></div>
      </Link>)}</div>
      {!entries.length && <div className={styles.empty}><ImagePlus size={25} aria-hidden="true" /><h3>带入素材，继续制作商品详情</h3><p>当前素材支持国内或跨境详情图，切换到详情创作即可继续。</p><Link href={marketHref(market, "detail")}>选择详情创作方式 <ArrowRight size={16} aria-hidden="true" /></Link></div>}
    </section>
    <div className={styles.notes}>
      {entries.some(entry => entry.id === "amazon-visual-suite") && <p><Layers3 size={16} aria-hidden="true" /><span>亚马逊套图包含 21 张图片，主图、副图和桌面 / 移动 A+ 在结果中分组查看与下载。</span></p>}
      <p><ImagePlus size={16} aria-hidden="true" /><span>只需要单张图片？试试<Link href="/workspace/product-image/white-background">电商白底图</Link>或<Link href="/workspace/product-image/scene-main">场景主图 <ArrowUpRight size={12} aria-hidden="true" /></Link></span></p>
    </div>
    <footer className={styles.alternatives}><span>也可以从这里开始</span><div>
      <Link href="/style-replica"><span className={styles.alternativeIcon}><Sparkles size={20} aria-hidden="true" /></span><span><strong>有参考，做一键复刻</strong><small>把喜欢的风格，变成自己的套图</small></span><ArrowRight size={16} aria-hidden="true" /></Link>
      <Link href="/inspiration"><span className={styles.alternativeIcon}><Lightbulb size={20} aria-hidden="true" /></span><span><strong>还没方向？先找灵感</strong><small>看看好案例，找到创作的起点</small></span><ArrowRight size={16} aria-hidden="true" /></Link>
      <Link href="/tools"><span className={styles.alternativeIcon}><Grid2X2 size={20} aria-hidden="true" /></span><span><strong>查看全部工具</strong><small>更多商品图与精修创作能力</small></span><ArrowRight size={16} aria-hidden="true" /></Link>
    </div></footer>
  </div></AppShell>;
}
