// Browsing labels describe visible compositions; native template identities stay in the catalog.
const appearances: Record<string, [string, string, string]> = {
  "apple-minimal-v1": ["清单讲解", "蓝白留白", "双层标题 · 人物让位"],
  "product-explainer-v1": ["图文演示", "产品讲解", "横竖分屏 · 手机图卡"],
  "knowledge-talk-v1": ["人物口播", "重点口播", "分层论点 · 橙色强调"],
  "presenter-openings-v1": ["人物口播", "人物亮相", "全屏开场 · 大字标题"],
  "rotation-cards-v1": ["图文演示", "轮换图卡", "纵深叠放 · 逐张呈现"],
  "azl-panels-v1": ["图文演示", "杂志多格", "图文分区 · 素材换位"],
  "unified-chapter-v1": ["清单讲解", "章节导航", "章节大字 · 模糊背景"],
  "unified-paper-typewriter-v1": ["清单讲解", "纸感打字", "独立人物 · 逐字呈现"],
  "chenxi-broll-v1": ["人物口播", "场景切换", "人物近景 · 上下分屏"],
  "bihuo-02-v1": ["清单讲解", "白底胶囊", "清单逐项 · 圆形人物"],
  "bihuo-03-v1": ["清单讲解", "应用窗口", "三步节点 · 讲义排版"],
  "bihuo-04-v1": ["清单讲解", "应用窗口", "清单卡片 · 阅读进度"],
  "bihuo-08-v1": ["人物口播", "透视网格", "立体空间 · 醒目标题"],
  "bihuo-09-v1": ["清单讲解", "古卷纸纹", "米黄底色 · 重点便签"],
  "bihuo-10-v1": ["图文演示", "生活手记", "手写标题 · 纸质卡片"],
  "bihuo-11-v1": ["图文演示", "暖色旧笺", "柔焦背景 · 圆窗人物"],
  "bihuo-13-v1": ["图文演示", "青瓷底色", "上下分区 · 双画面"],
  "bihuo-14-v1": ["资讯解读", "青绿光窗", "网格底纹 · 荧光描边"],
  "bihuo-15-v1": ["资讯解读", "蓝白光晕", "柔和底色 · 悬浮图卡"],
  "bihuo-16-v1": ["图文演示", "蓝色透视", "双图卡片 · 人物小窗"],
  "bihuo-19-v1": ["图文演示", "暖色留白", "大幅配图 · 悬浮圆窗"],
  "bihuo-23-v1": ["资讯解读", "快讯直播", "资讯横栏 · 橙色光框"],
  "bihuo-24-v1": ["人物口播", "青白双语", "深青底色 · 双行字幕"],
  "bihuo-26-v1": ["人物口播", "靛蓝圆窗", "圆形构图 · 黄色重点"],
  "bihuo-27-v1": ["人物口播", "莓夜蓝调", "深紫底色 · 细线画框"],
  "bihuo-28-v1": ["资讯解读", "紫夜图卡", "倾斜资料 · 荧光标记"],
  "bihuo-29-v1": ["资讯解读", "紫夜光窗", "白色信息卡 · 蓝色光框"],
  "bihuo-32-v1": ["图文演示", "商务铜影", "暖色柔焦 · 纵向图文"],
  "bihuo-33-v1": ["资讯解读", "活力光框", "深色网格 · 亮色强调"],
  "bihuo-34-v1": ["人物口播", "黑底黄字", "极简分割线 · 大字重点"],
  "bihuo-36-v1": ["人物口播", "银灰画框", "浅灰留白 · 圆角人物"],
  "bihuo-40-v1": ["人物口播", "简洁白卡", "倾斜画框 · 黑黄对比"],
  "bihuo-47-v1": ["图文演示", "臻境商务", "网格空间 · 叠层图文"],
  "bihuo-48-v1": ["图文演示", "素材展示", "大幅配图 · 圆形人物"],
};

export function templateAppearance(card: { id: string; category: string; visual_features: string[] }) {
  const [collection, signature, detail] = appearances[card.id] ?? [card.category, card.visual_features[0] || card.category, card.visual_features.slice(1, 3).join(" · ")];
  return { collection, signature, detail };
}
