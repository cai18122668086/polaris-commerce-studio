"use client";

import { useRef, useState } from "react";
import { TopNavigation } from "./top-navigation";
import { ToolSidebar } from "./tool-sidebar";
import { TaskDrawer } from "./task-drawer";
import { AnnouncementPrompt } from "./announcement-prompt";
import { usePathname } from "next/navigation";
import { getFeatureByRoute } from "@/lib/feature-registry";
import { CreationWorkspaceBar } from "./creation-workspace-bar";
import { CreditAccountHeader, CreditUsageNotice } from "@/features/billing/components/credit-account";

export function AppShell({
  children,
  flush = false,
  sidebar = true,
}: {
  children: React.ReactNode;
  flush?: boolean;
  sidebar?: boolean;
}) {
  const [taskOpen, setTaskOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const taskTriggerRef = useRef<HTMLButtonElement>(null);
  const pathname = usePathname();
  const feature = getFeatureByRoute(pathname);
  const creationId = feature?.id ?? (pathname === "/inspiration" ? "inspiration" : undefined);
  const showSidebar = sidebar && !creationId;

  return (
    <div className={`app-shell${creationId ? " app-shell--creation" : ""}${pathname === "/" ? " app-shell--home" : ""}`} data-feature={creationId}>
      {pathname === "/account" ? <CreditAccountHeader /> : <TopNavigation
        onOpenTasks={() => setTaskOpen(true)}
        onOpenSidebar={() => setSidebarOpen(true)}
        showMenu={showSidebar}
        taskOpen={taskOpen}
        taskTriggerRef={taskTriggerRef}
      />}
      {creationId && <CreationWorkspaceBar key={creationId} featureId={creationId} />}
      {feature && <CreditUsageNotice jobType={feature.jobType} taskPreset={feature.taskPreset} />}
      <div className="app-shell__body">
        {showSidebar && (
          <ToolSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        )}
        <main
          className={[
            "main-content",
            flush ? "main-content--flush" : "",
            !showSidebar ? "main-content--wide" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {children}
        </main>
      </div>
      {pathname !== "/account" && <TaskDrawer
        open={taskOpen}
        onClose={() => setTaskOpen(false)}
        triggerRef={taskTriggerRef}
      />}
      {pathname !== "/account" && <AnnouncementPrompt />}
    </div>
  );
}

