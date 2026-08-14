"use client";

import { FileWarning, Image as ImageIcon, LoaderCircle } from "lucide-react";
import { useAsset, useAssetAccessUrl } from "@/features/assets/api/assets";
import { errorMessage } from "@/lib/api/request";
import type { JobDetail } from "@/lib/api/types";
import { jobAssetRoleLabel } from "@/lib/jobs/presentation";

export function JobAssetPreview({ workspaceId, relation }: { workspaceId: string; relation: JobDetail["assets"][number] }) {
  const asset = useAsset(workspaceId, relation.asset_id);
  const access = useAssetAccessUrl(workspaceId, relation.asset_id);
  const assetName = asset.data?.original_filename ?? relation.asset_id;
  const unavailable = asset.error ?? access.error;
  return (
    <article className="job-asset-card">
      <div className="job-asset-card__media">{access.isPending ? <LoaderCircle className="spin" size={20} aria-label="正在获取预览" /> : access.data?.url ? <img src={access.data.url} alt={assetName} /> : <ImageIcon size={22} />}</div>
      <div className="job-asset-card__body"><strong title={assetName}>{assetName}</strong><span>{jobAssetRoleLabel(relation.role)}</span>{asset.data && <small>{asset.data.width ?? "-"} ? {asset.data.height ?? "-"}</small>}{unavailable ? <p className="job-asset-card__error" role="alert"><FileWarning size={13} />Asset unavailable: {errorMessage(unavailable)}</p> : asset.data?.lifecycle_status && asset.data.lifecycle_status !== "ready" ? <p className="job-asset-card__error" role="status">Asset status: {asset.data.lifecycle_status}</p> : null}</div>
    </article>
  );
}
