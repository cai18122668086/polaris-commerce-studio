"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bell,
  ChevronDown,
  CircleHelp,
  Menu,
  PanelRightOpen,
  Zap,
} from "lucide-react";
import { BrandMark } from "./brand-mark";

const navItems = [
  { label: "首页", href: "/" },
  { label: "一句话改图", href: "/workspace/local-edit" },
  { label: "功能大全", href: "/#tools" },
  { label: "电商套图", href: "/workspace/detail-pack" },
  { label: "素材中心", href: "/assets" },
  { label: "生成记录", href: "/jobs" },
];

export function TopNavigation({
  onOpenTasks,
  onOpenSidebar,
  showMenu = true,
}: {
  onOpenTasks: () => void;
  onOpenSidebar: () => void;
  showMenu?: boolean;
}) {
  const pathname = usePathname();

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
                : item.href === "/#tools"
                  ? false
                  : pathname.startsWith(item.href);
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
          <button className="usage-pill" aria-label="剩余创作次数">
            <Zap size={15} />
            <span>创作额度</span>
            <strong>268</strong>
          </button>
          <Link href="/help" className="icon-button desktop-only" aria-label="帮助">
            <CircleHelp size={19} />
          </Link>
          <button className="icon-button desktop-only" aria-label="通知">
            <Bell size={19} />
            <i className="notification-dot" />
          </button>
          <button className="task-trigger" onClick={onOpenTasks}>
            <PanelRightOpen size={18} />
            <span>任务</span>
            <i>2</i>
          </button>
          <Link href="/dashboard" className="user-menu" aria-label="打开个人控制台">
            <span className="avatar">林</span>
            <span className="desktop-only">
              林小满
              <small>品牌设计师</small>
            </span>
            <ChevronDown size={14} className="desktop-only" />
          </Link>
        </div>
      </div>
    </header>
  );
}
