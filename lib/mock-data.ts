export type JobStatus =
  | "draft"
  | "queued"
  | "planning"
  | "processing"
  | "partial"
  | "completed"
  | "failed"
  | "cancelled";

export type MockJob = {
  id: string;
  title: string;
  type: "局部修改" | "商品详情图";
  status: JobStatus;
  progress: number;
  createdAt: string;
  duration: string;
  count: string;
  cover: string;
  note: string;
};

export const productImages = {
  skincare:
    "https://images.unsplash.com/photo-1556228578-8c89e6adf883?auto=format&fit=crop&w=1200&q=88",
  headphones:
    "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=1200&q=88",
  handbag:
    "https://images.unsplash.com/photo-1584917865442-de89df76afd3?auto=format&fit=crop&w=1200&q=88",
  shoes:
    "https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=1200&q=88",
  perfume:
    "https://images.unsplash.com/photo-1547887538-e3a2f32cb1cc?auto=format&fit=crop&w=1200&q=88",
  watch:
    "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=1200&q=88",
};

export const mockJobs: MockJob[] = [
  {
    id: "XH-0725-1842",
    title: "LUMIÈRE 精华液 · 天猫详情套图",
    type: "商品详情图",
    status: "processing",
    progress: 72,
    createdAt: "今天 18:42",
    duration: "预计剩余 3 分钟",
    count: "6 / 8 页",
    cover: productImages.skincare,
    note: "卖点页正在生成，主视觉与成分页已完成",
  },
  {
    id: "LE-0725-1638",
    title: "降噪耳机 · 替换耳罩材质",
    type: "局部修改",
    status: "completed",
    progress: 100,
    createdAt: "今天 16:38",
    duration: "用时 1分26秒",
    count: "1 张结果",
    cover: productImages.headphones,
    note: "严格像素锁定通过，选区外变化为 0",
  },
  {
    id: "XH-0724-2105",
    title: "NOIR 通勤手袋 · 小红书种草图",
    type: "商品详情图",
    status: "partial",
    progress: 83,
    createdAt: "昨天 21:05",
    duration: "用时 8分12秒",
    count: "5 / 6 页",
    cover: productImages.handbag,
    note: "第 4 页文字排版校验失败，可单独重试",
  },
  {
    id: "LE-0724-1420",
    title: "运动鞋 · 清除鞋面反光",
    type: "局部修改",
    status: "failed",
    progress: 38,
    createdAt: "昨天 14:20",
    duration: "已停止",
    count: "0 张结果",
    cover: productImages.shoes,
    note: "选区边缘过窄，建议扩大 12–20px 后重试",
  },
  {
    id: "XH-0723-1033",
    title: "暮光香氛 · 京东首屏套图",
    type: "商品详情图",
    status: "queued",
    progress: 8,
    createdAt: "7月23日 10:33",
    duration: "队列前方 1 项",
    count: "0 / 5 页",
    cover: productImages.perfume,
    note: "素材完整，等待规划资源",
  },
];

export const mockAssets = [
  {
    id: "A-1820",
    title: "鎏金焕亮精华液 45ml",
    kind: "上传原图",
    source: "商品详情图",
    createdAt: "今天 18:20",
    size: "2400 × 2400",
    image: productImages.skincare,
    tone: "violet",
  },
  {
    id: "A-1754",
    title: "QuietForm Pro 耳机",
    kind: "严格锁定结果",
    source: "局部修改",
    createdAt: "今天 16:41",
    size: "2048 × 2048",
    image: productImages.headphones,
    tone: "orange",
  },
  {
    id: "A-1511",
    title: "NOIR Pebble 通勤手袋",
    kind: "生成结果",
    source: "商品详情图",
    createdAt: "昨天 21:13",
    size: "1500 × 2000",
    image: productImages.handbag,
    tone: "sand",
  },
  {
    id: "A-1308",
    title: "RIFT 轻量运动鞋",
    kind: "上传原图",
    source: "局部修改",
    createdAt: "昨天 14:08",
    size: "1800 × 1800",
    image: productImages.shoes,
    tone: "coral",
  },
  {
    id: "A-1204",
    title: "暮光木质香氛",
    kind: "生成结果",
    source: "商品详情图",
    createdAt: "7月23日",
    size: "1500 × 2000",
    image: productImages.perfume,
    tone: "blue",
  },
  {
    id: "A-0982",
    title: "Arc One 极简腕表",
    kind: "上传原图",
    source: "素材上传",
    createdAt: "7月21日",
    size: "2000 × 2000",
    image: productImages.watch,
    tone: "mint",
  },
];

export const detailPages = [
  { page: 1, title: "品牌主视觉", quality: "高质量", status: "completed" },
  { page: 2, title: "核心成分科技", quality: "高质量", status: "completed" },
  { page: 3, title: "肤感与质地", quality: "均衡", status: "completed" },
  { page: 4, title: "三重焕亮机制", quality: "高质量", status: "processing" },
  { page: 5, title: "实验数据佐证", quality: "均衡", status: "queued" },
  { page: 6, title: "使用步骤", quality: "均衡", status: "queued" },
];
