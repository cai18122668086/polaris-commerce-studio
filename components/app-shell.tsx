"use client";

import { useState } from "react";
import { TopNavigation } from "./top-navigation";
import { ToolSidebar } from "./tool-sidebar";
import { TaskDrawer } from "./task-drawer";
import { RuntimeCapabilityBanner } from "./runtime-capability-banner";

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

  return (
    <div className="app-shell">
      <TopNavigation
        onOpenTasks={() => setTaskOpen(true)}
        onOpenSidebar={() => setSidebarOpen(true)}
        showMenu={sidebar}
      />
      <RuntimeCapabilityBanner />
      <div className="app-shell__body">
        {sidebar && (
          <ToolSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        )}
        <main
          className={[
            "main-content",
            flush ? "main-content--flush" : "",
            !sidebar ? "main-content--wide" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {children}
        </main>
      </div>
      <TaskDrawer open={taskOpen} onClose={() => setTaskOpen(false)} />
    </div>
  );
}

