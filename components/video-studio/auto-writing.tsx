"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ArrowRight, Check, Copy, LoaderCircle, PencilLine, RotateCcw } from "lucide-react";
import { AUTO_STAGES, useAutoWriting, type AutoDraft, type AutoRun, type AutoStart } from "@/features/video-studio/use-auto-writing";
import { PLATFORM_LABEL, type AnalysisDoc, type DraftDoc, type DraftLine, type Platform, type ReferenceDoc } from "@/features/video-studio/use-viral-writing";
import type { useProjectSession } from "@/features/video-studio/use-project-session";
import { ComparisonPanel, TeardownReport } from "./teardown-report";
import studio from "./video-studio.module.css";
import css from "./auto-writing.module.css";

type ProjectSession = ReturnType<typeof useProjectSession>["session"];
const spoken = (text: string) => Math.max(1, Math.round(text.replace(/[^\p{L}\p{N}]/gu, "").length / 4.8));
const LIMITS = [["price", "不写价格"], ["net_quantity", "不写净含量"], ["health_effect", "不写功效疗效"]] as const;

/* ------------------------------------------------------------------ start */

function StartForm({ initial, busy, onStart, onCancel }: { initial: Partial<AutoStart>; busy: boolean; onStart: (input: AutoStart) => void; onCancel?: () => void }) {
  const [platform, setPlatform] = useState<Platform>(initial.platform || "douyin");
  const [query, setQuery] = useState(initial.query || "");
  const [facts, setFacts] = useState(initial.facts_text || "");
  const [limits, setLimits] = useState<AutoStart["restricted_claims"]>(initial.restricted_claims || []);
  const [forbidden, setForbidden] = useState((initial.forbidden_terms || []).join("，"));
  const isLinks = /https?:\/\//.test(query);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim() || facts.trim().length < 4) return;
    onStart({ platform, query: query.trim(), facts_text: facts.trim(), restricted_claims: limits, forbidden_terms: forbidden.split(/[，,\n]/).map(s => s.trim()).filter(Boolean).slice(0, 50) });
  };
  return <form className={css.form} onSubmit={submit}>
    <div className={css.field}>
      <span className={css.label}>去哪找爆款</span>
      <div className={css.platforms} role="radiogroup" aria-label="对标平台">
        {(["douyin", "xiaohongshu"] as Platform[]).map(key => <label key={key} data-active={platform === key || undefined}>
          <input type="radio" name="auto-platform" checked={platform === key} onChange={() => setPlatform(key)} />{PLATFORM_LABEL[key]}
        </label>)}
      </div>
    </div>
    <label className={css.field}>
      <span className={css.label}>关键词，或直接贴链接</span>
      <textarea rows={2} maxLength={4000} value={query} onChange={event => setQuery(event.target.value)} placeholder="例如：护手霜、宝宝辅食、减脂早餐；也可以粘贴 1–3 条分享链接" />
      <small>{isLinks ? "识别到链接：AI 直接用你给的作品做对标。" : "AI 会按点赞从高到低找爆款，再挑最适合你的几条。"}</small>
    </label>
    <label className={css.field}>
      <span className={css.label}>你的产品和事实</span>
      <textarea rows={7} maxLength={3000} value={facts} onChange={event => setFacts(event.target.value)}
        placeholder={"想到什么写什么，AI 只会用你写的内容：\n· 你是谁（身份、从业年限、店铺）\n· 产品叫什么，卖点、规格、价格\n· 真实的使用经历、客户反馈"} />
      <small>没写的信息不会出现在稿子里；原视频里的品牌、价格、功效也不会被搬过来。</small>
    </label>
    <div className={css.limits}>
      {LIMITS.map(([key, text]) => <label key={key}><input type="checkbox" checked={limits.includes(key)} onChange={event => setLimits(event.target.checked ? [...limits, key] : limits.filter(v => v !== key))} />{text}</label>)}
      <input aria-label="禁用词" className={css.forbidden} value={forbidden} onChange={event => setForbidden(event.target.value)} placeholder="禁用词，逗号隔开（选填）" />
    </div>
    <div className={css.actions}>
      {onCancel && <button type="button" className={studio.outlineButton} onClick={onCancel}>取消</button>}
      <small>大约 3–5 分钟，期间可以离开这个页面。会调用搜索和写稿模型（计费）。</small>
      <button type="submit" className={studio.primaryButton} disabled={busy || !query.trim() || facts.trim().length < 4}>{busy ? "提交中…" : "让 AI 写 3 版口播稿"}<ArrowRight size={15} /></button>
    </div>
  </form>;
}

/* --------------------------------------------------------------- progress */

