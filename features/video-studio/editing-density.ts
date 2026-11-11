export const minDistinctMotionGroups = 5;
export const preferredDistinctMotionGroups = 10;

type Beat = { id: string; group_id: string; source_only_available?: boolean };

export function repeatedEffectsForReduction(active: readonly Beat[], edited: ReadonlySet<string>) {
  const seen = new Set<string>();
  return active.flatMap(beat => {
    if (beat.group_id === "Z-M00") return [];
    const repeated = seen.has(beat.group_id);
    seen.add(beat.group_id);
    return repeated && beat.source_only_available && !edited.has(beat.id) ? [beat.id] : [];
  });
}
