"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpenText, PencilLine, Plus, Search, Trash2, X } from "lucide-react";
import { LIBRARY_PAGE_SIZE, useScriptLibrary } from "@/features/video-studio/use-script-library";
import {
  LIBRARY_PLATFORM_LABEL, SOURCE_LABEL, bodySummary, displayTitle, editChanged, editOf, pageState, scriptStats, toggle, togglePage,
  type LibraryEdit, type LibraryEntry, type LibraryPlatform,
} from "@/features/video-studio/script-library-format";
import type { ToastTone } from "./studio-toast";
import { PageHero } from "./page-hero";
import { Empty } from "./studio-primitives";
import { ScriptParts } from "./script-library-parts";
import studio from "./video-studio.module.css";
import css from "./script-library.module.css";

const when = (iso: string) => new Date(iso).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
const FILTERS: { key: LibraryPlatform | ""; label: string }[] = [{ key: "", label: "全部" }, { key: "douyin", label: "抖音" }, { key: "xiaohongshu", label: "小红书" }];

/* ----------------------------------------------------------- 详情抽屉 */

function Detail({ entry, busy, onClose, onSave, onDelete, onUse, onCopy }: {
  entry: LibraryEntry; busy: string; onClose: () => void; onSave: (edit: LibraryEdit) => Promise<void>;
  onDelete: () => Promise<void>; onUse: () => void; onCopy: (text: string) => void;
}) {
  const [edit, setEdit] = useState<LibraryEdit | null>(null);
  const [confirming, setConfirming] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => { panel.current?.focus(); }, []);
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  const ref = entry.benchmark_refs[0];
  return <div className={css.overlay} onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={panel} className={css.drawer} role="dialog" aria-modal="true" aria-label="文案详情" tabIndex={-1}>
      <header className={css.drawerHead}>
        <div>
          <b>{displayTitle(entry)}</b>
          <small>{[entry.platform && LIBRARY_PLATFORM_LABEL[entry.platform], SOURCE_LABEL[entry.source], when(entry.created_at), entry.revision > 1 ? `第 ${entry.revision} 版` : ""].filter(Boolean).join(" · ")}</small>
        </div>
        <button type="button" className={css.close} onClick={onClose} aria-label="关闭"><X size={18} /></button>
      </header>
      <div className={css.drawerBody}>
        {!entry.publish_title && !entry.publish_body && !edit && <p className={css.note}>这是改版前存的文案，只有口播稿。可以点「编辑」补上标题和发布正文。</p>}
        <ScriptParts parts={entry} edit={edit} onChange={setEdit} onCopy={onCopy} />
        {ref?.title && <p className={css.note}>参考的爆款：{ref.title}</p>}
      </div>
      <footer className={css.drawerFoot}>
        {edit ? <>
          <button type="button" className={studio.outlineButton} onClick={() => setEdit(null)}>取消</button>
          <button type="button" className={studio.primaryButton} disabled={!!busy || !edit.script.trim() || !editChanged(entry, edit)} onClick={() => void onSave(edit).then(() => setEdit(null))}>{busy === "save" ? "正在保存…" : "保存"}</button>
        </> : confirming ? <>
          <span className={css.confirmText}>删除后文案库里不再显示这条。</span>
          <button type="button" className={studio.outlineButton} onClick={() => setConfirming(false)}>不删了</button>
          <button type="button" className={css.danger} disabled={!!busy} onClick={() => void onDelete()}>{busy === "remove" ? "正在删除…" : "确认删除"}</button>
        </> : <>
          <button type="button" className={css.quiet} onClick={() => setConfirming(true)}><Trash2 size={14} />删除</button>
          <button type="button" className={studio.outlineButton} onClick={() => setEdit(editOf(entry))}><PencilLine size={14} />编辑</button>
          <button type="button" className={studio.primaryButton} onClick={onUse}>用这条去做口播<ArrowRight size={14} /></button>
        </>}
      </footer>
    </div>
  </div>;
}

/* --------------------------------------------------------------- 页面 */

