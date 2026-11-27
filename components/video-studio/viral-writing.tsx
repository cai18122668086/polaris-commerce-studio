"use client";

import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { ArrowRight, Check, Copy, ExternalLink, LoaderCircle, RotateCcw, Search } from "lucide-react";
import { billableLabel } from "@/features/video-studio/credit-notes";
import { useVideoCredits } from "@/features/video-studio/credits";
import { writingIssueMessage } from "@/features/video-studio/writing-issue";
import {
  MAX_PICKS, PLATFORM_LABEL, useViralWriting,
  type AnalysisDoc, type Candidate, type DraftDoc, type DraftLine, type DraftMode, type Facts, type Job, type Platform, type ReferenceDoc,
} from "@/features/video-studio/use-viral-writing";
import type { useProjectSession } from "@/features/video-studio/use-project-session";
import { BASE, asked, buildFacts, slotKey } from "@/features/video-studio/viral-facts";
import studio from "./video-studio.module.css";
import { BenchmarkCover, coverSrc } from "./benchmark-cover";
import { TeardownReport } from "./teardown-report";
import css from "./viral-writing.module.css";

type ProjectSession = ReturnType<typeof useProjectSession>["session"];
type Flow = ReturnType<typeof useViralWriting>;
export type ViralStep = "find" | "confirm" | "teardown" | "facts" | "draft";
export type Pick = { search_task_id: string; item: Candidate };

/** 先做抖音和小红书；B站后端已接好，界面暂不开放。 */
const SEARCH_PLATFORMS: Platform[] = ["douyin", "xiaohongshu"];

export const VIRAL_STEPS: { id: ViralStep; label: string; hint: string }[] = [
  { id: "find", label: "找对标", hint: "抖音、小红书按点赞搜，或粘贴链接" },
  { id: "confirm", label: "确认对标", hint: "最多 3 条，提取口播原文" },
  { id: "teardown", label: "拆解表", hint: "钩子、结构、表达、为什么火" },
  { id: "facts", label: "我的事实", hint: "把原稿的信息换成你的" },
  { id: "draft", label: "仿写口播稿", hint: "逐句对照，确认后去做口播" },
];

const wan = (value: number | null | undefined) => value == null ? "—" : value >= 10000 ? `${(value / 10000).toFixed(value >= 100000 ? 0 : 1)}万` : value.toLocaleString("zh-CN");
const pct = (value: number | null | undefined) => value == null ? "—" : `${Math.round(value * 100)}%`;
const clock = (value: number | null | undefined) => value == null ? "" : `${Math.floor(value / 60)}:${String(Math.round(value % 60)).padStart(2, "0")}`;
const spoken = (text: string) => Math.max(1, Math.round(text.replace(/[^\p{L}\p{N}]/gu, "").length / 4.8));

function Busy({ children }: { children: ReactNode }) {
  return <p className={css.busy} role="status"><LoaderCircle size={15} className={css.spin} />{children}</p>;
}

/* ---------------------------------------------------------------- 1 找对标 */

function CandidateCard({ item, cover, checked, disabled, onToggle }: { item: Candidate; cover?: string; checked: boolean; disabled: boolean; onToggle: () => void }) {
  const dry = (item.collect_like_ratio ?? 0) >= 0.4;
  return <li className={css.card} data-checked={checked || undefined}>
    <button type="button" className={css.cardHit} aria-pressed={checked} disabled={disabled && !checked} onClick={onToggle}>
      <span className={css.cover}>
        <BenchmarkCover src={cover} label={PLATFORM_LABEL[item.platform]} emptyClassName={css.coverEmpty} />
        {item.duration_seconds ? <span className={css.duration}>{clock(item.duration_seconds)}</span> : null}
        <span className={css.check} aria-hidden>{checked && <Check size={14} />}</span>
      </span>
      <span className={css.cardBody}>
        <b className={css.cardTitle}>{item.title || item.description || "未提供标题"}</b>
        <span className={css.author}>{item.author_name || "作者未知"}{item.author_follower_count ? ` · 粉丝 ${wan(item.author_follower_count)}` : ""}</span>
        <span className={css.metrics}>
          <span><small>赞</small>{wan(item.like_count)}</span>
          <span><small>藏</small>{wan(item.collect_count)}</span>
          <span><small>评</small>{wan(item.comment_count)}</span>
          {item.platform === "bilibili" ? <span><small>播放</small>{wan(item.view_count)}</span> : <span><small>转</small>{wan(item.share_count)}</span>}
        </span>
        {item.collect_like_ratio != null && <span className={css.ratio} data-strong={dry || undefined}>收藏率 {pct(item.collect_like_ratio)}{dry ? " · 干货型" : ""}</span>}
      </span>
    </button>
    <a className={css.open} href={item.source_url} target="_blank" rel="noreferrer">看原视频<ExternalLink size={12} /></a>
  </li>;
}

