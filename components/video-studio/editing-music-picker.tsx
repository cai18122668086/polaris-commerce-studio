"use client";

import { Music2, ChevronRight } from "lucide-react";
import { useState } from "react";
import { editingMusicLabels, type EditingMusicPreference } from "@/features/video-studio/editing-options";
import { Dialog } from "./studio-primitives";
import flow from "./editing-flow.module.css";

export function EditingMusicPicker({ value, onChange, disabled, voiceOnly = false }: {
  value: EditingMusicPreference; onChange: (value: EditingMusicPreference) => void; disabled?: boolean; voiceOnly?: boolean;
}) {
  const [opened, setOpened] = useState(false);
  const [draft, setDraft] = useState(value);
  if (voiceOnly) return <div className={flow.sourceOption}><h3><Music2 size={15} />音乐</h3><label className={flow.voiceOnly}><input type="radio" name="apple-voice-only" checked readOnly />口播原声</label></div>;
  return <div className={flow.sourceOption}>
    <h3><Music2 size={15} />音乐</h3>
    <button type="button" className={flow.optionPicker} disabled={disabled} onClick={() => { setDraft(value); setOpened(true); }}>
      <span>{editingMusicLabels[value]}</span><ChevronRight size={15} />
    </button>
    {opened && <Dialog title="选择配乐" onClose={() => setOpened(false)}>
      <div className={flow.musicChoices} role="radiogroup" aria-label="配乐方式">
        {(Object.keys(editingMusicLabels) as EditingMusicPreference[]).map(choice => <label key={choice}>
          <input type="radio" name="editing-music" checked={draft === choice} onChange={() => setDraft(choice)} />
          <span><b>{editingMusicLabels[choice]}</b><small>{choice === "template" ? "由所选模板搭配背景音乐" : choice === "lower" ? "在模板音量基础上降低，让人声更突出" : "保留口播人声和画面音效"}</small></span>
        </label>)}
      </div>
      <footer className={flow.modalFooter}><button type="button" onClick={() => { onChange(draft); setOpened(false); }}>确定</button></footer>
    </Dialog>}
  </div>;
}
