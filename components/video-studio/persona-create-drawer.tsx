"use client";

import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { mediaUrl } from "@/lib/api/base-url";
import type { useVideoLibrary, VideoAvatar, VideoVoice } from "@/features/video-studio/library";
import type { usePersonas, VideoPersona } from "@/features/video-studio/personas";
import { personaNameError } from "@/features/video-studio/persona-rules";
import { SideDrawer } from "./side-drawer";
import base from "./video-studio.module.css";
import styles from "./library-drawers.module.css";

type Library = Pick<ReturnType<typeof useVideoLibrary>, "avatars" | "voices">;
type Personas = Pick<ReturnType<typeof usePersonas>, "personas" | "create">;
const avatarLabel = (item: VideoAvatar) => item.name.replace(/-(sit_body|whole_body)$/, "").replaceAll("-", " · ");

/** 单个音频播放器：同一时间只放一个试听。 */
export function useAudition() {
  const player = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState("");
  useEffect(() => () => { player.current?.pause(); }, []);
  const toggle = (id: string, url: string | null | undefined) => {
    if (!url) return;
    if (playing === id) { player.current?.pause(); setPlaying(""); return; }
    player.current?.pause();
    const audio = new Audio(mediaUrl(url));
    audio.onended = () => setPlaying(current => current === id ? "" : current);
    audio.onerror = () => setPlaying(current => current === id ? "" : current);
    player.current = audio; setPlaying(id);
    void audio.play().catch(() => setPlaying(""));
  };
  return { playing, toggle };
}

/**
 * 新建固定形象抽屉（契约 C4）：选形象（我的 / 公共）+ 选声音（系统 / 我的克隆）+ 起名。
 * onCreated(persona)：保存成功后回调，persona 字段同 GET /personas（含封面、声音名、试听地址）。
 */
