"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ArrowRight, Check, Copy, LoaderCircle, PencilLine, RotateCcw } from "lucide-react";
import { AUTO_STAGES, useAutoWriting, type AutoDraft, type AutoRun, type AutoStart } from "@/features/video-studio/use-auto-writing";
import { PLATFORM_LABEL, type AnalysisDoc, type DraftDoc, type Platform, type ReferenceDoc } from "@/features/video-studio/use-viral-writing";
import { editChanged, editOf, fullText, needsFill, toggle, type FillStatus, type LibraryEdit, type LibraryEntry, type LibraryPlatform } from "@/features/video-studio/script-library-format";
import { scriptLibraryApi } from "@/features/video-studio/use-script-library";
import { billableLabel, FREE_TRIAL_TEXT, isPriced, useVideoCredits } from "@/features/video-studio/credits";
import { ScriptParts } from "./script-library-parts";
import type { ToastTone } from "./studio-toast";
import lib from "./script-library.module.css";
import type { useProjectSession } from "@/features/video-studio/use-project-session";
import { coverSrc } from "./benchmark-cover";
import { ComparisonPanel, TeardownReport } from "./teardown-report";
import studio from "./video-studio.module.css";
import css from "./auto-writing.module.css";

type ProjectSession = ReturnType<typeof useProjectSession>["session"];
const LIMITS = [["price", "不写价格"], ["net_quantity", "不写净含量"], ["health_effect", "不写功效疗效"]] as const;

/* ------------------------------------------------------------------ start */

