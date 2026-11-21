export type EditingMusicPreference = "lower" | "template" | "raise" | "off";

export function referenceScript(value: string | null | undefined): string | undefined {
  return value?.trim() || undefined;
}

export function matchesReferenceScript(options: { reference_script?: string | null }, current: string): boolean {
  return referenceScript(options.reference_script) === referenceScript(current);
}

/** Background-music level tiers, in display order: 轻 / 标准 / 明显, then off. */
export const editingMusicLabels: Record<EditingMusicPreference, string> = {
  lower: "配乐 · 轻",
  template: "配乐 · 标准",
  raise: "配乐 · 明显",
  off: "不使用配乐",
};

export const editingMusicHints: Record<EditingMusicPreference, string> = {
  lower: "比模板低 6 dB，口播最突出",
  template: "按模板设计的音量，口播时自动压低",
  raise: "比模板高 3 dB，口播时仍自动压低",
  off: "只保留口播人声和画面音效",
};

export function isEditingMusicPreference(value: unknown): value is EditingMusicPreference {
  return typeof value === "string" && value in editingMusicLabels;
}
