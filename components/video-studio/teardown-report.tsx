"use client";

import type { AnalysisDoc, Comparison, ReferenceDoc } from "@/features/video-studio/use-viral-writing";
import { PLATFORM_LABEL } from "@/features/video-studio/use-viral-writing";
import css from "./teardown-report.module.css";

/**
 * 可视化拆解报告：数据表现、为什么火、开头钩子、结构时间轴、值得学的表达、
 * 受众与转化、可复用骨架。Only what the saved analysis and public counts say.
 */

const wan = (value: number | null | undefined) => value == null ? "—" : value >= 10000 ? `${(value / 10000).toFixed(value >= 100000 ? 0 : 1)}万` : value.toLocaleString("zh-CN");
const pct = (value: number | null | undefined) => value == null ? "—" : `${Math.round(value * 100)}%`;
// Section shades: one warm hue at different strengths, never a rainbow.
const SHADES = [82, 58, 70, 44, 64, 36, 52, 30];

export function TeardownReport({ reference, analysis, cover, reason }: { reference: ReferenceDoc; analysis: AnalysisDoc; cover?: string | null; reason?: string }) {
  const a = analysis.body; const m = reference.body.source_metrics;
  const text = new Map(reference.body.sentences.map(s => [s.id, s.text]));
  const order = reference.body.sentences.map(s => s.id);
  const total = Math.max(1, reference.body.original_text.length);
  const sections = a.sections.map((section, i) => {
    const ids = order.slice(order.indexOf(section.first_sentence_id), order.indexOf(section.last_sentence_id) + 1);
    const words = ids.map(id => text.get(id) || "").join(" ");
    return { ...section, words, share: words.length / total, shade: SHADES[i % SHADES.length] };
  });
  const collectRate = m?.like_count ? (m.collect_count ?? 0) / m.like_count : null;
  const hook = (a.hook?.sentence_ids || a.hook_sentence_ids).map(id => text.get(id)).filter(Boolean).join(" ");
  const why = a.why_hot?.length ? a.why_hot : m?.readings || [];

  return <article className={css.report}>
    <header className={css.head}>
      {cover ? <img src={cover} alt="" referrerPolicy="no-referrer" className={css.cover} /> : <span />}
      <div className={css.headText}>
        <small>{m ? PLATFORM_LABEL[m.platform] : "对标"}{m?.author_name ? ` · ${m.author_name}` : ""}</small>
        <h3>{m?.title || a.topic}</h3>
        {reason && <p className={css.reason}>AI 选它：{reason}</p>}
      </div>
      {m && <dl className={css.stats}>
        <div><dt>点赞</dt><dd>{wan(m.like_count)}</dd></div>
        <div><dt>收藏</dt><dd>{wan(m.collect_count)}</dd></div>
        <div><dt>评论</dt><dd>{wan(m.comment_count)}</dd></div>
        <div data-strong={(collectRate ?? 0) >= 0.4 || undefined}><dt>收藏率</dt><dd>{pct(collectRate)}</dd></div>
      </dl>}
    </header>

    {why.length > 0 && <section className={css.block}>
      <h4>为什么火</h4>
      <ul className={css.why}>{why.map((line, i) => <li key={i}>{line}</li>)}</ul>
    </section>}

    <section className={css.block}>
      <h4>开头钩子{a.hook && <span className={css.tag}>{a.hook.type}</span>}</h4>
      <blockquote className={css.hook}>{hook}</blockquote>
      {a.hook && <div className={css.hookNotes}><p><b>手法</b>{a.hook.technique}</p><p><b>为什么留得住人</b>{a.hook.why}</p></div>}
    </section>

    <section className={css.block}>
      <h4>结构拆解 <small>{sections.length} 段 · 宽度按原文字数占比</small></h4>
      <div className={css.timeline} role="img" aria-label={"结构：" + sections.map(s => s.function).join(" → ")}>
        {sections.map((s, i) => <span key={s.id} style={{ flexGrow: Math.max(s.share, 0.05), background: `color-mix(in srgb, var(--tr-warm) ${s.shade}%, transparent)` }} title={`${s.function} ${Math.round(s.share * 100)}%`}>
          <b>{i + 1}</b>
        </span>)}
      </div>
      <ol className={css.sections}>{sections.map((s, i) => <li key={s.id}>
        <span className={css.dot} style={{ background: `color-mix(in srgb, var(--tr-warm) ${s.shade}%, transparent)` }}>{i + 1}</span>
        <div>
          <p className={css.sectionHead}><b>{s.function}</b><small>{Math.round(s.share * 100)}%{s.emotion ? ` · ${s.emotion}` : ""}</small></p>
          {s.technique && <p className={css.technique}>{s.technique}</p>}
          <p className={css.quote}>{s.words}</p>
          <p className={css.explain}>{s.explanation}</p>
        </div>
      </li>)}</ol>
    </section>

    {!!a.expressions?.length && <section className={css.block}>
      <h4>值得学的表达</h4>
      <div className={css.cards}>{a.expressions.map((e, i) => <div key={i} className={css.card}>
        <b>{e.name}</b>
        <q>{e.quote}</q>
        <p>{e.effect}</p>
        <p className={css.reuse}>你可以：{e.how_to_reuse}</p>
      </div>)}</div>
    </section>}

    {(a.audience || !!a.conversion?.length) && <section className={css.twoCol}>
      {a.audience && <div className={css.block}>
        <h4>打给谁</h4>
        <p>{a.audience.who}</p>
        {!!a.audience.pain_points.length && <div className={css.chips}>{a.audience.pain_points.map((p, i) => <span key={i}>{p}</span>)}</div>}
        {a.audience.desire && <p className={css.muted}>想要：{a.audience.desire}</p>}
      </div>}
      {!!a.conversion?.length && <div className={css.block}>
        <h4>互动与转化</h4>
        <ul className={css.plain}>{a.conversion.map((c, i) => <li key={i}><span className={css.tag}>{c.kind}</span>{c.note}</li>)}</ul>
      </div>}
    </section>}

    {(a.title_formula || a.reusable_structure.length > 0) && <section className={css.block}>
      <h4>可以直接套用的骨架</h4>
      {a.title_formula && <p className={css.formula}>{a.title_formula}</p>}
      <ol className={css.flow}>{a.reusable_structure.map((line, i) => <li key={i}>{line}</li>)}</ol>
    </section>}
  </article>;
}

export function ComparisonPanel({ comparison, count }: { comparison: Comparison; count: number }) {
  return <section className={css.compare}>
    <h4>{count} 条对标的共性</h4>
    <div className={css.compareGrid}>
      <div><small>共同的钩子</small><ul>{comparison.common_hooks.map((t, i) => <li key={i}>{t}</li>)}</ul></div>
      <div><small>共同的结构</small><ol>{comparison.common_structure.map((t, i) => <li key={i}>{t}</li>)}</ol></div>
      {comparison.common_expressions.length > 0 && <div><small>共同的表达</small><ul>{comparison.common_expressions.map((t, i) => <li key={i}>{t}</li>)}</ul></div>}
    </div>
    {comparison.template_reuse && <p className={css.note}>{comparison.template_reuse}</p>}
  </section>;
}
