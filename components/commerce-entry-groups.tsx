import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import styles from "./commerce-entry-groups.module.css";

export function CommerceEntryGroups() {
  return <section className={styles.groups} aria-label="按电商市场选择创作">
    <article id="domestic-commerce" className={styles.group}>
      <span>淘宝 · 天猫 · 京东 · 拼多多</span><h2>国内电商</h2>
      <p>按商品上新需要，选择主图轮播或详情页。</p>
      <Link href="/workspace/domestic-main-image"><strong>国内主图与轮播</strong><small>1 张搜索主图 + 5 张轮播图</small><ArrowUpRight size={18} /></Link>
      <Link href="/workspace/detail-pack"><strong>国内商品详情页</strong><small>卖点、场景与商品细节，连贯讲清</small><ArrowUpRight size={18} /></Link>
    </article>
    <article id="crossborder-commerce" className={styles.group}>
      <span>AMAZON</span><h2>跨境电商</h2>
      <p>亚马逊完整套图，按主副图与 A+ 分组交付。</p>
      <Link href="/workspace/amazon-visual-suite"><strong>亚马逊主图与副图</strong><small>完整套图中的 1 张主图 + 6 张副图</small><ArrowUpRight size={18} /></Link>
      <Link href="/workspace/amazon-visual-suite"><strong>亚马逊 A+ 内容</strong><small>同一套图中的桌面 7 张 + 移动 7 张 A+</small><ArrowUpRight size={18} /></Link>
    </article>
  </section>;
}