function FindStep({ flow, picks, setPicks, searchCredits, short }: { flow: Flow; picks: Pick[]; setPicks: (next: Pick[]) => void; searchCredits: number | null | undefined; short: boolean }) {
  const [mode, setMode] = useState<"keyword" | "link">("keyword");
  const [platform, setPlatform] = useState<Platform>("douyin");
  const [keyword, setKeyword] = useState("");
  const [publish, setPublish] = useState("unlimited");
  const [links, setLinks] = useState("");
  const [rootId, setRootId] = useState("");
  const roots = flow.searchRoots;
  const root = roots.find(job => job.id === rootId) || roots[0];
  const pages = root ? flow.pagesOf(root.id) : [];
  const seen = new Map<string, { item: Candidate; page: string }>();
  for (const page of pages) for (const item of page.result.items || []) if (!seen.has(item.platform_id)) seen.set(item.platform_id, { item, page: page.id });
  const items = [...seen.values()].sort((a, b) => (b.item.like_count ?? -1) - (a.item.like_count ?? -1));
  const last = pages.at(-1);
  const pending = pages.some(page => ["queued", "running"].includes(page.status));
  const toggle = (item: Candidate, page: string) => {
    const has = picks.some(pick => pick.item.platform_id === item.platform_id);
    setPicks(has ? picks.filter(pick => pick.item.platform_id !== item.platform_id) : picks.length >= MAX_PICKS ? picks : [...picks, { search_task_id: page, item }]);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (mode === "keyword" && keyword.trim()) void flow.search(platform, keyword.trim(), publish).then(() => setRootId(""));
    if (mode === "link" && links.trim()) void flow.pasteLinks(links.trim()).then(() => setRootId(""));
  };
  if (flow.config && !flow.config.search) return <div className={css.emptyState}><b>对标搜索暂时用不了</b><p>搜索服务还没有开通，请联系管理员。</p></div>;

  return <div className={css.stack}>
    <form className={css.searchBox} onSubmit={submit}>
      <div className={css.segment} role="tablist" aria-label="找对标方式">
        <button type="button" role="tab" aria-selected={mode === "keyword"} onClick={() => setMode("keyword")}>搜关键词</button>
        <button type="button" role="tab" aria-selected={mode === "link"} onClick={() => setMode("link")}>粘贴链接</button>
      </div>
      {mode === "keyword" ? <>
        <div className={css.platforms} role="radiogroup" aria-label="对标平台">
          {SEARCH_PLATFORMS.map(key => <label key={key} data-active={platform === key || undefined}>
            <input type="radio" name="platform" value={key} checked={platform === key} onChange={() => setPlatform(key)} />{PLATFORM_LABEL[key]}
          </label>)}
        </div>
        <div className={css.searchRow}>
          <label className={css.keyword}><Search size={16} /><input aria-label="关键词" value={keyword} maxLength={120} onChange={event => setKeyword(event.target.value)} placeholder="输入关键词，例如：护手霜、宝宝辅食、减脂早餐" /></label>
          {platform === "douyin" && <select aria-label="发布时间" value={publish} onChange={event => setPublish(event.target.value)}>
            <option value="unlimited">发布时间不限</option><option value="half_year">最近半年</option><option value="one_week">最近一周</option><option value="one_day">最近一天</option>
          </select>}
          <button type="submit" className={studio.primaryButton} disabled={!keyword.trim() || !!flow.busy || pending || short}>{flow.busy === "search" ? "搜索中…" : billableLabel("按点赞找爆款", searchCredits)}</button>
        </div>
        <small className={css.note}>结果一律按点赞从高到低排列。{platform === "xiaohongshu" ? "小红书只搜视频笔记；口播原文由我们自己识别，每条约 1–2 分钟。" : ""}</small>
      </> : <>
        <textarea className={css.linkInput} aria-label="对标链接" rows={4} maxLength={4000} value={links} onChange={event => setLinks(event.target.value)}
          placeholder={"直接粘贴分享内容或链接，最多 3 条，支持抖音、小红书\n例如抖音或小红书 App 里「分享 → 复制链接」得到的整段文字"} />
        <div className={css.searchRow}><small className={css.note}>读取作品信息不扣积分。</small><button type="submit" className={studio.primaryButton} disabled={!links.trim() || !!flow.busy || pending}>{flow.busy === "links" ? "读取中…" : "读取链接"}</button></div>
      </>}
    </form>

    {roots.length > 1 && <label className={css.history}>之前的搜索
      <select value={root?.id || ""} onChange={event => setRootId(event.target.value)}>
        {roots.map(job => <option key={job.id} value={job.id}>{job.result.mode === "links" ? "粘贴的链接" : `${PLATFORM_LABEL[(job.result.platform as Platform) || "douyin"] || ""} · ${job.result.keyword}`}</option>)}
      </select>
    </label>}

    {pending && <Busy>{root?.result.mode === "links" ? "正在读取链接里的作品…" : "正在按点赞抓取爆款…"}</Busy>}
    {pages.some(page => page.status === "failed" || page.status === "unknown") && <p className={css.warn}>{pages.find(page => page.status === "unknown") ? "这次搜索的结果还没确认，不会重复扣费，稍后刷新看看。" : "这次没有搜到，换个关键词或平台试试。"}</p>}
    {items.length > 0 && <>
      <div className={css.resultHead}><b>{root?.result.mode === "links" ? "链接里的作品" : `「${root?.result.keyword}」点赞最高的作品`}</b><small>勾选 1–{MAX_PICKS} 条作为对标</small></div>
      <ol className={css.grid}>{items.map(({ item, page }) => <CandidateCard key={item.platform_id} item={item} cover={coverSrc(flow.workspaceId, page, item.platform_id)} checked={picks.some(pick => pick.item.platform_id === item.platform_id)} disabled={picks.length >= MAX_PICKS} onToggle={() => toggle(item, page)} />)}</ol>
      {last?.result.has_more && <button type="button" className={studio.outlineButton} disabled={!!flow.busy || pending || short} onClick={() => void flow.nextPage(last.id)}>{billableLabel("再看一页", searchCredits)}</button>}
    </>}
    {root && !pending && pages.every(page => page.status === "completed") && !items.length && <div className={css.emptyState}><b>没有找到可用的视频</b><p>可能都是图文或超过 5 分钟的视频。换个关键词，或直接粘贴链接。</p></div>}
  </div>;
}

