"use client";

import type { ReactNode } from "react";
import styles from "./page-hero.module.css";

/** Which abstract scene sits in the glass 9:16 frame. Purely decorative, drawn in CSS. */
export type Motif = "script" | "edit" | "works" | "avatar" | "voice" | "library";

const range = (n: number) => Array.from({ length: n }, (_, i) => i);

function MotifInner({ motif }: { motif: Motif }) {
  if (motif === "script") return <div className={styles.script}>{range(6).map(i => <i key={i} style={{ width: `${[86, 72, 92, 64, 80, 40][i]}%`, animationDelay: `${i * 0.45}s` }} />)}<b className={styles.caret} /></div>;
  if (motif === "edit") return <div className={styles.edit}>
    <span className={styles.editFrame} />
    <div className={styles.tracks}>{range(3).map(row => <div key={row}>{range(4).map(i => <i key={i} style={{ flexGrow: [[3, 2, 4, 2], [2, 5, 2, 3], [4, 2, 3, 3]][row][i] }} />)}</div>)}<span className={styles.playhead} /></div>
  </div>;
  if (motif === "works") return <div className={styles.works}><span className={styles.play} /></div>;
  if (motif === "avatar") return <div className={styles.avatar}><span className={styles.ring} /><span className={`${styles.ring} ${styles.ringOuter}`} /><span className={styles.head} /><span className={styles.shoulders} /></div>;
  if (motif === "voice") return <div className={styles.voice}>{range(22).map(i => <i key={i} style={{ animationDelay: `${(i % 7) * 0.14 + (i % 3) * 0.09}s`, height: `${[30, 52, 74, 46, 90, 60, 38][i % 7]}%` }} />)}</div>;
  return <div className={styles.library}>{range(3).map(i => <span key={i} className={styles.doc} style={{ transform: `translate(${(2 - i) * 10}px, ${(2 - i) * -10}px)` }}>{range(4).map(j => <i key={j} />)}</span>)}</div>;
}

/** Glass 9:16 frame with a slow light sweep, a drifting ember glow and one thin orbit line. */
function MotifScene({ motif, compact = false }: { motif: Motif; compact?: boolean }) {
  return <div className={`${styles.scene} ${compact ? styles.sceneCompact : ""}`} aria-hidden="true">
    <span className={styles.glow} />
    <span className={styles.orbit} />
    {motif === "works" && <><span className={`${styles.frame} ${styles.ghostA}`} /><span className={`${styles.frame} ${styles.ghostB}`} /></>}
    <span className={styles.frame}><span className={styles.sweep} /><MotifInner motif={motif} /></span>
  </div>;
}

/**
 * Page opening for inner studio pages: eyebrow, title with one accent phrase,
 * a sentence, small label/value facts and the page's main actions, beside an
 * abstract scene for what the page does. Same structure on every page.
 */
export function PageHero({ eyebrow, title, accent, description, facts = [], actions, motif, compact = false }: {
  eyebrow: string;
  title: string;
  accent?: string;
  description: string;
  facts?: { label: string; value: ReactNode }[];
  actions?: ReactNode;
  motif: Motif;
  /** C9：页面已有批次或结果时传 true——头图收成一行标题 + 一句说明（无插画、无眉标），把首屏让给结果区。 */
  compact?: boolean;
}) {
  if (compact) return <section className={styles.heroCompact}>
    <div className={styles.compactCopy}>
      <h1>{title}{accent && <em>{accent}</em>}</h1>
      <p>{description}</p>
    </div>
    {facts.length > 0 && <dl className={styles.compactFacts}>{facts.map(fact => <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}</dl>}
    {actions && <div className={styles.compactActions}>{actions}</div>}
  </section>;
  return <section className={styles.hero}>
    <div className={styles.copy}>
      <span className={styles.eyebrow}>{eyebrow}</span>
      <h1>{title}{accent && <em>{accent}</em>}</h1>
      <p>{description}</p>
      {facts.length > 0 && <dl className={styles.facts}>{facts.map(fact => <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}</dl>}
      {actions && <div className={styles.actions}>{actions}</div>}
    </div>
    <MotifScene motif={motif} />
  </section>;
}

/** Empty state with the page's scene and the next three steps, instead of a bare icon. */
export function GuidedEmpty({ title, description, steps, action, motif }: {
  title: string;
  description: string;
  steps: string[];
  action?: ReactNode;
  motif: Motif;
}) {
  return <div className={styles.empty}>
    <MotifScene motif={motif} compact />
    <div>
      <b>{title}</b>
      <p>{description}</p>
      <ol>{steps.map((step, index) => <li key={step}><span>{index + 1}</span>{step}</li>)}</ol>
      {action && <div className={styles.actions}>{action}</div>}
    </div>
  </div>;
}

/** Abstract portrait outline for the empty avatar slot in the voice editor. */
export function PortraitOutline() {
  return <div className={styles.portraitOutline} aria-hidden="true"><MotifScene motif="avatar" compact /></div>;
}
