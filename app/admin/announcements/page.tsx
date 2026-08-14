"use client";

import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { AnnouncementAdmin } from "@/features/announcements/components/announcement-admin";

export default function AdminAnnouncementsPage() {
  const [filter, setFilter] = useState<"all" | "draft" | "published" | "archived">("all");
  return (
    <AppShell sidebar={false}>
      <AnnouncementAdmin filter={filter} onFilterChange={setFilter} />
    </AppShell>
  );
}
