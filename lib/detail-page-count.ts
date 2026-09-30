export const DETAIL_PAGE_COUNT_ERROR = "请输入 1–12 之间的整数屏数。";

export function parseDetailPageCount(input: string): number | undefined {
  if (!/^\d+$/.test(input)) return undefined;
  const count = Number(input);
  return Number.isInteger(count) && count >= 1 && count <= 12 ? count : undefined;
}
