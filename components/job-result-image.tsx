"use client";

import { Download, ExternalLink, LoaderCircle } from "lucide-react";
import { useAssetAccessUrl } from "@/features/assets/api/assets";
import { errorMessage } from "@/lib/api/request";
import styles from "./workflow-results.module.css";

export function JobResultImage({ workspaceId, assetId, alt, label }: {
  workspaceId?: string;
  assetId: string;
  alt: string;
  label?: string;
}) {
  const access = useAssetAccessUrl(workspaceId, assetId);
  if (access.isPending) return <div className={styles.resultState}><LoaderCircle className="spin" />正在获取结果…</div>;
  if (access.error || !access.data?.url) return <div className={`${styles.resultState} ${styles.resultStateError}`} role="alert">{errorMessage(access.error ?? new Error("结果访问地址不可用。"))}</div>;
  return (
    <article className={styles.resultCard}>
      <a href={access.data.url} target="_blank" rel="noreferrer" aria-label={`${alt}，单张查看`}><img src={access.data.url} alt={alt} /><ExternalLink size={15} /></a>
      <div><strong>{label ?? alt}</strong><a href={access.data.url} download aria-label={`下载${alt}`}><Download size={14} />下载</a></div>
    </article>
  );
}
