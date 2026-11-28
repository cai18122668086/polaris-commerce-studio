"use client";

import type { ReactNode } from "react";
import { Copy } from "lucide-react";
import { LIBRARY_PLATFORM_LABEL, TITLE_LIMIT, scriptStats, titleLength, titleWarning, type LibraryEdit, type LibraryPlatform } from "@/features/video-studio/script-library-format";
import css from "./script-library.module.css";

type Parts = { publish_title: string; publish_body: string; script: string; platform: LibraryPlatform | "" };

/**
 * 一条文案的三块：标题 / 发布正文 / 口播稿。每块单独复制；编辑时三块一起改，
 * 存的是文案库里同一条的新版本。
 */
export function ScriptParts({ parts, edit, onChange, onCopy, scriptMaxHeight, hideScript, legacy }: {
  parts: Parts; edit?: LibraryEdit | null; onChange?: (edit: LibraryEdit) => void;
  onCopy: (text: string) => void; scriptMaxHeight?: number; hideScript?: boolean;
  /** 改版前生成、只有口播稿的版本：标题和正文两块换成一句说明 + 这里传入的操作（补写按钮）。 */
  legacy?: ReactNode;
}) {
  const platform = parts.platform;
  const limit = platform ? TITLE_LIMIT[platform] : null;
  const title = edit ? edit.publish_title : parts.publish_title;
  const stats = scriptStats(edit ? edit.script : parts.script);
  const warning = titleWarning(title, platform);
  const copy = (text: string, label: string) => <button type="button" className={css.copy} onClick={() => onCopy(text)} disabled={!text.trim()} aria-label={`复制${label}`}><Copy size={13} />复制</button>;
  const legacyView = legacy !== undefined && !edit;
  return <div className={css.parts}>
    {legacyView && <section className={css.part} data-legacy>
      <p className={css.legacyNote}>这一版生成于旧版本，没有标题和正文</p>
      {legacy}
    </section>}
    {!legacyView && <><section className={css.part}>
      <header>
        <span className={css.partLabel}>标题</span>
        <small className={warning ? css.warnText : undefined}>{platform ? `${LIBRARY_PLATFORM_LABEL[platform]} · ` : ""}{titleLength(title.trim())}{limit ? ` / ${limit}` : ""} 字</small>
        {!edit && copy(parts.publish_title, "标题")}
      </header>
      {edit && onChange
        ? <input className={css.titleInput} aria-label="标题" value={edit.publish_title} maxLength={80} placeholder="写一个发布用的标题" onChange={event => onChange({ ...edit, publish_title: event.target.value })} />
        : <p className={css.titleText}>{parts.publish_title || <span className={css.placeholder}>还没有标题</span>}</p>}
      {edit && warning && <small className={css.warnText}>{warning}</small>}
    </section>
    <section className={css.part}>
      <header>
        <span className={css.partLabel}>发布正文</span>
        <small>可直接粘贴发布</small>
        {!edit && copy(parts.publish_body, "发布正文")}
      </header>
      {edit && onChange
        ? <textarea className={css.field} aria-label="发布正文" rows={5} maxLength={2000} value={edit.publish_body} placeholder="正文和 #话题 标签" onChange={event => onChange({ ...edit, publish_body: event.target.value })} />
        : <p className={css.bodyText}>{parts.publish_body || <span className={css.placeholder}>还没有发布正文</span>}</p>}
    </section></>}
    {!hideScript && <section className={css.part}>
      <header>
        <span className={css.partLabel}>口播稿</span>
        <small>{stats.label}</small>
        {!edit && copy(parts.script, "口播稿")}
      </header>
      {edit && onChange
        ? <textarea className={css.field} aria-label="口播稿" rows={9} maxLength={3000} value={edit.script} onChange={event => onChange({ ...edit, script: event.target.value })} />
        : <p className={css.scriptText} style={scriptMaxHeight ? { maxHeight: scriptMaxHeight } : undefined}>{parts.script}</p>}
    </section>}
  </div>;
}
