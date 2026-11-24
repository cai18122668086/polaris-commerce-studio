"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, ShieldCheck } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { getAdminAccess } from "@/features/admin/api/admin";

/** 只对管理员显示内部工具页；权限以后台 /admin/overview/access 的判断为准（与账号面板共用同一份缓存） */
export function AdminGate({ children, title = "这个页面仅限管理员使用" }: { children: ReactNode; title?: string }) {
  const access = useQuery({
    queryKey: ["admin", "access"],
    queryFn: ({ signal }) => getAdminAccess(signal),
    staleTime: 5 * 60_000,
    retry: false,
  });
  if (access.data?.can_manage) return <>{children}</>;
  return (
    <div className="empty-state" style={{ width: "100%", minHeight: "60vh", display: "grid", placeContent: "center", justifyItems: "center", gap: 12, textAlign: "center", padding: "48px 16px" }} data-admin-gate={access.isPending ? "checking" : "denied"}>
      {access.isPending ? <Loader2 className="spin" size={24} aria-hidden="true" /> : <ShieldCheck size={30} aria-hidden="true" />}
      <h1 style={{ margin: 0, fontSize: 22, fontWeight: 500 }}>{access.isPending ? "正在确认访问权限…" : title}</h1>
      {!access.isPending && <p style={{ margin: 0, color: "var(--muted, #8f8b84)" }}>如需使用，请联系管理员开通。</p>}
      {!access.isPending && <Link className="auth-button auth-button--secondary" href="/">返回首页</Link>}
    </div>
  );
}
