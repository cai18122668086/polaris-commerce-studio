"use client";

import { useEffect, useState } from "react";
import { Loader2, LogIn, Pause, Play, Plus, RefreshCw, ShieldCheck, Square } from "lucide-react";

import { AdminShell } from "@/components/admin/admin-shell";
import { getAdminAccess, getAdminAccounts, getAdminWorkspaces, type AdminOperationalAccount, type AdminWorkspace } from "@/features/admin/api/admin";
import { apiClient } from "@/lib/api/client";
import { errorDiagnostic, unwrapApiResponse, type ApiResult } from "@/lib/api/request";
import styles from "./page.module.css";

type Platform = "taobao" | "1688" | "jd" | "pinduoduo";
type LoginSessionInfo = { status?: string } | null;
type LoginStatusResponse = { state?: string; message?: string; loginSession?: LoginSessionInfo };
type LoginApiEnvelope = { data?: LoginStatusResponse } & LoginStatusResponse;

const platforms: Array<{ value: Platform; label: string }> = [
  { value: "taobao", label: "淘宝 / 天猫" },
  { value: "1688", label: "1688" },
  { value: "jd", label: "京东" },
  { value: "pinduoduo", label: "拼多多" },
];

const accountStatusLabels: Record<string, string> = { active: "可用", paused: "已暂停", disabled: "已停用" };
const loginStateLabels: Record<string, string> = { unknown: "未确认", ready: "已登录", needs_login: "需要登录" };

function platformLabel(value: string) {
  return platforms.find((item) => item.value === value)?.label ?? value;
}

