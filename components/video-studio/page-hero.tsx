"use client";

import type { ReactNode } from "react";
import styles from "./page-hero.module.css";

const ART = "/video-studio/art/";
export type ArtName = "model-cardigan" | "model-jeans" | "olay-model" | "olay-main" | "cat-hero" | "bag-tan" | "serum-arch" | "cardigan";
const src = (name: ArtName) => `${ART}${name}.webp`;

/** Three tilted work cards: one in focus, two dimmed behind it. Decorative only. */
function ArtStack({ art, compact = false }: { art: [ArtName, ArtName, ArtName]; compact?: boolean }) {
  return <div className={`${styles.stack} ${compact ? styles.stackCompact : ""}`} aria-hidden="true">
    <img className={styles.ghostBack} src={src(art[2])} alt="" loading="lazy" />
    <img className={styles.ghostMid} src={src(art[1])} alt="" loading="lazy" />
    <img className={styles.front} src={src(art[0])} alt="" loading="lazy" />
  </div>;
}

/**
 * Page opening for inner studio pages: eyebrow, title with one accent phrase,
 * a sentence, small label/value facts and the page's main actions, beside a
 * stack of real work previews. Same structure on every page so the studio
 * reads as one product.
 */
export function PageHero({ eyebrow, title, accent, description, facts = [], actions, art }: {
  eyebrow: string;
  title: string;
  accent?: string;
  description: string;
  facts?: { label: string; value: ReactNode }[];
  actions?: ReactNode;
  art: [ArtName, ArtName, ArtName];
}) {
  return <section className={styles.hero}>
    <div className={styles.copy}>
      <span className={styles.eyebrow}>{eyebrow}</span>
      <h1>{title}{accent && <em>{accent}</em>}</h1>
      <p>{description}</p>
      {facts.length > 0 && <dl className={styles.facts}>{facts.map(fact => <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}</dl>}
      {actions && <div className={styles.actions}>{actions}</div>}
    </div>
    <ArtStack art={art} />
  </section>;
}

/** Empty state with a dimmed collage and the next three steps, instead of a bare icon. */
export function GuidedEmpty({ title, description, steps, action, art }: {
  title: string;
  description: string;
  steps: string[];
  action?: ReactNode;
  art: [ArtName, ArtName, ArtName];
}) {
  return <div className={styles.empty}>
    <ArtStack art={art} compact />
    <div>
      <b>{title}</b>
      <p>{description}</p>
      <ol>{steps.map((step, index) => <li key={step}><span>{index + 1}</span>{step}</li>)}</ol>
      {action && <div className={styles.actions}>{action}</div>}
    </div>
  </div>;
}
