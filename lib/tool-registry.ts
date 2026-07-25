import {
  Eraser,
  FolderClock,
  Images,
  LibraryBig,
  Paintbrush2,
  ScanLine,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

type ToolItem = {
  title: string;
  description: string;
  href: string;
  icon: LucideIcon;
  tone: string;
  badge?: string;
};

type ToolGroup = {
  label: string;
  items: ToolItem[];
};

export const toolGroups: ToolGroup[] = [
  {
    label: "创作工具",
    items: [
      {
        title: "局部修改",
        description: "像素级锁定修改",
        href: "/workspace/local-edit",
        icon: Paintbrush2,
        tone: "indigo",
      },
    ],
  },
  {
    label: "电商套图",
    items: [
      {
        title: "商品详情图",
        description: "多平台智能成套",
        href: "/workspace/detail-pack",
        icon: Sparkles,
        tone: "violet",
        badge: "推荐",
      },
    ],
  },
  {
    label: "资产管理",
    items: [
      {
        title: "个人控制台",
        description: "用量与最近创作",
        href: "/dashboard",
        icon: LibraryBig,
        tone: "indigo",
      },
      {
        title: "生成记录",
        description: "查看全部任务",
        href: "/jobs",
        icon: FolderClock,
        tone: "blue",
      },
      {
        title: "个人素材库",
        description: "管理创作资产",
        href: "/assets",
        icon: Images,
        tone: "cyan",
      },
    ],
  },
];

export const futureTools = [
  { label: "智能换背景", icon: LibraryBig },
  { label: "电商白底图", icon: Sparkles },
  { label: "智能抠图", icon: ScanLine },
  { label: "瑕疵消除", icon: Eraser },
];