function StartForm({ initial, busy, onStart, onCancel, writingPriced = false }: { initial: Partial<AutoStart>; busy: boolean; onStart: (input: AutoStart) => void; onCancel?: () => void; writingPriced?: boolean }) {
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
      <small>{facts.trim().length > 0 && facts.trim().length < 60
        ? "写得越具体越好：只有一两句的话，稿子会反复说同样几句。可以再补卖点、规格价格、真实的客户反馈。"
        : "没写的信息不会出现在稿子里；原视频里的品牌、价格、功效也不会被搬过来。"}</small>
    </label>
    <div className={css.limits}>
      {LIMITS.map(([key, text]) => <label key={key}><input type="checkbox" checked={limits.includes(key)} onChange={event => setLimits(event.target.checked ? [...limits, key] : limits.filter(v => v !== key))} />{text}</label>)}
      <input aria-label="禁用词" className={css.forbidden} value={forbidden} onChange={event => setForbidden(event.target.value)} placeholder="禁用词，逗号隔开（选填）" />
    </div>
    <div className={css.actions}>
      {onCancel && <button type="button" className={studio.outlineButton} onClick={onCancel}>取消</button>}
      <small>大约 3–5 分钟，期间可以离开这个页面。每版都有标题、发布正文和口播稿，写好自动存进文案库。会调用搜索和写稿模型{writingPriced ? "，按步骤扣积分" : `（${FREE_TRIAL_TEXT}）`}。</small>
      <button type="submit" className={studio.primaryButton} disabled={busy || !query.trim() || facts.trim().length < 4}>{busy ? "提交中…" : "让 AI 写 3 版文案"}<ArrowRight size={15} /></button>
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

type Parts = { publish_title: string; publish_body: string; script: string; platform: LibraryPlatform | "" };

function VersionCard({ entry, draft, reference, item, platform, selecting, checked, onToggle, onUse, onSave, onFill, fillCredits, copyText }: {
  entry: AutoDraft; draft: DraftDoc | undefined; reference: ReferenceDoc | undefined; item: LibraryEntry | undefined; platform: LibraryPlatform | "";
  selecting: boolean; checked: boolean; onToggle: () => void; onUse: (id: string) => void;
  onSave: (item: LibraryEntry, edit: LibraryEdit) => Promise<void>; copyText: (text: string) => void;
  onFill: (entry: AutoDraft, item: LibraryEntry | undefined, script: string) => Promise<FillStatus | undefined>; fillCredits: number | null | undefined;
}) {
  const [edit, setEdit] = useState<LibraryEdit | null>(null);
  const [saving, setSaving] = useState(false);
  const [filling, setFilling] = useState(false);
  const [fillError, setFillError] = useState("");
  if (!draft) return <div className={css.version} data-empty>
    <header><b>{entry.label}</b></header>
    <p className={css.muted}>这版没有通过事实检查，没写出来。其他几版可以直接用。</p>
  </div>;
  const d = draft.body.draft;
  // One line for the user's own facts this version left out, then the rest.
  const unused = d.warnings.flatMap(t => /你填的「(.+?)」这版没用上/.exec(t)?.[1] ?? []);
  const notes = [
    ...(unused.length ? [`这版没用上：${unused.join("、")}。可以点「编辑」加进去，或挑别的版本。`] : []),
    ...[...d.missing_facts, ...d.warnings].filter(t => !/你填的「/.test(t) && /已删去|缺少|未提供|话题标签/.test(t)),
  ];
  const parts: Parts = item ?? { publish_title: d.publish_title || "", publish_body: d.publish_body || "", script: draft.body.text, platform };
  const blocked = draft.body.shape_check.verdict === "FAIL" || /【[^】]*】|[XＸ]{2,}|待补|待填/.test(parts.script);
  const legacy = needsFill(parts);
  const fill = async () => {
    setFilling(true); setFillError("");
    try {
      const status = await onFill(entry, item, parts.script).catch(() => undefined);
      if (!status || status.status !== "completed") setFillError(status?.message || "这次没写好，没有扣积分，可以再试一次。");
    } finally { setFilling(false); }
  };
  const save = async () => {
    if (!item || !edit) return;
    setSaving(true);
    try { await onSave(item, edit); setEdit(null); } finally { setSaving(false); }
  };
  return <div className={css.version} data-editing={edit ? true : undefined} data-checked={checked || undefined}>
    <header>
      <div className={css.versionTitle}>
        {selecting && item && <input type="checkbox" className={css.check} checked={checked} onChange={onToggle} aria-label={`选择${entry.label}`} />}
        <b>{entry.label}</b>
        {item ? <span className={css.saved}><Check size={12} />已存入文案库</span> : null}
      </div>
      <small>参考：{reference?.body.source_metrics?.title || "对标"}{item && item.revision > 1 ? " · 已修改" : ""}</small>
    </header>
    <ScriptParts parts={parts} edit={edit} onChange={setEdit} onCopy={copyText} scriptMaxHeight={360} legacy={legacy ? <>
      <button type="button" className={studio.outlineButton} disabled={filling} onClick={() => void fill()}>{filling ? "正在补写…" : billableLabel("补写标题和正文", fillCredits)}</button>
      {fillError && <small className={css.muted} role="alert">{fillError}</small>}
    </> : undefined} />
    {!edit && !item && !legacy && <p className={css.muted}>这版是改版前写的，没有存进文案库。</p>}
    {!edit && notes.length > 0 && <details className={css.notes}><summary>提示（{notes.length}）</summary><ul>{notes.map((t, i) => <li key={i}>{t}</li>)}</ul></details>}
    <footer>
      {edit ? <>
        <button type="button" className={studio.outlineButton} onClick={() => setEdit(null)}>取消</button>
        <button type="button" className={studio.primaryButton} disabled={saving || !edit.script.trim() || !item || !editChanged(item, edit)} onClick={() => void save()}>{saving ? "正在保存…" : "保存"}</button>
      </> : <>
        <button type="button" className={css.iconButton} aria-label="复制三项" title="复制标题、正文和口播稿" onClick={() => copyText(fullText(parts))}><Copy size={14} /></button>
        {item && <button type="button" className={studio.outlineButton} onClick={() => setEdit(editOf(item))}><PencilLine size={14} />编辑</button>}
        {item && <button type="button" className={studio.primaryButton} disabled={blocked} onClick={() => onUse(item.id)}>用这条去做口播<ArrowRight size={14} /></button>}
      </>}
    </footer>
  </div>;
}

function Results({ flow, run, copyText, notify, onUseScripts, onRestart, onManual }: {
  flow: ReturnType<typeof useAutoWriting>; run: AutoRun; copyText: (text: string) => void; notify?: (text: string, tone?: ToastTone) => void;
  onUseScripts: (ids: string[]) => void; onRestart: () => void; onManual?: () => void;
}) {
  const r = run.result;
  const benchmarks = (r.benchmarks || []).filter(b => b.analysis_id);
  const [tab, setTab] = useState(r.main_reference_id || benchmarks[0]?.reference_id || "");
  const current = benchmarks.find(b => b.reference_id === tab) || benchmarks[0];
  const drafts = r.drafts || [];
  const platform: LibraryPlatform | "" = r.request?.platform === "xiaohongshu" || r.request?.platform === "douyin" ? r.request.platform : "";
  const [items, setItems] = useState<Map<string, LibraryEntry>>(new Map());
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const entryIds = drafts.map(d => d.library_entry_id).filter((id): id is string => !!id);
  const docIds = drafts.filter(d => !d.library_entry_id && d.document_id).map(d => d.document_id as string);
  const key = [...entryIds, "|", ...docIds].join(",");
  useEffect(() => {
    let live = true;
    const library = scriptLibraryApi(flow.workspaceId);
    void Promise.all([library.byIds(entryIds), library.byDocuments(docIds)]).then(([a, b]) => {
      if (live) setItems(new Map([...a.items, ...b.items].map(item => [item.id, item])));
    }).catch(() => undefined);
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flow.workspaceId, key]);
  // 旧版本补写时新建的文案库条目，按版本记住（它没有 writing_document_id）。
  const [filled, setFilled] = useState<Map<string, LibraryEntry>>(new Map());
  const fillRequests = useRef(new Map<string, string>());
  const fillCredits = useVideoCredits(flow.workspaceId).note(["writing_publish_fill"]).credits;
  const itemOf = (d: AutoDraft) => filled.get(d.key) || (d.library_entry_id && items.get(d.library_entry_id)) || [...items.values()].find(item => item.writing_document_id === d.document_id);
  /** 旧版本（只有口播稿）补写标题和正文：复用文案库的 publish-fill；不在库里的先存一条再补写。 */
  const fillLegacy = async (d: AutoDraft, item: LibraryEntry | undefined, script: string): Promise<FillStatus | undefined> => {
    const library = scriptLibraryApi(flow.workspaceId);
    let row = item;
    if (!row) {
      const requestId = fillRequests.current.get(d.key) || crypto.randomUUID();
      fillRequests.current.set(d.key, requestId);
      row = await library.create({ request_id: requestId, script, platform });
      const created = row;
      setFilled(map => new Map(map).set(d.key, created));
    }
    let status = await library.fill(row.id, platform || "douyin", crypto.randomUUID());
    for (let i = 0; i < 60 && status.status === "running"; i += 1) {
      await new Promise(resolve => setTimeout(resolve, 2500));
      status = await library.fillStatus(row.id, status.task_id);
    }
    const next = status.entry;
    if (status.status === "completed" && next) {
      setFilled(map => new Map(map).set(d.key, next));
      notify?.("已补写标题和正文", "success");
    }
    return status;
  };
  const ready = drafts.map(itemOf).filter((item): item is LibraryEntry => !!item);
  const save = async (item: LibraryEntry, edit: LibraryEdit) => {
    try {
      const next = await scriptLibraryApi(flow.workspaceId).update(item, edit);
      setItems(map => new Map(map).set(next.id, next));
      notify?.("已保存到文案库", "success");
    } catch (caught) {
      notify?.(caught instanceof Error && caught.message ? caught.message : "没有保存成功，请重试。", "error");
      throw caught;
    }
  };
  return <div className={css.results} data-selecting={selecting || undefined}>
    <section>
      <div className={css.sectionHead}>
        <div className={css.headText}>
          <h3>{drafts.filter(d => d.document_id).length} 版文案，挑一版用</h3>
          {ready.length > 0 && <small>标题、发布正文和口播稿已自动存进文案库。</small>}
        </div>
        <div className={css.headActions}>
          {onManual && <button type="button" className={css.textButton} onClick={onManual}>自己挑对标、逐步来</button>}
          <button type="button" className={studio.outlineButton} onClick={onRestart}><RotateCcw size={14} />换个方向重来</button>
          {ready.length > 1 && <button type="button" className={studio.outlineButton} aria-pressed={selecting} onClick={() => { setSelecting(!selecting); setSelected([]); }}>{selecting ? "取消多选" : "选几条去做口播"}</button>}
        </div>
      </div>
      <div className={css.versions}>{drafts.map(entry => {
        const item = itemOf(entry);
        const doc = flow.latest(flow.doc<DraftDoc>(entry.document_id));
        return <VersionCard key={entry.key} entry={entry} draft={doc} reference={flow.doc<ReferenceDoc>(entry.reference_id)} item={item} platform={platform}
          selecting={selecting} checked={!!item && selected.includes(item.id)} onToggle={() => item && setSelected(ids => toggle(ids, item.id))}
          onUse={id => onUseScripts([id])} onSave={save} onFill={fillLegacy} fillCredits={fillCredits} copyText={copyText} />;
      })}</div>
    </section>
    {selecting && <div className={lib.bar} role="region" aria-label="已选文案">
      <span>已选 <b>{selected.length}</b> 条</span>
      <button type="button" className={lib.link} onClick={() => setSelected(ready.map(item => item.id))}>全选</button>
      <button type="button" className={studio.primaryButton} disabled={!selected.length} onClick={() => onUseScripts(selected)}>用这 {selected.length} 条去做口播<ArrowRight size={15} /></button>
    </div>}
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
        return ref && analysis ? <TeardownReport reference={ref} analysis={analysis} cover={coverSrc(flow.workspaceId, r.search_task_id, current.platform_id)} reason={current.reason} /> : null;
      })()}
    </section>}
  </div>;
}