/* ------------------------------------------------------------- 2 确认对标 */

function jobLine(job: Job, platform: string) {
  if (["queued", "running"].includes(job.status)) return platform === "xiaohongshu" ? "正在识别口播，每条约 1–2 分钟…" : "正在提取口播原文…";
  if (job.status === "failed") return job.error_code === "VIDEO_TRANSCRIPT_EMPTY" ? "没识别到人声，可能是纯音乐或图文。换一条对标吧。" : "提取没有成功，可以重试一次。";
  if (job.status === "unknown") return "提取结果还没确认，请稍后刷新。";
  if (job.status === "awaiting_resume") return "提取还在排队，点「继续」查询结果。";
  return "";
}

function ConfirmStep({ flow, picks, setPicks, onNext, writingCredits, short }: { flow: Flow; picks: Pick[]; setPicks: (next: Pick[]) => void; onNext: () => void; writingCredits: number | null | undefined; short: boolean }) {
  const pendingAnalysis = flow.runRefs.filter(ref => !flow.analysisOf(ref) && !["queued", "running"].includes(flow.analysisJobOf(ref)?.status || ""));
  const extracting = flow.runJobs.some(job => ["queued", "running"].includes(job.status));
  if (picks.length) return <div className={css.stack}>
    <p className={css.lead}>确认后会提取这 {picks.length} 条的口播原文，用来拆解和仿写。提取不扣积分。</p>
    <ol className={css.pickList}>{picks.map(pick => { const item = pick.item; return <li key={item.platform_id}>
      <BenchmarkCover src={coverSrc(flow.workspaceId, pick.search_task_id, item.platform_id)} label={PLATFORM_LABEL[item.platform]} emptyClassName={css.coverEmpty} />
      <div><b>{item.title || item.description}</b><small>{PLATFORM_LABEL[item.platform]} · {item.author_name || "作者未知"} · 赞 {wan(item.like_count)} · 藏 {wan(item.collect_count)}</small></div>
      <button type="button" className={css.textButton} onClick={() => setPicks(picks.filter(other => other.item.platform_id !== item.platform_id))}>移除</button>
    </li>; })}</ol>
    <div className={css.actions}><button type="button" className={studio.primaryButton} disabled={!!flow.busy} onClick={() => void flow.confirm(picks.map(pick => ({ search_task_id: pick.search_task_id, platform_id: pick.item.platform_id }))).then(() => setPicks([]))}>
      {flow.busy === "confirm" ? "提交中…" : `确认这 ${picks.length} 条对标`}<ArrowRight size={15} /></button></div>
  </div>;
  if (!flow.runJobs.length) return <div className={css.emptyState}><b>还没有选对标</b><p>先在「找对标」里勾选 1–{MAX_PICKS} 条点赞高的作品。</p></div>;

  return <div className={css.stack}>
    <ol className={css.transcripts}>{flow.runJobs.map(job => {
      const ref = flow.refOf(job); const metrics = ref?.body.source_metrics; const platform = job.benchmark_source?.platform || "douyin";
      return <li key={job.id}>
        <header><b>{metrics?.title || ref?.body.original_text.slice(0, 24) || job.benchmark_source?.platform_id}</b>
          <small>{PLATFORM_LABEL[platform as Platform]}{metrics ? ` · 赞 ${wan(metrics.like_count)} · 藏 ${wan(metrics.collect_count)}` : ""}</small>
          {job.benchmark_source && <a href={job.benchmark_source.source_url} target="_blank" rel="noreferrer">原视频<ExternalLink size={12} /></a>}
        </header>
        {ref ? <details><summary>{job.result.source === "note_text" ? "这条没有口播，用的是笔记正文" : "口播原文"} · {ref.body.original_text.length} 字{job.result.source === "note_text" ? "" : ` · 约 ${spoken(ref.body.original_text)} 秒`}</summary><p className={css.transcript}>{ref.body.sentences.map(s => s.text).join("\n")}</p></details>
          : job.status === "completed" ? <Busy>正在整理原文…</Busy>
          : ["queued", "running"].includes(job.status) ? <Busy>{jobLine(job, platform)}</Busy>
          : <p className={css.warn}>{jobLine(job, platform)} {job.can_resume && <button type="button" className={css.textButton} onClick={() => void flow.resume(job.id)}>继续</button>}</p>}
      </li>;
    })}</ol>
    <div className={css.actions}>
      {flow.runRefs.length > 0 && (pendingAnalysis.length
        ? <button type="button" className={studio.primaryButton} disabled={!!flow.busy || short || !flow.config?.generate} onClick={() => void flow.analyse(pendingAnalysis).then(onNext)}>
            {billableLabel(`开始拆解 ${pendingAnalysis.length} 条`, typeof writingCredits === "number" ? writingCredits * pendingAnalysis.length : writingCredits)}<ArrowRight size={15} /></button>
        : <button type="button" className={studio.primaryButton} disabled={extracting} onClick={onNext}>看拆解表<ArrowRight size={15} /></button>)}
    </div>
  </div>;
}

