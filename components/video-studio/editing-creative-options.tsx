"use client";

import { useState } from "react";
import { Image as ImageIcon, ChevronRight } from "lucide-react";
import type { components } from "@/lib/api/generated/openapi";
import { Dialog } from "./studio-primitives";
import flow from "./editing-flow.module.css";

export type AppleCreativeOptions = components["schemas"]["EditingAppleCreativeOptions"];
export const defaultAppleOptions: AppleCreativeOptions = { schema_version: "tengli.apple-creative/1", title: "", subtitle: "", name_card: { enabled: false, name: "", description: "" }, cover: "auto" };

export function EditingCreativeOptions({ value, onChange, disabled }: {
  value: AppleCreativeOptions; onChange: (value: AppleCreativeOptions) => void; disabled?: boolean;
}) {
  const nameCard = value.name_card || defaultAppleOptions.name_card!;
  return <div className={flow.creativeOptions}>
    <h2>文字</h2>
    <label>主标题<input value={value.title || ""} maxLength={60} disabled={disabled} placeholder="选填，根据口播自动生成" onChange={event => onChange({ ...value, title: event.target.value })} /></label>
    <label>副标题<input value={value.subtitle || ""} maxLength={100} disabled={disabled} placeholder="选填，根据口播自动生成" onChange={event => onChange({ ...value, subtitle: event.target.value })} /></label>
    <div className={flow.nameCardHeading}><h3>人物名片</h3><label className={flow.nameCardSwitch}><input type="checkbox" checked={nameCard.enabled || false} disabled={disabled} onChange={event => onChange({ ...value, name_card: { ...nameCard, enabled: event.target.checked } })} /><span>{nameCard.enabled ? "开启" : "关闭"}</span></label></div>
    {nameCard.enabled && <div className={flow.nameCardFields}><label>姓名<input value={nameCard.name || ""} maxLength={32} disabled={disabled} placeholder="请输入姓名" onChange={event => onChange({ ...value, name_card: { ...nameCard, name: event.target.value } })} /></label><label>介绍<input value={nameCard.description || ""} maxLength={80} disabled={disabled} placeholder="请输入身份或介绍" onChange={event => onChange({ ...value, name_card: { ...nameCard, description: event.target.value } })} /></label></div>}
  </div>;
}

export function EditingCoverPicker({ value, onChange, disabled }: {
  value: "auto" | "none"; onChange: (value: "auto" | "none") => void; disabled?: boolean;
}) {
  const [opened, setOpened] = useState(false);
  const [draft, setDraft] = useState(value);
  return <div className={flow.sourceOption}><h3><ImageIcon size={15} />封面</h3><button type="button" className={flow.optionPicker} disabled={disabled} onClick={() => { setDraft(value); setOpened(true); }}><span>{value === "none" ? "不设置封面" : "从成片生成封面"}</span><ChevronRight size={15} /></button>
    {opened && <Dialog title="选择封面" onClose={() => setOpened(false)}><div className={flow.musicChoices} role="radiogroup" aria-label="封面方式">{(["auto", "none"] as const).map(choice => <label key={choice}><input type="radio" name="editing-cover" checked={draft === choice} onChange={() => setDraft(choice)} /><span><b>{choice === "auto" ? "从成片生成封面" : "不设置封面"}</b><small>{choice === "auto" ? "使用成片中的标题画面" : "由视频播放器显示默认画面"}</small></span></label>)}</div><footer className={flow.modalFooter}><button type="button" onClick={() => { onChange(draft); setOpened(false); }}>确定</button></footer></Dialog>}
  </div>;
}
