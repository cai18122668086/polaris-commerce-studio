"use client";

import { useState } from "react";
import { AudioLines, Check, Library, Mic, Pause, Play, Search, UserRound, X } from "lucide-react";
import type { VideoVoice } from "@/features/video-studio/library";
import { Dialog, Empty, PickerFooter, PickerTabs } from "./studio-primitives";
import baseStyles from "./video-studio.module.css";
import pickerStyles from "./selection-controls.module.css";
const styles = { ...baseStyles, ...pickerStyles };

type VoiceBrowserProps = {
  voices: VideoVoice[]; selectedId: string; playingId: string;
  onSelect: (voice: VideoVoice) => void; onPreview: (voice: VideoVoice) => void;
  inDialog?: boolean;
};

export function VoiceBrowser({ voices, selectedId, playingId, onSelect, onPreview, inDialog = false }: VoiceBrowserProps) {
  const [gender, setGender] = useState("全部");
  const [language, setLanguage] = useState("全部");
  const [keyword, setKeyword] = useState("");
  const [search, setSearch] = useState("");
  const visible = voices.filter(voice => (gender === "全部" || voice.gender === gender)
    && (language === "全部" || voice.language === language)
    && `${voice.name} ${voice.tag} ${voice.description}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
    .sort((a, b) => Number(!!b.preview_url) - Number(!!a.preview_url));
  const languages = [...new Set(voices.map(v => v.language).filter((v): v is string => !!v))];
  const playing = voices.find(voice => voice.id === playingId);
  const reset = () => { setGender("全部"); setLanguage("全部"); setKeyword(""); setSearch(""); };

  return <div className={`${styles.voiceBrowser} ${inDialog ? styles.voiceBrowserDialog : ""}`}>
    <div className={styles.voiceFilters}>
      <div className={styles.voiceGenderFilter}><span>性别</span><div className={styles.pickerSegments} role="group" aria-label="筛选音色性别">{["全部", "男", "女"].map(value => <button type="button" key={value} aria-pressed={gender === value} onClick={() => setGender(value)}>{value}</button>)}</div></div>
      <form className={styles.voiceSearchForm} onSubmit={event => { event.preventDefault(); setSearch(keyword.trim()); }}><label className={styles.pickerSearch}><Search size={15} /><input placeholder="搜索音色名称或关键词" aria-label="搜索声音" value={keyword} onChange={event => { setKeyword(event.target.value); if (!event.target.value) setSearch(""); }} />{keyword && <button type="button" aria-label="清空音色搜索" onClick={() => { setKeyword(""); setSearch(""); }}><X size={14} /></button>}</label><button type="submit" className={styles.voiceSearchButton}>搜索</button></form>
      <label className={styles.voiceLanguageFilter}><span>语言</span><select aria-label="筛选音色语言" value={language} onChange={event => setLanguage(event.target.value)}><option>全部</option>{languages.map(value => <option key={value}>{value}</option>)}</select></label>
    </div>
    <div className={styles.pickerResultMeta}><span>{search ? `“${search}”的搜索结果` : voices.some(voice => voice.source === "own") ? "我的声音" : "系统音色"}<b>{visible.length}</b></span><small aria-live="polite">{playing ? <><i className={styles.playingDot} />正在试听 · {playing.name}</> : "点击播放，试听固定短样片"}</small></div>
    <div className={styles.voiceResults} aria-label="音色列表">
      {visible.length ? <div className={styles.voiceRows}>{visible.map(voice => <article key={voice.id} data-playing={playingId === voice.id || undefined} className={`${styles.voiceRow} ${selectedId === voice.id ? styles.voiceRowSelected : ""}`}>
        <button type="button" className={styles.voiceRowSelect} disabled={voice.available === false} aria-label={`选择${voice.name}`} aria-pressed={selectedId === voice.id} onClick={() => onSelect(voice)}><span className={`${styles.voiceAvatar} ${voice.gender === "男" ? styles.voiceAvatarMale : voice.gender === "女" ? styles.voiceAvatarFemale : ""}`}><AudioLines size={22} /></span><span className={styles.voiceRowText}><b title={voice.name}>{voice.name}</b><span>{voice.gender !== "未知" && <small className={voice.gender === "男" ? styles.maleVoiceTag : styles.femaleVoiceTag}>{voice.gender}</small>}<small>{voice.language || voice.tag}</small>{voice.available === false && <small>待启用</small>}</span></span><span className={styles.voiceRowCheck}>{selectedId === voice.id && <Check size={12} />}</span></button>
        <button type="button" className={styles.voicePreviewOverlay} disabled={!voice.preview_url} aria-label={`${playingId === voice.id ? "停止试听" : "试听"}${voice.name}`} aria-pressed={playingId === voice.id} title={voice.preview_url ? "播放缓存样片，不重复合成" : "试听待准备"} onClick={() => onPreview(voice)}>{playingId === voice.id ? <Pause size={13} fill="currentColor" /> : <Play size={13} fill="currentColor" />}</button>
      </article>)}</div> : <Empty icon={<Search size={28} />} title="没有找到匹配声音" description="换一个关键词，或选择其他性别与语言。" action={<button type="button" className={styles.outlineButton} onClick={reset}>重置筛选</button>} />}
    </div>
  </div>;
}

export function VoicePicker({ voices, selectedId, playingId, onSelect, onPreview, onApply, onClose, onClone }: Omit<VoiceBrowserProps, "inDialog"> & { onApply: () => void; onClose: () => void; onClone: () => void }) {
  const [tab, setTab] = useState(voices.find(voice => voice.id === selectedId)?.source === "own" ? "own" : "public");
  const selected = voices.find(voice => voice.id === selectedId);
  const visible = voices.filter(voice => tab === "own" ? voice.source === "own" : voice.source !== "own");
  const selectedInTab = selected && (tab === "own" ? selected.source === "own" : selected.source !== "own");
  const changeTab = (value: string) => { const playing = voices.find(voice => voice.id === playingId); if (playing) onPreview(playing); setTab(value); };
  return <Dialog title="选择声音" className={styles.voiceDialog} onClose={onClose}>
    <PickerTabs label="声音来源" value={tab} onChange={changeTab} items={[{ id: "own", label: "我的声音", icon: <UserRound size={15} /> }, { id: "public", label: "系统声音", icon: <Library size={15} /> }]} />
    {visible.length ? <VoiceBrowser voices={visible} selectedId={selectedId} playingId={playingId} onSelect={onSelect} onPreview={onPreview} inDialog /> : <Empty icon={<Mic size={29} />} title="暂无专属声音" description="上传本人的清晰录音，创建专属声音。" action={<button type="button" className={styles.outlineButton} onClick={onClone}>克隆我的声音</button>} />}
    <PickerFooter selected={selectedInTab ? selected.name : undefined} hint={selectedInTab ? selected.language || selected.tag : undefined} disabled={!selected || selected.available === false || !selectedInTab} applyLabel="应用声音" onApply={onApply} onClose={onClose} />
  </Dialog>;
}