export default function AdminAccountsPage() {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [accounts, setAccounts] = useState<AdminOperationalAccount[]>([]);
  const [workspaces, setWorkspaces] = useState<AdminWorkspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [platform, setPlatform] = useState<Platform>("taobao");
  const [accountKey, setAccountKey] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [activeLoginIds, setActiveLoginIds] = useState<Set<string>>(() => new Set());
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [access, accountResult, workspaceResult] = await Promise.all([
        getAdminAccess(),
        getAdminAccounts({ limit: 100 }),
        getAdminWorkspaces({ limit: 100, status: "active" }),
      ]);
      setAllowed(access.can_manage);
      setAccounts(accountResult.items);
      setWorkspaces(workspaceResult.items);
      setWorkspaceId((current) => current || workspaceResult.items[0]?.id || "");
    } catch (cause) {
      setAllowed(false);
      setError(errorDiagnostic(cause));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function createAccount() {
    if (!workspaceId || !accountKey.trim()) {
      setError("请选择工作区并输入账号标识。");
      return;
    }
    setBusyId("new");
    setError("");
    setMessage("");
    try {
      await apiClient.POST("/api/ecommerce/accounts", {
        body: {
          workspace_id: workspaceId,
          platform,
          account_key: accountKey.trim(),
          display_name: displayName.trim() || null,
        },
      });
      setAccountKey("");
      setDisplayName("");
      setShowForm(false);
      setMessage("账号已添加。请在账号列表中按需启动受控登录。");
      await load();
    } catch (cause) {
      setError(errorDiagnostic(cause));
    } finally {
      setBusyId(null);
    }
  }

  async function updateStatus(account: AdminOperationalAccount) {
    const nextStatus = account.status === "active" ? "paused" : "active";
    setBusyId(account.id);
    setError("");
    try {
      await apiClient.PATCH("/api/ecommerce/accounts/{account_id}", {
        params: { path: { account_id: account.id } },
        body: { status: nextStatus },
      });
      setMessage(nextStatus === "active" ? "账号已恢复。" : "账号已暂停，不会被新任务选中。");
      await load();
    } catch (cause) {
      setError(errorDiagnostic(cause));
    } finally {
      setBusyId(null);
    }
  }

  function updateLoginActivity(accountId: string, data: LoginStatusResponse) {
    setActiveLoginIds((current) => {
      const next = new Set(current);
      if (data.loginSession?.status === "active") {
        next.add(accountId);
      } else {
        next.delete(accountId);
      }
      return next;
    });
  }

  function readLoginStatus(response: ApiResult<unknown>): LoginStatusResponse {
    const envelope = unwrapApiResponse(response) as LoginApiEnvelope;
    return envelope.data ?? envelope;
  }

  async function startLogin(account: AdminOperationalAccount) {
    setBusyId(account.id);
    setError("");
    setMessage("");
    try {
      if (account.active_lease_task_id) {
        setError("该账号当前被任务占用，请等待任务完成后再登录。");
        return;
      }
      const response = await apiClient.POST("/api/ecommerce/session/start", {
        body: { account_id: account.id, platform: account.platform as Platform },
      });
      const data = readLoginStatus(response);
      updateLoginActivity(account.id, data);
      setMessage(data.message || "登录流程已启动，请继续在受控运维通道中完成登录。");
      await load();
    } catch (cause) {
      setError(errorDiagnostic(cause));
    } finally {
      setBusyId(null);
    }
  }

  async function cancelLogin(account: AdminOperationalAccount) {
    setBusyId(account.id);
    setError("");
    try {
      const response = await apiClient.POST("/api/ecommerce/session/cancel", { body: { account_id: account.id } });
      const data = readLoginStatus(response);
      updateLoginActivity(account.id, data);
      setMessage(data.message || "已请求取消该账号的登录流程。");
      await load();
    } catch (cause) {
      setError(errorDiagnostic(cause));
    } finally {
      setBusyId(null);
    }
  }

  async function refreshLogin(account: AdminOperationalAccount) {
    setBusyId(account.id);
    setError("");
    try {
      const response = await apiClient.GET("/api/ecommerce/session/status", {
        params: { query: { account_id: account.id, platform: account.platform } },
      });
      const data = readLoginStatus(response);
      updateLoginActivity(account.id, data);
      setMessage(`${account.label}：${data.message || loginStateLabels[data.state || "unknown"] || data.state || "状态已刷新"}`);
      await load();
    } catch (cause) {
      setError(errorDiagnostic(cause));
    } finally {
      setBusyId(null);
    }
  }

  if (loading || allowed === null) {
    return <AdminShell><div className={styles.center}><Loader2 className="spin" size={24} /> 正在检查管理员账号池权限…</div></AdminShell>;
  }
  if (!allowed) {
    return <AdminShell><div className={styles.center}><ShieldCheck size={30} /><h1>暂无电商账号管理权限</h1><p>{error || "请使用有效的管理员身份登录。"}</p><button className={styles.secondary} type="button" onClick={() => void load()}><RefreshCw size={15} />重新载入</button></div></AdminShell>;
  }

  return <AdminShell>
    <main className={styles.page}>
      <header className={styles.header}>
        <div><span className={styles.eyebrow}><ShieldCheck size={14} /> ADMIN / ACCOUNTS</span><h1>电商账号池</h1><p>账号、登录会话和独立浏览器 Profile 只在管理员后台维护；普通爬虫用户只能提交商品链接。</p></div>
        <button className={styles.secondary} type="button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} />刷新</button>
      </header>
      {message ? <p className={styles.success} role="status">{message}</p> : null}
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      <section className={styles.card}>
        <div className={styles.sectionHeader}><div><h2>账号列表</h2><p>{accounts.length} 个账号 · 不在前台展示账号标识、Profile 或租约路径。</p></div><button className={styles.primary} type="button" onClick={() => setShowForm((value) => !value)}><Plus size={15} />添加账号</button></div>
        {showForm ? <div className={styles.form}>
          <label>工作区<select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}><option value="">请选择工作区</option>{workspaces.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}</select></label>
          <label>平台<select value={platform} onChange={(event) => setPlatform(event.target.value as Platform)}>{platforms.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          <label>账号标识<input value={accountKey} onChange={(event) => setAccountKey(event.target.value)} placeholder="手机号、会员名或内部备注" /></label>
          <label>显示名称<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="例如：淘宝主账号" /></label>
          <button className={styles.primary} type="button" onClick={() => void createAccount()} disabled={busyId === "new"}>{busyId === "new" ? "保存中…" : "保存账号"}</button>
        </div> : null}
        <div className={styles.tableWrap}><table><thead><tr><th>账号</th><th>状态</th><th>任务与租约</th><th>登录运维</th></tr></thead><tbody>{accounts.length === 0 ? <tr><td colSpan={4} className={styles.empty}>暂无账号，请先添加一个平台账号。</td></tr> : accounts.map((account) => <tr key={account.id}><td><strong>{account.label}</strong><small>{platformLabel(account.platform)} · {account.workspace_name || account.workspace_id}</small></td><td><strong>{accountStatusLabels[account.status] || account.status}</strong><small>{loginStateLabels[account.login_state] || account.login_state}</small></td><td><strong>{account.profile_busy ? "使用中" : "空闲"}</strong><small>{account.active_lease_task_id || `${account.task_count} 个任务`}</small></td><td><div className={styles.actions}><button type="button" className={styles.action} onClick={() => void refreshLogin(account)} disabled={busyId === account.id}><RefreshCw size={14} />状态</button>{activeLoginIds.has(account.id) ? null : <button type="button" className={styles.action} onClick={() => void startLogin(account)} disabled={busyId === account.id}><LogIn size={14} />{account.login_state === "ready" ? "重新登录" : "登录"}</button>}<button type="button" className={styles.action} onClick={() => void updateStatus(account)} disabled={busyId === account.id || account.status === "disabled"}>{account.status === "active" ? <Pause size={14} /> : <Play size={14} />}{account.status === "active" ? "暂停" : "恢复"}</button>{activeLoginIds.has(account.id) ? <button type="button" className={styles.action} onClick={() => void cancelLogin(account)} disabled={busyId === account.id}><Square size={14} />取消登录</button> : null}</div></td></tr>)}</tbody></table></div>
      </section>
    </main>
  </AdminShell>;
}
