/** Segment rows and change summary for the 分段工作台 (one row per spoken segment of a plan). */
export type WorkbenchBeat = {
  id: string;
  text: string;
  group_id: string;
  source_only_available: boolean;
  dependency_blocker?: string | null;
};
export type WorkbenchSelection = {
  music: "keep" | "lower" | "raise" | "off";
  musicTrackId: string;
  segments: string[];
  effects: { beat_id: string; group_id: string }[];
  highlights: { beat_id: string }[];
  images: { beat_id: string }[];
};
export type SegmentRow = {
  id: string;
  index: number;
  text: string;
  kept: boolean;
  changes: string[];
  blocker?: string;
  layoutFailed: boolean;
};

/** Source-only segments carry no motion, so the plan's own Z-M00 beats read as 原画面 too. */
export function segmentRows(beats: WorkbenchBeat[], selected: WorkbenchSelection, layoutFailures: ReadonlySet<string | null | undefined> = new Set()): SegmentRow[] {
  const effects = new Set(selected.effects.map(edit => edit.beat_id));
  const highlights = new Set(selected.highlights.map(edit => edit.beat_id));
  const images = new Set(selected.images.map(edit => edit.beat_id));
  return beats.map((beat, index) => {
    const kept = selected.segments.includes(beat.id);
    const changes = kept ? ["保留原画面"] : [
      ...(effects.has(beat.id) ? ["换动效"] : []),
      ...(highlights.has(beat.id) ? ["改强调词"] : []),
      ...(images.has(beat.id) ? ["换配图"] : []),
    ];
    const blocked = !!beat.dependency_blocker && !kept && !effects.has(beat.id);
    return {
      id: beat.id,
      index: index + 1,
      text: beat.text,
      kept: kept || beat.group_id === "Z-M00",
      changes,
      ...(blocked ? { blocker: beat.dependency_blocker! } : {}),
      layoutFailed: layoutFailures.has(beat.id),
    };
  });
}

const musicLabel: Record<WorkbenchSelection["music"], string> = { lower: "配乐 · 轻", keep: "", raise: "配乐 · 明显", off: "关闭配乐" };

/** One line describing what 「生成新版」 will apply; empty when nothing changed. */
export function changeSummary(beats: WorkbenchBeat[], selected: WorkbenchSelection): string {
  const changed = segmentRows(beats, selected).filter(row => row.changes.length).length;
  return [
    changed ? `已调整 ${changed} 段` : "",
    musicLabel[selected.music],
    selected.musicTrackId && selected.music !== "off" ? "更换配乐曲目" : "",
  ].filter(Boolean).join(" · ");
}

/** 工作台「字幕」校对的对象：用户点「调整本版」时选中的那一版任务；没有选中就不显示入口。 */
export function revisingTask<T extends { id: string; options: unknown }>(tasks: T[], selection?: { taskId: string } | null): { id: string; options: T["options"] } | undefined {
  const task = selection ? tasks.find(item => item.id === selection.taskId) : undefined;
  return task ? { id: task.id, options: task.options } : undefined;
}
