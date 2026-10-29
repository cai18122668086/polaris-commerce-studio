type ResultItem = { id: string; ordinal: number };
type ResultAsset = { direction: string; is_deliverable?: boolean; job_item_id?: string | null };

export function firstMissingReplicaOrdinal(items: readonly ResultItem[], assets: readonly ResultAsset[]): number | undefined {
  const delivered = new Set(assets.filter(asset => asset.direction === "output" && asset.is_deliverable).map(asset => asset.job_item_id));
  return items.reduce<number | undefined>((first, item) => {
    if (delivered.has(item.id)) return first;
    return first === undefined ? item.ordinal : Math.min(first, item.ordinal);
  }, undefined);
}