/* ------------------------------------------------------------------- page */

export function AutoWriting({ workspaceId, projectId, session, productFacts, copyText, notify, onUseScripts, onManual }: {
  workspaceId: string; projectId: string; session: ProjectSession; productFacts: string;
  copyText: (text: string) => void; notify?: (text: string, tone?: ToastTone) => void;
  onUseScripts: (ids: string[]) => void; onManual?: () => void;
}) {
  const flow = useAutoWriting({ workspaceId, projectId, session });
  const credits = useVideoCredits(workspaceId);
  const [form, setForm] = useState(false);
  const run = flow.run;
  const inputs = run?.result.request;
  const candidates = flow.candidates();
  const picks = (run?.result.benchmarks?.length ? run.result.benchmarks : run?.result.ranked?.slice(0, 3) || [])
    .map(p => ({ title: candidates.get(p.platform_id)?.title || p.platform_id, reason: p.reason }));
  const showForm = form || !run;
  return <div className={css.page}>
    {showForm ? <StartForm initial={inputs || { facts_text: productFacts }} busy={flow.busy === "start"} writingPriced={isPriced(credits.note(["benchmark_search", "writing_generate"]).credits)}
      onCancel={run ? () => setForm(false) : undefined}
      onStart={input => void flow.start(input).then(() => setForm(false))} />
      : flow.running ? <Progress run={run} picks={picks} />
      : run.status === "completed" ? <Results flow={flow} run={run} copyText={copyText} notify={notify} onUseScripts={onUseScripts} onRestart={() => setForm(true)} onManual={onManual} />
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