export function PersonaCreateDrawer({ open, onClose, library, personas, onCreated, initialAvatarId = "", initialVoiceId = "" }: { open: boolean; onClose: () => void; library: Library; personas: Personas; onCreated?: (persona: VideoPersona) => void; initialAvatarId?: string; initialVoiceId?: string }) {
  const [name, setName] = useState("");
  const [avatarId, setAvatarId] = useState(initialAvatarId);
  const [voiceId, setVoiceId] = useState(initialVoiceId);
  const [avatarTab, setAvatarTab] = useState<"own" | "public">(library.avatars.some(item => item.id === initialAvatarId && item.source === "quanyu_public") ? "public" : "own");
  const [voiceTab, setVoiceTab] = useState<"system" | "own">(library.voices.some(item => item.id === initialVoiceId && item.source === "own") ? "own" : "system");
  const [keyword, setKeyword] = useState("");
  const [voiceKeyword, setVoiceKeyword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [touched, setTouched] = useState(false);
  const requestId = useRef("");
  const audition = useAudition();

  const own = library.avatars.filter(item => item.source === "self_owned");
  const shownAvatars = (avatarTab === "own" ? own : library.avatars.filter(item => item.source === "quanyu_public"))
    .filter(item => `${item.name}${item.tag}`.toLowerCase().includes(keyword.trim().toLowerCase()));
  const usableVoices = library.voices.filter(item => item.available !== false);
  const shownVoices = usableVoices.filter(item => (voiceTab === "own" ? item.source === "own" : item.source !== "own") && `${item.name}${item.tag}${item.description}`.toLowerCase().includes(voiceKeyword.trim().toLowerCase()))
    .sort((a, b) => Number(!!b.preview_url) - Number(!!a.preview_url));
  const avatar = library.avatars.find(item => item.id === avatarId);
  const voice = library.voices.find(item => item.id === voiceId);
  const nameError = personaNameError(name, personas.personas.map(item => item.name));
  const ready = !nameError && !!avatar && !!voice;

  const submit = async () => {
    setTouched(true);
    if (!ready || busy || !avatar || !voice) return;
    requestId.current ||= crypto.randomUUID();
    setBusy(true); setError("");
    try {
      const persona = await personas.create({ name: name.trim(), avatar_id: avatar.id, voice_id: voice.id }, requestId.current);
      requestId.current = ""; setName(""); setTouched(false);
      onCreated?.(persona); onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存没有完成，请重试；重复提交不会建出两个。");
    } finally { setBusy(false); }
  };

  const footer = <>
    <span className={styles.footerNote}>{avatar && voice ? `${avatarLabel(avatar)} · ${voice.name}` : "选好形象和声音后起个名字"}</span>
    <button type="button" className={base.outlineButton} disabled={busy} onClick={onClose}>取消</button>
    <button type="button" className={base.primaryButton} disabled={busy || !avatar || !voice} onClick={() => void submit()}>{busy ? "正在保存…" : "保存固定形象"}</button>
  </>;

  const voiceRow = (item: VideoVoice) => <div key={item.id} className={styles.voiceChoice} data-selected={voiceId === item.id}>
    <button type="button" aria-pressed={voiceId === item.id} onClick={() => setVoiceId(item.id)}><b>{item.name}</b><small>{[item.gender !== "未知" ? item.gender : "", item.language || item.tag, item.description].filter(Boolean).join(" · ")}</small></button>
    {item.preview_url
      ? <button type="button" className={styles.listen} aria-label={`试听${item.name}`} onClick={() => audition.toggle(item.id, item.preview_url)}>{audition.playing === item.id ? <Pause size={12} /> : <Play size={12} />}{audition.playing === item.id ? "停止" : "试听"}</button>
      : <span className={styles.noPreview}>暂无试听</span>}
  </div>;

  return <SideDrawer open={open} title="新建固定形象" description="把形象和声音搭配好存起来，口播时选一个就同时带出两者。" onClose={onClose} closeDisabled={busy} footer={footer}>
    <label className={styles.field}><span>名字</span><input aria-label="固定形象名字" value={name} maxLength={30} placeholder="例如：门店店长·暖光" onChange={event => setName(event.target.value)} onBlur={() => setTouched(true)} /></label>
    {touched && nameError && <p className={styles.error} role="alert">{nameError}</p>}

    <section className={styles.field} aria-label="选择形象">
      <p className={styles.sectionLabel}>形象<small>{avatar ? `已选：${avatarLabel(avatar)}` : "未选择"}</small></p>
      <div className={styles.choiceTabs} role="tablist" aria-label="形象来源">{([["own", `我的形象 ${own.length}`], ["public", "公共形象"]] as const).map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={avatarTab === key} onClick={() => setAvatarTab(key)}>{label}</button>)}</div>
      {avatarTab === "public" && <input className={styles.search} aria-label="搜索形象" placeholder="搜索形象" value={keyword} onChange={event => setKeyword(event.target.value)} />}
      {shownAvatars.length ? <div className={styles.avatarChoices}>{shownAvatars.map(item => <button key={item.id} type="button" className={styles.avatarChoice} aria-pressed={avatarId === item.id} onClick={() => setAvatarId(item.id)}>
        <span><img src={mediaUrl(item.cover_url)} alt="" loading="lazy" />{!item.ready && <span className={styles.status} data-tone="busy">{item.id.startsWith("own-avatar-") ? "定制中" : "需生成动作"}</span>}</span>
        <b>{avatarLabel(item)}</b>
      </button>)}</div> : <p className={styles.notice}>{avatarTab === "own" ? "还没有定制形象。可以先选公共形象，或在形象库里定制一个。" : "没有找到匹配的形象。"}</p>}
      {avatar && !avatar.ready && <p className={styles.notice}>这个形象还在定制中。可以先保存搭配，固定形象卡会标「形象定制中」，定制完成后自动可用。</p>}
    </section>

    <section className={styles.field} aria-label="选择声音">
      <p className={styles.sectionLabel}>声音<small>{voice ? `已选：${voice.name}` : "未选择"}</small></p>
      <div className={styles.choiceTabs} role="tablist" aria-label="声音来源">{([["system", "系统声音"], ["own", "我的声音"]] as const).map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={voiceTab === key} onClick={() => setVoiceTab(key)}>{label}</button>)}</div>
      {voiceTab === "system" && <input className={styles.search} aria-label="搜索声音" placeholder="搜索声音，例如：女声、新闻、温柔" value={voiceKeyword} onChange={event => setVoiceKeyword(event.target.value)} />}
      {shownVoices.length ? <div className={styles.voiceChoices}>{shownVoices.map(voiceRow)}</div> : <p className={styles.notice}>{voiceTab === "own" ? "还没有可用的专属声音（声音克隆暂未开通），先用系统声音吧。" : voiceKeyword.trim() && usableVoices.some(item => item.source !== "own") ? "没有找到匹配的声音，换个关键词试试，例如：女声、男声、温柔。" : "系统声音暂时读不到，请稍后重试。"}</p>}
    </section>
    {error && <p className={styles.error} role="alert">{error}</p>}
  </SideDrawer>;
}
