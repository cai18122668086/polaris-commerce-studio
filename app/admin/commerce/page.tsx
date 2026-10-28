"use client";

import { Loader2, RefreshCw, Search, ShieldCheck, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { AdminShell } from "@/components/admin/admin-shell";
import { commerceRequest, listCommerce, parseYuan, type Audit, type CommerceAccess, type CommerceData, type CommerceOverview, type CommerceTab, type Customer, type GenerationJob, type Order, type Refund, type SupportCase } from "@/features/admin/api/commerce";
import type { AdminPagination } from "@/features/admin/api/admin";
import styles from "./page.module.css";

const emptyData: CommerceData = { customers: [], orders: [], ledger: [], jobs: [], cases: [], refunds: [], audit: [] };
const navigation: Array<[CommerceTab, string]> = [["customers", "客户管理"], ["orders", "充值订单"], ["ledger", "积分流水"], ["jobs", "任务与售后"], ["refunds", "退款处理"], ["audit", "操作审计"]];
const labels: Record<string, string> = { pending: "待付款", paid: "已到账", processing: "处理中", completed: "已完成", rejected: "已驳回", failed: "失败", partial: "部分成功", cancelled: "已取消", queued: "排队中", planning: "规划中", open: "待处理", in_progress: "跟进中", resolved: "已解决", purchase: "充值", membership: "会员发放", renewal: "待生效续费", reserve: "任务冻结", settle: "生成消费", release: "任务释放", expire: "积分到期", gift: "人工赠送", compensation: "售后补偿", refund_hold: "退款冻结", refund: "退款扣回", refund_release: "退款释放" };
const money = (fen: number) => `¥${(fen / 100).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const time = (value: string | null | undefined) => value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "—";
const signed = (n: number) => `${n > 0 ? "+" : ""}${n.toLocaleString("zh-CN")}`;
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "操作失败，请稍后重试。";

type Drawer = { kind: "customer"; item: Customer } | { kind: "order"; item: Order } | { kind: "job"; item: GenerationJob } | { kind: "refund"; item: Refund } | { kind: "case"; item: SupportCase } | { kind: "audit"; item: Audit };
const blankForm = { note: "", kind: "gift", credits: "", reason: "", jobId: "", amount: "", issue: "", resolution: "", caseStatus: "in_progress", receipt: "", confirmOrder: "", verified: false, resultStatus: "completed", cancelMembership: false };

function Badge({ value }: { value: string }) {
  const tone = ["paid", "completed", "resolved"].includes(value) ? styles.good : ["failed", "rejected"].includes(value) ? styles.bad : ["processing", "open", "partial", "in_progress"].includes(value) ? styles.warn : "";
  return <span className={`${styles.badge} ${tone}`}>{labels[value] ?? value}</span>;
}

function Details({ items }: { items: Array<[string, ReactNode]> }) {
  return <dl className={styles.details}>{items.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? "—"}</dd></div>)}</dl>;
}

function Modal({ title, subtitle, children, close, busy }: { title: string; subtitle: string; children: ReactNode; close: () => void; busy: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close(); }, []);
  return <dialog ref={ref} className={styles.dialog} onCancel={(event) => { if (busy) event.preventDefault(); else close(); }} aria-labelledby="commerce-dialog-title">
    <div className={styles.dialogHeader}><div><h2 id="commerce-dialog-title">{title}</h2><p>{subtitle}</p></div><button type="button" className={styles.button} disabled={busy} onClick={close} aria-label="关闭详情"><X size={16} /></button></div>
    <div className={styles.dialogBody}>{children}</div>
  </dialog>;
}

export default function CommercePage() {
  const [tab, setTab] = useState<CommerceTab>("customers");
  const [access, setAccess] = useState<CommerceAccess | null>(null);
  const [overview, setOverview] = useState<CommerceOverview | null>(null);
  const [data, setData] = useState(emptyData);
  const [pagination, setPagination] = useState<AdminPagination>({ total: 0, limit: 20, offset: 0, has_more: false });
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [scope, setScope] = useState<{ id: string; label: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [drawer, setDrawer] = useState<Drawer | null>(null);
  const [form, setForm] = useState(blankForm);
  const [mode, setMode] = useState("");
  const [dialogError, setDialogError] = useState("");
  const requestKey = useRef("");
  const requestVersion = useRef(0);
  const can = (permission: string) => access?.permissions.includes(permission) ?? false;

  const load = useCallback(async (signal?: AbortSignal) => {
    const version = ++requestVersion.current;
    try {
      const [allowed, metrics, result] = await Promise.all([
        commerceRequest<CommerceAccess>("/access", { signal }), commerceRequest<CommerceOverview>("/overview", { signal }),
        listCommerce(tab, { limit: 20, offset, workspace_id: tab === "customers" ? undefined : scope?.id, search: ["cases", "audit"].includes(tab) ? undefined : search, status: ["orders", "jobs", "refunds"].includes(tab) ? status : undefined, entry_type: tab === "ledger" ? status : undefined }, signal),
      ]);
      if (signal?.aborted || version !== requestVersion.current) return;
      setAccess(allowed); setOverview(metrics); setData((current) => ({ ...current, [tab]: result.items })); setPagination(result.pagination); setError("");
    } catch (cause) { if (!signal?.aborted && version === requestVersion.current) setError(errorText(cause)); }
    finally { if (!signal?.aborted && version === requestVersion.current) setLoading(false); }
  }, [offset, scope, search, status, tab]);

  useEffect(() => {
    const controller = new AbortController();
    // This effect fetches external data; all state updates follow the request.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  function selectTab(next: CommerceTab) { if (next === "customers") setScope(null); setTab(next); setOffset(0); setStatus(""); setQuery(""); setSearch(""); setLoading(true); }
  function open(next: Drawer) {
    setDrawer(next); setMode(""); setDialogError(""); requestKey.current = crypto.randomUUID();
    setForm({ ...blankForm, note: next.kind === "customer" ? next.item.note : "", jobId: next.kind === "job" ? next.item.id : "", amount: next.kind === "order" ? (next.item.refundable_fen / 100).toFixed(2) : "", credits: next.kind === "order" ? String(next.item.refundable_credits) : "", issue: next.kind === "case" ? next.item.issue : "", resolution: next.kind === "case" ? next.item.resolution : "", caseStatus: next.kind === "case" ? next.item.status : "in_progress" });
  }
  function related(workspace: string, label: string, next: CommerceTab) { setScope({ id: workspace, label }); setDrawer(null); selectTab(next); }
  function update(field: keyof typeof blankForm, value: string | boolean) { setForm((current) => ({ ...current, [field]: value })); requestKey.current = crypto.randomUUID(); }
  async function perform(operation: () => Promise<unknown>, success: string, close = true) {
    setBusy(true); setDialogError("");
    try { await operation(); setMessage(success); if (close) setDrawer(null); await load(); }
    catch (cause) { setDialogError(errorText(cause)); }
    finally { setBusy(false); }
  }
  function searchSubmit(event: FormEvent) { event.preventDefault(); setSearch(query.trim()); setOffset(0); setLoading(true); }
  function submit(event: FormEvent) {
    event.preventDefault(); if (!drawer || busy) return;
    const post = (path: string, body: unknown, method = "POST") => commerceRequest(path, { method, body, requestKey: requestKey.current });
    if (drawer.kind === "customer" && mode === "note") void perform(() => post(`/customers/${drawer.item.workspace_id}/note`, { note: form.note }, "PATCH"), "售后备注已保存。");
    if (drawer.kind === "customer" && mode === "adjust") {
      if (!/^\d+$/.test(form.credits) || Number(form.credits) <= 0) { setDialogError("请填写正整数积分。"); return; }
      void perform(() => post(`/customers/${drawer.item.workspace_id}/adjustments`, { kind: form.kind, credits: Number(form.credits), reason: form.reason, job_id: form.jobId.trim() || null }), "积分已入账，操作与原因已记入审计。");
    }
    if (drawer.kind === "order" && mode === "refund") {
      const amount = parseYuan(form.amount);
      if (amount === null || amount <= 0 || !/^\d+$/.test(form.credits)) { setDialogError("请填写有效的退款金额和非负整数积分。"); return; }
      void perform(() => post(`/orders/${drawer.item.id}/refunds`, { amount_fen: amount, credits: Number(form.credits), reason: form.reason, cancel_future_membership: form.cancelMembership }), "退款申请已登记，对应积分已冻结。请完成真实人工退款后核验凭证。");
    }
    if (drawer.kind === "job") void perform(() => post("/cases", { workspace_id: drawer.item.workspace_id, job_id: drawer.item.id, issue: form.issue }), "售后记录已建立。");
    if (drawer.kind === "case") void perform(() => post(`/cases/${drawer.item.id}`, { status: form.caseStatus, resolution: form.resolution }, "PATCH"), "售后处理结果已保存。");
    if (drawer.kind === "refund") void perform(() => post(`/refunds/${drawer.item.id}/resolve`, { status: form.resultStatus, confirm_order_id: form.confirmOrder.trim(), receipt_reference: form.receipt.trim(), result_note: form.reason, receipt_verified: form.verified }), form.resultStatus === "completed" ? "人工退款已确认，原订单对应积分已扣回。" : "退款已驳回，冻结积分已释放。");
  }

  const filters = tab === "orders" ? ["pending", "paid"] : tab === "refunds" ? ["processing", "completed", "rejected"] : tab === "jobs" ? ["failed", "partial", "completed", "processing", "queued", "cancelled"] : tab === "ledger" ? ["purchase", "membership", "renewal", "reserve", "settle", "release", "expire", "gift", "compensation", "refund_hold", "refund", "refund_release"] : [];
  const title = drawer ? { customer: "客户详情", order: "充值订单", job: "生成任务与售后", refund: "人工退款记录", case: "售后跟进", audit: "操作审计" }[drawer.kind] : "";
  const subtitle = drawer ? (drawer.kind === "customer" ? drawer.item.workspace_id : String(drawer.item.id)) : "";
  const detailButton = (value: Drawer, label = "查看详情") => <button type="button" className={styles.button} onClick={() => open(value)}>{label}</button>;

  return <AdminShell><div className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>CUSTOMER OPERATIONS</span><h1>客户与支付管理</h1><p>从客户、订单到积分与任务，完整记录每一次售后处理。</p></div><div className={styles.actions}><span className={`${styles.badge} ${styles.good}`}><ShieldCheck size={12} /> {access?.global_enforcement_enabled ? "全平台积分计费已开启" : "按工作区开放"}</span><button className={styles.button} disabled={loading} onClick={() => { setLoading(true); void load(); }}><RefreshCw size={14} className={loading ? styles.spin : ""} />刷新数据</button></div></header>
    {error && <div className={styles.error} role="alert">{error}</div>}
    {message && <div className={styles.message} role="status">{message}</div>}
    {overview && <section className={styles.metrics} aria-label="客户运营概览"><div className={styles.metric}><small>客户工作区</small><strong>{overview.customers}</strong><em>积分按工作区独立记账</em></div><div className={styles.metric}><small>累计确认到账</small><strong>{money(overview.paid_fen)}</strong><em>已退款 {money(overview.refunded_fen)}</em></div><div className={styles.metric}><small>待核验退款</small><strong>{overview.pending_refunds}</strong><em>人工退款后核验原交易凭证</em></div><div className={styles.metric}><small>待处理售后</small><strong>{overview.open_cases}</strong><em>关联原任务并记录处理结果</em></div></section>}
    {scope && tab !== "customers" && <div className={styles.workspace}><span>当前客户：{scope.label} <small className={styles.mono}>{scope.id}</small></span><button className={styles.button} onClick={() => { setScope(null); setOffset(0); setLoading(true); }}>查看全部客户</button></div>}
    <section className={styles.panel}>
      <nav className={styles.tabs} aria-label="客户运营模块">{navigation.map(([key, label]) => <button type="button" key={key} className={`${styles.tab} ${tab === key || key === "jobs" && tab === "cases" ? styles.active : ""}`} aria-current={tab === key || key === "jobs" && tab === "cases" ? "page" : undefined} onClick={() => selectTab(key)}>{label}</button>)}</nav>
      <div className={styles.toolbar}>
        {!["cases", "audit"].includes(tab) && <form onSubmit={searchSubmit} className={styles.search}><input aria-label="搜索邮箱或关联编号" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tab === "customers" ? "按客户邮箱、姓名或工作区搜索" : tab === "ledger" ? "按客户邮箱、任务号或流水说明搜索" : "按客户邮箱、订单号或任务号搜索"} /><button className={styles.primary} type="submit"><Search size={15} />搜索</button></form>}
        {filters.length > 0 && <select aria-label="筛选状态或流水类型" value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0); setLoading(true); }}><option value="">{tab === "ledger" ? "全部流水类型" : "全部状态"}</option>{filters.map((value) => <option key={value} value={value}>{labels[value] ?? value}</option>)}</select>}
        {["jobs", "cases"].includes(tab) && <div className={styles.actions}><button className={tab === "jobs" ? styles.primary : styles.button} onClick={() => selectTab("jobs")}>生成任务</button><button className={tab === "cases" ? styles.primary : styles.button} onClick={() => selectTab("cases")}>售后记录</button></div>}
        {tab === "audit" && <span className={styles.muted}>记录操作人、关联对象、原因与处理时间。</span>}
      </div>
      {loading ? <div className={styles.empty}><Loader2 size={20} className={styles.spin} /> 正在载入真实数据…</div> : !access ? <div className={styles.empty}>请使用具有客户与支付权限的管理员账号。</div> : data[tab].length === 0 ? <div className={styles.empty}>当前筛选范围内暂无记录。</div> : <div className={styles.tableWrap}><table className={styles.table}>
        <thead><tr>{(tab === "customers" ? ["客户", "可用 / 冻结积分", "累计充值 / 消费", "最近使用", "开放状态 / 备注", "操作"] : tab === "orders" ? ["订单 / 客户", "套餐", "实付 / 积分", "支付与退款", "网关 / 到账时间", "操作"] : tab === "ledger" ? ["类型 / 说明", "客户工作区", "余额 / 冻结变化", "变更后余额", "关联订单 / 任务", "时间"] : tab === "jobs" ? ["任务 / 客户", "生成类型", "状态 / 成功张数", "预留 / 实际扣分", "失败原因", "操作"] : tab === "cases" ? ["售后编号", "关联任务", "问题", "处理状态 / 结果", "最近更新", "操作"] : tab === "refunds" ? ["原订单 / 客户", "退款 / 扣回积分", "处理状态", "退款凭证", "处理时间", "操作"] : ["时间", "操作人", "操作", "客户工作区", "关联对象", "详情"]).map((heading) => <th key={heading}>{heading}</th>)}</tr></thead>
        <tbody>
          {tab === "customers" && data.customers.map((row) => <tr key={row.workspace_id}><td><strong>{row.email ?? row.display_name ?? row.user_id}</strong><small>{row.workspace_name}</small><small>{row.workspace_id}</small></td><td><strong>{row.available_credits.toLocaleString()} / {row.reserved_credits.toLocaleString()}</strong><small>总余额 {row.balance_credits}</small></td><td><strong>{money(row.paid_fen)}</strong><small>累计消费 {row.consumed_credits} 分</small></td><td>{time(row.last_used_at)}<small>最近登录 {time(row.last_login_at)}</small></td><td><span className={`${styles.badge} ${row.enforcement_enabled ? styles.good : ""}`}>{row.enforcement_enabled ? "已开放" : "未开放"}</span><small>{row.note || "暂无售后备注"}</small></td><td>{detailButton({ kind: "customer", item: row }, "管理客户")}</td></tr>)}
          {tab === "orders" && data.orders.map((row) => <tr key={row.id}><td><strong>{row.email ?? row.workspace_id}</strong><small>{row.id}</small></td><td><strong>{row.package_name}</strong><small>{row.product_kind === "membership" ? `${row.months} 个月会员，按月发分` : "积分包"}</small></td><td><strong>{money(row.amount_fen)} / {row.credits} 分</strong><small>赠送 {row.bonus_credits === null ? "套餐未单独拆分" : `${row.bonus_credits} 分`}</small></td><td><Badge value={row.status} /><small>已退款 {money(row.refunded_fen)}{row.processing_refund_fen ? ` · 处理中 ${money(row.processing_refund_fen)}` : ""}</small></td><td><small>{row.gateway_trade_no ?? "尚无到账网关单号"}</small>{time(row.paid_at)}</td><td>{detailButton({ kind: "order", item: row })}</td></tr>)}
          {tab === "ledger" && data.ledger.map((row) => <tr key={row.id}><td><Badge value={row.entry_type} /><small>#{row.id} · {row.description}</small></td><td><small>{row.workspace_id}</small></td><td><strong>{signed(row.delta_balance_credits)} 分</strong><small>冻结 {signed(row.delta_reserved_credits)} 分</small></td><td>{row.balance_after_credits}<small>冻结 {row.reserved_after_credits}</small></td><td><small>{row.purchase_id ?? row.job_id ?? row.adjustment_id ?? row.refund_id ?? "历史流水未记录关联编号"}</small>{row.job_id && row.purchase_id && <small>{row.job_id}</small>}</td><td>{time(row.created_at)}</td></tr>)}
          {tab === "jobs" && data.jobs.map((row) => <tr key={row.id}><td><strong>{row.email ?? row.workspace_id}</strong><small>{row.display_name ?? row.id}</small><small>{row.id}</small></td><td>{row.type}</td><td><Badge value={row.status} /><small>成功 {row.succeeded_item_count} / {row.expected_item_count} 张</small></td><td><strong>{row.estimated_credits ?? "—"} / {row.actual_credits ?? "未结算"}</strong></td><td><small>{row.error_code ?? "—"}</small><small>{row.error_message ?? "暂无失败原因"}</small></td><td>{detailButton({ kind: "job", item: row }, "任务售后")}</td></tr>)}
          {tab === "cases" && data.cases.map((row) => <tr key={row.id}><td><small>{row.id}</small><small>{row.workspace_id}</small></td><td><small>{row.job_id ?? "客户一般问题"}</small></td><td><small>{row.issue}</small></td><td><Badge value={row.status} /><small>{row.resolution || "尚未记录处理结果"}</small></td><td>{time(row.updated_at)}</td><td>{detailButton({ kind: "case", item: row }, "跟进处理")}</td></tr>)}
          {tab === "refunds" && data.refunds.map((row) => <tr key={row.id}><td><strong>{row.email ?? row.workspace_id}</strong><small>{row.purchase_id}</small><small>{row.id}</small></td><td><strong>{money(row.amount_fen)} / {row.credits} 分</strong><small>{row.reason}</small></td><td><Badge value={row.status} /><small>人工审核退款</small></td><td><small>{row.receipt_reference ?? "待人工退款并核验"}</small><small>{row.result_note}</small></td><td>{time(row.confirmed_at ?? row.created_at)}</td><td>{detailButton({ kind: "refund", item: row }, row.status === "processing" ? "核验处理" : "查看记录")}</td></tr>)}
          {tab === "audit" && data.audit.map((row) => <tr key={row.id}><td>{time(row.occurred_at)}</td><td><small>{row.actor_user_id}</small></td><td>{row.action.replace("commerce.", "")}</td><td><small>{row.workspace_id}</small></td><td><small>{row.resource_id}</small></td><td>{detailButton({ kind: "audit", item: row })}</td></tr>)}
        </tbody>
      </table></div>}
      <footer className={styles.pagination}><span>共 {pagination.total} 条 · 每页 20 条</span><button className={styles.button} disabled={loading || offset === 0} onClick={() => { setOffset(Math.max(0, offset - 20)); setLoading(true); }}>上一页</button><span>第 {Math.floor(offset / 20) + 1} 页</span><button className={styles.button} disabled={loading || !pagination.has_more} onClick={() => { setOffset(offset + 20); setLoading(true); }}>下一页</button></footer>
    </section>
    {drawer && <Modal title={title} subtitle={subtitle} busy={busy} close={() => setDrawer(null)}>
      {dialogError && <div className={styles.error} role="alert">{dialogError}</div>}
      {drawer.kind === "customer" && <><Details items={[["客户邮箱", drawer.item.email], ["工作区", drawer.item.workspace_name], ["可用积分", drawer.item.available_credits], ["冻结积分", drawer.item.reserved_credits], ["累计充值", money(drawer.item.paid_fen)], ["累计消费", `${drawer.item.consumed_credits} 分`]]} /><div className={styles.actions}>{(["orders", "ledger", "jobs"] as CommerceTab[]).map((next) => <button className={styles.button} key={next} onClick={() => related(drawer.item.workspace_id, drawer.item.email ?? drawer.item.workspace_name, next)}>查看{next === "orders" ? "订单" : next === "ledger" ? "流水" : "任务"}</button>)}{can("support:manage") && <button className={styles.button} onClick={() => setMode("note")}>编辑备注</button>}{can("credits:manage") && <button className={styles.primary} onClick={() => setMode("adjust")}>赠送 / 补偿积分</button>}</div>{!mode && <p className={styles.muted}>{drawer.item.note || "暂无售后备注"}</p>}</>}
      {drawer.kind === "order" && <><Details items={[["套餐", drawer.item.package_name], ["实付金额", money(drawer.item.amount_fen)], ["支付状态", <Badge key="status" value={drawer.item.status} />], ["网关单号", drawer.item.gateway_trade_no], ["到账时间", time(drawer.item.paid_at)], ["已发放积分", drawer.item.issued_credits], ["已消费或到期合计", drawer.item.used_or_expired_credits], ["本单剩余 / 冻结", `${drawer.item.remaining_credits} / ${drawer.item.held_credits}`], ["已退款 / 处理中", `${money(drawer.item.refunded_fen)} / ${money(drawer.item.processing_refund_fen)}`], ["原到账流水", drawer.item.ledger_entry_id]]} /><p className={styles.muted}>历史积分来源未分开记录消费和到期原因时，按合计展示；退款金额由管理员审核，不自动按剩余积分折算。</p><div className={styles.actions}>{can("credits:manage") && <button className={styles.button} disabled={busy} onClick={() => void perform(async () => { const result = await commerceRequest<{ order: Order; gateway_paid: boolean }>(`/orders/${drawer.item.id}/reconcile`, { method: "POST" }); setDrawer({ kind: "order", item: result.order }); }, "已完成网关查单核对。", false)}>查单核对到账</button>}{can("refunds:manage") && drawer.item.status === "paid" && drawer.item.refundable_fen > 0 && !drawer.item.processing_refund_fen && <button className={styles.danger} onClick={() => setMode("refund")}>登记人工退款</button>}</div></>}
      {drawer.kind === "job" && <><Details items={[["任务状态", <Badge key="status" value={drawer.item.status} />], ["客户", drawer.item.email], ["实际扣分", drawer.item.actual_credits ?? "尚未结算"], ["成功 / 失败", `${drawer.item.succeeded_item_count} / ${drawer.item.failed_item_count}`], ["失败代码", drawer.item.error_code], ["失败说明", drawer.item.error_message]]} /><button className={styles.button} onClick={() => related(drawer.item.workspace_id, drawer.item.email ?? drawer.item.workspace_id, "cases")}>查看客户售后记录</button></>}
      {drawer.kind === "refund" && <Details items={[["原订单", drawer.item.purchase_id], ["退款金额", money(drawer.item.amount_fen)], ["扣回积分", drawer.item.credits], ["处理状态", <Badge key="status" value={drawer.item.status} />], ["原申请原因", drawer.item.reason], ["凭证编号", drawer.item.receipt_reference], ["处理结果", drawer.item.result_note], ["网关结果", drawer.item.gateway_result], ["处理人", drawer.item.confirmed_by_user_id], ["处理时间", time(drawer.item.confirmed_at)]]} />}
      {drawer.kind === "case" && <Details items={[["原任务", drawer.item.job_id], ["售后状态", <Badge key="status" value={drawer.item.status} />], ["客户问题", drawer.item.issue], ["现有处理结果", drawer.item.resolution || "待跟进"]]} />}
      {drawer.kind === "audit" && <Details items={[["操作人", drawer.item.actor_user_id], ["时间", time(drawer.item.occurred_at)], ["关联对象", drawer.item.resource_id], ["操作", drawer.item.action], ...Object.entries(drawer.item.details).map(([key, value]): [string, ReactNode] => [key, typeof value === "object" ? JSON.stringify(value) : String(value)])]} />}
      <form className={styles.form} onSubmit={submit} hidden={!(drawer.kind === "customer" && mode || drawer.kind === "order" && mode === "refund" || drawer.kind === "job" && can("support:manage") || drawer.kind === "case" && can("support:manage") || drawer.kind === "refund" && drawer.item.status === "processing" && can("refunds:manage"))}>
        {drawer.kind === "customer" && mode === "note" && <label>售后备注<textarea value={form.note} maxLength={4000} onChange={(event) => update("note", event.target.value)} /></label>}
        {drawer.kind === "customer" && mode === "adjust" && <><h3>确认积分调整</h3><p>积分直接发放到当前客户工作区。每次操作记录原因和操作人。</p><label>操作类型<select value={form.kind} onChange={(event) => update("kind", event.target.value)}><option value="gift">人工赠送</option><option value="compensation">任务售后补偿</option></select></label><label>积分数量<input required type="number" min="1" max="100000" step="1" value={form.credits} onChange={(event) => update("credits", event.target.value)} /></label><label>关联任务号{form.kind === "compensation" ? "（必填）" : "（可选）"}<input required={form.kind === "compensation"} value={form.jobId} onChange={(event) => update("jobId", event.target.value)} /></label><label>具体原因<textarea required minLength={3} maxLength={500} value={form.reason} onChange={(event) => update("reason", event.target.value)} /></label></>}
        {drawer.kind === "order" && mode === "refund" && <><h3>登记人工退款并冻结积分</h3><p>可登记金额上限 {money(drawer.item.refundable_fen)}，本单当前可扣回 {drawer.item.refundable_credits} 分。登记后先冻结，实际转账需人工完成。</p><label>本次退款金额（元）<input required inputMode="decimal" value={form.amount} onChange={(event) => update("amount", event.target.value)} /></label><label>本次扣回积分<input required type="number" min="0" max={drawer.item.refundable_credits} step="1" value={form.credits} onChange={(event) => update("credits", event.target.value)} /></label>{drawer.item.product_kind === "membership" && <label className={styles.check}><input type="checkbox" checked={form.cancelMembership} required onChange={(event) => update("cancelMembership", event.target.checked)} />退款成功后终止该订单后续会员发放，并扣回全部未使用积分</label>}<label>审核原因<textarea required minLength={3} maxLength={500} value={form.reason} onChange={(event) => update("reason", event.target.value)} /></label></>}
        {drawer.kind === "job" && <><h3>建立任务售后记录</h3><label>客户问题与处理方向<textarea required minLength={3} maxLength={4000} value={form.issue} onChange={(event) => update("issue", event.target.value)} /></label></>}
        {drawer.kind === "case" && <><label>处理状态<select value={form.caseStatus} onChange={(event) => update("caseStatus", event.target.value)}><option value="open">待处理</option><option value="in_progress">跟进中</option><option value="resolved">已解决</option></select></label><label>处理结果<textarea required={form.caseStatus === "resolved"} minLength={form.caseStatus === "resolved" ? 3 : undefined} maxLength={4000} value={form.resolution} onChange={(event) => update("resolution", event.target.value)} /></label></>}
        {drawer.kind === "refund" && <><h3>核验人工退款结果</h3><label>处理决定<select value={form.resultStatus} onChange={(event) => update("resultStatus", event.target.value)}><option value="completed">确认已人工退款，扣回原冻结积分</option><option value="rejected">驳回申请，释放冻结积分</option></select></label><label>输入完整原订单号确认<input required value={form.confirmOrder} onChange={(event) => update("confirmOrder", event.target.value)} autoComplete="off" /></label>{form.resultStatus === "completed" && <><label>真实退款交易号或凭证编号<input required minLength={6} maxLength={500} value={form.receipt} onChange={(event) => update("receipt", event.target.value)} /></label><label className={styles.check}><input type="checkbox" required checked={form.verified} onChange={(event) => update("verified", event.target.checked)} />我已核验收款对象、金额及真实退款凭证，确认人工退款完成</label></>}<label>核验或驳回说明<textarea required minLength={3} maxLength={500} value={form.reason} onChange={(event) => update("reason", event.target.value)} /></label></>}
        <button className={drawer.kind === "refund" || mode === "refund" ? styles.danger : styles.primary} type="submit" disabled={busy}>{busy ? "正在提交…" : mode === "adjust" ? "确认发放并记录审计" : mode === "refund" ? "确认登记并冻结积分" : drawer.kind === "refund" ? "确认处理结果" : "保存记录"}</button>
      </form>
    </Modal>}
  </div></AdminShell>;
}