function Progress({ run, picks }: { run: AutoRun; picks: { title: string; reason: string }[] }) {
  const current = AUTO_STAGES.findIndex(stage => stage.key === run.result.stage);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const started = run.result.started_at ? Date.parse(run.result.started_at) : now;
  const seconds = Math.max(0, Math.round((now - started) / 1000));
  return <div className={css.progress}>
    <p className={css.lead}>AI 正在替你干活，已用 {Math.floor(seconds / 60)} 分 {seconds % 60} 秒。可以先去做别的，回来这里就能看到结果。</p>
    <ol className={css.stages}>{AUTO_STAGES.map((stage, i) => {
      const state = current < 0 ? "todo" : i < current ? "done" : i === current ? "now" : "todo";
      return <li key={stage.key} data-state={state}>
        <span className={css.stageMark}>{state === "done" ? <Check size={12} /> : state === "now" ? <LoaderCircle size={13} className={css.spin} /> : i + 1}</span>
        <b>{stage.label}</b>
      </li>;
    })}</ol>
    {picks.length > 0 && <div className={css.picks}>
      <small>AI 选中的对标</small>
      <ul>{picks.map((p, i) => <li key={i}><b>{p.title}</b><span>{p.reason}</span></li>)}</ul>
    </div>}
  </div>;
}

/* ---------------------------------------------------------------- results */

function VersionCard({ entry, draft, reference, busy, onUse, onSave, copyText }: {
  entry: AutoDraft; draft: DraftDoc | undefined; reference: ReferenceDoc | undefined; busy: boolean;
  onUse: (draft: DraftDoc) => void; onSave: (draft: DraftDoc, lines: DraftLine[]) => Promise<void>; copyText: (text: string) => void;
}) {
  const [editing, setEditing] = useState<DraftLine[] | null>(null);
  if (!draft) return <div className={css.version} data-empty>
    <header><b>{entry.label}</b></header>
    <p className={css.muted}>这版没有通过事实检查，没写出来。其他几版可以直接用。</p>
  </div>;
  const d = draft.body.draft;
  // One line for the user's own facts this version left out, then the rest.
  const unused = d.warnings.flatMap(t => /你填的「(.+?)」这版没用上/.exec(t)?.[1] ?? []);
  const notes = [
    ...(unused.length ? [`这版没用上：${unused.join("、")}。可以点「改一改」加进去，或挑别的版本。`] : []),
    ...[...d.missing_facts, ...d.warnings].filter(t => !/你填的「/.test(t) && /已删去|缺少|未提供/.test(t)),
  ];
  const blocked = draft.body.shape_check.verdict === "FAIL" || /【[^】]*】|[XＸ]{2,}|待补|待填/.test(draft.body.text);
  return <div className={css.version} data-editing={editing ? true : undefined}>
    <header>
      <b>{entry.label}</b>
      <small>参考：{reference?.body.source_metrics?.title || "对标"} · {draft.body.text.length} 字 · 约 {spoken(draft.body.text)} 秒{draft.body.revision ? " · 已修改" : ""}</small>
    </header>
    {editing ? <div className={css.editLines}>{editing.map((line, i) => <textarea key={i} rows={2} value={line.text} maxLength={1500} onChange={event => setEditing(editing.map((row, j) => j === i ? { ...row, text: event.target.value } : row))} />)}</div>
      : <p className={css.script}>{d.sentences.map(line => line.text).join("\n")}</p>}
    {!editing && notes.length > 0 && <details className={css.notes}><summary>提示（{notes.length}）</summary><ul>{notes.map((t, i) => <li key={i}>{t}</li>)}</ul></details>}
    <footer>
      {editing ? <>
        <button type="button" className={studio.outlineButton} onClick={() => setEditing(null)}>取消</button>
        <button type="button" className={studio.primaryButton} disabled={busy || editing.some(line => !line.text.trim())} onClick={() => void onSave(draft, editing).then(() => setEditing(null))}>保存修改</button>
      </> : <>
        <button type="button" className={css.iconButton} aria-label="复制全文" onClick={() => copyText(draft.body.text)}><Copy size={14} /></button>
        <button type="button" className={studio.outlineButton} onClick={() => setEditing(d.sentences.map(line => ({ ...line })))}><PencilLine size={14} />改一改</button>
        <button type="button" className={studio.primaryButton} disabled={busy || blocked} onClick={() => onUse(draft)}>用这版<ArrowRight size={14} /></button>
      </>}
    </footer>
  </div>;
}

