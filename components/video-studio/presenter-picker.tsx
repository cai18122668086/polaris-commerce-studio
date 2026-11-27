"use client";

import { useState } from "react";
import { Check, Library, Link2, Plus, Search, UserRound, UsersRound, X } from "lucide-react";
import type { VideoAvatar, VideoVoice } from "@/features/video-studio/library";
import type { GenerationJob } from "@/features/video-studio/library";
import type { VideoPersona } from "@/features/video-studio/personas";
import { ownAvatarStatus } from "@/features/video-studio/persona-rules";
import { mediaUrl } from "@/lib/api/base-url";
import { Dialog, Empty, PickerFooter, PickerTabs } from "./studio-primitives";
import baseStyles from "./video-studio.module.css";
import pickerStyles from "./selection-controls.module.css";
import own from "./talking-studio.module.css";
const styles = { ...baseStyles, ...pickerStyles };

export type PresenterChoice = { kind: "persona"; persona: VideoPersona } | { kind: "avatar"; avatar: VideoAvatar };
type Tab = "persona" | "own" | "public";

export const avatarLabel = (avatar: Pick<VideoAvatar, "name">) => avatar.name.replace(/-(sit_body|whole_body)$/, "").replaceAll("-", " · ");

/**
 * 选数字人：固定形象（形象+声音已绑定）→ 我的形象 → 公共形象。
 * 「+ 新建固定形象」「+ 定制新形象」：W6 的抽屉合入前先去形象库，口播页的设置已存草稿，回来不丢。
 */
