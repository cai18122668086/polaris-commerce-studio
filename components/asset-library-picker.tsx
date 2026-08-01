"use client";

import { Check, FileWarning, Image as ImageIcon, LoaderCircle } from "lucide-react";

import { useAssetAccessUrl, useAssets } from "@/features/assets/api/assets";
import type { Asset } from "@/lib/api/types";
import styles from "./product-image-workspace.module.css";

function LibraryAssetCard({
  asset,
  workspaceId,
  selected,
  disabled,
  onToggle,
}: {
  asset: Asset;
  workspaceId: string;
  selected: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  const access = useAssetAccessUrl(workspaceId, asset.id);
  const dimensions = asset.width && asset.height
    ? `${asset.width} × ${asset.height}`
    : "尺寸待识别";

  return (
    <button
      type="button"
      className={styles.libraryAsset}
      data-selected={selected || undefined}
      disabled={disabled}
      onClick={onToggle}
      aria-pressed={selected}
      aria-label={`${selected ? "取消选择" : "选择"} ${asset.original_filename}`}
    >
      <span className={styles.libraryAssetPreview}>
        {access.data?.url ? (
          <img src={access.data.url} alt="" />
        ) : access.isError ? (
          <FileWarning size={22} />
        ) : (
          <LoaderCircle className="spin" size={22} />
        )}
        <i>{selected ? <Check size={14} /> : null}</i>
      </span>
      <span className={styles.libraryAssetCopy}>
        <strong>{asset.original_filename}</strong>
        <small>{dimensions}</small>
      </span>
    </button>
  );
}

export function AssetLibraryPicker({
  workspaceId,
  title,
  description,
  selectedIds,
  excludedIds = [],
  onChange,
  maxItems = 8,
  disabled = false,
}: {
  workspaceId?: string;
  title: string;
  description: string;
  selectedIds: string[];
  excludedIds?: string[];
  onChange: (assetIds: string[]) => void;
  maxItems?: number;
  disabled?: boolean;
}) {
  const assetsQuery = useAssets(workspaceId, { limit: 60 });
  const assets = (assetsQuery.data?.items ?? []).filter(
    (asset) => asset.lifecycle_status === "ready" && asset.media_kind === "image",
  );

  const toggle = (assetId: string) => {
    if (selectedIds.includes(assetId)) {
      onChange(selectedIds.filter((id) => id !== assetId));
      return;
    }
    if (selectedIds.length < maxItems) onChange([...selectedIds, assetId]);
  };

  return (
    <section className={styles.assetPicker} aria-label={title}>
      <div className={styles.assetPickerHeading}>
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        <span>{selectedIds.length} / {maxItems}</span>
      </div>

      {!workspaceId || assetsQuery.isPending ? (
        <div className={styles.libraryState}>
          <LoaderCircle className="spin" size={19} /> 正在读取素材库…
        </div>
      ) : assetsQuery.isError ? (
        <div className={styles.libraryState} role="alert">
          <FileWarning size={19} /> 素材库暂时不可用，请先使用本地上传。
        </div>
      ) : assets.length ? (
        <div className={styles.libraryGrid}>
          {assets.map((asset) => (
            <LibraryAssetCard
              key={asset.id}
              asset={asset}
              workspaceId={workspaceId}
              selected={selectedIds.includes(asset.id)}
              disabled={
                disabled ||
                excludedIds.includes(asset.id) ||
                (!selectedIds.includes(asset.id) && selectedIds.length >= maxItems)
              }
              onToggle={() => toggle(asset.id)}
            />
          ))}
        </div>
      ) : (
        <div className={styles.libraryState}>
          <ImageIcon size={19} /> 素材库暂无图片，上传后会自动出现在这里。
        </div>
      )}
    </section>
  );
}