function Results({ flow, run, copyText, onAdopted, onRestart, onManual }: {
  flow: ReturnType<typeof useAutoWriting>; run: AutoRun; copyText: (text: string) => void; onAdopted: () => Promise<void>; onRestart: () => void; onManual?: () => void;
}) {
  const r = run.result;
  const benchmarks = (r.benchmarks || []).filter(b => b.analysis_id);
  const [tab, setTab] = useState(r.main_reference_id || benchmarks[0]?.reference_id || "");
  const candidates = flow.candidates();
  const current = benchmarks.find(b => b.reference_id === tab) || benchmarks[0];
  const drafts = r.drafts || [];
  return <div className={css.results}>
    <section>
      <div className={css.sectionHead}>
        <h3>{drafts.filter(d => d.document_id).length} 版口播稿，挑一版用</h3>
        <div className={css.headActions}>
          {onManual && <button type="button" className={css.textButton} onClick={onManual}>自己挑对标、逐步来</button>}
          <button type="button" className={studio.outlineButton} onClick={onRestart}><RotateCcw size={14} />换个方向重来</button>
        </div>
      </div>
      <div className={css.versions}>{drafts.map(entry => {
        const draft = flow.latest(flow.doc<DraftDoc>(entry.document_id));
        return <VersionCard key={entry.key} entry={entry} draft={draft} reference={flow.doc<ReferenceDoc>(entry.reference_id)} busy={!!flow.busy}
          copyText={copyText} onUse={doc => void flow.adopt(doc, onAdopted)}
          onSave={(doc, lines) => flow.revise(doc, doc.body.draft.title, lines)} />;
      })}</div>
    </section>
    {benchmarks.length > 0 && <section>
      <div className={css.sectionHead}><h3>拆解报告</h3></div>
      {r.comparison && benchmarks.length > 1 && <ComparisonPanel comparison={r.comparison} count={benchmarks.length} />}
      {benchmarks.length > 1 && <div className={css.tabs} role="tablist">{benchmarks.map((b, i) => {
        const ref = flow.doc<ReferenceDoc>(b.reference_id);
        return <button key={b.reference_id} type="button" role="tab" aria-selected={b === current} onClick={() => setTab(b.reference_id)}>
          对标 {i + 1}{b.reference_id === r.main_reference_id ? " · 主" : ""}<small>{ref?.body.source_metrics?.title?.slice(0, 14)}</small>
        </button>;
      })}</div>}
      {current && (() => {
        const ref = flow.doc<ReferenceDoc>(current.reference_id); const analysis = flow.doc<AnalysisDoc>(current.analysis_id);
        return ref && analysis ? <TeardownReport reference={ref} analysis={analysis} cover={candidates.get(current.platform_id)?.cover_url} reason={current.reason} /> : null;
      })()}
    </section>}
  </div>;
}

/* ------------------------------------------------------------------- page */

export function AutoWriting({ workspaceId, projectId, session, productFacts, copyText, onAdopted, onManual }: {
  workspaceId: string; projectId: string; session: ProjectSession; productFacts: string;
  copyText: (text: string) => void; onAdopted: () => Promise<void>; onManual?: () => void;
}) {
  const flow = useAutoWriting({ workspaceId, projectId, session });
  const [form, setForm] = useState(false);
  const run = flow.run;
  const inputs = run?.result.request;
  const candidates = flow.candidates();
  const picks = (run?.result.benchmarks?.length ? run.result.benchmarks : run?.result.ranked?.slice(0, 3) || [])
    .map(p => ({ title: candidates.get(p.platform_id)?.title || p.platform_id, reason: p.reason }));
  const showForm = form || !run;
  return <div className={css.page}>
    {showForm ? <StartForm initial={inputs || { facts_text: productFacts }} busy={flow.busy === "start"}
      onCancel={run ? () => setForm(false) : undefined}
      onStart={input => void flow.start(input).then(() => setForm(false))} />
      : flow.running ? <Progress run={run} picks={picks} />
      : run.status === "completed" ? <Results flow={flow} run={run} copyText={copyText} onAdopted={onAdopted} onRestart={() => setForm(true)} onManual={onManual} />
      : <div className={css.problem}>
          <b>{run.status === "awaiting_resume" ? "处理中断了" : "这次没有写完"}</b>
          <p>{run.result.message || "可以点「继续」从断点接着做，已经完成的步骤不会重新扣费。"}</p>
          <div className={css.actions}>
            <button type="button" className={studio.outlineButton} onClick={() => setForm(true)}>换个方向重来</button>
            <button type="button" className={studio.primaryButton} disabled={!!flow.busy} onClick={() => void flow.resume(run.id)}>继续<ArrowRight size={15} /></button>
          </div>
        </div>}
    {flow.error && <p className={css.error} role="alert">{flow.error}</p>}
    {showForm && onManual && <button type="button" className={css.textButton} onClick={onManual}>想自己挑对标、一步步来？</button>}
  </div>;
}
