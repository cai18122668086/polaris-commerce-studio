"use client";

import { useState } from "react";
import { TopNavigation } from "./top-navigation";
import { ToolSidebar } from "./tool-sidebar";
import { TaskDrawer } from "./task-drawer";

export function AppShell({
  children,
  flush = false,
}: {
  children: React.ReactNode;
  flush?: boolean;
}) {
  const [taskOpen, setTaskOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="app-shell">
      <TopNavigation
        onOpenTasks={() => setTaskOpen(true)}
        onOpenSidebar={() => setSidebarOpen(true)}
      />
      <div className="app-shell__body">
        <ToolSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        <main className={`main-content ${flush ? "main-content--flush" : ""}`}>
          {children}
        </main>
      </div>
      <TaskDrawer open={taskOpen} onClose={() => setTaskOpen(false)} />
    </div>
  );
}