/* --------------------------------------------------------------- 3 拆解表 */

function TeardownStep({ flow, main, setMain, onNext, writingCredits, short }: { flow: Flow; main: string; setMain: (id: string) => void; onNext: () => void; writingCredits: number | null | undefined; short: boolean }) {
  const refs = flow.runRefs;
  const [tab, setTab] = useState("");
  const current = refs.find(ref => ref.id === tab) || refs.find(ref => ref.id === main) || refs[0];
  if (!current) return <div className={css.emptyState}><b>还没有可拆解的原文</b><p>先在「确认对标」里提取口播原文。</p></div>;
  const analyses = refs.map(ref => flow.analysisOf(ref)).filter((doc): doc is AnalysisDoc => !!doc);
  const analysis = flow.analysisOf(current);
  const job = flow.analysisJobOf(current);
  const comparing = ["queued", "running"].includes(flow.latestCompare?.status || "");
  const cmp = flow.comparison;
  return <div className={css.stack}>
    {refs.length > 1 && <div className={css.tabs} role="tablist">{refs.map((ref, i) => <button key={ref.id} type="button" role="tab" aria-selected={ref.id === current.id} onClick={() => setTab(ref.id)}>
      对标 {i + 1}{ref.id === main ? " · 主对标" : ""}{!flow.analysisOf(ref) && ["queued", "running"].includes(flow.analysisJobOf(ref)?.status || "") ? " · 拆解中" : ""}</button>)}</div>}
    {analysis ? <TeardownReport reference={current} analysis={analysis} />
      : ["queued", "running"].includes(job?.status || "") ? <Busy>正在像运营专家一样逐句拆解，约 30–60 秒…</Busy>
      : <div className={css.emptyState}><b>{job?.status === "failed" ? "这次拆解没有通过检查" : "这条还没拆解"}</b><p>{job?.status === "failed" ? "模型的拆解引用了原文里没有的句子，已拦下。可以再拆一次。" : "拆解会调用文稿模型。"}</p>
          <button type="button" className={studio.primaryButton} disabled={!!flow.busy || short} onClick={() => void flow.analyse([current])}>{billableLabel(job ? "重新拆解" : "开始拆解", writingCredits)}</button></div>}
    {analyses.length >= 2 && <section className={css.panel}><h3>{analyses.length} 条对标的共性</h3>
      {cmp ? <>
        <p><small className={css.muted}>共同的钩子</small></p><ul className={css.plain}>{cmp.common_hooks.map((t, i) => <li key={i}>{t}</li>)}</ul>
        <p><small className={css.muted}>共同的结构</small></p><ol className={css.plain}>{cmp.common_structure.map((t, i) => <li key={i}>{t}</li>)}</ol>
        {!!cmp.common_expressions.length && <><p><small className={css.muted}>共同的表达</small></p><ul className={css.plain}>{cmp.common_expressions.map((t, i) => <li key={i}>{t}</li>)}</ul></>}
        {cmp.template_reuse && <p className={css.warn}>{cmp.template_reuse}</p>}
        <p className={css.formula}><small>推荐主对标</small>对标 {refs.findIndex(ref => ref.id === cmp.recommended_reference_document_id) + 1}：{cmp.recommendation_reason}</p>
      </> : comparing ? <Busy>正在对比几条对标…</Busy>
        : <button type="button" className={studio.outlineButton} disabled={!!flow.busy || short} onClick={() => void flow.compare(analyses, current)}>{billableLabel("生成共性对比", writingCredits)}</button>}
    </section>}
    {analysis && <div className={css.actions}>
      {refs.length > 1 && <label className={css.mainPick}><input type="radio" checked={main === current.id} onChange={() => setMain(current.id)} />用这条做主对标仿写</label>}
      <button type="button" className={studio.primaryButton} onClick={() => { if (!refs.some(ref => ref.id === main)) setMain(current.id); onNext(); }}>下一步：填我的事实<ArrowRight size={15} /></button>
    </div>}
  </div>;
}

