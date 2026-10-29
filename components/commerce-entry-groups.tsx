import Link from "next/link";
import { ArrowRight, ArrowUpRight, Globe2, ShoppingBag } from "lucide-react";
import { COMMERCE_ENTRIES } from "@/lib/commerce-entrypoints";
import styles from "./commerce-entry-groups.module.css";

export function CommerceEntryGroups() {
  const markets = [
    { id: "domestic", anchor: "domestic-commerce", title: "国内电商", platforms: "淘宝 · 天猫 · 京东 · 拼多多", icon: ShoppingBag },
    { id: "international", anchor: "crossborder-commerce", title: "跨境电商", platforms: "Amazon · Shopify · TikTok Shop · Shopee 等", icon: Globe2 },
  ] as const;

  return (
    <section className={styles.section} aria-label="按电商市场选择创作">
      <header className={styles.heading}>
        <div>
          <span className="commerce-eyebrow">CREATE FOR YOUR MARKET</span>
          <h2>为你的销售平台做图。</h2>
          <p>已确定销售平台？选择对应工作台，直接上传商品。</p>
        </div>
        <Link className={styles.guide} href="/create">帮我选择套图 <ArrowRight size={16} aria-hidden="true" /></Link>
      </header>
      <div className={styles.groups}>
        {markets.map(market => (
          <article id={market.anchor} key={market.id} className={styles.group} data-market={market.id} aria-labelledby={`${market.anchor}-title`}>
            <header className={styles.marketHeading}>
              <span className={styles.marketIcon}><market.icon size={22} aria-hidden="true" /></span>
              <div><h3 id={`${market.anchor}-title`}>{market.title}</h3><p>{market.platforms}</p></div>
            </header>
            {COMMERCE_ENTRIES.filter(entry => entry.market === market.id).map(entry => (
              <Link key={entry.id} className={styles.entry} href={entry.href}>
                <span className={styles.entryCopy}><strong>{entry.title}</strong><small>{entry.id === "amazon-visual-suite" ? "21 张 · 主图 / 副图 / 桌面与移动 A+" : entry.output}</small></span>
                <span className={styles.entryArrow}><ArrowUpRight size={18} aria-hidden="true" /></span>
              </Link>
            ))}
          </article>
        ))}
      </div>
    </section>
  );
}
