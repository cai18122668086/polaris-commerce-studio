"use client";

import Link from "next/link";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Clock3,
  ExternalLink,
  Image as ImageIcon,
  LoaderCircle,
  Plus,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Square,
  Store,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import { getAssetAccessUrl } from "@/features/assets/api/assets";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { errorMessage, unwrapApiResponse } from "@/lib/api/request";
import { apiClient } from "@/lib/api/client";
import styles from "./commerce-crawler-workspace.module.css";

type Platform = "auto" | "1688" | "taobao" | "jd" | "pinduoduo";
type AccountStatus = "active" | "paused" | "disabled";
type LoginState = "unknown" | "ready" | "needs_login";
type CrawlStatus =
  | "created"
  | "queued"
  | "running"
  | "waiting_session"
  | "cancelling"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "retry_scheduled";

type Account = {
  id: string;
  platform: Exclude<Platform, "auto">;
  account_key: string;
  display_name: string | null;
  status: AccountStatus;
  login_state: LoginState;
  profile_busy: boolean;
  last_used_at: string | null;
  last_login_at: string | null;
};

type LoginSession = {
  id: string;
  status: "active" | "completed" | "expired" | "cancelled" | "failed";
  transport: "local_visible" | "headless_qr";
  startedAt: string | null;
  expiresAt: string | null;
  lastSeenAt: string | null;
  completedAt: string | null;
  errorCode: string | null;
};

type LoginStatus = {
  state: string;
  message?: string;
  previewAvailable?: boolean;
  platform?: string;
  loginSession?: LoginSession | null;
};

type CrawlTask = {
  id: string;
  workspace_id: string;
  platform: string;
  source_url: string;
  canonical_url: string;
  status: CrawlStatus;
  stage: string | null;
  progress: number;
  error_code: string | null;
  error_message_safe: string | null;
  attempt_count: number;
  max_attempts: number;
  account_id: string | null;
  result_snapshot_id: string | null;
  created_at: string | null;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
};

type CrawlEvent = {
  id: string;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  message: string;
  details: Record<string, unknown> | null;
  created_at: string | null;
};

type CrawlResult = {
  platform?: string;
  numIid?: string | null;
  title?: string | null;
  price?: string | null;
  shopName?: string | null;
  sales?: string | null;
  warnings?: string[];
  snapshotId?: string | null;
  assetIds?: Record<string, string[]>;
  assets?: Array<{ asset_id: string; role: string; ordinal: number; source_url?: string }>;
  imageUrls?: string[];
  descImageUrls?: string[];
  skuImageUrls?: string[];
};

type ApiEnvelope<T> = { success?: boolean; data: T };
type CrawlTaskHistory = {
  items: CrawlTask[];
  pagination: { total: number; limit: number; offset: number; has_more: boolean };
};

const platformOptions: Array<{ value: Platform; label: string }> = [
  { value: "auto", label: "自动识别" },
  { value: "1688", label: "1688" },
  { value: "taobao", label: "淘宝 / 天猫" },
  { value: "jd", label: "京东" },
  { value: "pinduoduo", label: "拼多多" },
];

const statusLabels: Record<CrawlStatus, string> = {
  created: "已创建",
  queued: "排队中",
  running: "抓取中",
  waiting_session: "等待登录 / 验证",
  cancelling: "正在取消",
  succeeded: "抓取成功",
  failed: "抓取失败",
  cancelled: "已取消",
  retry_scheduled: "准备重试",
};

const statusTone: Record<CrawlStatus, string> = {
  created: "muted",
  queued: "blue",
  running: "blue",
  waiting_session: "amber",
  cancelling: "amber",
  succeeded: "green",
  failed: "red",
  cancelled: "muted",
  retry_scheduled: "blue",
};

const accountPlatformLabels: Record<Exclude<Platform, "auto">, string> = {
  "1688": "1688",
  taobao: "淘宝 / 天猫",
  jd: "京东",
  pinduoduo: "拼多多",
};

