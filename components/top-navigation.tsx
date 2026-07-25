"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bell,
  ChevronDown,
  CircleHelp,
  Grid2X2,
  Menu,
  PanelRightOpen,
  Zap,
} from "lucide-react";
import { toolGroups } from "@/lib/tool-registry";
import { BrandMark } from "./brand-mark";

const navItems = [
  { label: "首页", href: "/" },
  { label: "电商套图", href: "/workspace/detail-pack" },
  { label: "素材中心", href: "/assets" },
  { label: "使用帮助", href: "/help" },
];

const creativeGroups = toolGroups.filter((group) => group.label !== "资产管理");

export function TopNavigation({
  onOpenTasks,
  onOpenSidebar,
}: {
  onOpenTasks: () => void;
  onOpenSidebar: () => void;
}) {
  const pathname = usePathname();

  return (
    <header className="top-nav">
      <div className="top-nav__inner">
        <button className="icon-button mobile-menu" onClick={onOpenSidebar} aria-label="打开菜单">
          <Menu size={20} />
        </button>
        <Link href="/" className="top-nav__brand">
          <BrandMark />
        </Link>
        <nav className="main-nav" aria-label="主导航">
          {navItems.slice(0, 1).map((item) => {
            const active =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
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
          <div className="nav-menu">
            <Link
              href="/#tools"
              className={`nav-menu__trigger ${pathname.startsWith("/workspace") ? "active" : ""}`}
            >
              AI 功能大全
              <ChevronDown size={13} />
            </Link>
            <div className="nav-mega">
              <div className="nav-mega__head">
                <span>
                  <Grid2X2 size={16} />
                  创作工具
                </span>
                <Link href="/#tools">查看全部功能</Link>
              </div>
              <div className="nav-mega__grid">
                {creativeGroups.flatMap((group) =>
                  group.items.map((item) => {
                    const Icon = item.icon;
                    return (
                      <Link key={item.href} href={item.href} className="nav-tool-link">
                        <span className={`tool-icon tone-${item.tone}`}>
                          <Icon size={18} />
                        </span>
                        <span>
                          <strong>{item.title}</strong>
                          <small>{item.description}</small>
                        </span>
                        {item.badge && <em>{item.badge}</em>}
                      </Link>
                    );
                  }),
                )}
              </div>
              <div className="nav-mega__footer">
                <Link href="/jobs">生成记录</Link>
                <Link href="/assets">个人素材库</Link>
                <span>新工具将自动加入这里</span>
              </div>
            </div>
          </div>
          {navItems.slice(1).map((item) => {
            const active = pathname.startsWith(item.href);
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
        <Link href="/#tools" className="mobile-tool-entry">
          <Grid2X2 size={16} />
          <span>全部工具</span>
        </Link>
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
