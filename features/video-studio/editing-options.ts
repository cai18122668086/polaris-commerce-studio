export type EditingMusicPreference = "template" | "lower" | "off";

export function referenceScript(value: string | null | undefined): string | undefined {
  return value?.trim() || undefined;
}

export function matchesReferenceScript(options: { reference_script?: string | null }, current: string): boolean {
  return referenceScript(options.reference_script) === referenceScript(current);
}

export const editingMusicLabels: Record<EditingMusicPreference, string> = {
  template: "使用模板配乐",
  lower: "降低配乐音量",
  off: "不使用配乐",
};
