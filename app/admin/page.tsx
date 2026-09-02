"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CircleCheck,
  Clock3,
  ExternalLink,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Users,
  Workflow,
} from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/components/app-shell";
import {
  getAdminAccounts,
  getAdminLogDetail,
  getAdminLogs,
  getAdminOverview,
  getAdminUsers,
  getAdminWorkspaces,
  type AdminAccount,
  type AdminLog,
  type AdminLogDetail,
  type AdminLogEvent,
  type AdminOperationalAccount,
  type AdminOverview,
  type AdminUser,
  type AdminWorkspace,
} from "@/features/admin/api/admin";
import styles from "./page.module.css";

const platformMeta: Record<string, { label: string; shortLabel: string }> = {
  taobao: { label: "淘宝 / 天猫", shortLabel: "淘宝" },
  "1688": { label: "1688", shortLabel: "1688" },
  jd: { label: "京东", shortLabel: "京东" },
  pinduoduo: { label: "拼多多", shortLabel: "拼多多" },
};

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatTime(value: string | null) {
  if (!value) return "暂无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return date.toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" });
}

function loginLabel(account: AdminAccount) {
  if (account.login_state === "ready") return "已登录";
  if (account.needs_relogin) return "需要重新登录";
  if (account.status === "paused") return "账号已暂停";
  if (account.status === "disabled") return "账号已停用";
  return "待确认";
}

function userStatusLabel(status: string) {
  return status === "active" ? "活跃" : status === "suspended" ? "已暂停" : "非活跃";
}

function logKindLabel(log: AdminLog) {
  return log.kind === "crawl" ? "抓取" : "生成";
}

function logPlatformLabel(platform: string | null) {
  return platform ? platformMeta[platform]?.shortLabel ?? platform : "生成任务";
}

function workspaceStatusLabel(status: string) {
  return status === "active" ? "活跃" : status === "archived" ? "已归档" : status;
}

function StatusPill({ status, warning = false }: { status: string; warning?: boolean }) {
  return <span className={warning ? styles.statusNeedsLogin : styles.statusPill}>{status}</span>;
}

function eventTypeLabel(event: AdminLogEvent) {
  const labels: Record<string, string> = {
    created: "已创建",
    queued: "已排队",
    started: "已开始",
    finished: "已结束",
    status_changed: "状态变化",
    retry_scheduled: "已安排重试",
    "job.dispatch_requested": "提交任务",
    "job.cancel_requested": "请求取消",
    "xinghe.planning_rejected": "计划校验失败",
    "xinghe.image_budget_rejected": "预算校验失败",
    "xinghe.image_reserved": "预留资源",
    "xinghe.image_provider_completed": "生成服务完成",
    "provider.beta_job_settled": "用量已结算",
    "provider.beta_job_attempts_recorded": "尝试记录已保存",
    "provider.beta_job_released": "释放资源",
    "domestic_detail.auto_confirm": "计划已确认",
  };
  return labels[event.event_type] ?? "任务事件";
}

