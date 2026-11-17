"use client";

import Image from "next/image";
import { ArrowUpRight, Check, Clock3, Gift, MessageCircle, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useBodyScrollLock } from "@/lib/hooks/use-body-scroll-lock";
import { usePublicGrowth, useRewards } from "@/features/billing/api/rewards";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { withReturnTo } from "@/lib/auth/return-to";
import { useRouter } from "next/navigation";
import { apiClient } from "@/lib/api/client";
import { errorMessage, unwrapApiResponse } from "@/lib/api/request";
import { WECHAT_SUPPORT_QR, WECHAT_SUPPORT_URL } from "@/lib/customer-support";
import { newcomerDialogBlocks } from "@/lib/newcomer-offer-policy";
import styles from "./welcome-credits.module.css";

const registerHref = withReturnTo("/auth/register", "/account#rewards");
const promptKey = "polaris.welcome-credits.day";

export function WelcomeCreditsBanner({ compact = false }: { compact?: boolean }) {
  const publicGrowth = usePublicGrowth();
  const { workspace } = useWorkspace();
  const router = useRouter();
  const rewards = useRewards(compact ? undefined : workspace?.id);
  const signedIn = Boolean(workspace && !compact);
  const eligible = publicGrowth.data?.welcome_enabled && !signedIn;
  const newcomer = signedIn && rewards.data?.welcome_claimed;
  const canRequestSupport = newcomer && !rewards.data?.support_claimed;
  const showSignedInBanner = signedIn && (newcomer || rewards.data?.checkin_enabled || rewards.data?.referral_enabled);
  const heading = signedIn ? newcomer ? "注册福利" : "每日创作福利" : "注册就送";
  const amount = signedIn ? newcomer ? "50 积分已到账" : "" : "50 积分";
  const subheading = !signedIn || canRequestSupport
    ? "联系客服，再领 50 积分"
    : rewards.data?.checkin_enabled ? "每日签到领积分" : "邀请好友，返赠积分";
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useBodyScrollLock(open && Boolean(eligible));

  useEffect(() => {
    if (compact || !eligible) return;
    const day = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
    let interactedAt = Date.now();
    const defer = () => { interactedAt = Date.now(); };
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible" || Date.now() - interactedAt < 5_000) return;
      if (document.activeElement?.matches("input, textarea, select, [contenteditable=true]")) return;
      if (Array.from(document.querySelectorAll("dialog[open], [aria-modal=true]")).some(newcomerDialogBlocks)) return;
      window.clearInterval(timer);
      try {
        if (localStorage.getItem(promptKey) === day) return;
        localStorage.setItem(promptKey, day);
      } catch { /* Closing the dialog still works with browser storage disabled. */ }
      setOpen(true);
    }, 500);
    window.addEventListener("pointerdown", defer);
    window.addEventListener("keydown", defer);
    window.addEventListener("scroll", defer, true);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("pointerdown", defer);
      window.removeEventListener("keydown", defer);
      window.removeEventListener("scroll", defer, true);
    };
  }, [compact, eligible]);

  useEffect(() => {
    const element = dialog.current;
    if (open && eligible && element && !element.open) element.showModal();
    return () => element?.close();
  }, [open, eligible]);

  if (!eligible && !showSignedInBanner) return null;
  return <>
    <div className={compact ? undefined : styles.preview} data-welcome-credits>
      <section className={compact ? styles.compact : styles.offer} aria-label={signedIn ? "账户福利" : "新用户注册福利"}>
        <div className={styles.copy}><h2>{heading}{amount && <> <span>{amount}</span></>}</h2><p className={styles.headline}>{subheading}</p></div>
        {!compact && <div className={styles.action}><button type="button" onClick={() => router.push(signedIn ? "/account#rewards" : registerHref)}>
          {signedIn ? canRequestSupport ? "领取客服赠分" : "查看福利" : "立即领取"}<ArrowUpRight size={19} />
        </button></div>}
      </section>
    </div>
    {open && eligible && <dialog ref={dialog} className={styles.dialog} aria-labelledby="welcome-credits-title" onCancel={event => { event.preventDefault(); setOpen(false); }}>
      <header className={styles.modalTop}>
        <button type="button" className={styles.close} aria-label="关闭注册福利" onClick={() => setOpen(false)}><X size={23} /></button>
        <h2 id="welcome-credits-title">注册就送 50 积分</h2>
        <p>联系客服，再领 50 积分</p>
      </header>
      <div className={styles.modalBody}>
        <button className={styles.primary} type="button" onClick={() => { setOpen(false); router.push(registerHref); }}>立即注册领取<ArrowUpRight size={21} /></button>
        <button className={styles.secondary} type="button" onClick={() => setOpen(false)}>稍后领取</button>
        <footer className={styles.terms}>新人专享 · 每项奖励限领一次
          <details><summary>领取规则</summary><p>新用户完成邮箱验证后，50 积分自动到账。联系极光商绘客服并通过核实后，再送 50 积分。两笔积分分别自到账起 30 天有效。</p></details>
        </footer>
      </div>
    </dialog>}
  </>;
}

