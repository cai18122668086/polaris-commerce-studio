"use client";

import { useState } from "react";
import { Ellipsis, Pause, Play, Plus } from "lucide-react";
import { mediaUrl } from "@/lib/api/base-url";
import type { usePersonas, VideoPersona } from "@/features/video-studio/personas";
import { personaNameError } from "@/features/video-studio/persona-rules";
import { useAudition } from "./persona-create-drawer";
import base from "./video-studio.module.css";
import styles from "./library-drawers.module.css";

type Personas = ReturnType<typeof usePersonas>;
const label = (name: string) => name.replace(/-(sit_body|whole_body)$/, "").replaceAll("-", " · ");

/** 形象库第一个分区「我的固定形象」：封面 + 名字 + 声音名 + 试听；改名 / 删除 / 使用。 */
export function PersonaShelf({ personas, onCreate, onUse, onError }: { personas: Personas; onCreate: () => void; onUse?: (persona: VideoPersona) => void; onError?: (text: string) => void }) {
  const audition = useAudition();
  const [editing, setEditing] = useState("");
  const [draftName, setDraftName] = useState("");
  const [confirming, setConfirming] = useState("");
  const [busy, setBusy] = useState("");
  const [menu, setMenu] = useState("");
  const run = async (id: string, task: () => Promise<unknown>) => {
    if (busy) return; setBusy(id);
    try { await task(); } catch (reason) { onError?.(reason instanceof Error ? reason.message : "操作没有完成，请重试。"); } finally { setBusy(""); }
  };
  const rename = (persona: VideoPersona) => {
    const error = personaNameError(draftName, personas.personas.filter(item => item.id !== persona.id).map(item => item.name));
    if (error) { onError?.(error); return; }
    void run(persona.id, async () => { await personas.update(persona.id, { name: draftName.trim() }); setEditing(""); });
  };
  return <section className={styles.shelf} aria-labelledby="persona-shelf-title">
    <div className={styles.shelfHead}>
      <div><h2 id="persona-shelf-title">我的固定形象</h2><p>形象和声音搭配好存起来，口播时选一个就同时带出两者，适合矩阵账号长期复用。</p></div>
      {personas.personas.length > 0 && <button type="button" className={base.outlineButton} onClick={onCreate}><Plus size={15} />新建固定形象</button>}
    </div>
    {personas.error && <p className={styles.error} role="alert">{personas.error}</p>}
    <div className={styles.personaGrid}>
      {personas.personas.map(persona => <article key={persona.id} className={styles.personaCard} aria-label={persona.name}>
        <div className={styles.personaCover} data-unavailable={!persona.available}>
          {persona.cover_url ? <img src={mediaUrl(persona.cover_url)} alt={`${persona.name}的形象`} loading="lazy" /> : null}
          {!persona.available && <span className={styles.status} data-tone={persona.unavailable_reason?.includes("定制中") ? "busy" : "failed"}>{persona.unavailable_reason?.includes("定制中") ? "形象定制中" : "不可用"}</span>}
          <div className={styles.cardMenu}>
            <button type="button" className={styles.menuButton} aria-label={`${persona.name}的更多操作`} aria-expanded={menu === persona.id} onClick={() => { setMenu(menu === persona.id ? "" : persona.id); setConfirming(""); }}><Ellipsis size={16} /></button>
            {menu === persona.id && <div className={styles.menuPanel} role="menu">
              {confirming === persona.id ? <>
                <p>删除后不影响已生成的视频，形象和声音本身也会保留。</p>
                <button type="button" role="menuitem" className={styles.danger} disabled={busy === persona.id} onClick={() => void run(persona.id, async () => { await personas.remove(persona.id); setMenu(""); })}>{busy === persona.id ? "正在删除…" : "确认删除"}</button>
                <button type="button" role="menuitem" onClick={() => setConfirming("")}>取消</button>
              </> : <>
                <button type="button" role="menuitem" onClick={() => { setEditing(persona.id); setDraftName(persona.name); setMenu(""); }}>改名</button>
                <button type="button" role="menuitem" className={styles.danger} onClick={() => setConfirming(persona.id)}>删除</button>
              </>}
            </div>}
          </div>
        </div>
        <div className={styles.personaMeta}>
          {editing === persona.id ? <div className={styles.renameRow}>
            <input aria-label="新名字" value={draftName} maxLength={30} autoFocus onChange={event => setDraftName(event.target.value)} onKeyDown={event => { if (event.key === "Enter") rename(persona); if (event.key === "Escape") setEditing(""); }} />
            <button type="button" className={styles.linkButton} disabled={busy === persona.id} onClick={() => rename(persona)}>保存</button>
          </div> : <b title={persona.name}>{persona.name}</b>}
          <span title={`${label(persona.avatar_name)} · ${persona.voice_name}`}>{label(persona.avatar_name)} · {persona.voice_name}</span>
          {!persona.available && persona.unavailable_reason && <span className={styles.reason}>{persona.unavailable_reason}</span>}
          <div className={styles.personaActions}>
            {persona.voice_preview_url
              ? <button type="button" className={styles.listen} aria-label={`试听${persona.voice_name}`} onClick={() => audition.toggle(persona.id, persona.voice_preview_url)}>{audition.playing === persona.id ? <Pause size={12} /> : <Play size={12} />}{audition.playing === persona.id ? "停止" : "试听"}</button>
              : <span className={styles.noPreview}>暂无试听</span>}
            {onUse && <button type="button" className={styles.useButton} disabled={!persona.available} onClick={() => onUse(persona)}>使用</button>}
          </div>
        </div>
      </article>)}
      <button type="button" className={styles.newCard} onClick={onCreate}><Plus size={20} /><b>新建固定形象</b><small>选一个形象 + 一个声音，起个名字就好</small></button>
    </div>
  </section>;
}
