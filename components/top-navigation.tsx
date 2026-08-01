"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { RefObject } from "react";
import {
  Bell,
  ChevronDown,
  CircleHelp,
  Menu,
  PanelRightOpen,
  Zap,
} from "lucide-react";
import { useJobs } from "@/features/jobs/api/jobs";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { getFeatureById, getFeatureByRoute } from "@/lib/feature-registry";
import { BrandMark } from "./brand-mark";

const localEditFeature = getFeatureById("local-edit");
const detailPackFeature = getFeatureById("detail-pack");

const navItems = [
  { label: "首页", href: "/" },
  {
    label: localEditFeature?.title ?? "一句话改图",
    href: localEditFeature?.route ?? "/workspace/local-edit",
  },
  { label: "功能大全", href: "/tools" },
  {
    label: detailPackFeature?.title ?? "电商套图",
    href: detailPackFeature?.route ?? "/workspace/detail-pack",
  },
  { label: "素材中心", href: "/assets" },
  { label: "生成记录", href: "/jobs" },
];

export function TopNavigation({
  onOpenTasks,
  onOpenSidebar,
  showMenu = true,
  taskOpen,
  taskTriggerRef,
}: {
  onOpenTasks: () => void;
  onOpenSidebar: () => void;
  showMenu?: boolean;
  taskOpen: boolean;
  taskTriggerRef: RefObject<HTMLButtonElement | null>;
}) {
  const pathname = usePathname();
  const currentFeature = getFeatureByRoute(pathname);
  const { workspace } = useWorkspace();
  const jobs = useJobs(workspace?.id, { limit: 20 });
  const activeCount =
    jobs.data?.items.filter((job) =>
      ["queued", "planning", "awaiting_confirmation", "processing", "cancelling"].includes(
        job.status,
      ),
    ).length ?? 0;

  return (
    <header className="top-nav">
      <div className="top-nav__inner">
        {showMenu && (
          <button
            className="icon-button mobile-menu"
            onClick={onOpenSidebar}
            aria-label="打开菜单"
          >
            <Menu size={20} />
          </button>
        )}
        <Link href="/" className="top-nav__brand">
          <BrandMark />
        </Link>
        <nav className="main-nav" aria-label="主导航">
          {navItems.map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/"
                : item.href === "/tools"
                  ? pathname === "/tools" ||
                    Boolean(
                      currentFeature &&
                        currentFeature.jobType !== "local_edit" &&
                        currentFeature.jobType !== "detail_pack",
                    )
                  : pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={active ? "active" : ""}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="top-nav__actions">
          <span className="usage-pill" aria-label="当前为零付费内部 mock 环境">
            <Zap size={15} />
            <span>内部 mock</span>
            <strong>0 付费</strong>
          </span>
          <Link href="/help" className="icon-button desktop-only" aria-label="帮助">
            <CircleHelp size={19} />
          </Link>
          <button className="icon-button desktop-only" aria-label="通知">
            <Bell size={19} />
            <i className="notification-dot" />
          </button>
          <button
            ref={taskTriggerRef}
            className="task-trigger"
            onClick={onOpenTasks}
            aria-label={`打开任务中心，${activeCount} 个进行中任务`}
            aria-controls="task-drawer"
            aria-expanded={taskOpen}
            aria-haspopup="dialog"
          >
            <PanelRightOpen size={18} />
            <span>任务</span>
            <i>{activeCount}</i>
          </button>
          <Link href="/dashboard" className="user-menu" aria-label="打开个人控制台">
            <span className="avatar">{workspace?.name.slice(0, 1) ?? "内"}</span>
            <span className="desktop-only">
              {workspace?.name ?? "内部测试"}
              <small>{workspace?.role ?? "development"}</small>
            </span>
            <ChevronDown size={14} className="desktop-only" />
          </Link>
        </div>
      </div>
    </header>
  );
}
