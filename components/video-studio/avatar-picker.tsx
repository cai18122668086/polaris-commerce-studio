"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronLeft, ChevronRight, Library, Play, Search, UserRound, UsersRound, X } from "lucide-react";
import type { VideoAvatar } from "@/features/video-studio/library";
import { Dialog, Empty, PickerFooter, PickerTabs } from "./studio-primitives";
import baseStyles from "./video-studio.module.css";
import pickerStyles from "./selection-controls.module.css";
const styles = { ...baseStyles, ...pickerStyles };

type Props = {
  avatars: VideoAvatar[]; selectedId: string; loading: boolean; error: string;
  onSelect: (id: string) => void; onApply: () => void; onClose: () => void;
  onReload: () => void; onClone: () => void;
};
const PAGE_SIZE = 12;
const labelOf = (avatar: VideoAvatar) => avatar.name.replace(/-(sit_body|whole_body)$/, "").replaceAll("-", " · ");

export function AvatarPicker({ avatars, selectedId, loading, error, onSelect, onApply, onClose, onReload, onClone }: Props) {
  const initial = avatars.find(avatar => avatar.id === selectedId);
  const [tab, setTab] = useState(initial?.source === "self_owned" ? "own" : "public");
  const [gender, setGender] = useState("全部");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [preview, setPreview] = useState<VideoAvatar>();
  const resultsRef = useRef<HTMLDivElement>(null);
  const filtered = avatars.filter(avatar => (tab === "own" ? avatar.source === "self_owned" : avatar.source === "quanyu_public") && (gender === "全部" || avatar.gender === gender) && `${avatar.name} ${avatar.tag}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pages);
  useEffect(() => { resultsRef.current?.scrollTo({ top: 0 }); }, [tab, gender, search, currentPage]);
  const visible = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  const selected = avatars.find(avatar => avatar.id === selectedId);
  const changeTab = (value: string) => { setTab(value); setGender("全部"); setSearch(""); setPage(1); };

  return <Dialog title="选择数字人" className={styles.avatarPickerDialog} onClose={onClose}>
    <PickerTabs label="数字人来源" value={tab} onChange={changeTab} items={[{ id: "own", label: "我的定制", icon: <UserRound size={15} /> }, { id: "public", label: "公共模特", icon: <Library size={15} /> }]} />
    <div className={styles.avatarPickerFilters}>
      <div className={styles.pickerSegments} role="group" aria-label="筛选数字人性别">{["全部", "男", "女"].map(value => <button key={value} type="button" aria-pressed={gender === value} onClick={() => { setGender(value); setPage(1); }}>{value}</button>)}</div>
      <label className={styles.pickerSearch}><Search size={16} /><input aria-label="搜索数字人" placeholder="搜索数字人" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} />{search && <button type="button" aria-label="清空数字人搜索" onClick={() => { setSearch(""); setPage(1); }}><X size={14} /></button>}</label>
    </div>
    <div className={styles.pickerResultMeta}><span>{tab === "own" ? "我的数字人" : "公共数字人"}<b>{filtered.length}</b></span><small>点击选择形象，播放查看动作</small></div>
    <div ref={resultsRef} className={styles.avatarPickerResults} aria-label="数字人列表" aria-busy={loading}>
      {loading ? <div className={styles.avatarPickerGrid} aria-label="正在加载数字人">{Array.from({ length: 8 }, (_, index) => <div className={styles.avatarSkeleton} key={index} />)}</div> : error ? <Empty icon={<UsersRound size={28} />} title="数字人暂未加载" description={error} action={<button className={styles.outlineButton} onClick={onReload}>重新加载</button>} /> : visible.length ? <div className={styles.avatarPickerGrid} key={`${tab}:${gender}:${search}:${currentPage}`}>
        {visible.map(avatar => <article key={avatar.id} className={`${styles.avatarPickerCard} ${selectedId === avatar.id ? styles.avatarPickerSelected : ""}`}>
          <button type="button" className={styles.avatarPickerSelect} aria-label={`选择${avatar.name}`} aria-pressed={selectedId === avatar.id} onClick={() => onSelect(avatar.id)}>
            <span className={styles.avatarPickerStage}>
              <img className={styles.avatarPickerBackdrop} src={avatar.cover_url || undefined} alt="" aria-hidden="true" loading="lazy" />
              <img className={styles.avatarPickerPortrait} src={avatar.cover_url || undefined} alt={`${avatar.name}完整形象`} loading="lazy" />
              {selectedId === avatar.id && <span className={styles.avatarPickerCheck}><Check size={13} /></span>}
            </span>
            <span className={styles.avatarPickerCaption}><b title={avatar.name}>{labelOf(avatar)}</b><small>{avatar.source === "self_owned" && !avatar.ready ? "待生成动作" : avatar.gender === "未知" ? avatar.tag : `${avatar.gender} · ${avatar.tag}`}</small></span>
          </button>
          <button type="button" className={styles.avatarPickerPreview} aria-label={`预览${avatar.name}`} onClick={() => setPreview(avatar)}><Play size={13} fill="currentColor" /><span>预览</span></button>
        </article>)}
      </div> : <Empty icon={<UsersRound size={29} />} title={tab === "own" && !search && gender === "全部" ? "暂无定制数字人" : "没有找到匹配形象"} description={tab === "own" ? "可以先选择公共模特，或查看形象克隆。" : "试试其他关键词，或重置筛选。"} action={tab === "own" ? <button className={styles.outlineButton} onClick={onClone}>查看形象克隆</button> : <button className={styles.outlineButton} onClick={() => { setSearch(""); setGender("全部"); setPage(1); }}>重置筛选</button>} />}
    </div>
    <nav className={styles.pickerPagination} aria-label="数字人分页"><span>共 {filtered.length} 个形象</span><button aria-label="上一页数字人" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={16} /></button>{Array.from({ length: pages }, (_, index) => index + 1).map(number => <button key={number} aria-label={`数字人第${number}页`} aria-current={currentPage === number ? "page" : undefined} onClick={() => setPage(number)}>{number}</button>)}<button aria-label="下一页数字人" disabled={currentPage === pages} onClick={() => setPage(currentPage + 1)}><ChevronRight size={16} /></button></nav>
    <PickerFooter selected={selected ? labelOf(selected) : undefined} disabled={!selected || loading} applyLabel="应用形象" onApply={onApply} onClose={onClose} />
    {preview && <Dialog title={labelOf(preview)} className={styles.pickerPreviewDialog} onClose={() => setPreview(undefined)}>{preview.preview_url ? <video controls playsInline preload="metadata" src={preview.preview_url} className={styles.pickerPreviewMedia} /> : <img src={preview.cover_url || undefined} alt={preview.name} className={styles.pickerPreviewMedia} />}<p className={styles.pickerPreviewNote}>{preview.ready ? "动作模板已就绪，可用于口播创作。" : "参考形象；生成动作模板后可用于口播。"}</p><footer className={styles.dialogFooter}><button className={styles.outlineButton} onClick={() => setPreview(undefined)}>返回选择</button><button className={styles.primaryButton} onClick={() => { onSelect(preview.id); setPreview(undefined); }}>选择此形象</button></footer></Dialog>}
  </Dialog>;
}
