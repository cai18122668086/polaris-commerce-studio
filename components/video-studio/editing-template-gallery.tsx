"use client";

import { useEffect, useState } from "react";
import { Check, Play, Search, ArrowUpRight, ChevronLeft, ChevronRight, Heart } from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import { Dialog } from "./studio-primitives";
import { TEMPLATE_COLLECTIONS, isTemplateListed, templateAppearance } from "@/features/video-studio/template-appearance";
import styles from "./editing-template-gallery.module.css";
import { mediaUrl } from "@/lib/api/base-url";

export type TemplateCard = components["schemas"]["TemplateCatalogCard"];
type Sample = components["schemas"]["EditingTemplateSample"];
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
/** First row: styles from every collection. */
const recommended = ["bihuo-02-v1", "bihuo-04-v1", "bihuo-14-v1", "bihuo-36-v1", "bihuo-48-v1", "bihuo-10-v1", "bihuo-24-v1", "bihuo-09-v1"];

function Poster({ card }: { card: TemplateCard }) {
  const [failed, setFailed] = useState(false);
  const url = card.example?.poster_url || card.style_preview?.poster_url;
  const { collection, name } = templateAppearance(card);
  return url && !failed ? <img src={mediaUrl(url)} alt={`${name} · 模板封面`} loading="lazy" decoding="async" width={270} height={480} onError={() => setFailed(true)} />
    : <div className={styles.coverText}><small>{collection}</small><strong>{name}</strong><span>预览完整效果</span></div>;
}

