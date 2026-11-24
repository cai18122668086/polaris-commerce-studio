"use client";

import { useEffect, useState } from "react";
import { Check, Play, Search, ArrowUpRight, ChevronLeft, ChevronRight, Heart } from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import { Dialog } from "./studio-primitives";
import { templateAppearance } from "@/features/video-studio/template-appearance";
import styles from "./editing-template-gallery.module.css";
import { mediaUrl } from "@/lib/api/base-url";

export type TemplateCard = components["schemas"]["TemplateCatalogCard"];
type Sample = components["schemas"]["EditingTemplateSample"];
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const recommended = ["apple-minimal-v1", "bihuo-02-v1", "bihuo-03-v1", "bihuo-04-v1", "bihuo-08-v1", "bihuo-09-v1", "bihuo-24-v1", "bihuo-36-v1"];

function Poster({ card }: { card: TemplateCard }) {
  const [failed, setFailed] = useState(false);
  const url = card.example?.poster_url || card.style_preview?.poster_url;
  return url && !failed ? <img src={mediaUrl(url)} alt={`${card.name} · 模板封面`} loading="lazy" decoding="async" width={270} height={480} onError={() => setFailed(true)} />
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
  const [favorites, setFavorites] = useState<string[]>([]);
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const favoriteKey = `tengli-editing-favorites:${workspaceId}`;
  // Hydrate the browser-only preference after SSR; workspace changes re-read their own key.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    try {
      const saved: unknown = JSON.parse(localStorage.getItem(favoriteKey) || "[]");
      setFavorites(Array.isArray(saved) ? saved.filter((id): id is string => typeof id === "string") : []);
    } catch { setFavorites([]); }
  }, [favoriteKey]);
  /* eslint-enable react-hooks/set-state-in-effect */
  const favorite = (id: string) => {
    const next = favorites.includes(id) ? favorites.filter(value => value !== id) : [...favorites, id];
    setFavorites(next);
    try { localStorage.setItem(favoriteKey, JSON.stringify(next)); } catch { /* Optional preference. */ }
  };
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
  const openLibrary = () => { setDraft(selected); setFilter("全部"); setQuery(""); setFavoritesOnly(false); setLibraryOpen(true); };
  const openPreview = (card: TemplateCard, project = false) => { setPlaybackError(false); setPreview({ card, project }); };
  const selectedCard = cards.find(card => card.id === selected);
  const shortlist = [...recommended.map(id => cards.find(card => card.id === id)).filter((card): card is TemplateCard => !!card)];
  for (const card of cards) if (shortlist.length < 8 && !shortlist.some(item => item.id === card.id)) shortlist.push(card);
  if (selectedCard && !shortlist.some(card => card.id === selected)) shortlist.unshift(selectedCard);
  const matches = cards.filter(card => {
    const appearance = templateAppearance(card);
    return (!favoritesOnly || favorites.includes(card.id)) && (filter === "全部" || appearance.collection === filter) && (!query.trim() || `${card.name} ${card.category} ${card.visual_features.join(" ")} ${appearance.signature} ${appearance.detail}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  });
  const cardView = (card: TemplateCard, inLibrary = false) => {
    const active = (inLibrary ? draft : selected) === card.id;
    const playable = !!(card.example?.url || card.style_preview?.url);
    const appearance = templateAppearance(card);
    return <article key={card.id} className={`${styles.card} ${active ? styles.selected : ""}`} data-template-card={card.id}>
      <div className={styles.cover}>
        <button type="button" className={styles.posterSelect} aria-pressed={active} aria-label={`选择模板 · ${card.name}`} onClick={() => inLibrary ? setDraft(card.id) : choose(card)}><Poster card={card} /></button>
        {active && <span className={styles.selectionBadge} aria-hidden="true"><Check size={14} /></span>}
        <button type="button" className={styles.favorite} aria-label={`${favorites.includes(card.id) ? "取消收藏" : "收藏模板"} · ${card.name}`} aria-pressed={favorites.includes(card.id)} onClick={() => favorite(card.id)}><Heart size={15} fill={favorites.includes(card.id) ? "currentColor" : "none"} /></button>
        {playable && <button type="button" className={styles.play} aria-label={`预览模板 · ${card.name}`} onClick={() => openPreview(card)}><Play size={13} fill="currentColor" /><span>预览</span></button>}
      </div>
      <button type="button" className={styles.chooseCard} title={card.name} onClick={() => inLibrary ? setDraft(card.id) : choose(card)}><small>{appearance.collection}<span>{active ? "已选" : appearance.signature}</span></small><b>{card.name}</b><span className={styles.cardDetail}>{appearance.detail}</span></button>
    </article>;
  };
  const previewCard = preview?.card;
  const ownSample = samples.find(row => row.template_id === previewCard?.id);
  const previewUrl = preview?.project ? ownSample?.final.url : previewCard?.example?.url || previewCard?.style_preview?.url;
  const previewList = libraryOpen && matches.some(card => card.id === previewCard?.id) ? matches : cards;
  const previewIndex = previewList.findIndex(card => card.id === previewCard?.id);
  const movePreview = (direction: number) => {
    const card = previewList[(previewIndex + direction + previewList.length) % previewList.length];
    if (card) openPreview(card);
  };
  return <section id="editing-templates" className={styles.gallery} aria-label="选择动效模板">
    <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>挑选你的视频风格</span><h2>选择模板</h2></div><button type="button" className={styles.moreTemplates} onClick={openLibrary}>浏览全部 {cards.length || ""} 款 <ArrowUpRight size={14} /></button></div>
    {error && <p role="alert">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>重试</button></p>}
    {!cards.length && !error && <p role="status">正在读取模板…</p>}
    <div className={styles.templateScroll}><div className={styles.grid}>{shortlist.map(card => cardView(card))}</div></div>
    {selectedCard && <div className={styles.selectedSummary}><span className={styles.selectionLabel}><Check size={14} /> 已选模板</span><strong>{selectedCard.name}</strong><span>{selectedCard.capabilities?.includes("video_materials") ? "支持图片和视频 · 按需添加" : (selectedCard.capabilities?.includes("images") ?? selectedCard.material_mode === "images") ? "支持配图 · 按需添加" : "以口播和文字呈现"}</span></div>}
    {libraryOpen && <Dialog title="模板库" wide className={styles.templateLibraryDialog} onClose={() => setLibraryOpen(false)}><div className={styles.libraryFilters}>
      <div className={styles.libraryTabs} role="group" aria-label="模板范围"><button type="button" aria-pressed={!favoritesOnly} onClick={() => setFavoritesOnly(false)}>全部模板 <span>{cards.length}</span></button><button type="button" aria-pressed={favoritesOnly} onClick={() => setFavoritesOnly(true)}><Heart size={14} /> 我的收藏 <span>{favorites.length}</span></button></div>
      <label className={styles.searchBox}><Search size={16} /><input className={styles.templateSearch} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索模板、风格、字幕…" aria-label="搜索模板" /></label>
      <div className={styles.filters} role="group" aria-label="模板分类">{["全部", ...new Set(cards.map(card => templateAppearance(card).collection))].map(category => <button type="button" key={category} aria-pressed={filter === category} onClick={() => setFilter(category)}>{category}</button>)}</div>
    </div><p className={styles.resultCount} role="status">{matches.length} 款风格</p>
      <div className={`${styles.grid} ${styles.libraryGrid}`}>{matches.map(card => cardView(card, true))}</div>
      {!matches.length && <div className={styles.noTemplates}><Search size={24} /><p>{favoritesOnly && !favorites.length ? "点击卡片上的爱心，收藏喜欢的风格" : "没有找到相关模板"}</p><button type="button" onClick={() => { setQuery(""); setFilter("全部"); setFavoritesOnly(false); }}>查看全部模板</button></div>}
      <footer className={styles.modalFooter}><span>{cards.find(card => card.id === draft)?.name || "请选择喜欢的风格"}</span><button type="button" className={styles.secondaryAction} onClick={() => setLibraryOpen(false)}>取消</button><button type="button" disabled={!draft} onClick={() => { const card = cards.find(card => card.id === draft); if (card) { choose(card); setLibraryOpen(false); } }}>使用此模板</button></footer>
    </Dialog>}
    {previewCard && <Dialog title={previewCard.name} className={styles.templatePreviewDialog} onClose={() => setPreview(undefined)}><div className={styles.templatePreview}>
      <div className={styles.previewStage}><div className={styles.previewScreen}>{previewUrl && <video key={previewUrl} src={mediaUrl(previewUrl)} poster={mediaUrl(preview?.project ? undefined : previewCard.example?.poster_url || previewCard.style_preview?.poster_url || undefined)} controls autoPlay muted playsInline preload="metadata" aria-label={`${previewCard.name}${preview?.project ? "本项目成片" : "模板示例"}`} onError={() => setPlaybackError(true)} />}</div><div className={styles.previewNavigation}><button type="button" aria-label="上一个模板" disabled={previewList.length < 2} onClick={() => movePreview(-1)}><ChevronLeft size={18} /></button><span>{previewIndex + 1} / {previewList.length}</span><button type="button" aria-label="下一个模板" disabled={previewList.length < 2} onClick={() => movePreview(1)}><ChevronRight size={18} /></button></div></div>
      <div className={styles.previewDetails}><span className={styles.templateCategory}>{templateAppearance(previewCard).collection}</span><h3>{previewCard.name}</h3><p className={styles.signature}>{templateAppearance(previewCard).detail}</p><ul>{previewCard.visual_features.slice(0, 3).map(feature => <li key={feature}>{feature}</li>)}</ul><p>{previewCard.material_requirements.slice(0, 2).join(" · ")}</p>
        {!previewCard.example && !preview?.project && <small>历史题材片段，仅供版式参考</small>}
        {playbackError && <p role="alert">示例暂时无法播放，请关闭后重试。</p>}
        <small>{preview?.project ? "正在观看本项目已有成片" : "正在观看已有模板示例"} · 点击播放器开启声音</small>
        {ownSample && <div className={styles.sampleTabs} role="group" aria-label="预览来源"><button type="button" aria-pressed={!preview?.project} onClick={() => openPreview(previewCard)}>模板示例</button><button type="button" aria-pressed={!!preview?.project} onClick={() => openPreview(previewCard, true)}>本项目成片</button></div>}
        <button type="button" className={styles.useTemplate} onClick={() => { choose(previewCard); setPreview(undefined); setLibraryOpen(false); }}>使用此模板</button>
      </div>
    </div></Dialog>}
  </section>;
}
