import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { COMMERCE_ENTRIES } from "@/lib/commerce-entrypoints";
import styles from "./commerce-entry-groups.module.css";

export function CommerceEntryGroups() {
  return <section className={styles.groups} aria-label="按电商市场选择创作">
    <article id="domestic-commerce" className={styles.group}>
      <span>淘宝 · 天猫 · 京东 · 拼多多</span><h2>国内电商</h2>
      <p>按商品上新需要，选择主图轮播或详情页。</p>
      {COMMERCE_ENTRIES.filter(entry => entry.market === "domestic").map(entry => <Link key={entry.id} href={entry.href}><strong>{entry.title}</strong><small>{entry.output}</small><ArrowUpRight size={18} /></Link>)}
    </article>
    <article id="crossborder-commerce" className={styles.group}>
      <span>Amazon · Shopify · TikTok Shop · Shopee 等</span><h2>跨境电商</h2>
      <p>亚马逊选择完整套图，其他海外渠道选择商品详情图。</p>
      {COMMERCE_ENTRIES.filter(entry => entry.market === "international").map(entry => <Link key={entry.id} href={entry.href}><strong>{entry.title}</strong><small>{entry.output}</small><ArrowUpRight size={18} /></Link>)}
    </article>
  </section>;
}