/* ------------------------------------------------------------ 4 我的事实 */

type Answers = Record<string, string>;

function FactsStep({ flow, main, answers, setAnswers, forbidden, setForbidden, limits, setLimits, mode, setMode, productFacts, onNext, writingCredits, short }: {
  flow: Flow; main: ReferenceDoc | undefined; answers: Answers; setAnswers: (next: Answers) => void; forbidden: string; setForbidden: (v: string) => void;
  limits: Facts["restricted_claims"]; setLimits: (v: Facts["restricted_claims"]) => void; mode: DraftMode; setMode: (m: DraftMode) => void;
  productFacts: string; onNext: () => void; writingCredits: number | null | undefined; short: boolean;
}) {
  const analysis = flow.analysisOf(main);
  useEffect(() => { if (!answers.points && productFacts.trim() && productFacts.length <= 1000) setAnswers({ ...answers, points: productFacts.trim() }); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!main || !analysis) return <div className={css.emptyState}><b>先完成拆解</b><p>拆解表出来以后，这里会列出原稿里需要换成你自己信息的地方。</p></div>;
  const slots = analysis.body.replace_slots || [];
  const text = new Map(main.body.sentences.map(s => [s.id, s.text]));
  const facts = buildFacts(slots, answers, forbidden, limits);
  const declared = facts.facts.filter(f => f.status === "user_declared").length;
  const field = (id: string, label: string, question: string, rows: number, quote?: string) => <label key={id} className={css.fact}>
    <span><b>{label}</b>{quote && <small>原稿：“{quote}”</small>}</span>
    <textarea rows={rows} maxLength={1000} value={answers[id] || ""} placeholder={question} onChange={event => setAnswers({ ...answers, [id]: event.target.value })} />
  </label>;
  return <div className={css.stack}>
    <p className={css.lead}>仿写只会用你写在这里的信息。没写的就不会出现在稿子里，原稿的品牌、价格、功效也不会被搬过来。</p>
    {slots.length > 0 && <section className={css.panel}><h3>原稿里要换掉的信息</h3>{slots.map(slot => field(slotKey(slot.id), slot.label, slot.question, 1, slot.source_quote || text.get(slot.sentence_id)))}</section>}
    <section className={css.panel}><h3>关于你和产品</h3>{BASE.filter(item => !asked(slots, item)).map(item => field(item.id, item.label, item.question, item.rows))}</section>
    <section className={css.panel}><h3>不能写的</h3>
      <div className={css.limits}>{([["price", "不写价格"], ["net_quantity", "不写净含量"], ["health_effect", "不写疗效"]] as const).map(([key, label]) => <label key={key}><input type="checkbox" checked={limits.includes(key)} onChange={event => setLimits(event.target.checked ? [...limits, key] : limits.filter(v => v !== key))} />{label}</label>)}</div>
      <label className={css.fact}><span><b>禁用词</b><small>每行一个，例如竞品名、平台违禁词</small></span><textarea rows={2} value={forbidden} onChange={event => setForbidden(event.target.value)} /></label>
    </section>
    <div className={css.modeRow} role="radiogroup" aria-label="仿写方式">
      <label data-active={mode === "shadow" || undefined}><input type="radio" checked={mode === "shadow"} onChange={() => setMode("shadow")} /><b>逐句影子仿写</b><small>句数、句式、语气照原稿，只换成你的信息</small></label>
      <label data-active={mode === "structure" || undefined}><input type="radio" checked={mode === "structure"} onChange={() => setMode("structure")} /><b>结构仿写</b><small>沿用段落和手法，用你的话重新说，更自然</small></label>
    </div>
    <div className={css.actions}><small className={css.note}>{declared ? `已填 ${declared} 项` : "至少填一项"}</small>
      <button type="button" className={studio.primaryButton} disabled={!declared || !!flow.busy || short || !flow.config?.generate} onClick={() => void flow.write(main, analysis, facts, mode).then(onNext)}>
        {flow.busy === "write" ? "提交中…" : billableLabel("一键仿写口播稿", writingCredits)}<ArrowRight size={15} /></button></div>
  </div>;
}

/* ---------------------------------------------------------- 5 仿写口播稿 */

function marked(text: string, replacements: string[]) {
  const words = replacements.filter(Boolean).sort((a, b) => b.length - a.length);
  if (!words.length) return text;
  const parts = text.split(new RegExp(`(${words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`));
  return parts.map((part, i) => words.includes(part) ? <mark key={i}>{part}</mark> : part);
}

function DraftStep({ flow, main, onRewrite, onAdopted, copyText, writingCredits }: { flow: Flow; main: ReferenceDoc | undefined; onRewrite: () => void; onAdopted: () => Promise<void>; copyText: (text: string) => void; writingCredits: number | null | undefined }) {
  const drafts = flow.draftsOf(main);
  const [chosen, setChosen] = useState("");
  const [editing, setEditing] = useState<DraftLine[] | null>(null);
  const draft: DraftDoc | undefined = drafts.find(doc => doc.id === chosen) || drafts[0];
  const job = flow.latestTask("fact_draft");
  const writing = ["queued", "running"].includes(job?.status || "") && job?.reference_document_id === main?.id;
  const failed = job?.status === "failed" && job.reference_document_id === main?.id;
  if (!main) return <div className={css.emptyState}><b>先选好对标并填写事实</b></div>;
  const source = new Map(main.body.sentences.map(s => [s.id, s.text]));
  const analysis = flow.analysisOf(main);
  const sectionName = new Map((analysis?.body.sections || []).map(s => [s.id, s.function]));
  const d = draft?.body.draft;
  const blockers = d ? [
    ...(draft.body.shape_check.verdict === "FAIL" ? ["结构检查没通过，请逐句修改或重写。"] : []),
    ...(/【[^】]*】|\[[^\]]*\]|[XＸxｘ]{2,}|＿{2,}|_{2,}|待补|待填/.test(draft.body.text) ? ["稿子里还有待补的空位，请逐句修改补上。"] : []),
  ] : [];
  return <div className={css.stack}>
    {writing && <Busy>正在对照原稿逐句仿写，约 30–60 秒…</Busy>}
    {failed && !writing && <p className={css.warn}>{writingIssueMessage(job?.result.validation_issue ?? null)} <button type="button" className={css.textButton} onClick={onRewrite}>回去改事实</button></p>}
    {!d && !writing && !failed && <div className={css.emptyState}><b>还没有仿写稿</b><p>在「我的事实」里填好信息后，点「一键仿写口播稿」。</p></div>}
    {d && draft && <>
      <div className={css.draftHead}>
        <div><b>{d.title}</b><small>{draft.body.text.length} 字 · 约 {spoken(draft.body.text)} 秒 · {d.schema_version === "tengli.structure-draft/1" ? "结构仿写" : "逐句影子仿写"}{draft.body.revision ? " · 已手动修改" : ""}</small></div>
        {drafts.length > 1 && <select aria-label="仿写版本" value={draft.id} onChange={event => { setChosen(event.target.value); setEditing(null); }}>{drafts.map((doc, i) => <option key={doc.id} value={doc.id}>第 {drafts.length - i} 版 · {doc.body.draft.title}</option>)}</select>}
      </div>
      <table className={css.table}><colgroup><col style={{ width: "40%" }} /><col style={{ width: "60%" }} /></colgroup><thead><tr><th>{d.sentences[0]?.reference_sentence_id ? "原稿" : "段落"}</th><th>你的口播稿</th></tr></thead>
        <tbody>{(editing || d.sentences).map((line, i) => <tr key={i}>
          <td className={css.quote}>{line.reference_sentence_id ? source.get(line.reference_sentence_id) : sectionName.get(line.analysis_section_id || "")}</td>
          <td>{editing ? <textarea rows={2} value={line.text} maxLength={1500} onChange={event => setEditing(editing.map((row, j) => j === i ? { ...row, text: event.target.value } : row))} /> : <span className={css.line}>{marked(line.text, d.replacements.map(r => r.replacement))}</span>}</td>
        </tr>)}</tbody></table>
      {d.missing_facts.length > 0 && <details className={css.notes}><summary>可以补充的信息（{d.missing_facts.length}）</summary><ul className={css.plain}>{d.missing_facts.map((t, i) => <li key={i}>{t}</li>)}</ul></details>}
      {d.warnings.length + (draft.body.shape_check.warnings?.length || 0) > 0 && <details className={css.notes}><summary>核对提示（{d.warnings.length + (draft.body.shape_check.warnings?.length || 0)}）</summary><ul className={css.plain}>{[...d.warnings, ...(draft.body.shape_check.warnings || [])].map((t, i) => <li key={i}>{t}</li>)}</ul></details>}
      {blockers.map((t, i) => <p key={i} className={css.warn}>{t}</p>)}
      <div className={css.actions}>
        {editing ? <>
          <button type="button" className={studio.outlineButton} onClick={() => setEditing(null)}>取消修改</button>
          <button type="button" className={studio.primaryButton} disabled={!!flow.busy || editing.some(line => !line.text.trim())} onClick={() => void flow.revise(draft, d.title, editing).then(() => setEditing(null))}>保存修改</button>
        </> : <>
          <button type="button" className={studio.outlineButton} onClick={() => copyText(draft.body.text)}><Copy size={14} />复制全文</button>
          <button type="button" className={studio.outlineButton} onClick={() => setEditing(d.sentences.map(line => ({ ...line })))}>逐句修改</button>
          <button type="button" className={studio.outlineButton} disabled={!!flow.busy} onClick={onRewrite}><RotateCcw size={14} />{billableLabel("换个说法重写", writingCredits)}</button>
          <button type="button" className={studio.primaryButton} disabled={!!flow.busy || blockers.length > 0} onClick={() => void flow.adopt(draft, onAdopted)}>{flow.busy === "adopt" ? "正在保存…" : "确认文案，去做口播"}<ArrowRight size={15} /></button>
        </>}
      </div>
    </>}
  </div>;
}