export function ScriptLibraryPage({ workspaceId, notify, copyText, onUseScripts, onWrite }: {
  workspaceId: string; notify: (text: string, tone?: ToastTone) => void; copyText: (text: string) => void;
  onUseScripts: (ids: string[]) => void; onWrite: () => void;
}) {
  const lib = useScriptLibrary(workspaceId);
  const [selected, setSelected] = useState<string[]>([]);
  const [open, setOpen] = useState<LibraryEntry | null>(null);
  const items = lib.page?.items || [];
  const total = lib.page?.total || 0;
  const pageIds = items.map(item => item.id);
  const state = pageState(selected, pageIds);
  const pages = Math.max(1, Math.ceil(total / LIBRARY_PAGE_SIZE));
  const current = Math.floor(lib.offset / LIBRARY_PAGE_SIZE) + 1;
  const filtered = !!lib.query.trim() || !!lib.platform;
  const save = async (edit: LibraryEdit) => {
    if (!open) return;
    try { const next = await lib.save(open, edit); setOpen(next); notify("已保存到文案库", "success"); }
    catch (caught) { notify(caught instanceof Error && caught.message ? caught.message : "没有保存成功，请重试。", "error"); throw caught; }
  };
  const remove = async () => {
    if (!open) return;
    try { await lib.remove(open.id); setSelected(ids => ids.filter(id => id !== open.id)); setOpen(null); notify("已删除"); }
    catch (caught) { notify(caught instanceof Error && caught.message ? caught.message : "没有删除成功，请重试。", "error"); }
  };
  return <div className={css.page} data-selecting={selected.length > 0 || undefined}>
    <PageHero eyebrow="文案库" title="写好的文案，" accent="都在这里"
      description="爆款文案写好的每一版会自动存进来：标题、发布正文和口播稿一起保存。可以挑一条或几条，直接去做口播。"
      facts={[{ label: "已存文案", value: lib.page ? total : "—" }]}
      actions={<button type="button" className={studio.primaryButton} onClick={onWrite}><Plus size={16} />写爆款文案</button>} motif="library" />
    <div className={css.toolbar}>
      <label className={css.search}><Search size={15} /><input data-bare type="search" aria-label="搜索文案" placeholder="搜索标题或正文" value={lib.query} onChange={event => lib.search(event.target.value)} /></label>
      <div className={css.filters} role="radiogroup" aria-label="按平台筛选">
        {FILTERS.map(item => <button key={item.key || "all"} type="button" role="radio" aria-checked={lib.platform === item.key} onClick={() => lib.filter(item.key)}>{item.label}</button>)}
      </div>
      {items.length > 0 && <label className={css.selectAll}>
        <input type="checkbox" checked={state === "all"} ref={node => { if (node) node.indeterminate = state === "some"; }} onChange={() => setSelected(ids => togglePage(ids, pageIds))} />
        全选本页
      </label>}
    </div>
    {lib.error && <p className={css.error} role="alert">{lib.error} <button type="button" className={css.link} onClick={() => void lib.reload()}>重新读取</button></p>}
    {lib.page && !items.length && !lib.loading && (filtered
      ? <Empty icon={<Search size={25} />} title="没有找到匹配的文案" description="换一个关键词或平台试试。" />
      : <Empty icon={<BookOpenText size={27} />} title="文案库还是空的" description="去「爆款文案」写一版，写好会自动存到这里。" action={<button type="button" className={studio.primaryButton} onClick={onWrite}>写爆款文案</button>} />)}
    {items.length > 0 && <ul className={css.list} aria-busy={lib.loading || undefined}>
      {items.map(item => {
        const checked = selected.includes(item.id);
        const stats = scriptStats(item.script);
        const summary = bodySummary(item.publish_body) || (item.publish_title ? "" : bodySummary(item.script.split(/[。！？!?\n]/).slice(1).join("。"), 60));
        return <li key={item.id} data-checked={checked || undefined}>
          <input type="checkbox" className={css.check} checked={checked} aria-label={`选择「${displayTitle(item)}」`} onChange={() => setSelected(ids => toggle(ids, item.id))} />
          <button type="button" className={css.row} onClick={() => setOpen(item)}>
            <b className={css.rowTitle}>{displayTitle(item)}</b>
            {summary && <span className={css.rowSummary}>{summary}</span>}
            <span className={css.rowMeta}>
              <span className={css.metaPlatform}>{item.platform ? LIBRARY_PLATFORM_LABEL[item.platform] : "未标注"}</span>
              <span className={css.metaStats}>口播 {stats.label}</span>
              <time dateTime={item.created_at}>{when(item.created_at)}</time>
            </span>
          </button>
        </li>;
      })}
    </ul>}
    {pages > 1 && <nav className={css.pager} aria-label="翻页">
      <button type="button" disabled={current <= 1 || lib.loading} onClick={() => lib.setOffset(lib.offset - LIBRARY_PAGE_SIZE)}>上一页</button>
      <span>{current} / {pages}</span>
      <button type="button" disabled={current >= pages || lib.loading} onClick={() => lib.setOffset(lib.offset + LIBRARY_PAGE_SIZE)}>下一页</button>
    </nav>}
    {selected.length > 0 && <div className={css.bar} role="region" aria-label="已选文案">
      <span>已选 <b>{selected.length}</b> 条</span>
      <button type="button" className={css.link} onClick={() => setSelected([])}>清空</button>
      <button type="button" className={studio.primaryButton} onClick={() => onUseScripts(selected)}>用这 {selected.length} 条去做口播<ArrowRight size={15} /></button>
    </div>}
    {open && <Detail key={open.id + open.revision} entry={open} busy={lib.busy} onClose={() => setOpen(null)} onSave={save} onDelete={remove} onUse={() => onUseScripts([open.id])} onCopy={copyText} />}
  </div>;
}
