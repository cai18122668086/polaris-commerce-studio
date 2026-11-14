"use client";

import { useEffect, useState } from "react";
import { Check, Play, Search, ArrowUpRight } from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import { Dialog } from "./studio-primitives";
import styles from "./editing-flow.module.css";

export type TemplateCard = components["schemas"]["TemplateCatalogCard"];
type Sample = components["schemas"]["EditingTemplateSample"];
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const recommended = ["apple-minimal-v1", "bihuo-02-v1", "bihuo-03-v1", "bihuo-04-v1", "bihuo-08-v1", "bihuo-09-v1", "bihuo-24-v1", "bihuo-36-v1"];

function Poster({ card }: { card: TemplateCard }) {
  const [failed, setFailed] = useState(false);
  const url = card.example?.poster_url || card.style_preview?.poster_url;
  return url && !failed ? <img src={url} alt={`${card.name} · 模板封面`} loading="lazy" decoding="async" width={270} height={480} onError={() => setFailed(true)} />
    : <div className={styles.coverText}><small>{card.category}</small><strong>{card.name}</strong><span>预览完整效果</span></div>;
}

export function EditingTemplateGallery({ workspaceId, projectId, selected, onSelect, onRestore, sampleRevision }: {
  workspaceId: string; projectId: string; selected: string; onSelect: (card: TemplateCard) => void; onRestore: (card: TemplateCard) => void; sampleRevision: string;
}) {
  const [cards, setCards] = useState<TemplateCard[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<{ card: TemplateCard; project?: boolean }>();
  const [playbackError, setPlaybackError] = useState(false);
  const [filter, setFilter] = useState("全部");
  const [retry, setRetry] = useState(0);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const selectionKey = `tengli-editing-template:${workspaceId}:${projectId}`;
  useEffect(() => {
    if (selected || !cards.length) return;
    try {
      const card = cards.find(card => card.id === localStorage.getItem(selectionKey));
      if (card) onRestore(card);
    } catch { /* Optional preference. */ }
  }, [cards, onRestore, selected, selectionKey]);
  useEffect(() => {
    const controller = new AbortController();
    void apiClient.GET(`${root}/editing-template-catalog`, {
      params: { path: { workspace_id: workspaceId } }, signal: controller.signal,
    }).then(result => { if (!controller.signal.aborted) { setCards(unwrapApiResponse(result)); setError(""); } })
      .catch(() => { if (!controller.signal.aborted) setError("模板暂时无法读取，请重试。"); });
    return () => controller.abort();
  }, [workspaceId, retry]);
  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    void apiClient.GET(`${root}/projects/{project_id}/editing-template-samples`, {
      params: { path: { workspace_id: workspaceId, project_id: projectId } }, signal: controller.signal,
    }).then(result => { if (!controller.signal.aborted) setSamples(unwrapApiResponse(result)); })
      .catch(() => { /* Installed examples remain available. */ });
    return () => controller.abort();
  }, [workspaceId, projectId, sampleRevision]);
  const choose = (card: TemplateCard) => {
    try { localStorage.setItem(selectionKey, card.id); } catch { /* Optional preference. */ }
    onSelect(card);
  };
  const openLibrary = () => { setDraft(selected); setFilter("全部"); setQuery(""); setLibraryOpen(true); };
  const openPreview = (card: TemplateCard, project = false) => { setPlaybackError(false); setPreview({ card, project }); };
  const selectedCard = cards.find(card => card.id === selected);
  const shortlist = [...recommended.map(id => cards.find(card => card.id === id)).filter((card): card is TemplateCard => !!card)];
  for (const card of cards) if (shortlist.length < 8 && !shortlist.some(item => item.id === card.id)) shortlist.push(card);
  if (selectedCard && !shortlist.some(card => card.id === selected)) shortlist.unshift(selectedCard);
  const matches = cards.filter(card => (filter === "全部" || card.category === filter) && (!query.trim() || `${card.name} ${card.category} ${card.visual_features.join(" ")}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())));
  const cardView = (card: TemplateCard, inLibrary = false) => {
    const active = (inLibrary ? draft : selected) === card.id;
    const playable = !!(card.example?.url || card.style_preview?.url);
    return <article key={card.id} className={`${styles.card} ${active ? styles.selected : ""}`} data-template-card={card.id}>
      <div className={styles.cover}>
        <button type="button" className={styles.posterSelect} aria-pressed={active} aria-label={`选择模板 · ${card.name}`} onClick={() => inLibrary ? setDraft(card.id) : choose(card)}><Poster card={card} /></button>
        {active && <span className={styles.selectionBadge} aria-hidden="true"><Check size={14} /></span>}
        {playable && <button type="button" className={styles.play} aria-label={`预览模板 · ${card.name}`} onClick={() => openPreview(card)}><Play size={13} fill="currentColor" /><span>预览</span></button>}
      </div>
      <button type="button" className={styles.chooseCard} title={card.name} onClick={() => inLibrary ? setDraft(card.id) : choose(card)}><b>{card.name}</b><small>{card.category}{active ? " · 已选" : ""}</small></button>
    </article>;
  };
  const previewCard = preview?.card;
  const ownSample = samples.find(row => row.template_id === previewCard?.id);
  const previewUrl = preview?.project ? ownSample?.final.url : previewCard?.example?.url || previewCard?.style_preview?.url;
  return <section id="editing-templates" className={styles.gallery} aria-label="选择动效模板">
    <div className={styles.sectionHeading}><div><h2>选择模板</h2><p className={styles.sectionHint}>先看风格，再开始创作</p></div><button type="button" className={styles.moreTemplates} onClick={openLibrary}>全部 {cards.length || ""} 款 <ArrowUpRight size={13} /></button></div>
    {error && <p role="alert">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>重试</button></p>}
    {!cards.length && !error && <p role="status">正在读取模板…</p>}
    <div className={styles.templateScroll}><div className={styles.grid}>{shortlist.map(card => cardView(card))}</div></div>
    {selectedCard && <div className={styles.selectedSummary}><span className={styles.selectionLabel}><Check size={14} /> 已选模板</span><strong>{selectedCard.name}</strong><span>{(selectedCard.capabilities?.includes("images") ?? selectedCard.material_mode === "images") ? "支持配图 · 按需添加" : "以口播和文字呈现"}</span></div>}
    {libraryOpen && <Dialog title="模板库" wide className={styles.templateLibraryDialog} onClose={() => setLibraryOpen(false)}><div className={styles.libraryFilters}>
      <label className={styles.searchBox}><Search size={16} /><input className={styles.templateSearch} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索模板、风格、字幕…" aria-label="搜索模板" /></label>
      <div className={styles.filters} role="group" aria-label="模板分类">{["全部", ...new Set(cards.map(card => card.category))].map(category => <button type="button" key={category} aria-pressed={filter === category} onClick={() => setFilter(category)}>{category}</button>)}</div>
    </div><p className={styles.resultCount} role="status">{matches.length} 款风格</p>
      <div className={`${styles.grid} ${styles.libraryGrid}`}>{matches.map(card => cardView(card, true))}</div>
      {!matches.length && <div className={styles.noTemplates}><Search size={24} /><p>没有找到相关模板</p><button type="button" onClick={() => { setQuery(""); setFilter("全部"); }}>查看全部模板</button></div>}
      <footer className={styles.modalFooter}><span>{cards.find(card => card.id === draft)?.name || "请选择喜欢的风格"}</span><button type="button" className={styles.secondaryAction} onClick={() => setLibraryOpen(false)}>取消</button><button type="button" disabled={!draft} onClick={() => { const card = cards.find(card => card.id === draft); if (card) { choose(card); setLibraryOpen(false); } }}>使用此模板</button></footer>
    </Dialog>}
    {previewCard && <Dialog title={previewCard.name} className={styles.templatePreviewDialog} onClose={() => setPreview(undefined)}><div className={styles.templatePreview}>
      <div className={styles.previewScreen}>{previewUrl && <video key={previewUrl} src={previewUrl} poster={previewCard.example?.poster_url || previewCard.style_preview?.poster_url || undefined} controls autoPlay playsInline preload="metadata" aria-label={`${previewCard.name}${preview?.project ? "本项目成片" : "模板示例"}`} onError={() => setPlaybackError(true)} />}</div>
      <div className={styles.previewDetails}><span className={styles.templateCategory}>{previewCard.category}</span><h3>{previewCard.name}</h3><p>{previewCard.material_requirements.slice(0, 2).join(" · ")}</p><ul>{previewCard.visual_features.slice(0, 3).map(feature => <li key={feature}>{feature}</li>)}</ul>
        {!previewCard.example && !preview?.project && <small>历史题材片段，仅供版式参考</small>}
        {playbackError && <p role="alert">示例暂时无法播放，请关闭后重试。</p>}
        {ownSample && <button type="button" className={styles.secondaryAction} onClick={() => openPreview(previewCard, !preview?.project)}>{preview?.project ? "观看模板示例" : "观看本项目成片"}</button>}
        <button type="button" className={styles.useTemplate} onClick={() => { choose(previewCard); setPreview(undefined); setLibraryOpen(false); }}>使用此模板</button>
      </div>
    </div></Dialog>}
  </section>;
}