/* ------------------------------------------------------------------- page */

export function ViralWriting({ workspaceId, projectId, session, productFacts, copyText, onAdopted, onStep }: {
  workspaceId: string; projectId: string; session: ProjectSession; productFacts: string;
  copyText: (text: string) => void; onAdopted: () => Promise<void>; onStep?: (step: ViralStep) => void;
}) {
  const flow = useViralWriting({ workspaceId, projectId, session });
  const credits = useVideoCredits(workspaceId);
  const searchNote = credits.note(["benchmark_search"]);
  const writingNote = credits.note(["writing_generate"]);
  const [step, setStepState] = useState<ViralStep>();
  const [picks, setPicks] = useState<Pick[]>([]);
  const [main, setMain] = useState("");
  const [answers, setAnswers] = useState<Answers>({});
  const [forbidden, setForbidden] = useState("");
  const [limits, setLimits] = useState<Facts["restricted_claims"]>([]);
  const [mode, setMode] = useState<DraftMode>("shadow");
  const mainRef = flow.runRefs.find(ref => ref.id === main) || flow.runRefs.find(ref => ref.id === flow.comparison?.recommended_reference_document_id) || flow.runRefs[0];
  const suggested: ViralStep = flow.draftsOf(mainRef).length ? "draft" : flow.analysisOf(mainRef) ? "teardown" : flow.runJobs.length ? "confirm" : "find";
  const current = step || suggested;
  const go = (next: ViralStep) => { setStepState(next); onStep?.(next); };
  const done: Record<ViralStep, boolean> = {
    find: flow.runJobs.length > 0, confirm: flow.runRefs.length > 0, teardown: !!flow.analysisOf(mainRef),
    facts: flow.draftsOf(mainRef).length > 0, draft: false,
  };
  const meta = VIRAL_STEPS.find(item => item.id === current)!;
  return <div className={css.layout}>
    <ol className={css.steps} aria-label="爆款文案步骤">{VIRAL_STEPS.map((item, i) => <li key={item.id}>
      <button type="button" aria-current={item.id === current ? "step" : undefined} onClick={() => go(item.id)}>
        <span className={css.stepIndex} data-done={done[item.id] || undefined}>{done[item.id] ? <Check size={12} /> : i + 1}</span>
        <span><b>{item.label}</b><small>{item.hint}</small></span>
      </button></li>)}</ol>
    <section className={css.stage} aria-label={meta.label}>
      <header className={css.stageHeader}><h2>{meta.label}</h2>{current === "teardown" && mainRef && flow.runRefs.length > 1 && <small>主对标：{mainRef.body.source_metrics?.title || "对标 1"}</small>}</header>
      {current === "find" && <FindStep flow={flow} picks={picks} setPicks={setPicks} searchCredits={searchNote.credits} short={searchNote.insufficient} />}
      {current === "confirm" && <ConfirmStep flow={flow} picks={picks} setPicks={setPicks} onNext={() => go("teardown")} writingCredits={writingNote.credits} short={writingNote.insufficient} />}
      {current === "teardown" && <TeardownStep flow={flow} main={mainRef?.id || ""} setMain={setMain} onNext={() => go("facts")} writingCredits={writingNote.credits} short={writingNote.insufficient} />}
      {current === "facts" && <FactsStep flow={flow} main={mainRef} answers={answers} setAnswers={setAnswers} forbidden={forbidden} setForbidden={setForbidden} limits={limits} setLimits={setLimits} mode={mode} setMode={setMode} productFacts={productFacts} onNext={() => go("draft")} writingCredits={writingNote.credits} short={writingNote.insufficient} />}
      {current === "draft" && <DraftStep flow={flow} main={mainRef} onRewrite={() => go("facts")} onAdopted={onAdopted} copyText={copyText} writingCredits={writingNote.credits} />}
      {flow.error && <p className={css.error} role="alert">{flow.error}</p>}
    </section>
    {current === "find" && picks.length > 0 && <div className={css.tray}>
      <span>已选 {picks.length} / {MAX_PICKS}</span>
      <span className={css.trayItems}>{picks.map(pick => <span key={pick.item.platform_id}>{pick.item.title.slice(0, 14) || pick.item.platform_id}</span>)}</span>
      <button type="button" className={studio.primaryButton} onClick={() => go("confirm")}>确认对标<ArrowRight size={15} /></button>
    </div>}
  </div>;
}