const accountStatusLabels: Record<AccountStatus, string> = {
  active: "可用",
  paused: "已暂停",
  disabled: "已禁用",
};

const loginStateLabels: Record<LoginState, string> = {
  unknown: "未确认登录",
  ready: "已登录",
  needs_login: "需要登录",
};

function unwrap<T>(result: unknown): T {
  return unwrapApiResponse(result as { data?: T; error?: unknown; response: Response });
}

function formatTime(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatPlatform(value: string | null | undefined) {
  if (!value) return "—";
  return accountPlatformLabels[value as Exclude<Platform, "auto">] ?? value;
}

function classifyUrl(raw: string): { platform: Exclude<Platform, "auto">; label: string } | null {
  try {
    const host = new URL(raw.trim()).hostname.toLowerCase().replace(/\.$/, "");
    const matches = (domain: string) => host === domain || host.endsWith(`.${domain}`);
    if (matches("1688.com")) return { platform: "1688", label: "1688" };
    if (matches("taobao.com") || matches("tmall.com") || matches("tb.cn")) {
      return { platform: "taobao", label: matches("tmall.com") ? "天猫" : "淘宝" };
    }
    if (matches("jd.com") || matches("3.cn") || matches("npcitem.jd.hk")) return { platform: "jd", label: "京东" };
    if (matches("pinduoduo.com") || matches("yangkeduo.com")) return { platform: "pinduoduo", label: "拼多多" };
    return null;
  } catch {
    return null;
  }
}

function eventIcon(event: CrawlEvent) {
  if (event.to_status === "succeeded") return <CheckCircle2 size={15} />;
  if (event.to_status === "failed") return <XCircle size={15} />;
  if (event.event_type.includes("cancel")) return <Square size={13} />;
  return <CircleDot size={15} />;
}

function AssetThumb({ workspaceId, assetId, label }: { workspaceId: string; assetId: string; label: string }) {
  const [url, setUrl] = useState<string>();
  const [busy, setBusy] = useState(true);
  useEffect(() => {
    let active = true;
    void getAssetAccessUrl(workspaceId, assetId)
      .then((access) => { if (active) setUrl(access.url); })
      .catch(() => { if (active) setUrl(undefined); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [assetId, workspaceId]);
  return (
    <a className={styles.assetCard} href={url} target="_blank" rel="noreferrer" aria-label={`查看${label}`}>
      <div className={styles.assetMedia}>
        {busy ? <LoaderCircle className="spin" size={20} /> : url ? <img src={url} alt={label} /> : <ImageIcon size={22} />}
      </div>
      <span>{label}</span>
      <small>{assetId}</small>
    </a>
  );
}

export function CommerceCrawlerWorkspace() {
  const { workspace } = useWorkspace();
  const workspaceId = workspace?.id;
  const [url, setUrl] = useState("");
  const [platform, setPlatform] = useState<Platform>("auto");
  const [accountId, setAccountId] = useState("");
  const [includeDescImages, setIncludeDescImages] = useState(true);
  const [maxAttempts, setMaxAttempts] = useState(1);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountsBusy, setAccountsBusy] = useState(false);
  const [accountFormOpen, setAccountFormOpen] = useState(false);
  const [newAccount, setNewAccount] = useState({ platform: "taobao" as Exclude<Platform, "auto">, account_key: "", display_name: "" });
  const [tasks, setTasks] = useState<CrawlTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string>();
  const [task, setTask] = useState<CrawlTask>();
  const [events, setEvents] = useState<CrawlEvent[]>([]);
  const [result, setResult] = useState<CrawlResult>();
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [message, setMessage] = useState<string>();
  const [error, setError] = useState<string>();
  const [loginStatusByAccount, setLoginStatusByAccount] = useState<Record<string, LoginStatus>>({});
  const [loginPreviewUrls, setLoginPreviewUrls] = useState<Record<string, string>>({});
  const [loginBusyAccountId, setLoginBusyAccountId] = useState<string>();

  const urlHint = useMemo(() => classifyUrl(url), [url]);
  const compatibleAccounts = accounts.filter((account) => {
    const target = platform === "auto" ? urlHint?.platform : platform;
    return !target || account.platform === target;
  });
  const effectiveAccountId = compatibleAccounts.some((account) => account.id === accountId) ? accountId : "";
  const selectedAccount = accounts.find((account) => account.id === effectiveAccountId);

  const loadAccounts = useCallback(async () => {
    if (!workspaceId) return;
    setAccountsBusy(true);
    try {
      const response = await apiClient.GET("/api/ecommerce/accounts", { params: { query: { workspace_id: workspaceId } } });
      const data = unwrap<ApiEnvelope<Account[]>>(response);
      setAccounts(data.data ?? []);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setAccountsBusy(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadAccounts(), 0);
    return () => window.clearTimeout(timer);
  }, [loadAccounts]);

  const loadLoginPreview = useCallback(async (accountId: string) => {
    try {
      const response = await apiClient.GET("/api/ecommerce/session/preview", {
        params: { query: { account_id: accountId } },
      });
      const blob = unwrap<Blob>(response);
      const nextUrl = URL.createObjectURL(blob);
      setLoginPreviewUrls((current) => {
        const previousUrl = current[accountId];
        if (previousUrl) URL.revokeObjectURL(previousUrl);
        return { ...current, [accountId]: nextUrl };
      });
    } catch {
      // The preview can legitimately be unavailable for a few polling cycles
      // while Chromium is loading the official login page.
    }
  }, []);

  const loadLoginStatus = useCallback(async (account: Account) => {
    try {
      const response = await apiClient.GET("/api/ecommerce/session/status", {
        params: { query: { account_id: account.id, platform: account.platform } },
      });
      const data = unwrap<ApiEnvelope<LoginStatus>>(response).data;
      setLoginStatusByAccount((current) => ({ ...current, [account.id]: data }));
      if (data.loginSession?.status === "active" && data.previewAvailable) {
        void loadLoginPreview(account.id);
      }
      if (data.loginSession?.status !== "active") {
        setLoginPreviewUrls((current) => {
          const previousUrl = current[account.id];
          if (previousUrl) URL.revokeObjectURL(previousUrl);
          if (!(account.id in current)) return current;
          const next = { ...current };
          delete next[account.id];
          return next;
        });
      }
    } catch {
      // Account list and the task workspace remain usable if a status poll
      // fails; the next poll will retry without surfacing noisy errors.
    }
  }, [loadLoginPreview]);

  useEffect(() => {
    if (!accounts.length) return;
    const timer = window.setTimeout(() => {
      void Promise.all(accounts.map((account) => loadLoginStatus(account)));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [accounts, loadLoginStatus]);

  const hasActiveLogin = Object.values(loginStatusByAccount).some(
    (status) => status.loginSession?.status === "active",
  );

  useEffect(() => {
    if (!hasActiveLogin || !accounts.length) return;
    const refresh = () => {
      void Promise.all(
        accounts
          .filter((account) => loginStatusByAccount[account.id]?.loginSession?.status === "active")
          .map((account) => loadLoginStatus(account)),
      );
    };
    const timer = window.setInterval(refresh, 2500);
    return () => window.clearInterval(timer);
  }, [accounts, hasActiveLogin, loadLoginStatus, loginStatusByAccount]);

  useEffect(() => () => {
    Object.values(loginPreviewUrls).forEach((url) => URL.revokeObjectURL(url));
  }, [loginPreviewUrls]);

  const startLogin = async (account: Account) => {
    setLoginBusyAccountId(account.id);
    setError(undefined);
    setMessage(undefined);
    try {
      const response = await apiClient.POST("/api/ecommerce/session/start", {
        body: { account_id: account.id, platform: account.platform },
      });
      const data = unwrap<ApiEnvelope<LoginStatus>>(response).data;
      setLoginStatusByAccount((current) => ({ ...current, [account.id]: data }));
      if (data.state === "ready") {
        setMessage(`${account.display_name || account.account_key} 已确认登录，可用于抓取。`);
        await loadAccounts();
      } else {
        setMessage("登录流程已启动。请在下方受保护的官方二维码预览中完成登录，系统会自动确认状态。 ");
      }
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoginBusyAccountId(undefined);
    }
  };

  const cancelLogin = async (account: Account) => {
    setLoginBusyAccountId(account.id);
    setError(undefined);
    try {
      const response = await apiClient.POST("/api/ecommerce/session/cancel", {
        body: { account_id: account.id },
      });
      const data = unwrap<ApiEnvelope<LoginStatus>>(response).data;
      setLoginStatusByAccount((current) => ({ ...current, [account.id]: data }));
      setMessage("已取消该账号的登录流程。需要时可以重新发起登录。");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoginBusyAccountId(undefined);
    }
  };

  const loadTaskHistory = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const response = await apiClient.GET("/api/ecommerce/crawl-tasks", {
        params: { query: { workspace_id: workspaceId, limit: 8, offset: 0 } },
      });
      const history = unwrap<ApiEnvelope<CrawlTaskHistory>>(response).data;
      const nextTasks = history.items ?? [];
      setTasks(nextTasks);
      setSelectedTaskId(nextTasks[0]?.id);
      setTask(undefined);
      setEvents([]);
      setResult(undefined);
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }, [workspaceId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadTaskHistory(), 0);
    return () => window.clearTimeout(timer);
  }, [loadTaskHistory]);

  const loadTaskDetail = useCallback(async (taskId: string, quiet = false) => {
    if (!quiet) setDetailLoading(true);
    try {
      const [taskResponse, eventsResponse] = await Promise.all([
        apiClient.GET("/api/ecommerce/crawl-tasks/{task_id}", { params: { path: { task_id: taskId } } }),
        apiClient.GET("/api/ecommerce/crawl-tasks/{task_id}/events", { params: { path: { task_id: taskId } } }),
      ]);
      const nextTask = unwrap<ApiEnvelope<CrawlTask>>(taskResponse).data;
      setTask(nextTask);
      setEvents(unwrap<ApiEnvelope<CrawlEvent[]>>(eventsResponse).data ?? []);
      setTasks((current) => current.some((item) => item.id === nextTask.id) ? current.map((item) => item.id === nextTask.id ? nextTask : item) : [nextTask, ...current].slice(0, 8));
      if (nextTask.status === "succeeded") {
        const resultResponse = await apiClient.GET("/api/ecommerce/crawl-tasks/{task_id}/result", { params: { path: { task_id: taskId } } });
        setResult(unwrap<ApiEnvelope<{ result: CrawlResult }>>(resultResponse).data.result);
      } else {
        setResult(undefined);
      }
    } catch (requestError) {
      if (!quiet) setError(errorMessage(requestError));
    } finally {
      if (!quiet) setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedTaskId) return;
    const initial = window.setTimeout(() => void loadTaskDetail(selectedTaskId), 0);
    const timer = window.setInterval(() => void loadTaskDetail(selectedTaskId, true), 2500);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [loadTaskDetail, selectedTaskId]);

  const createTask = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedUrl = url.trim();
    if (!workspace?.id) return setError("工作区尚未就绪，请稍后重试。");
    if (!trimmedUrl) return setError("请输入真实商品链接。");
    try { new URL(trimmedUrl); } catch { return setError("商品链接格式不正确，请粘贴完整 URL。"); }
    setLoading(true); setError(undefined); setMessage(undefined);
    try {
      const response = await apiClient.POST("/api/ecommerce/crawl-tasks", {
        params: { header: { "Idempotency-Key": crypto.randomUUID() } },
        body: {
          workspace_id: workspace.id,
          url: trimmedUrl,
          platform,
          includeDescImages,
          max_attempts: maxAttempts,
          account_id: effectiveAccountId || null,
        },
      });
      const created = unwrap<ApiEnvelope<CrawlTask>>(response).data;
      setTasks((current) => [created, ...current.filter((item) => item.id !== created.id)].slice(0, 8));
      setSelectedTaskId(created.id);
      setTask(created);
      setEvents([]);
      setResult(undefined);
      setMessage("任务已进入真实异步爬虫队列。页面会自动刷新状态。指定账号时会严格绑定该账号的独立 Profile。");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally { setLoading(false); }
  };

  const cancelTask = async () => {
    if (!task) return;
    setLoading(true); setError(undefined);
    try {
      const response = await apiClient.POST("/api/ecommerce/crawl-tasks/{task_id}/cancel", { params: { path: { task_id: task.id } } });
      const nextTask = unwrap<ApiEnvelope<CrawlTask>>(response).data;
      setTask(nextTask); setTasks((current) => current.map((item) => item.id === nextTask.id ? nextTask : item));
      setMessage("已发送取消请求。");
    } catch (requestError) { setError(errorMessage(requestError)); } finally { setLoading(false); }
  };

  const retryTask = async () => {
    if (!task) return;
    setLoading(true); setError(undefined);
    try {
      const response = await apiClient.POST("/api/ecommerce/crawl-tasks/{task_id}/retry", { params: { path: { task_id: task.id } } });
      const nextTask = unwrap<ApiEnvelope<CrawlTask>>(response).data;
      setTask(nextTask); setResult(undefined); setTasks((current) => current.map((item) => item.id === nextTask.id ? nextTask : item));
      setMessage("任务已重新排队。");
    } catch (requestError) { setError(errorMessage(requestError)); } finally { setLoading(false); }
  };

  const addAccount = async () => {
    if (!workspaceId || !newAccount.account_key.trim()) return setError("请输入平台账号标识。");
    setAccountsBusy(true); setError(undefined);
    try {
      const response = await apiClient.POST("/api/ecommerce/accounts", { body: { workspace_id: workspaceId, platform: newAccount.platform, account_key: newAccount.account_key.trim(), display_name: newAccount.display_name.trim() || null } });
      const account = unwrap<ApiEnvelope<Account>>(response).data;
      setAccounts((current) => [...current, account]);
      setAccountId(account.id);
      setNewAccount({ platform: newAccount.platform, account_key: "", display_name: "" });
      setAccountFormOpen(false);
      setMessage("账号已添加。首次使用前，请通过受控登录流程完成平台登录。");
    } catch (requestError) { setError(errorMessage(requestError)); } finally { setAccountsBusy(false); }
  };

  const toggleAccount = async (account: Account) => {
    const nextStatus: AccountStatus = account.status === "active" ? "paused" : "active";
    setAccountsBusy(true); setError(undefined);
    try {
      const response = await apiClient.PATCH("/api/ecommerce/accounts/{account_id}", { params: { path: { account_id: account.id } }, body: { status: nextStatus } });
      const next = unwrap<ApiEnvelope<Account>>(response).data;
      setAccounts((current) => current.map((item) => item.id === next.id ? next : item));
      setMessage(nextStatus === "active" ? "账号已恢复，可参与后续调度。" : "账号已暂停，不会被新的任务选中。");
    } catch (requestError) { setError(errorMessage(requestError)); } finally { setAccountsBusy(false); }
  };

  const canCancel = task && ["created", "queued", "running", "waiting_session", "cancelling"].includes(task.status);
  const canRetry = task && ["failed", "waiting_session", "cancelled"].includes(task.status);
  const assetGroups = result?.assetIds ?? {};
  const assets = Object.entries(assetGroups).flatMap(([role, ids]) => ids.map((id) => ({ role, id })));

  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div>
          <span className={styles.eyebrow}><Store size={16} /> 国内电商运营</span>
          <h1>真实商品爬虫</h1>
          <p>提交商品链接后进入异步任务队列，实时查看平台会话、抓取进度、事件和商品资产。</p>
        </div>
        <div className={styles.heroNote}><ShieldCheck size={18} /><span>真实 Provider 链路<br /><small>不返回 Cookie、Profile 路径或 Secret</small></span></div>
      </header>

      <div className={styles.layout}>
        <main className={styles.mainColumn}>
          <section className={styles.card}>
            <div className={styles.cardHeading}><div><span className={styles.step}>01</span><div><h2>新建抓取任务</h2><p>选择平台并粘贴需要验证的真实商品链接。</p></div></div><span className={styles.liveBadge}><span />异步队列</span></div>
            <form onSubmit={createTask} className={styles.form}>
              <div className={styles.fieldGrid}>
                <label>平台<select value={platform} onChange={(event) => setPlatform(event.target.value as Platform)}>{platformOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                <label>最大尝试次数<select value={maxAttempts} onChange={(event) => setMaxAttempts(Number(event.target.value))}><option value={1}>1 次</option><option value={2}>2 次</option><option value={3}>3 次</option></select></label>
              </div>
              <label>商品 URL<div className={styles.urlInput}><input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://item.taobao.com/item.htm?id=..." inputMode="url" /><span>{urlHint ? `${urlHint.label} · 已识别` : "支持 1688、淘宝 / 天猫、京东、拼多多"}</span></div></label>
              <div className={styles.accountRow}>
                <label className={styles.accountSelect}>执行账号<select value={effectiveAccountId} onChange={(event) => setAccountId(event.target.value)}><option value="">不指定账号（使用默认平台会话）</option>{compatibleAccounts.map((account) => <option key={account.id} value={account.id} disabled={account.status !== "active" || account.login_state !== "ready" || account.profile_busy}>{account.display_name || account.account_key} · {accountPlatformLabels[account.platform]} · {account.status !== "active" ? accountStatusLabels[account.status] : loginStateLabels[account.login_state]}{account.profile_busy ? " · 使用中" : ""}</option>)}</select></label>
                <button type="button" className={styles.outlineButton} onClick={() => setAccountFormOpen((value) => !value)}><Plus size={15} />添加账号</button>
                <button type="button" className={styles.iconButton} onClick={() => void loadAccounts()} disabled={accountsBusy} aria-label="刷新账号"><RefreshCw size={15} className={accountsBusy ? "spin" : ""} /></button>
              </div>
              {accountFormOpen ? <div className={styles.inlineForm}><label>平台<select value={newAccount.platform} onChange={(event) => setNewAccount((current) => ({ ...current, platform: event.target.value as Exclude<Platform, "auto"> }))}>{platformOptions.filter((option) => option.value !== "auto").map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label><label>账号标识<input value={newAccount.account_key} onChange={(event) => setNewAccount((current) => ({ ...current, account_key: event.target.value }))} placeholder="手机号、会员名或内部备注" /></label><label>显示名称<input value={newAccount.display_name} onChange={(event) => setNewAccount((current) => ({ ...current, display_name: event.target.value }))} placeholder="例如：淘宝主账号" /></label><button className={styles.primaryButton} type="button" onClick={() => void addAccount()} disabled={accountsBusy}>保存账号</button></div> : null}
              {selectedAccount && <p className={styles.accountHint}><ShieldCheck size={14} />已指定 {selectedAccount.display_name || selectedAccount.account_key}。任务只会使用该账号的独立浏览器 Profile。</p>}
              {accounts.length ? <div className={styles.accountList}>{accounts.map((account) => {
                const loginStatus = loginStatusByAccount[account.id];
                const loginActive = loginStatus?.loginSession?.status === "active";
                const loginBusy = loginBusyAccountId === account.id;
                const previewUrl = loginPreviewUrls[account.id];
                return <div className={styles.accountItem} key={account.id}>
                  <div className={styles.accountMain}><strong>{account.display_name || account.account_key}</strong><span>{accountPlatformLabels[account.platform]} · {accountStatusLabels[account.status]} · {loginStateLabels[account.login_state]}{account.profile_busy ? " · Profile 使用中" : ""}</span>{loginStatus?.message ? <small>{loginStatus.message}</small> : null}
                    {loginActive && previewUrl ? <div className={styles.loginPreview}><img src={previewUrl} alt={`${account.display_name || account.account_key} 官方登录二维码`} /><span>仅用于当前登录流程，请在官方页面完成扫码。</span></div> : null}
                  </div>
                  <div className={styles.accountActions}><button type="button" className={styles.accountAction} onClick={() => void (loginActive ? cancelLogin(account) : startLogin(account))} disabled={accountsBusy || loginBusy || account.status !== "active" || account.profile_busy}>{loginBusy ? "处理中…" : loginActive ? "取消登录" : account.login_state === "ready" ? "重新登录" : "登录"}</button><button type="button" className={styles.accountAction} onClick={() => void toggleAccount(account)} disabled={accountsBusy || loginBusy || account.status === "disabled"}>{account.status === "active" ? "暂停" : "恢复"}</button></div>
                </div>;
              })}</div> : null}
              <label className={styles.checkbox}><input type="checkbox" checked={includeDescImages} onChange={(event) => setIncludeDescImages(event.target.checked)} /><span>同时抓取详情图和 SKU 图（会增加任务耗时）</span></label>
              <button className={styles.primaryButton} type="submit" disabled={loading || !workspace?.id}>{loading ? <LoaderCircle size={17} className="spin" /> : <Plus size={17} />}{loading ? "正在提交…" : "提交真实抓取任务"}</button>
            </form>
            {message ? <p className={styles.successMessage}><CheckCircle2 size={15} />{message}</p> : null}
            {error ? <p className={styles.errorMessage} role="alert"><AlertCircle size={15} />{error}</p> : null}
          </section>

          <section className={styles.card}>
            <div className={styles.cardHeading}><div><span className={styles.step}>02</span><div><h2>任务历史</h2><p>显示当前工作区最近的真实爬虫任务，刷新页面后仍可继续查看状态和结果。</p></div></div><Clock3 size={19} className={styles.headingIcon} /></div>
            {tasks.length ? <div className={styles.taskList}>{tasks.map((item) => <button type="button" key={item.id} className={`${styles.taskRow} ${selectedTaskId === item.id ? styles.taskRowActive : ""}`} onClick={() => setSelectedTaskId(item.id)}><span className={`${styles.statusDot} ${styles[`tone-${statusTone[item.status]}`]}`} /><span className={styles.taskRowMain}><strong>{item.source_url}</strong><small>{formatPlatform(item.platform)} · {formatTime(item.created_at)}</small></span><span className={`${styles.statusPill} ${styles[`tone-${statusTone[item.status]}`]}`}>{statusLabels[item.status]}</span><ChevronDown size={16} className={styles.rowChevron} /></button>)}</div> : <div className={styles.empty}><Clock3 size={24} /><strong>还没有抓取任务</strong><span>提交第一个真实商品链接后，任务会出现在这里。</span></div>}
          </section>
        </main>

        <aside className={styles.detailColumn}>
          <section className={`${styles.card} ${styles.detailCard}`}>
            <div className={styles.cardHeading}><div><span className={styles.step}>03</span><div><h2>任务详情</h2><p>{task ? `任务 ${task.id}` : "选择一个任务查看实时状态"}</p></div></div>{detailLoading ? <LoaderCircle size={18} className="spin" /> : null}</div>
            {task ? <>
              <div className={styles.statusHeader}><div><span className={`${styles.statusPill} ${styles[`tone-${statusTone[task.status]}`]}`}>{statusLabels[task.status]}</span><strong>{task.stage || "—"}</strong></div><span>{task.progress}%</span></div>
              <div className={styles.progress}><span style={{ width: `${task.progress}%` }} /></div>
              <dl className={styles.metaGrid}><div><dt>平台</dt><dd>{formatPlatform(task.platform)}</dd></div><div><dt>尝试</dt><dd>{task.attempt_count} / {task.max_attempts}</dd></div><div><dt>账号</dt><dd>{task.account_id ? (accounts.find((item) => item.id === task.account_id)?.display_name || task.account_id) : "默认平台会话"}</dd></div><div><dt>开始时间</dt><dd>{formatTime(task.started_at)}</dd></div></dl>
              {task.error_message_safe ? <div className={styles.taskError}><AlertCircle size={16} /><div><strong>{task.error_code || "任务异常"}</strong><span>{task.error_message_safe}</span></div></div> : null}
              <div className={styles.actionRow}>{canCancel ? <button className={styles.outlineButton} type="button" onClick={() => void cancelTask()} disabled={loading || task.status === "cancelling"}><Square size={14} />取消任务</button> : null}{canRetry ? <button className={styles.outlineButton} type="button" onClick={() => void retryTask()} disabled={loading}><RotateCcw size={14} />重新排队</button> : null}<button className={styles.iconButton} type="button" onClick={() => void loadTaskDetail(task.id)} disabled={detailLoading} aria-label="刷新任务"><RefreshCw size={15} className={detailLoading ? "spin" : ""} /></button></div>
              <div className={styles.subsection}><h3>事件时间线</h3>{events.length ? <ol className={styles.timeline}>{events.slice().reverse().map((event) => <li key={event.id}><span className={styles.timelineIcon}>{eventIcon(event)}</span><div><strong>{event.message}</strong><small>{formatTime(event.created_at)}{event.to_status ? ` · ${statusLabels[event.to_status as CrawlStatus] ?? event.to_status}` : ""}</small></div></li>)}</ol> : <p className={styles.mutedText}>暂无事件。</p>}</div>
            </> : <div className={styles.empty}><CircleDot size={24} /><strong>等待选择任务</strong><span>提交任务后，这里会显示队列、会话和结果状态。</span></div>}
          </section>
        </aside>
      </div>

      {task?.status === "succeeded" && result ? <section className={`${styles.card} ${styles.resultCardSection}`}><div className={styles.cardHeading}><div><span className={styles.step}>04</span><div><h2>商品结果与内部资产</h2><p>结果来自 ProductSnapshot；图片通过受保护的资产访问接口加载。</p></div></div><span className={styles.resultCount}>{assets.length} 个资产</span></div><div className={styles.productSummary}><div><span className={styles.resultPlatform}>{formatPlatform(result.platform)}</span><h2>{result.title || "未返回商品标题"}</h2><p>{result.shopName || "未返回店铺"} · {result.price || "价格未返回"}{result.sales ? ` · ${result.sales}` : ""}</p></div>{result.numIid ? <code>{result.numIid}</code> : null}</div>{result.warnings?.length ? <div className={styles.warningList}>{result.warnings.map((warning) => <span key={warning}><AlertCircle size={14} />{warning}</span>)}</div> : null}{assets.length ? <div className={styles.assetGrid}>{assets.map(({ role, id }) => <AssetThumb key={`${role}-${id}`} workspaceId={task.workspace_id} assetId={id} label={`${role === "main" ? "主图" : role === "detail" ? "详情图" : "SKU 图"} · ${id}`} />)}</div> : <div className={styles.noAssets}><ImageIcon size={20} />任务成功但暂未返回内部图片资产。</div>}<Link className={styles.resultLink} href="/assets">前往个人素材库查看全部资产 <ExternalLink size={14} /></Link></section> : null}
    </div>
  );
}
