"use client";

import { PrimaryNavigationLink } from "./primary-navigation-link";
import styles from "./top-navigation.module.css";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import {
  ChevronDown,
  CircleHelp,
  Menu,
  PanelRightOpen,
  UserRound,
  Zap,
} from "lucide-react";
import { useJobs } from "@/features/jobs/api/jobs";
import { authUserLabel, useCurrentAuthUser } from "@/features/auth/api/me";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { getFeatureByRoute } from "@/lib/feature-registry";
import {
  AI_FEATURES_MENU,
  AI_NAVIGATION_MENUS,
  AI_TOOLBOX_MENU,
  MOBILE_PRIMARY_NAVIGATION_LINKS,
  PRIMARY_NAVIGATION_LINKS,
  type NavigationMenuDefinition,
} from "@/lib/navigation-registry";
import { BrandMark } from "./brand-mark";
import { AnnouncementBanner } from "./announcement-banner";
import {
  MobileNavigationMenu,
  NavigationMegaMenu,
} from "./navigation-mega-menu";

type OpenMenu = NavigationMenuDefinition["key"] | "mobile" | null;

function menuContainsFeature(menu: NavigationMenuDefinition, featureId: string | undefined) {
  return menu.groups.some((group) =>
    group.items.some((item) => item.featureId === featureId),
  );
}

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
  const currentUser = useCurrentAuthUser();
  const accountLabel = authUserLabel(currentUser.data);
  const jobs = useJobs(workspace?.id, { limit: 20 });
  const [openMenu, setOpenMenu] = useState<OpenMenu>(null);
  const desktopNavigationRef = useRef<HTMLElement>(null);
  const mobileTriggerRef = useRef<HTMLButtonElement>(null);
  const mobilePanelRef = useRef<HTMLDivElement>(null);
  const activeTaskStatuses = [
    "queued",
    "planning",
    "awaiting_confirmation",
    "processing",
    "cancelling",
  ];
  const activeCount =
    jobs.data?.items.filter((job) => activeTaskStatuses.includes(job.status)).length ?? 0;
  const errorCount =
    jobs.data?.items.filter((job) => ["failed", "partial"].includes(job.status)).length ?? 0;
  const taskStateClass = activeCount ? "is-active" : errorCount ? styles.taskNotice : "";
  const taskLabel = activeCount ? "进行中" : "任务中心";
  const taskAriaLabel = activeCount
    ? `打开任务中心，${activeCount} 个进行中任务`
    : errorCount ? `打开任务中心，${errorCount} 项任务可查看详情` : "打开任务中心";

  useEffect(() => {
    if (!openMenu) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpenMenu(null);
      }
    };
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        !desktopNavigationRef.current?.contains(target) &&
        !mobileTriggerRef.current?.contains(target) &&
        !mobilePanelRef.current?.contains(target)
      ) {
        setOpenMenu(null);
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [openMenu]);

  const renderMegaMenu = (menu: NavigationMenuDefinition) => (
    <NavigationMegaMenu
      key={menu.key}
      definition={menu}
      activeFeatureId={currentFeature?.id}
      active={
        pathname === menu.href ||
        (menu.href === "/tools" && pathname.startsWith("/tools/")) ||
        (menuContainsFeature(menu, currentFeature?.id) &&
          !PRIMARY_NAVIGATION_LINKS.some(item => item.href === pathname))
      }
      open={openMenu === menu.key}
      onClose={() => setOpenMenu(null)}
      onToggle={() => setOpenMenu((current) => (current === menu.key ? null : menu.key))}
    />
  );

  return (
    <header className={`top-nav ${styles.header}`}>
      <div className="top-nav__inner">
        {showMenu && (
          <button
            className="icon-button mobile-menu"
            onClick={onOpenSidebar}
            aria-label="打开功能侧栏"
          >
            <Menu size={20} />
          </button>
        )}
        <Link href="/" className="top-nav__brand" aria-label="返回首页">
          <BrandMark />
        </Link>
        <nav ref={desktopNavigationRef} className="main-nav" aria-label="主导航">
          {PRIMARY_NAVIGATION_LINKS.slice(0, 2).map((item) => (
            <PrimaryNavigationLink key={item.href} href={item.href} label={item.label}
              active={pathname === item.href || pathname.startsWith(`${item.href}/`)} />
          ))}
          {renderMegaMenu(AI_FEATURES_MENU)}
          {renderMegaMenu(AI_TOOLBOX_MENU)}
          {PRIMARY_NAVIGATION_LINKS.slice(2).map((item) => (
            <PrimaryNavigationLink key={item.href} href={item.href} label={item.label}
              active={pathname === item.href || pathname.startsWith(`${item.href}/`)} />
          ))}
        </nav>
        <button
          ref={mobileTriggerRef}
          type="button"
          className="mobile-tool-entry"
          onClick={() => setOpenMenu((current) => (current === "mobile" ? null : "mobile"))}
          aria-label="打开主导航"
          aria-controls="mobile-primary-navigation"
          aria-expanded={openMenu === "mobile"}
        >
          <Menu size={15} />
          <span>导航</span>
          <ChevronDown
            className="mobile-tool-entry__chevron"
            size={13}
            style={{ transform: openMenu === "mobile" ? "rotate(180deg)" : undefined }}
          />
        </button>
        <MobileNavigationMenu
          open={openMenu === "mobile"}
          menus={AI_NAVIGATION_MENUS}
          onClose={() => setOpenMenu(null)}
          panelRef={mobilePanelRef}
          primaryLinks={MOBILE_PRIMARY_NAVIGATION_LINKS}
          pathname={pathname}
        />
        <div className="top-nav__actions">
          <AnnouncementBanner />
          <Link href="/dashboard" className="usage-pill" aria-label="套餐与用量">
            <Zap size={15} />
            <span>套餐与用量</span>
          </Link>
          <Link href="/help" className="usage-pill desktop-only" aria-label="帮助">
            <CircleHelp size={16} />
            <span>帮助</span>
          </Link>
          <button
            ref={taskTriggerRef}
            className={`task-trigger ${taskStateClass}`}
            onClick={onOpenTasks}
            aria-label={taskAriaLabel}
            aria-controls="task-drawer"
            aria-expanded={taskOpen}
            aria-haspopup="dialog"
          >
            <PanelRightOpen size={18} />
            <span>{taskLabel}</span>
            {activeCount || errorCount ? <i>{activeCount || errorCount}</i> : null}
          </button>
          <Link
            href="/account"
            className="user-menu"
            aria-label={`个人中心：${accountLabel}`}
            title={accountLabel}
          >
            <span className="avatar" aria-hidden="true">
              <UserRound size={17} />
            </span>
            <span className="desktop-only">{accountLabel}</span>
          </Link>
        </div>
      </div>
    </header>
  );
}
