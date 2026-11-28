"use client";

/* 创作首页的创作输入框（熔光 studio 原型的 composer）。
   首页首屏输入的文字通过 ?prompt= 带进来预填；同一标签页内切换市场时保留（sessionStorage）。 */

import { useEffect, useRef, useState } from "react";
import { ArrowDown, Sparkles } from "lucide-react";

import { CREATION_BRIEF_KEY as STORAGE_KEY } from "@/lib/creation-brief";

import styles from "./creation-brief.module.css";
const MAX = 2000;

export function CreationBrief({ initial }: { initial?: string | null }) {
  const [text, setText] = useState(() => (initial ?? "").slice(0, MAX));
  const area = useRef<HTMLTextAreaElement>(null);
  const fromHome = Boolean(initial && initial.trim());

  // 没有从首页带文字时，恢复本标签页里上次写的内容
  useEffect(() => {
    if (fromHome) { window.sessionStorage.setItem(STORAGE_KEY, initial!.slice(0, MAX)); return; }
    const saved = window.sessionStorage.getItem(STORAGE_KEY);
    if (saved) setText(saved); // eslint-disable-line react-hooks/set-state-in-effect -- 只在挂载时读取一次本地草稿
  }, [fromHome, initial]);

  // 从首页带文字进来时，把光标放到末尾，方便接着写
  useEffect(() => {
    if (!fromHome || !area.current) return;
    const el = area.current; el.focus({ preventScroll: true }); el.setSelectionRange(el.value.length, el.value.length);
  }, [fromHome]);

  const update = (value: string) => { const v = value.slice(0, MAX); setText(v); window.sessionStorage.setItem(STORAGE_KEY, v); };

  return (
    <section className={styles.composer} aria-label="创作输入">
      <label className={styles.label} htmlFor="creation-brief">描述你的商品和想要的画面</label>
      <textarea
        id="creation-brief"
        ref={area}
        className={styles.field}
        data-bare
        rows={3}
        value={text}
        maxLength={MAX}
        onChange={(event) => update(event.target.value)}
        placeholder="例如：白色身体乳，浴室晨光，天猫主图 5 张"
      />
      <div className={styles.foot}>
        <span className={styles.hint}>{fromHome ? "已带入你在首页写的描述，可以继续修改。" : "先写下商品和画面，再在下方选一套图开始创作。"}</span>
        <a className={styles.go} href="#creation-options"><Sparkles size={15} aria-hidden="true" />选择套图<ArrowDown size={15} aria-hidden="true" /></a>
      </div>
    </section>
  );
}