export function EditingTemplateGallery({ workspaceId, projectId, selected, onSelect, onRestore, sampleRevision, fallbackId }: {
  workspaceId: string; projectId: string; selected: string; onSelect: (card: TemplateCard) => void; onRestore: (card: TemplateCard) => void; sampleRevision: string;
  /** 本机没有记住模板时，沿用该项目上次编排的模板 */
  fallbackId?: string;
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
      const remembered = cards.find(card => card.id === localStorage.getItem(selectionKey));
      const card = remembered ?? cards.find(card => card.id === fallbackId);
      if (card) onRestore(card);
    } catch {
      const card = cards.find(card => card.id === fallbackId);
      if (card) onRestore(card);
    }
  }, [cards, fallbackId, onRestore, selected, selectionKey]);
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
  // Hidden templates stay valid for projects that already use them; they are just not offered again.
  const listed = cards.filter(card => isTemplateListed(card.id));
  const selectedCard = cards.find(card => card.id === selected);
  const shortlist = [...recommended.map(id => listed.find(card => card.id === id)).filter((card): card is TemplateCard => !!card)];
  for (const card of listed) if (shortlist.length < 8 && !shortlist.some(item => item.id === card.id)) shortlist.push(card);
  if (selectedCard && !shortlist.some(card => card.id === selected)) shortlist.unshift(selectedCard);
  const collectionOrder = TEMPLATE_COLLECTIONS.map(row => row.name as string);
  const ordered = [...listed].sort((a, b) => collectionOrder.indexOf(templateAppearance(a).collection) - collectionOrder.indexOf(templateAppearance(b).collection));
  const inScope = (card: TemplateCard) => !favoritesOnly || favorites.includes(card.id);
  const matches = ordered.filter(card => {
    const appearance = templateAppearance(card);
    return inScope(card) && (filter === "全部" || appearance.collection === filter) && (!query.trim() || `${appearance.name} ${appearance.collection} ${appearance.detail} ${appearance.hint}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  });
  const collectionCount = (name: string) => listed.filter(card => inScope(card) && (name === "全部" || templateAppearance(card).collection === name)).length;
  const cardView = (card: TemplateCard, inLibrary = false) => {
    const active = (inLibrary ? draft : selected) === card.id;
    const playable = !!(card.example?.url || card.style_preview?.url);
    const appearance = templateAppearance(card);
    return <article key={card.id} className={`${styles.card} ${active ? styles.selected : ""}`} data-template-card={card.id}>
      <div className={styles.cover}>
        <button type="button" className={styles.posterSelect} aria-pressed={active} aria-label={`选择模板 · ${appearance.name}`} onClick={() => inLibrary ? setDraft(card.id) : choose(card)}><Poster card={card} /></button>
        {active && <span className={styles.selectionBadge} aria-hidden="true"><Check size={14} /></span>}
        <button type="button" className={styles.favorite} aria-label={`${favorites.includes(card.id) ? "取消收藏" : "收藏模板"} · ${appearance.name}`} aria-pressed={favorites.includes(card.id)} onClick={() => favorite(card.id)}><Heart size={15} fill={favorites.includes(card.id) ? "currentColor" : "none"} /></button>
        {playable && <button type="button" className={styles.play} aria-label={`预览模板 · ${appearance.name}`} onClick={() => openPreview(card)}><Play size={13} fill="currentColor" /><span>预览</span></button>}
      </div>
      <button type="button" className={styles.chooseCard} title={appearance.name} onClick={() => inLibrary ? setDraft(card.id) : choose(card)}><small>{appearance.collection}{active && <span>已选</span>}</small><b>{appearance.name}</b><span className={styles.cardDetail}>{appearance.detail}</span></button>
    </article>;
  };
  const previewCard = preview?.card;
  const ownSample = samples.find(row => row.template_id === previewCard?.id);
  const previewUrl = preview?.project ? ownSample?.final.url : previewCard?.example?.url || previewCard?.style_preview?.url;
  const previewList = libraryOpen && matches.some(card => card.id === previewCard?.id) ? matches : shortlist.some(card => card.id === previewCard?.id) ? shortlist : ordered;
  const previewLook = previewCard ? templateAppearance(previewCard) : undefined;
  const previewIndex = previewList.findIndex(card => card.id === previewCard?.id);
  const movePreview = (direction: number) => {
    const card = previewList[(previewIndex + direction + previewList.length) % previewList.length];
    if (card) openPreview(card);
  };
  return <section id="editing-templates" className={styles.gallery} aria-label="选择动效模板">
    <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>挑选你的视频风格</span><h2>选择模板</h2></div><button type="button" className={styles.moreTemplates} onClick={openLibrary}>浏览全部 {listed.length || ""} 款 <ArrowUpRight size={14} /></button></div>
    {error && <p role="alert">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>重试</button></p>}
    {!cards.length && !error && <p role="status">正在读取模板…</p>}
    <div className={styles.templateScroll}><div className={styles.grid}>{shortlist.map(card => cardView(card))}</div></div>
    {selectedCard && <div className={styles.selectedSummary}><span className={styles.selectionLabel}><Check size={14} /> 已选模板</span><strong>{templateAppearance(selectedCard).name}</strong><span>{selectedCard.capabilities?.includes("video_materials") ? "支持图片和视频 · 按需添加" : (selectedCard.capabilities?.includes("images") ?? selectedCard.material_mode === "images") ? "支持配图 · 按需添加" : "以口播和文字呈现"}</span></div>}
    {libraryOpen && <Dialog title="模板库" wide className={styles.templateLibraryDialog} onClose={() => setLibraryOpen(false)}><div className={styles.libraryFilters}>
      <div className={styles.libraryTabs} role="group" aria-label="模板范围"><button type="button" aria-pressed={!favoritesOnly} onClick={() => setFavoritesOnly(false)}>全部模板 <span>{listed.length}</span></button><button type="button" aria-pressed={favoritesOnly} onClick={() => setFavoritesOnly(true)}><Heart size={14} /> 我的收藏 <span>{listed.filter(card => favorites.includes(card.id)).length}</span></button></div>
      <label className={styles.searchBox}><Search size={16} /><input className={styles.templateSearch} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索模板、风格、字幕…" aria-label="搜索模板" /></label>
      <div className={styles.filters} role="group" aria-label="模板分类">{["全部", ...collectionOrder].map(category => <button type="button" key={category} aria-pressed={filter === category} onClick={() => setFilter(category)}>{category}<span>{collectionCount(category)}</span></button>)}</div>
    </div><p className={styles.resultCount} role="status">{filter === "全部" ? `${matches.length} 款风格` : `${TEMPLATE_COLLECTIONS.find(row => row.name === filter)?.hint} · ${matches.length} 款`}</p>
      <div className={`${styles.grid} ${styles.libraryGrid}`}>{matches.map(card => cardView(card, true))}</div>
      {!matches.length && <div className={styles.noTemplates}><Search size={24} /><p>{favoritesOnly && !favorites.length ? "点击卡片上的爱心，收藏喜欢的风格" : "没有找到相关模板"}</p><button type="button" onClick={() => { setQuery(""); setFilter("全部"); setFavoritesOnly(false); }}>查看全部模板</button></div>}
      <footer className={styles.modalFooter}><span>{(() => { const card = cards.find(row => row.id === draft); return card ? templateAppearance(card).name : "请选择喜欢的风格"; })()}</span><button type="button" className={styles.secondaryAction} onClick={() => setLibraryOpen(false)}>取消</button><button type="button" disabled={!draft} onClick={() => { const card = cards.find(card => card.id === draft); if (card) { choose(card); setLibraryOpen(false); } }}>使用此模板</button></footer>
    </Dialog>}
    {previewCard && previewLook && <Dialog title={previewLook.name} className={styles.templatePreviewDialog} onClose={() => setPreview(undefined)}><div className={styles.templatePreview}>
      <div className={styles.previewStage}><div className={styles.previewScreen}>{previewUrl && <video key={previewUrl} src={mediaUrl(previewUrl)} poster={mediaUrl(preview?.project ? undefined : previewCard.example?.poster_url || previewCard.style_preview?.poster_url || undefined)} controls autoPlay muted playsInline preload="metadata" aria-label={`${previewLook.name}${preview?.project ? "本项目成片" : "模板示例"}`} onError={() => setPlaybackError(true)} />}</div><div className={styles.previewNavigation}><button type="button" aria-label="上一个模板" disabled={previewList.length < 2} onClick={() => movePreview(-1)}><ChevronLeft size={18} /></button><span>{previewIndex + 1} / {previewList.length}</span><button type="button" aria-label="下一个模板" disabled={previewList.length < 2} onClick={() => movePreview(1)}><ChevronRight size={18} /></button></div></div>
      <div className={styles.previewDetails}><span className={styles.templateCategory}>{previewLook.collection}</span><h3>{previewLook.name}</h3><p className={styles.signature}>{previewLook.detail}</p><p>{previewLook.hint}</p><p>{previewCard.material_requirements.slice(0, 2).join(" · ")}</p>
        {!previewCard.example && !preview?.project && <small>历史题材片段，仅供版式参考</small>}
        {playbackError && <p role="alert">示例暂时无法播放，请关闭后重试。</p>}
        <small>{preview?.project ? "正在观看本项目已有成片" : "正在观看已有模板示例"} · 点击播放器开启声音</small>
        {ownSample && <div className={styles.sampleTabs} role="group" aria-label="预览来源"><button type="button" aria-pressed={!preview?.project} onClick={() => openPreview(previewCard)}>模板示例</button><button type="button" aria-pressed={!!preview?.project} onClick={() => openPreview(previewCard, true)}>本项目成片</button></div>}
        <button type="button" className={styles.useTemplate} onClick={() => { choose(previewCard); setPreview(undefined); setLibraryOpen(false); }}>使用此模板</button>
      </div>
    </div></Dialog>}
  </section>;
}
