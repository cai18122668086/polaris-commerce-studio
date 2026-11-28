import { AdminGate } from "@/components/admin/admin-gate";
import { AppShell } from "@/components/app-shell";
import { CommerceCrawlerWorkspace } from "@/components/commerce-crawler-workspace";

export const metadata = { title: "真实商品爬虫", robots: { index: false } };

/* 内部运维工具：只对管理员开放（与 /admin 使用同一权限判断） */
export default function CommerceCrawlerPage() {
  return <AppShell><AdminGate><CommerceCrawlerWorkspace /></AdminGate></AppShell>;
}