function LogDetailDialog({
  detail,
  loading,
  error,
  onClose,
}: {
  detail: AdminLogDetail | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}) {
  return <div className={styles.dialogBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="admin-log-detail-title">
      <div className={styles.dialogHeader}>
        <div><span className={styles.sectionEyebrow}>READ-ONLY DETAIL</span><h2 id="admin-log-detail-title">任务详情</h2><p>仅显示脱敏状态和事件时间线。</p></div>
        <button className={styles.closeButton} type="button" onClick={onClose} aria-label="关闭任务详情">×</button>
      </div>
      {loading ? <div className={styles.dialogLoading}><Loader2 className={styles.spin} size={20} /> 正在加载任务事件…</div> : error ? <div className={styles.dialogError}>{error}</div> : detail ? <div className={styles.dialogBody}>
        <div className={styles.detailSummary}>
          <div><small>任务类型</small><strong>{logKindLabel(detail)} · {logPlatformLabel(detail.platform)}</strong></div>
          <div><small>任务 ID</small><strong>{detail.id}</strong></div>
          <div><small>工作区</small><strong>{detail.workspace_name ?? detail.workspace_id}</strong></div>
          <div><small>状态</small><strong className={detail.status === "failed" ? styles.warningText : ""}>{detail.status}</strong></div>
          <div><small>阶段 / 进度</small><strong>{detail.stage ?? "未分阶段"} · {detail.progress}%</strong></div>
          <div><small>尝试次数</small><strong>{formatCount(detail.attempt_count)}</strong></div>
          {detail.error_code ? <div><small>错误</small><strong className={styles.warningText}>{detail.error_code} · {detail.error_message ?? "请根据错误码定位。"}</strong></div> : null}
        </div>
        <div className={styles.timelineHeading}><h3>事件时间线</h3><span>{formatCount(detail.events.length)} 个事件</span></div>
        {detail.events.length === 0 ? <p className={styles.empty}>暂无可展示的事件。</p> : <ol className={styles.timeline}>{detail.events.map((event) => <li key={event.id} className={styles.timelineItem}><span className={styles.timelineDot} /><div><div className={styles.timelineMeta}><strong>{eventTypeLabel(event)}</strong><time>{formatTime(event.occurred_at)}</time></div><p>{event.message}</p>{event.from_status || event.to_status ? <small>{event.from_status ?? "—"} → {event.to_status ?? "—"}</small> : null}</div></li>)}</ol>}
      </div> : null}
    </section>
  </div>;
}

export default function AdminDashboardPage() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [workspaces, setWorkspaces] = useState<AdminWorkspace[]>([]);
  const [userTotal, setUserTotal] = useState(0);
  const [workspaceTotal, setWorkspaceTotal] = useState(0);
  const [logs, setLogs] = useState<AdminLog[]>([]);
  const [logTotal, setLogTotal] = useState(0);
  const [operationalAccounts, setOperationalAccounts] = useState<AdminOperationalAccount[]>([]);
  const [accountTotal, setAccountTotal] = useState(0);
  const [logKind, setLogKind] = useState<"all" | "generation" | "crawl">("all");
  const [logStatus, setLogStatus] = useState("");
  const [logPlatform, setLogPlatform] = useState("");
  const [selectedLog, setSelectedLog] = useState<AdminLogDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (refresh = false) => {
    setError(null);
    if (refresh) setRefreshing(true);
    else setLoading(true);
    try {
      const [nextOverview, nextUsers, nextWorkspaces, nextLogs, nextAccounts] = await Promise.all([
        getAdminOverview(),
        getAdminUsers({ limit: 20 }),
        getAdminWorkspaces({ limit: 20 }),
        getAdminLogs({
          kind: logKind,
          status: logStatus || undefined,
          platform: logPlatform || undefined,
          limit: 20,
        }),
        getAdminAccounts({ limit: 20 }),
      ]);
      setOverview(nextOverview);
      setUsers(nextUsers.items);
      setUserTotal(nextUsers.pagination.total);
      setWorkspaces(nextWorkspaces.items);
      setWorkspaceTotal(nextWorkspaces.pagination.total);
      setLogs(nextLogs.items);
      setLogTotal(nextLogs.pagination.total);
      setOperationalAccounts(nextAccounts.items);
      setAccountTotal(nextAccounts.pagination.total);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "管理员工作台暂时无法加载，请稍后重试。");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    // The initial request synchronizes this client screen with the protected API.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    // The filter state is intentionally read only when the initial load starts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedLog) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedLog(null);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedLog]);

  const openLog = async (log: AdminLog) => {
    setSelectedLog(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      setSelectedLog(await getAdminLogDetail(log.kind, log.id));
    } catch (cause) {
      setDetailError(cause instanceof Error ? cause.message : "任务详情暂时无法加载，请稍后重试。");
    } finally {
      setDetailLoading(false);
    }
  };

  if (loading) {
    return <AppShell sidebar={false}><div className={styles.center}><Loader2 className={styles.spin} size={24} /> 正在检查管理员工作台权限…</div></AppShell>;
  }

  if (error || !overview) {
    return <AppShell sidebar={false}><div className={styles.center}><ShieldCheck size={30} /><h1>暂无管理员工作台权限</h1><p>{error ?? "请使用公告管理工作台相同的管理员身份登录。"}</p><div className={styles.centerActions}><button className={styles.primary} type="button" onClick={() => void load(true)} disabled={refreshing}><RefreshCw size={16} /> 重新载入</button><Link className={styles.secondary} href="/admin/announcements">公告管理工作台 <ExternalLink size={15} /></Link></div></div></AppShell>;
  }

  const sessions = Object.entries(overview.crawler_sessions);
  const totalRelogin = sessions.reduce((sum, [, item]) => sum + item.needs_relogin_count, 0);

  return <AppShell sidebar={false}>
    <div className={styles.page}>
      <header className={styles.header}>
        <div><span className={styles.eyebrow}><ShieldCheck size={14} /> 运营工具</span><h1>管理员工作台</h1><p>先用只读概览掌握用户使用情况、任务运行状态和电商账号登录状态。</p></div>
        <button className={styles.secondary} type="button" onClick={() => void load(true)} disabled={refreshing}><RefreshCw className={refreshing ? styles.spin : ""} size={16} /> {refreshing ? "刷新中…" : "刷新数据"}</button>
      </header>

      <nav className={styles.adminNav} aria-label="管理中心导航">
        <Link className={styles.adminNavActive} href="/admin"><ShieldCheck size={15} />工作台</Link>
        <Link href="/admin/announcements"><ExternalLink size={14} />公告管理</Link>
        <Link href="/admin/inspiration"><ExternalLink size={14} />灵感案例</Link>
        <Link href="/commerce-crawler"><Workflow size={15} />真实爬虫</Link>
      </nav>

      <section className={styles.metrics} aria-label="网站概况">
        <article className={styles.metricCard}><span className={styles.metricIcon}><Users size={20} /></span><div><small>网站用户</small><strong>{formatCount(overview.users.total)}</strong><p>{formatCount(overview.users.active)} 个活跃用户</p></div></article>
        <article className={styles.metricCard}><span className={styles.metricIcon}><Workflow size={20} /></span><div><small>工作区</small><strong>{formatCount(overview.workspaces.total)}</strong><p>{formatCount(overview.workspaces.active)} 个活跃工作区</p></div></article>
        <article className={styles.metricCard}><span className={styles.metricIcon}><Clock3 size={20} /></span><div><small>生成任务进行中</small><strong>{formatCount(overview.usage.jobs_running)}</strong><p>累计 {formatCount(overview.usage.jobs_total)} 个生成任务</p></div></article>
        <article className={`${styles.metricCard} ${overview.usage.jobs_failed || overview.usage.crawl_tasks_failed ? styles.metricCardWarn : ""}`}><span className={styles.metricIcon}><AlertTriangle size={20} /></span><div><small>失败任务</small><strong>{formatCount(overview.usage.jobs_failed + overview.usage.crawl_tasks_failed)}</strong><p>生成 {formatCount(overview.usage.jobs_failed)} · 抓取 {formatCount(overview.usage.crawl_tasks_failed)}</p></div></article>
      </section>

      <section className={styles.detailGrid} aria-label="用户和工作区使用情况">
        <article className={styles.section}>
          <div className={styles.sectionHeading}><div><span className={styles.sectionEyebrow}>USER USAGE</span><h2>网站用户</h2><p>展示必要的脱敏身份和使用量，不返回会话内容。</p></div><span className={styles.sectionCount}>共 {formatCount(userTotal)} 人</span></div>
          <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>用户</th><th>工作区</th><th>任务使用</th><th>最近登录</th></tr></thead><tbody>{users.length === 0 ? <tr><td colSpan={4} className={styles.tableEmpty}>暂无用户数据</td></tr> : users.map((user) => <tr key={user.id}><td><strong>{user.display_name}</strong><small>{user.email ?? "未提供邮箱"}</small><StatusPill status={userStatusLabel(user.status)} warning={user.status !== "active"} /></td><td>{user.active_workspace_count}/{user.workspace_count}<small>活跃 / 全部工作区</small></td><td><strong>{formatCount(user.workspace_jobs_total + user.crawl_tasks_total)}</strong><small>生成 {user.workspace_jobs_running} 运行中 · 抓取 {user.crawl_tasks_failed} 失败</small></td><td>{formatTime(user.last_login_at)}<small>活动 {formatTime(user.last_activity_at)}</small></td></tr>)}</tbody></table></div>
        </article>
        <article className={styles.section}>
          <div className={styles.sectionHeading}><div><span className={styles.sectionEyebrow}>WORKSPACE USAGE</span><h2>工作区</h2><p>从成员、生成任务、抓取任务和账号状态定位问题范围。</p></div><span className={styles.sectionCount}>共 {formatCount(workspaceTotal)} 个</span></div>
          <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>工作区</th><th>成员</th><th>任务</th><th>账号 / 活动</th></tr></thead><tbody>{workspaces.length === 0 ? <tr><td colSpan={4} className={styles.tableEmpty}>暂无工作区数据</td></tr> : workspaces.map((workspace) => <tr key={workspace.id}><td><strong>{workspace.name}</strong><small>{workspace.id}</small><StatusPill status={workspaceStatusLabel(workspace.status)} warning={workspace.status !== "active"} /></td><td>{workspace.active_member_count}/{workspace.member_count}<small>活跃 / 全部成员</small></td><td><strong>{formatCount(workspace.jobs_total + workspace.crawl_tasks_total)}</strong><small>生成 {workspace.jobs_running} 运行中 · 抓取 {workspace.crawl_tasks_failed} 失败</small></td><td>{workspace.account_count} 个账号{workspace.needs_relogin_count ? <small className={styles.warningText}>{workspace.needs_relogin_count} 个需重新登录</small> : <small>账号状态正常</small>}<small>活动 {formatTime(workspace.last_activity_at)}</small></td></tr>)}</tbody></table></div>
        </article>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeading}><div><span className={styles.sectionEyebrow}>SESSION CENTER</span><h2>电商平台登录状态</h2><p>仅展示账号状态和会话占用情况，不返回 Cookie、Profile 路径或任务请求内容。</p></div>{totalRelogin > 0 ? <span className={styles.warningBadge}><AlertTriangle size={15} /> {totalRelogin} 个账号需要重新登录</span> : <span className={styles.readyBadge}><CircleCheck size={15} /> 当前无待处理登录</span>}</div>
        <div className={styles.platformGrid}>
          {sessions.map(([platform, data]) => <article className={styles.platformCard} key={platform}>
            <div className={styles.platformHeading}><div><strong>{platformMeta[platform]?.label ?? platform}</strong><small>{data.account_count} 个账号 · {data.busy_count} 个 Profile 使用中</small></div><span className={data.needs_relogin_count ? styles.statusNeedsLogin : styles.statusReady}>{data.needs_relogin_count ? `${data.needs_relogin_count} 待处理` : "状态正常"}</span></div>
            <div className={styles.platformStats}><span>已登录 <b>{data.ready_count}</b></span><span>活跃 <b>{data.active_count}</b></span><span>需登录 <b>{data.needs_relogin_count}</b></span></div>
            <div className={styles.accountList}>
              {data.accounts.length === 0 ? <p className={styles.empty}>暂无已配置账号</p> : data.accounts.map((account) => <div className={styles.accountRow} key={account.id}><div className={styles.accountMain}><span className={`${styles.dot} ${account.needs_relogin ? styles.dotWarn : account.login_state === "ready" ? styles.dotReady : ""}`} /><div><strong>{account.label}</strong><small>{loginLabel(account)} · 最近登录：{formatTime(account.last_login_at)}</small></div></div><div className={styles.accountAside}>{account.profile_busy ? <span className={styles.busy}>使用中</span> : null}{account.needs_relogin ? <span className={styles.relogin}>重新登录</span> : null}</div></div>)}
            </div>
          </article>)}
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeading}><div><span className={styles.sectionEyebrow}>ACCOUNT OPERATIONS</span><h2>电商账号运维（只读）</h2><p>展示最近任务、失败 / 风控次数和当前 Profile 租约；此处不提供浏览器控制或账号状态修改。</p></div><span className={styles.sectionCount}>共 {formatCount(accountTotal)} 个账号</span></div>
        <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>账号</th><th>状态</th><th>任务统计</th><th>当前租约</th><th>最近任务</th></tr></thead><tbody>{operationalAccounts.length === 0 ? <tr><td colSpan={5} className={styles.tableEmpty}>暂无国内电商账号</td></tr> : operationalAccounts.map((account) => { const recent = account.recent_tasks[0]; return <tr key={account.id}><td><strong>{account.label}</strong><small>{platformMeta[account.platform]?.shortLabel ?? account.platform} · {account.workspace_name ?? account.workspace_id}</small></td><td><span className={account.needs_relogin ? styles.logStatusFailed : styles.logStatus}>{account.needs_relogin ? "需重新登录" : account.login_state === "ready" ? "已登录" : account.status}</span><small>{account.status === "active" ? "账号活跃" : account.status === "paused" ? "账号已暂停" : "账号已停用"}</small></td><td><strong>{formatCount(account.task_count)} 个任务</strong><small>失败 {account.failed_task_count} · 风控 {account.risk_control_count}</small></td><td>{account.profile_busy ? <><strong className={styles.warningText}>使用中</strong><small>{account.active_lease?.task_id ?? "任务未知"} · 到期 {formatTime(account.active_lease?.expires_at ?? null)}</small></> : account.lease_state === "expired" ? <><strong className={styles.warningText}>租约已过期</strong><small>{account.last_lease?.task_id ?? "任务未知"} · 到期 {formatTime(account.last_lease?.expires_at ?? null)}</small></> : <><strong>空闲</strong><small>当前没有活跃租约</small></>}</td><td>{recent ? <><strong>{recent.status} · {recent.stage ?? "未分阶段"}</strong><small>{recent.error_code ?? "无错误"} · {formatTime(recent.finished_at ?? recent.created_at)}</small></> : <span className={styles.empty}>暂无任务</span>}</td></tr>; })}</tbody></table></div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeading}>
          <div><span className={styles.sectionEyebrow}>TASK LOGS</span><h2>生成 / 抓取日志</h2><p>只展示任务状态、阶段、进度、稳定错误码和脱敏信息，不返回商品地址、请求参数或底层堆栈。</p></div>
          <span className={styles.sectionCount}>共 {formatCount(logTotal)} 条</span>
        </div>
        <div className={styles.logFilters}>
          <label>类型<select value={logKind} onChange={(event) => setLogKind(event.target.value as "all" | "generation" | "crawl")}><option value="all">全部</option><option value="generation">生成</option><option value="crawl">抓取</option></select></label>
          <label>状态<input value={logStatus} onChange={(event) => setLogStatus(event.target.value)} placeholder="例如 failed" /></label>
          <label>平台<select value={logPlatform} onChange={(event) => setLogPlatform(event.target.value)}><option value="">全部平台</option><option value="taobao">淘宝</option><option value="1688">1688</option><option value="jd">京东</option><option value="pinduoduo">拼多多</option></select></label>
          <button className={styles.secondary} type="button" onClick={() => void load(true)} disabled={refreshing}>应用筛选</button>
        </div>
        <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>任务</th><th>工作区</th><th>状态</th><th>错误 / 时间</th><th>操作</th></tr></thead><tbody>{logs.length === 0 ? <tr><td colSpan={5} className={styles.tableEmpty}>暂无符合条件的任务日志</td></tr> : logs.map((log) => <tr key={`${log.kind}-${log.id}`}><td><strong>{logKindLabel(log)} · {logPlatformLabel(log.platform)}</strong><small>{log.id}</small></td><td><strong>{log.workspace_name ?? "未知工作区"}</strong><small>{log.workspace_id}</small></td><td><span className={log.status === "failed" ? styles.logStatusFailed : styles.logStatus}>{log.status}</span><small>{log.stage ?? "未分阶段"} · {log.progress}% · {log.event_count} 个事件</small></td><td>{log.error_code ? <strong className={styles.warningText}>{log.error_code}</strong> : <strong>无错误</strong>}<small>{log.error_message ?? "—"} · {formatTime(log.finished_at ?? log.created_at)}</small></td><td><button className={styles.detailButton} type="button" onClick={() => void openLog(log)}>查看详情</button></td></tr>)}</tbody></table></div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeading}><div><span className={styles.sectionEyebrow}>NEXT MODULES</span><h2>后续管理员模块规划</h2><p>本阶段先保持只读和边界清晰，后续按模块逐步增加能力。</p></div></div>
        <div className={styles.plannedGrid}><div><strong>第三阶段：生成 / 抓取日志</strong><p>已提供脱敏事件时间线、错误码和筛选查询，不直接暴露原始 payload。</p></div><div><strong>第四阶段：账号运维操作</strong><p>当前已提供账号任务、失败 / 风控统计和租约只读信息；重新登录、暂停和恢复仍需安全授权与操作审计。</p></div><div><strong>部署与可靠性</strong><p>独立 Worker、PostgreSQL、Redis、对象存储和 Profile 持久卷仍需按部署计划验收。</p></div></div>
      </section>
      <p className={styles.generatedAt}>数据生成于 {formatTime(overview.generated_at)} · 最近 7 天新增用户：{formatCount(overview.users.recent_signups)}</p>
    </div>
    {selectedLog || detailLoading || detailError ? <LogDetailDialog detail={selectedLog} loading={detailLoading} error={detailError} onClose={() => { setSelectedLog(null); setDetailError(null); }} /> : null}
  </AppShell>;
}