export function SupportWelcomeReward({ workspaceId, claimed }: { workspaceId: string; claimed: boolean }) {
  const client = useQueryClient();
  const key = ["support-cases", workspaceId];
  const cases = useQuery({
    queryKey: key,
    refetchInterval: 30_000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(
      "/api/v1/workspaces/{workspace_id}/support-cases", { params: { path: { workspace_id: workspaceId } }, signal },
    )),
  });
  const claim = useMutation({
    mutationFn: async () => unwrapApiResponse(await apiClient.POST(
      "/api/v1/workspaces/{workspace_id}/support-cases",
      {
        params: { path: { workspace_id: workspaceId }, header: { "Idempotency-Key": "support-welcome" } },
        body: { issue: "申请添加客服赠送 50 积分", welcome_bonus: true },
      },
    )),
    onSuccess: created => {
      client.setQueryData<NonNullable<typeof cases.data>>(key, previous => [
        created, ...(previous ?? []).filter(item => item.id !== created.id),
      ]);
      void client.invalidateQueries({ queryKey: key });
    },
  });
  const request = cases.data?.find(item => item.welcome_bonus);
  const resolved = request?.status === "resolved";
  const needsCase = !claimed && !request;
  const unavailable = needsCase && cases.isError && !cases.data;
  return <section className={styles.support} aria-label="新用户客服奖励">
    <div className={styles.supportBody}>
      <header className={styles.supportHeader}>
        <span className={styles.supportIcon}><Gift size={20} aria-hidden="true" /></span>
        <h2>{claimed ? "客服赠分" : "联系客服，再领"} <strong>50 积分</strong></h2>
      </header>
      {needsCase && <p className={styles.supportDescription}>通过企业微信联系并提供注册邮箱，再提交申请。客服核实后发放积分。</p>}
      <div className={styles.supportActions}>
        <a className={styles.supportContact} href={WECHAT_SUPPORT_URL} target="_blank" rel="noopener noreferrer">
          <MessageCircle size={17} aria-hidden="true" />联系企业微信客服<ArrowUpRight size={15} aria-hidden="true" />
        </a>
        {needsCase && <button className={styles.supportApply} type="button" disabled={cases.isPending || claim.isPending || (unavailable && cases.isFetching)} onClick={() => unavailable ? void cases.refetch() : claim.mutate()}>
          {claim.isPending ? "正在提交…" : cases.isPending || (unavailable && cases.isFetching) ? "正在读取申请…" : unavailable ? "重新读取申请" : claim.isError ? "重新提交申请" : "已联系，提交申请"}
        </button>}
      </div>
      {needsCase && (claim.isError || unavailable) && <p className={styles.supportError} role="alert">
        {unavailable ? "暂时无法读取申请状态，请重试。" : errorMessage(claim.error)}
      </p>}
      <div className={styles.supportMeta}>
        {(claimed || request) && <p className={styles.supportStatus} data-state={claimed ? "claimed" : resolved ? "resolved" : "pending"} role="status">
          {claimed || resolved ? <Check size={17} aria-hidden="true" /> : <Clock3 size={16} aria-hidden="true" />}
          <span>{claimed ? "客服赠送的 50 积分已到账" : resolved ? request.resolution || "申请已处理" : "已提交，等待客服核实"}</span>
        </p>}
        <a className={styles.supportRecords} href="#help">查看客服记录<ArrowUpRight size={14} aria-hidden="true" /></a>
      </div>
    </div>
    <figure className={styles.supportQr}>
      <Image src={WECHAT_SUPPORT_QR} alt="极光商绘企业微信客服二维码" width={350} height={350} unoptimized />
      <figcaption>微信扫码联系</figcaption>
    </figure>
  </section>;
}
