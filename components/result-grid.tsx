"use client";

import { Image as ImageIcon } from "lucide-react";

import { JobResultImage } from "@/components/job-result-image";
import styles from "./product-image-workspace.module.css";

export type DeliverableResult = {
  asset_id: string;
  ordinal: number;
  role: string;
};

export function ResultGrid({
  workspaceId,
  assets,
  expectedCount,
  title = "生成结果",
}: {
  workspaceId?: string;
  assets: DeliverableResult[];
  expectedCount?: number;
  title?: string;
}) {
  if (!assets.length) {
    return (
      <div className={styles.resultEmpty}>
        <span><ImageIcon size={24} /></span>
        <strong>可交付图片将在这里显示</strong>
        <p>任务成功后，只展示标记为 deliverable 的独立 output Asset。</p>
      </div>
    );
  }

  return (
    <section className={styles.resultSection} aria-label={title}>
      <div className={styles.sectionHeading}>
        <div>
          <span>04</span>
          <div><h2>{title}</h2><p>每张结果都可独立查看和下载。</p></div>
        </div>
        <strong>{assets.length} / {expectedCount ?? assets.length}</strong>
      </div>
      <div className={styles.resultGrid}>
        {assets.map((asset, index) => (
          <JobResultImage
            key={`${asset.asset_id}-${asset.ordinal}`}
            workspaceId={workspaceId}
            assetId={asset.asset_id}
            alt={`${title} ${index + 1}`}
            label={`IMAGE-${String(asset.ordinal + 1).padStart(3, "0")}`}
          />
        ))}
      </div>
    </section>
  );
}
