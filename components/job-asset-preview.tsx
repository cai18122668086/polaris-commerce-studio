"use client";

import { FileWarning, Image as ImageIcon, LoaderCircle } from "lucide-react";
import { useAsset, useAssetAccessUrl } from "@/features/assets/api/assets";
import { errorMessage } from "@/lib/api/request";
import type { JobDetail } from "@/lib/api/types";
import { jobAssetRoleLabel } from "@/lib/jobs/presentation";

export function JobAssetPreview({ workspaceId, relation }: { workspaceId: string; relation: JobDetail["assets"][number] }) {
  const asset = useAsset(workspaceId, relation.asset_id);
  const access = useAssetAccessUrl(workspaceId, relation.asset_id);
  const preview = useAssetAccessUrl(workspaceId, relation.asset_id, "thumbnail");
  const assetName = asset.data?.original_filename ?? relation.asset_id;
  const unavailable = asset.error ?? access.error ?? preview.error;
  const cardBody = (
    <>
      <div className="job-asset-card__media">
        {preview.isPending ? <LoaderCircle className="spin" size={20} aria-label="正在获取预览" /> : preview.data?.url ? <img src={preview.data.url} alt={assetName} loading="lazy" decoding="async" /> : <ImageIcon size={22} />}
      </div>
      <div className="job-asset-card__body">
        <strong title={assetName}>{assetName}</strong>
        <span>{jobAssetRoleLabel(relation.role)}</span>
        {asset.data && <small>{asset.data.width ?? "-"} × {asset.data.height ?? "-"}</small>}
        {unavailable ? <p className="job-asset-card__error" role="alert"><FileWarning size={13} />素材暂不可用：{errorMessage(unavailable)}</p> : asset.data?.lifecycle_status && asset.data.lifecycle_status !== "ready" ? <p className="job-asset-card__error" role="status">素材状态：{asset.data.lifecycle_status}</p> : null}
      </div>
    </>
  );
  if (access.data?.url) {
    return <a className="job-asset-card" href={access.data.url} target="_blank" rel="noreferrer" aria-label={`查看原图 ${assetName}`} title="点击查看原图">{cardBody}</a>;
  }
  return <article className="job-asset-card">{cardBody}</article>;
}
