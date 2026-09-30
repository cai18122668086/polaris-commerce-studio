"use client";

import { Download, ExternalLink, LoaderCircle } from "lucide-react";
import { useState } from "react";
import {
  getAssetAccessUrl,
  useAssetAccessUrl,
} from "@/features/assets/api/assets";
import { errorMessage } from "@/lib/api/request";
import styles from "./workflow-results.module.css";

export function JobResultImage({ workspaceId, assetId, alt, label }: {
  workspaceId?: string;
  assetId: string;
  alt: string;
  label?: string;
}) {
  const access = useAssetAccessUrl(workspaceId, assetId);
  const preview = useAssetAccessUrl(workspaceId, assetId, "thumbnail");
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string>();
  const [failedUrl, setFailedUrl] = useState<string>();
  const download = async () => {
    if (!workspaceId || isDownloading) return;
    setIsDownloading(true);
    setDownloadError(undefined);
    try {
      const attachment = await getAssetAccessUrl(
        workspaceId,
        assetId,
        "attachment",
      );
      const anchor = document.createElement("a");
      anchor.href = attachment.url;
      anchor.download = "";
      anchor.rel = "noopener";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
    } catch (error) {
      setDownloadError(errorMessage(error));
    } finally {
      setIsDownloading(false);
    }
  };
  if (access.isPending || preview.isPending) return <div className={styles.resultState}><LoaderCircle className="spin" />正在获取结果…</div>;
  if (access.error || preview.error || !access.data?.url || !preview.data?.url) return <div className={`${styles.resultState} ${styles.resultStateError}`} role="alert">{errorMessage(access.error ?? preview.error ?? new Error("结果访问地址不可用。"))}</div>;
  if (failedUrl === preview.data.url) {
    return (
      <div className={`${styles.resultState} ${styles.resultStateError}`} role="alert">
        <span>结果图片加载失败。</span>
        <button type="button" onClick={() => { setFailedUrl(undefined); void preview.refetch(); }}>重新加载</button>
      </div>
    );
  }
  return (
    <article className={styles.resultCard}>
      <a href={access.data.url} target="_blank" rel="noreferrer" aria-label={`${alt}，单张查看`}><img src={preview.data.url} alt={alt} loading="lazy" decoding="async" onError={() => setFailedUrl(preview.data?.url)} /><ExternalLink size={15} /></a>
      <div><strong>{label ?? alt}</strong><button type="button" onClick={download} disabled={isDownloading || !workspaceId} aria-label={`下载${alt}`}>{isDownloading ? <LoaderCircle size={14} className="spin" /> : <Download size={14} />}{isDownloading ? "准备中…" : "下载"}</button></div>
      {downloadError ? <p className={styles.downloadError} role="alert">{downloadError}</p> : null}
    </article>
  );
}
