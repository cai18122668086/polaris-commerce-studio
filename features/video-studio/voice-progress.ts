// Processing is an estimate; only a confirmed ready result can reach 100%.
export function estimatedVoiceProgress(seconds: number) {
  const elapsed = Math.max(0, seconds);
  return Math.min(98, Math.floor(25 + 65 * (1 - Math.exp(-elapsed / 5)) + 9 * (1 - Math.exp(-Math.max(0, elapsed - 18) / 60))));
}