export function PresenterPicker({ title, personas, avatars, voices, jobs = [], selected, onApply, onClose, onCreatePersona, onCreateAvatar }: {
  title: string; personas: VideoPersona[]; avatars: VideoAvatar[]; voices: VideoVoice[]; jobs?: GenerationJob[];
  selected: { personaId?: string; avatarId?: string };
  onApply: (choice: PresenterChoice) => void; onClose: () => void; onCreatePersona: () => void; onCreateAvatar: () => void;
}) {
  const ready = avatars.filter(avatar => avatar.ready);
  // 我的形象：可用的在前；定制中/待确认的也列出来但置灰，完成后自动可选。
  const mine = [...ready.filter(avatar => avatar.source === "self_owned"), ...avatars.filter(avatar => avatar.source === "self_owned" && !avatar.ready)];
  const pub = ready.filter(avatar => avatar.source === "quanyu_public");
  const usable = personas;
  const initialTab: Tab = selected.personaId && usable.length ? "persona" : avatars.find(a => a.id === selected.avatarId)?.source === "self_owned" ? "own" : usable.some(p => p.available !== false) ? "persona" : ready.some(a => a.source === "self_owned") ? "own" : "public";
  const [tab, setTab] = useState<Tab>(initialTab);
  const [search, setSearch] = useState("");
  const [choice, setChoice] = useState<PresenterChoice | undefined>(() => {
    const persona = personas.find(p => p.id === selected.personaId);
    if (persona) return { kind: "persona", persona };
    const avatar = avatars.find(a => a.id === selected.avatarId);
    return avatar ? { kind: "avatar", avatar } : undefined;
  });
  const keyword = search.trim().toLocaleLowerCase();
  const avatarList = (tab === "own" ? mine : pub).filter(avatar => `${avatar.name} ${avatar.tag}`.toLocaleLowerCase().includes(keyword));
  const personaList = usable.filter(persona => persona.name.toLocaleLowerCase().includes(keyword));
  const coverOf = (id: string) => avatars.find(a => a.id === id)?.cover_url;
  const voiceName = (id: string) => voices.find(v => v.id === id)?.name;
  const selectedLabel = choice?.kind === "persona" ? choice.persona.name : choice ? avatarLabel(choice.avatar) : undefined;
  const jobOf = (avatarId: string) => jobs.find(job => job.kind === "h3_template" && job.avatar_id === avatarId);
  const card = (key: string, active: boolean, cover: string | undefined | null, name: string, note: string, pick: () => void, blocked = "") => <article key={key} className={`${styles.avatarPickerCard} ${active ? styles.avatarPickerSelected : ""} ${blocked ? own.pickerBlocked : ""}`}>
    <button type="button" className={styles.avatarPickerSelect} aria-label={blocked ? `${name}：${blocked}` : `选择${name}`} aria-pressed={active} disabled={!!blocked} onClick={pick}>
      <span className={styles.avatarPickerStage}>
        <img className={styles.avatarPickerBackdrop} src={mediaUrl(cover || undefined)} alt="" aria-hidden="true" loading="lazy" />
        <img className={styles.avatarPickerPortrait} src={mediaUrl(cover || undefined)} alt={name} loading="lazy" />
        {active && <span className={styles.avatarPickerCheck}><Check size={13} /></span>}
      </span>
      {blocked && <span className={own.blockedTag}>{blocked.includes("定制") ? "形象定制中" : "暂不可用"}</span>}
      <span className={styles.avatarPickerCaption}><b title={name}>{name}</b><small>{blocked || note}</small></span>
    </button>
  </article>;

  return <Dialog title={title} className={styles.avatarPickerDialog} onClose={onClose}>
    <PickerTabs label="数字人来源" value={tab} onChange={value => { setTab(value as Tab); setSearch(""); }} items={[
      { id: "persona", label: `固定形象${usable.length ? ` ${usable.length}` : ""}`, icon: <Link2 size={15} /> },
      { id: "own", label: `我的形象${mine.length ? ` ${mine.length}` : ""}`, icon: <UserRound size={15} /> },
      { id: "public", label: "公共形象", icon: <Library size={15} /> },
    ]} />
    <div className={own.pickerTools}>
      <label className={styles.pickerSearch}><Search size={16} /><input aria-label="搜索数字人" placeholder={tab === "persona" ? "搜索固定形象" : "搜索数字人"} value={search} onChange={event => setSearch(event.target.value)} />{search && <button type="button" aria-label="清空搜索" onClick={() => setSearch("")}><X size={14} /></button>}</label>
      {tab === "persona" ? <button type="button" className={own.quietButton} onClick={onCreatePersona}><Plus size={14} />新建固定形象</button> : tab === "own" ? <button type="button" className={own.quietButton} onClick={onCreateAvatar}><Plus size={14} />定制新形象</button> : null}
    </div>
    <p className={own.pickerHint}>{tab === "persona" ? "固定形象已绑定好形象和声音，选一个就完成这一条的设置。" : tab === "own" ? "你定制过的形象。正在定制中的形象完成后会出现在这里。" : "公共形象随时可用，之后在第 ③ 步选音色。"}</p>
    <div className={styles.avatarPickerResults} aria-label="数字人列表">
      {tab === "persona"
        ? personaList.length ? <div className={styles.avatarPickerGrid}>{personaList.map(persona => card(persona.id, choice?.kind === "persona" && choice.persona.id === persona.id, persona.cover_url || coverOf(persona.avatar_id), persona.name, `声音 · ${persona.voice_name || voiceName(persona.voice_id) || "已绑定"}`, () => setChoice({ kind: "persona", persona }), persona.available === false ? persona.unavailable_reason || "暂时不能使用" : ""))}</div>
          : <Empty icon={<Link2 size={28} />} title={search ? "没有找到匹配的固定形象" : "还没有固定形象"} description="把常用的形象和声音绑在一起，下次选一个就行。" action={<button type="button" className={styles.outlineButton} onClick={onCreatePersona}>新建固定形象</button>} />
        : avatarList.length ? <div className={styles.avatarPickerGrid}>{avatarList.map(avatar => card(avatar.id, choice?.kind === "avatar" && choice.avatar.id === avatar.id, avatar.cover_url, avatarLabel(avatar), avatar.gender === "未知" ? avatar.tag : `${avatar.gender} · ${avatar.tag}`, () => setChoice({ kind: "avatar", avatar }), avatar.ready ? "" : avatar.source === "self_owned" ? `${ownAvatarStatus(avatar, jobOf(avatar.id)).label}，完成后可选` : "暂不可用"))}</div>
          : <Empty icon={<UsersRound size={28} />} title={tab === "own" && !search ? "还没有定制形象" : "没有找到匹配形象"} description={tab === "own" ? "可以先用公共形象，或定制一个自己的形象。" : "换个关键词试试。"} action={tab === "own" ? <button type="button" className={styles.outlineButton} onClick={onCreateAvatar}>定制新形象</button> : undefined} />}
    </div>
    <PickerFooter selected={selectedLabel} hint={choice?.kind === "persona" ? "形象和声音一起带入" : undefined} disabled={!choice} applyLabel="使用这个形象" onApply={() => { if (choice) onApply(choice); }} onClose={onClose} />
  </Dialog>;
}
