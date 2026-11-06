"use client";

import { ArrowRight, BookOpenText, FileText, Search } from "lucide-react";
import { Empty } from "./studio-primitives";
import { TextDocument } from "./studio-content";
import styles from "./video-studio.module.css";

type SavedCopy = { id:string; title:string; text:string; date:string };
export function ScriptLibrary({ copies, compact, keyword, onUse, onCopy, onCreate }: { copies:SavedCopy[]; compact:boolean; keyword:string; onUse:(copy:SavedCopy)=>void; onCopy:(text:string)=>void; onCreate:()=>void }) {
  const query = compact ? "" : keyword.trim().toLocaleLowerCase();
  const visible = copies.filter(copy=>`${copy.title} ${copy.text}`.toLocaleLowerCase().includes(query));
  if (!copies.length) return <Empty icon={<BookOpenText size={27} />} title="还没有保存的文案" description="把满意的文案存下来，下次创作直接使用。" action={!compact && <button type="button" className={styles.primaryButton} onClick={onCreate}>开始创作</button>} />;
  if (!visible.length) return <Empty icon={<Search size={25} />} title="没有找到匹配文案" description="换一个标题或文案关键词试试。" />;
  return <div className={`${styles.copyList} ${compact ? styles.compactList : ""}`}>{visible.map(copy=><article key={copy.id}>
    <div><FileText size={16} /><b title={copy.title}>{copy.title}</b><time>{new Date(copy.date).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"})}</time></div>
    <TextDocument text={copy.text} title="文案预览" onCopy={onCopy} />
    <button type="button" className={styles.textButton} onClick={()=>onUse(copy)}>使用文案<ArrowRight size={14} /></button>
  </article>)}</div>;
}
