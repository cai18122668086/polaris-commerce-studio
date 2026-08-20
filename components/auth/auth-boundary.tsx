"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { isEmailVerified, sessionExists, signOut } from "@/features/auth/api/auth";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { initializeAuthClient } from "@/lib/auth/client";
import { getAuthMode } from "@/lib/auth/config";
import { currentReturnTo, loginHref, verifyEmailHref } from "@/lib/auth/return-to";
import { AUTH_ROUTES, isPublicRoute, routeRequiresWorkspace } from "@/lib/auth/routes";
import { onAuthUnauthorised } from "@/lib/auth/session-events";
import { AuthStatus } from "./auth-status";

type BoundaryResult = { pathname: string; state: "authenticated" | "error" };

export function AuthBoundary({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [result, setResult] = useState<BoundaryResult>();
  const [retryKey, setRetryKey] = useState(0);
  // This opt-in is only supplied by an ignored local .env.local file so the help UI can be reviewed without an external auth service.
  // Production and normal local runs retain the existing route protection because this is false unless explicitly configured.
  const localHelpPreview = process.env.NEXT_PUBLIC_LOCAL_HELP_PREVIEW === "true" && pathname === "/help";
  const publicRoute = isPublicRoute(pathname) || localHelpPreview;
  const developmentAuth = getAuthMode() === "development";

  const redirectToLogin = useCallback(() => {
    queryClient.clear();
    setResult(undefined);
    router.replace(loginHref(currentReturnTo()));
  }, [queryClient, router]);

  useEffect(() => {
    if (!developmentAuth) initializeAuthClient();
  }, [developmentAuth]);
  useEffect(() => {
    if (publicRoute || developmentAuth) return;
    return onAuthUnauthorised(redirectToLogin);
  }, [developmentAuth, publicRoute, redirectToLogin]);
  useEffect(() => {
    if (publicRoute || developmentAuth) return;
    let cancelled = false;
    async function checkAuthentication() {
      try {
        if (!(await sessionExists())) { if (!cancelled) redirectToLogin(); return; }
        if (!(await isEmailVerified())) {
          if (!cancelled) { queryClient.clear(); router.replace(verifyEmailHref(currentReturnTo())); }
          return;
        }
        if (!cancelled) setResult({ pathname, state: "authenticated" });
      } catch {
        if (!cancelled) setResult({ pathname, state: "error" });
      }
    }
    void checkAuthentication();
    return () => { cancelled = true; };
  }, [developmentAuth, pathname, publicRoute, queryClient, redirectToLogin, retryKey, router]);

  if (publicRoute) return <>{children}</>;
  if (developmentAuth) return routeRequiresWorkspace(pathname) ? <WorkspaceGate>{children}</WorkspaceGate> : <>{children}</>;
  if (!result) return <AuthStatus busy title="正在确认登录状态" description="请稍候，我们正在安全地恢复你的会话。" />;
  if (result.state === "error") return <AuthStatus title="暂时无法确认登录状态" description="认证服务暂时不可用，请检查网络后重试。">
    <button className="auth-button auth-button--primary" onClick={() => setRetryKey((key) => key + 1)}>重新检查</button>
    <Link className="auth-button auth-button--secondary" href={AUTH_ROUTES.login}>返回登录</Link>
  </AuthStatus>;
  return routeRequiresWorkspace(pathname) ? <WorkspaceGate>{children}</WorkspaceGate> : <>{children}</>;
}

function WorkspaceGate({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const workspaceQuery = useWorkspace();
  if (workspaceQuery.isPending) return <AuthStatus busy title="正在载入工作区" description="登录已完成，正在准备你的创作后台。" />;
  if (workspaceQuery.isError) return <AuthStatus title="工作区载入失败" description="暂时无法读取工作区，请稍后重试。登录状态不会受到影响。">
    <button className="auth-button auth-button--primary" onClick={() => void workspaceQuery.refetch()}>重新载入</button>
    <Link className="auth-button auth-button--secondary" href={AUTH_ROUTES.account}>前往账户</Link>
  </AuthStatus>;
  if (workspaceQuery.isEmpty) return <AuthStatus title="账号已就绪，等待分配工作区" description="工作区是登录后承载素材、任务和团队权限的创作后台。当前账号尚未加入工作区，请联系管理员完成分配。">
    <Link className="auth-button auth-button--primary" href={AUTH_ROUTES.account}>查看账户</Link>
    <button className="auth-button auth-button--secondary" onClick={async () => { await signOut(); queryClient.clear(); router.replace(AUTH_ROUTES.login); }}>退出登录</button>
  </AuthStatus>;
  return <>{children}</>;
}
