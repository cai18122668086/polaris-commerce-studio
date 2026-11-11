"use client";

import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import styles from "./editing-flow.module.css";

export type TemplateCard = components["schemas"]["TemplateCatalogCard"];
type Sample = components["schemas"]["EditingTemplateSample"];
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const roundLabels = { first: "首轮直出", replan: "调整后重排", recorded_response_replay: "已保存真实响应重核", operator_authored: "人工编排样片 · 本次模型结果待核对" };

export function EditingTemplateGallery({ workspaceId, projectId, selected, onSelect, onRestore, sampleRevision }: {
  workspaceId: string; projectId: string; selected: string; onSelect: (card: TemplateCard) => void; onRestore: (card: TemplateCard) => void; sampleRevision: string;
}) {
  const [cards, setCards] = useState<TemplateCard[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [error, setError] = useState("");
  const [sampleError, setSampleError] = useState("");
  const [playing, setPlaying] = useState("");
  const [filter, setFilter] = useState("全部");
  const [retry, setRetry] = useState(0);
  const [query, setQuery] = useState("");
  const selectionKey = `tengli-editing-template:${workspaceId}:${projectId}`;
  useEffect(() => {
    if (selected || !cards.length) return;
    try {
      const card = cards.find(card => card.id === localStorage.getItem(selectionKey));
      if (card) onRestore(card);
    } catch { /* Server task history remains available without browser storage. */ }
  }, [cards, onRestore, selected, selectionKey]);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void apiClient.GET(`${root}/editing-template-catalog`, {
      params: { path: { workspace_id: workspaceId } }, signal: controller.signal,
    }).then(result => { if (!controller.signal.aborted) setCards(unwrapApiResponse(result)); })
      .catch(() => { if (!controller.signal.aborted) setError("模板暂时无法读取，请重试。"); });
    return () => controller.abort();
  }, [workspaceId, retry]);
  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    void apiClient.GET(`${root}/projects/{project_id}/editing-template-samples`, {
      params: { path: { workspace_id: workspaceId, project_id: projectId } }, signal: controller.signal,
    }).then(result => { if (!controller.signal.aborted) setSamples(unwrapApiResponse(result)); })
      .catch(() => { /* Installed examples remain available when project samples cannot be read. */ });
    return () => controller.abort();
  }, [workspaceId, projectId, sampleRevision]);
  const choose = (card: TemplateCard) => {
    try { localStorage.setItem(selectionKey, card.id); } catch { /* Optional preference. */ }
    onSelect(card);
  };
  const selectedCard = cards.find(card => card.id === selected);
  const cardView = (card: TemplateCard) => {
    const sample = samples.find(row => row.template_id === card.id);
    const example = card.example;
    const snippet = card.style_preview;
    const own = playing === card.id + ":project";
    const url = own ? sample?.final.url : example?.url || snippet?.url || sample?.final.url;
    const nativeOnly = !own && !example && !!snippet;
    const active = selected === card.id;
    return <article key={card.id} className={`${styles.card} ${active ? styles.selected : ""}`} data-template-card={card.id}>
      <div className={styles.cover} data-style={card.material_mode}>
        {(playing === card.id || own) && url ? <><video src={url} controls autoPlay playsInline preload="metadata" aria-label={`${card.name}${own ? "本项目成片" : nativeOnly ? "原生样式片段" : "模板示例"}`} onError={() => setSampleError(card.id)} />{nativeOnly && <span className={styles.previewCaption}>历史题材 · 版式参考</span>}</> : <>
          {example?.poster_url || snippet?.poster_url ? <img src={example?.poster_url || snippet?.poster_url || ""} alt={`${card.name}${example ? "成片" : "原生样式片段"}画面`} loading="lazy" /> : <div className={styles.coverText}><small>{card.category}</small><strong>{card.name}</strong><span>{card.visual_features[0]}</span></div>}
          <span className={styles.cardBadge}>{card.status === "pending_originals" ? "原件待补" : example?.round === "operator_authored" ? "人工样片" : example?.origin === "operator_candidate" ? "人工调整版" : example ? "既有成片" : snippet ? "版式参考" : "样式待补"}</span>
          {url && <button type="button" className={styles.play} aria-label={`播放${nativeOnly ? "原生样式片段" : "真实示例"} · ${card.name}`} onClick={() => { setSampleError(""); setPlaying(card.id); }}>▶</button>}
        </>}
      </div>
      <button type="button" className={styles.chooseCard} aria-pressed={active} title={card.name} aria-label={`选择模板 · ${card.name}`} onClick={() => choose(card)}><b>{card.name}</b><small>{active ? "✓ 已选" : "选择"}</small></button>
      {sampleError === card.id && <small role="alert">示例播放失败，请重试</small>}
    </article>;
  };
  return <section id="editing-templates" className={styles.gallery} aria-label="选择动效模板">
    <div className={styles.sectionHeading}><h2>选择模板</h2><span>{cards.length} 套模板</span></div>
    <input className={styles.templateSearch} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索风格：三图、章节、字幕…" aria-label="搜索模板" />
    <div className={styles.filters} role="group" aria-label="模板分类">{["全部", ...new Set(cards.map(card => card.category))].map(category => <button type="button" key={category} aria-pressed={filter === category} onClick={() => setFilter(category)}>{category}</button>)}</div>
    {error && <p role="alert">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>重试</button></p>}
    {!cards.length && !error && <p role="status">正在读取模板…</p>}
    <div className={styles.templateScroll}><div className={styles.grid}>{cards.filter(card => (filter === "推荐" ? card.featured : filter === "全部" || card.category === filter) && (!query || `${card.name} ${card.visual_features.join(" ")}`.includes(query.trim()))).map(cardView)}{filter === "推荐" && !query && cards.some(card => !card.featured) && <button type="button" className={styles.moreTile} onClick={() => setFilter("全部")}><strong>＋</strong><b>全部风格</b><small>查看全部 {cards.length} 套</small></button>}</div></div>
    {selectedCard ? <div className={styles.selectionSummary}><b>已选 · {selectedCard.name}</b><span>{selectedCard.visual_features.join(" · ")}</span><details><summary>素材要求与示例说明</summary><p>{selectedCard.description}</p><ul>{selectedCard.material_requirements.map(line => <li key={line}>{line}</li>)}</ul>{selectedCard.example && <p>{selectedCard.example.title} · {roundLabels[selectedCard.example.round]} · {selectedCard.example.distinct_groups} 种 / {selectedCard.example.occurrences} 次 · {selectedCard.example.width}×{selectedCard.example.height}</p>}{selectedCard.style_preview && !selectedCard.example && <p>此为历史题材的原生片段，仅供对照版式；介绍本网站的新成片待验收。</p>}{selectedCard.id === "chenxi-broll-v1" && <p>三段真实操作业务片待验证，长录屏自动定位未接入。</p>}<details><summary>技术信息</summary><p>{selectedCard.sampled_group_count}/{selectedCard.group_ids.length} 个成员有编码样本，本期效果待预览。</p>{!!selectedCard.pending_original_group_ids.length && <p>原件待补：{selectedCard.pending_original_group_ids.join("、")}</p>}<p>{selectedCard.group_ids.join("、")}</p></details>{samples.find(s => s.template_id === selectedCard.id) && <button type="button" onClick={() => setPlaying(selectedCard.id + ":project")}>播放本项目成片</button>}</details></div> : <p className={styles.selectionHint}>点击卡片选择风格，点 ▶ 查看样片或版式参考</p>}
  </section>;
}
