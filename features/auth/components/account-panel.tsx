"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut, Mail, ShieldCheck, Sparkles, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { getSessionUserId, signOut } from "@/features/auth/api/auth";
import { authUserLabel, useCurrentAuthUser } from "@/features/auth/api/me";
import { AUTH_ROUTES } from "@/lib/auth/routes";
import { useAnnouncementAdminAccess } from "@/features/announcements/api/announcements";
import { getAdminAccess } from "@/features/admin/api/admin";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";

export function AccountPanel() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const currentUser = useCurrentAuthUser();
  const announcementAccess = useAnnouncementAdminAccess();
  const adminAccess = useQuery({
    queryKey: ["admin", "access"],
    queryFn: ({ signal }) => getAdminAccess(signal),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const inspirationAccess = useQuery({
    queryKey: ["inspiration", "admin-access"],
    queryFn: async ({ signal }) => {
      const result = await apiClient.GET("/api/v1/admin/inspiration/cases/access", { signal });
      return unwrapApiResponse(result);
    },
    staleTime: 5 * 60_000,
    retry: false,
  });
  const [sessionUserId, setSessionUserId] = useState<string>();
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState<string>();

  async function handleSignOut() {
    setSigningOut(true);
    setError(undefined);
    try {
      await signOut();
      queryClient.clear();
      router.replace(AUTH_ROUTES.login);
      router.refresh();
    } catch {
      setError("退出登录失败，请稍后重试。");
      setSigningOut(false);
    }
  }

  async function revealSessionUserId() {
    try {
      setSessionUserId(await getSessionUserId());
    } catch {
      setError("暂时无法读取会话信息。");
    }
  }

  if (currentUser.isPending) {
    return <div className="auth-inline-status">正在载入账户信息…</div>;
  }

  if (currentUser.isError) {
    return (
      <div className="auth-inline-status" role="alert">
        <p>账户信息载入失败。</p>
        <button
          className="auth-button auth-button--secondary"
          onClick={() => void currentUser.refetch()}
          type="button"
        >
          重新载入
        </button>
      </div>
    );
  }

  const user = currentUser.data;

  return (
    <section className="account-card" aria-labelledby="account-heading">
      <div className="account-card__heading">
        <span className="account-card__avatar" aria-hidden="true">
          <UserRound size={24} />
        </span>
        <div>
          <p>账户与安全</p>
          <h1 id="account-heading">{authUserLabel(user)}</h1>
        </div>
      </div>

      <dl className="account-details">
        <div>
          <dt><Mail size={16} /> 邮箱</dt>
          <dd>{user.email || "尚未提供"}</dd>
        </div>
        <div>
          <dt><ShieldCheck size={16} /> 邮箱验证</dt>
          <dd>{user.email_verified === false ? "待验证" : "已验证"}</dd>
        </div>
        <div>
          <dt>账户 ID</dt>
          <dd>{user.id}</dd>
        </div>
        <div>
          <dt>会话用户 ID</dt>
          <dd>
            {sessionUserId || (
              <button
                className="account-inline-button"
                onClick={() => void revealSessionUserId()}
                type="button"
              >
                点击查看
              </button>
            )}
          </dd>
        </div>
      </dl>

      {error ? <p className="auth-form__error" role="alert">{error}</p> : null}

      <div className="account-card__actions">
        {adminAccess.data?.can_manage ? (
          <Link className="auth-button auth-button--secondary" href="/admin">
            管理员工作台
          </Link>
        ) : null}
        {announcementAccess.data?.can_manage ? (
          <Link className="auth-button auth-button--secondary" href="/admin/announcements">
            公告管理工作台
          </Link>
        ) : null}
        {inspirationAccess.data?.can_manage ? (
          <Link className="auth-button auth-button--secondary" href="/admin/inspiration">
            <Sparkles size={17} />
            灵感案例管理工作台
          </Link>
        ) : null}
        <button
          className="auth-button auth-button--secondary"
          disabled={signingOut}
          onClick={() => void handleSignOut()}
          type="button"
        >
          <LogOut size={17} />
          {signingOut ? "正在退出…" : "退出登录"}
        </button>
      </div>
    </section>
  );
}
