"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { COMMERCE_ENTRIES, commerceEntryHref } from "@/lib/commerce-entrypoints";
import styles from "./create.module.css";

export default function CreatePage() {
  const search = useSearchParams();
  const marketValue = search.get("market");
  const market = marketValue === "domestic" || marketValue === "international" ? marketValue : undefined;
  const goal = search.get("goal");
  const hasAssets = search.getAll("assetId").length > 0;
  function marketHref(value: string) {
    const params = new URLSearchParams();
    if (goal === "main" || goal === "detail") params.set("goal", goal);
    params.set("market", value);
    for (const key of ["workspaceId", "assetId", "inspirationCaseId"]) {
      for (const value of search.getAll(key)) params.append(key, value);
    }
    return `/create?${params}`;
  }
  const entries = COMMERCE_ENTRIES.filter(entry => (!market || entry.market === market) && (!hasAssets || entry.acceptsHandoff));
  return <AppShell sidebar={false}><div className={styles.page}>
    <header><p>电商图片创作</p><h1>你的商品，准备在哪个市场上架？</h1><p>先选市场，再选图片用途。进入工作台后上传商品、填写真实卖点。</p></header>
    <nav className={styles.markets} aria-label="选择电商市场">
      <Link href={marketHref("domestic")} aria-current={market === "domestic" ? "page" : undefined}>国内电商<small>淘宝 · 天猫 · 京东 · 拼多多等</small></Link>
      <Link href={marketHref("international")} aria-current={market === "international" ? "page" : undefined}>跨境电商<small>Amazon · Shopify · TikTok Shop 等</small></Link>
    </nav>
    <h2>{goal === "main" ? "选择主图创作方式" : goal === "detail" ? "选择详情创作方式" : "选择你要制作的图片"}</h2>
    {hasAssets && <p className={styles.notice}>已带入 {search.getAll("assetId").length} 张素材。选择国内或跨境详情，素材会继续保留。<Link href="/create">不带素材，查看全部创作方式</Link></p>}
    <div className={styles.grid}>{entries.map(entry => <Link className={styles.card} href={commerceEntryHref(entry, search)} key={entry.id} data-recommended={goal === entry.goal || entry.goal === "both" || undefined}>
      <span>{entry.market === "domestic" ? "国内电商" : "跨境电商"}{goal && (goal === entry.goal || entry.goal === "both") ? " · 符合当前目标" : ""}</span><h3>{entry.title}</h3><p>{entry.description}</p><strong>{entry.output}</strong><b>进入工作台 <ArrowRight size={17} /></b>
    </Link>)}</div>
    <p className={styles.notice}>亚马逊完整套图统一生成 21 张。主副图和 A+ 在结果中分组查看与下载。需要单张素材，可使用<Link href="/workspace/product-image/white-background">白底图</Link>或<Link href="/workspace/product-image/scene-main">场景主图</Link>。</p>
    <footer><Link href="/style-replica">有参考，做一键复刻</Link><Link href="/inspiration">还没方向，去灵感专区</Link><Link href="/tools">查看全部工具</Link></footer>
  </div></AppShell>;
}
