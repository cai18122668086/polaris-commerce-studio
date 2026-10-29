export const COMMERCE_ENTRIES = [
  { id: "domestic-main-image", market: "domestic", title: "国内主图与轮播", href: "/workspace/domestic-main-image", description: "淘宝、天猫、京东等国内商品上新", output: "1 张搜索主图 + 5 张轮播图", goal: "main", acceptsHandoff: false },
  { id: "detail-pack", market: "domestic", title: "国内商品详情图", href: "/workspace/detail-pack", description: "用连贯的详情图讲清卖点、场景与细节", output: "1–12 页商品详情图", goal: "detail", acceptsHandoff: true },
  { id: "amazon-visual-suite", market: "international", title: "亚马逊完整套图", href: "/workspace/amazon-visual-suite", description: "主图、副图和 A+ 一次规划，按组交付", output: "主图 1 + 副图 6 + 桌面 A+ 7 + 移动 A+ 7 = 21 张", goal: "both", acceptsHandoff: false },
  { id: "crossborder-detail", market: "international", title: "跨境商品详情图", href: "/workspace/crossborder-detail", description: "Shopify、TikTok Shop、Shopee、AliExpress 等海外渠道", output: "8、10 或 12 张商品详情图", goal: "detail", acceptsHandoff: true },
] as const;

export type CommerceEntry = (typeof COMMERCE_ENTRIES)[number];

export function commerceEntryHref(entry: CommerceEntry, search?: Pick<URLSearchParams, "get" | "getAll">) {
  const ids = search?.getAll("assetId") ?? [];
  if (!ids.length || !entry.acceptsHandoff) return entry.href;
  const params = new URLSearchParams();
  for (const id of ids) params.append("assetId", id);
  for (const key of ["workspaceId", "inspirationCaseId"]) {
    const value = search?.get(key);
    if (value) params.set(key, value);
  }
  return `${entry.href}?${params}`;
}
