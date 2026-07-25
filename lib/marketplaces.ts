export type MarketRegion = "domestic" | "international";

export type Marketplace = {
  id: string;
  name: string;
  shortName: string;
  region: MarketRegion;
  format: string;
  mainImage: string;
  detailImage: string;
  note: string;
};

export const marketplaceGroups: Record<MarketRegion, Marketplace[]> = {
  domestic: [
    {
      id: "tmall",
      name: "天猫",
      shortName: "天",
      region: "domestic",
      format: "详情页 750px 宽",
      mainImage: "800 × 800（1:1）",
      detailImage: "750px 宽 · 建议分段输出",
      note: "适合品牌旗舰店与完整卖点叙事",
    },
    {
      id: "jd",
      name: "京东",
      shortName: "京",
      region: "domestic",
      format: "详情页 750px 宽",
      mainImage: "800 × 800（1:1）",
      detailImage: "750px 宽 · 建议分段输出",
      note: "突出参数、性能与购买决策信息",
    },
    {
      id: "taobao",
      name: "淘宝",
      shortName: "淘",
      region: "domestic",
      format: "详情页 750px 宽",
      mainImage: "800 × 800（1:1）",
      detailImage: "750px 宽 · 单段 800–1500px",
      note: "适合灵活的商品卖点和场景表达",
    },
    {
      id: "pdd",
      name: "拼多多",
      shortName: "拼",
      region: "domestic",
      format: "详情页 750px 宽",
      mainImage: "750 × 750（1:1）",
      detailImage: "750px 宽 · 转化优先",
      note: "强调价格利益点与核心功能",
    },
    {
      id: "douyin",
      name: "抖音电商",
      shortName: "抖",
      region: "domestic",
      format: "移动端竖版优先",
      mainImage: "800 × 800 / 750 × 1000",
      detailImage: "750px 宽 · 3:4 卖点图",
      note: "适合短节奏、强视觉的卖点呈现",
    },
    {
      id: "xiaohongshu",
      name: "小红书",
      shortName: "红",
      region: "domestic",
      format: "3:4 种草内容",
      mainImage: "1242 × 1660（3:4）",
      detailImage: "1080 × 1440 · 分页内容",
      note: "强调生活方式、体验与口碑表达",
    },
  ],
  international: [
    {
      id: "amazon",
      name: "Amazon",
      shortName: "A",
      region: "international",
      format: "Listing + A+",
      mainImage: "2000 × 2000（1:1）",
      detailImage: "A+ 模块 970px 宽",
      note: "主图、卖点图与 A+ 模块化内容",
    },
    {
      id: "shopify",
      name: "Shopify",
      shortName: "S",
      region: "international",
      format: "品牌独立站自适应",
      mainImage: "2048 × 2048（建议）",
      detailImage: "1440px 内容宽 · 响应式",
      note: "适合品牌化、模块化的商品详情页",
    },
    {
      id: "ebay",
      name: "eBay",
      shortName: "e",
      region: "international",
      format: "Listing 商品图",
      mainImage: "1600 × 1600（建议）",
      detailImage: "1200px 内容宽 · 模块化",
      note: "突出商品状态、规格与交付信息",
    },
    {
      id: "shopee",
      name: "Shopee",
      shortName: "S",
      region: "international",
      format: "移动端 1:1 优先",
      mainImage: "1024 × 1024（1:1）",
      detailImage: "750px 宽 · 分页卖点图",
      note: "适合东南亚市场的紧凑卖点表达",
    },
    {
      id: "lazada",
      name: "Lazada",
      shortName: "L",
      region: "international",
      format: "1:1 商品图优先",
      mainImage: "1000 × 1000（1:1）",
      detailImage: "750px 宽 · 详情模块",
      note: "兼顾商品参数与促销信息呈现",
    },
    {
      id: "tiktok-shop",
      name: "TikTok Shop",
      shortName: "T",
      region: "international",
      format: "社交电商竖版优先",
      mainImage: "1080 × 1080（1:1）",
      detailImage: "1080 × 1440（3:4）",
      note: "强调移动端可读性与内容节奏",
    },
    {
      id: "temu",
      name: "TEMU",
      shortName: "T",
      region: "international",
      format: "1:1 转化优先",
      mainImage: "800 × 800（1:1）",
      detailImage: "750 × 1000（3:4）",
      note: "聚焦功能、价格价值与商品细节",
    },
  ],
};
