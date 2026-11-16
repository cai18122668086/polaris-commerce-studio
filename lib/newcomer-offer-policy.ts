type ReminderState = {
  eligible: boolean;
  reminded: boolean;
  ready_at: string | null;
  server_now: string;
};

export function newcomerReminderReady(data: ReminderState | undefined, elapsedMs: number) {
  if (!data?.eligible || data.reminded || !data.ready_at) return false;
  return Date.parse(data.server_now) + Math.max(0, elapsedMs) >= Date.parse(data.ready_at);
}

export function newcomerDialogBlocks(element: Element) {
  // Task details contain the actual result and can remain open. Full-screen
  // previews, login, payments and confirmations must finish before an upsell.
  if (element.matches('[data-newcomer-result-detail="true"]') || element.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
  if (typeof window !== "undefined") {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    if (style.display === "none" || style.visibility !== "visible" || Number(style.opacity) === 0 || rect.width === 0 || rect.height === 0 || rect.right <= 0 || rect.bottom <= 0 || rect.left >= window.innerWidth || rect.top >= window.innerHeight) return false;
  }
  return true;
}


export function firstVisibleResult(assetIds: readonly string[]) {
  const ids = new Set(assetIds);
  for (const image of document.querySelectorAll<HTMLImageElement>("img[data-growth-asset]")) {
    const assetId = image.dataset.growthAsset;
    if (!assetId || !ids.has(assetId) || !image.complete || !image.naturalWidth) continue;
    const rect = image.getBoundingClientRect();
    const top = Math.max(0, rect.top);
    const left = Math.max(0, rect.left);
    const bottom = Math.min(window.innerHeight, rect.bottom);
    const right = Math.min(window.innerWidth, rect.right);
    if (bottom <= top || right <= left) continue;
    if (document.elementFromPoint((left + right) / 2, (top + bottom) / 2) === image) return assetId;
  }
}
