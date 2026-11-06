"use client";

import { ArrowRight, AudioLines, FileText, LoaderCircle } from "lucide-react";
import type { VideoDraft } from "@/features/video-studio/projects";
import { Dialog } from "./studio-primitives";
import { Disclosure, MetadataGrid, Notice, TextDocument } from "./studio-content";
import { languageLabel } from "./generation-details";
import base from "./video-studio.module.css";
import styles from "./generation-details.module.css";

export function GenerationConfirmation({ draft, avatar, voiceName, audioName, language, error, busy, saving, onClose, onConfirm, onCopy }: {
  draft:VideoDraft; avatar:{name:string; cover_url:string}; voiceName?:string; audioName?:string; language?:string; error:string; busy:boolean; saving:boolean; onClose:()=>void; onConfirm:()=>void; onCopy:(text:string)=>void;
}) {
  return <Dialog title="确认生成视频" onClose={onClose}>
    <div className={styles.review}>{avatar.cover_url && <img src={avatar.cover_url} alt={avatar.name} />}<div><h3>{draft.name || "未命名视频"}</h3><span>{avatar.name}</span><small>清晰度跟随所选形象原片</small></div></div>
    <MetadataGrid items={draft.drive === "text" ? [{label:"配音声音",value:voiceName || "已选声音"},{label:"语速",value:`${draft.speed.toFixed(1)}×`},{label:"表达情绪",value:draft.emotion},{label:"配音语言",value:language || languageLabel(draft.language)}] : [{label:"驱动方式",value:"上传音频"},{label:"音频文件",value:audioName || "已上传音频"}]} />
    {draft.drive === "text" ? <Disclosure title="配音确认稿" description="按此文案生成本次配音" icon={<FileText size={17} />} meta={`${draft.text.length} 字`}><TextDocument text={draft.text} title="确认文案" onCopy={onCopy} /></Disclosure> : <Notice><AudioLines size={14} /> 本次使用已上传音频驱动口播。</Notice>}
    <Notice>确认后开始制作，可在“我的作品”查看进度。</Notice>
    {error && <div role="alert"><Notice tone="warning">{error}</Notice></div>}
    <footer className={styles.actions}><button type="button" className={base.outlineButton} disabled={busy} onClick={onClose}>继续编辑</button><button type="button" className={base.primaryButton} disabled={saving || busy} onClick={onConfirm}>{busy ? <><LoaderCircle size={15} />正在提交</> : <>{error ? "查询原提交" : "确认生成"}<ArrowRight size={15} /></>}</button></footer>
  </Dialog>;
}
