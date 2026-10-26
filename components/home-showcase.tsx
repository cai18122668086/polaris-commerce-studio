"use client";

import Link from "next/link";
import { ArrowDown, ArrowRight, ArrowUpRight, Check, MoveUpRight, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { BrandMark } from "./brand-mark";
import { HOME_FEATURE_VISUALS } from "@/lib/home-feature-visuals";

export function HomeHero() {
  const [paused, setPaused] = useState(false);
  const heroRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const hero = heroRef.current;
    if (!hero || paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let frame = 0;
    let current = { x: hero.clientWidth * .72, y: hero.clientHeight * .68 };
    let target = { ...current };
    const draw = () => {
      current.x += (target.x - current.x) * .095;
      current.y += (target.y - current.y) * .095;
      hero.style.setProperty("--wash-x", `${current.x.toFixed(1)}px`);
      hero.style.setProperty("--wash-y", `${current.y.toFixed(1)}px`);
      if (Math.abs(target.x - current.x) + Math.abs(target.y - current.y) > .3) {
        frame = requestAnimationFrame(draw);
      } else frame = 0;
    };
    const move = (event: PointerEvent) => {
      if (event.pointerType === "touch") return;
      const rect = hero.getBoundingClientRect();
      target = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      hero.classList.add("is-pointer-active");
      if (!frame) frame = requestAnimationFrame(draw);
    };
    const leave = () => {
      target = { x: hero.clientWidth * .72, y: hero.clientHeight * .68 };
      hero.classList.remove("is-pointer-active");
      if (!frame) frame = requestAnimationFrame(draw);
    };
    hero.addEventListener("pointermove", move, { passive: true });
    hero.addEventListener("pointerleave", leave);
    return () => {
      cancelAnimationFrame(frame);
      hero.removeEventListener("pointermove", move);
      hero.removeEventListener("pointerleave", leave);
      hero.classList.remove("is-pointer-active");
    };
  }, [paused]);

  return (
    <section ref={heroRef} className={`commerce-hero${paused ? " is-paused" : ""}`} aria-labelledby="commerce-hero-title">
      <div className="commerce-color-wash" aria-hidden="true"><i /><i /><i /></div>
      <div className="commerce-hero__wordmark" aria-hidden="true">POLARIS</div>
      <div className="commerce-hero__inner">
        <div className="commerce-hero__copy">
          <p className="commerce-eyebrow"><span /> 为电商而生的 AI 创作空间</p>
          <h1 id="commerce-hero-title">让好商品，<br />一眼<span className="commerce-selection">出彩<i /><i /><i /><i /></span>。</h1>
          <p className="commerce-hero__description">参考同行做套图，上传商品做主图与详情。<br />从灵感到上架视觉，找到适合你的创作方式。</p>
          <div className="commerce-hero__actions">
            <Link className="commerce-button" href="/style-replica"><Sparkles size={18} /> 开始一键复刻 <ArrowUpRight size={20} /></Link>
            <a className="commerce-text-link" href="#start">选一个创作目标 <ArrowDown size={16} /></a>
          </div>
          <p className="commerce-hero__note">一键复刻 · 主图套图 · 详情图套图 · 灵感专区</p>
        </div>
        <div className="commerce-collage" aria-label="商品视觉创作">
          <div className="commerce-collage__shape" aria-hidden="true" />
          <span className="commerce-collage__spark" aria-hidden="true">✳</span>
          <Link href="/workspace/product-image/try-on" className="commerce-photo commerce-photo--fashion">
            <div className="commerce-photo__bar"><span /><span /><span /><small>LOOKBOOK / 01</small></div>
            <img src="/images/homepage-showcase/fashion.webp" alt="服饰模特穿搭展示效果" width={1536} height={2752} fetchPriority="high" />
            <span className="commerce-photo__caption">穿搭灵感，轻松呈现 <ArrowUpRight size={18} /></span>
          </Link>
          <Link href="/workspace/product-image/change-background" className="commerce-photo commerce-photo--product">
            <img src="/images/homepage-features/native-v2-webp/02-background-primary-desktop.webp" alt="耳机置于自然光家居场景的换背景效果" width={1374} height={1145} />
            <span className="commerce-photo__caption">给商品一个新场景 <MoveUpRight size={17} /></span>
          </Link>
          <Link href="/workspace/domestic-main-image" className="commerce-photo commerce-photo--commerce">
            <span className="commerce-photo__tag">PRODUCT VISUAL</span>
            <img src="/images/homepage-features/native-v2-webp/05-domestic-primary-mobile.webp" alt="家用电煮锅电商主图效果" width={1774} height={887} />
            <span className="commerce-photo__caption">商品主图，一眼心动 <ArrowUpRight size={16} /></span>
          </Link>
          <span className="commerce-collage__sticker"><Sparkles size={15} /> 好创意，即刻成图</span>
          <span className="commerce-collage__cursor" aria-hidden="true"><svg viewBox="0 0 32 36"><path d="M3 2v28l8-8 6 12 6-3-6-12h12Z" /></svg><b>极光商绘</b></span>
        </div>
      </div>
      <div className="commerce-hero__bottom"><span>让商品的每一面，都值得被看见。</span><span>SCROLL TO CREATE <ArrowDown size={13} /></span><button type="button" onClick={() => setPaused(!paused)} aria-pressed={paused}>{paused ? "播放动效" : "暂停动效"}</button></div>
    </section>
  );
}

/** Content stays visible when scripting or reduced-motion animations are disabled. */
export function HomeHomeReveal() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const nodes = document.querySelectorAll<HTMLElement>(".home-feature-card, .home-ai-toolbox__item, .commerce-closing, .commerce-showcase__head, .commerce-comparison, .commerce-value__copy");
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-revealed");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08 });
    nodes.forEach((node, index) => {
      node.style.setProperty("--reveal-delay", `${(index % 3) * 65}ms`);
      node.classList.add("commerce-reveal");
      observer.observe(node);
    });
    return () => {
      observer.disconnect();
      nodes.forEach((node) => node.classList.remove("commerce-reveal"));
    };
  }, []);
  return null;
}

const SHOWCASE_TOOLS = [
  { id: "change-background", label: "更换背景", title: "同一件商品，不止一种好场景。", description: "告别单调的展示背景，让光影、材质与空间一起衬托商品。", href: "/workspace/product-image/change-background" },
  { id: "local-edit", label: "一句话改图", title: "小小的改变，也能让质感出彩。", description: "圈出要修改的局部，用自然语言表达想法，让商品细节更贴近你的创意。", href: "/workspace/local-edit" },
  { id: "reference-remix", label: "一键模仿", title: "好灵感，变成自己的商品视觉。", description: "借鉴参考图的构图与氛围，为自己的商品找到新的表达方式。", href: "/workspace/reference-remix" },
] as const;

// The latest homepage promotes replica instead of background editing. Keep this
// demonstration independent of the featured-card selection.
const BACKGROUND_VISUAL = {
  primary: { desktop: { src: "/images/homepage-features/native-v2-webp/02-background-primary-desktop.webp" } },
  input: { desktop: { src: "/images/homepage-features/native-v2-webp/02-input-desktop.webp" } },
};

const GALLERY_IMAGES = [
  ["/images/homepage-showcase/outdoor.webp", "户外服饰场景"],
  ["/images/homepage-features/native-v2-webp/01-masked-primary-desktop.webp", "香氛商品视觉"],
  ["/images/homepage-features/native-v2-webp/04-detail-primary-desktop.webp", "随行杯卖点展示"],
  ["/images/homepage-showcase/fashion.webp", "时尚穿搭展示"],
  ["/images/homepage-features/native-v2-webp/05-domestic-primary-desktop.webp", "家电主图创作"],
  ["/images/homepage-features/native-v2-webp/02-background-primary-desktop.webp", "数码产品场景"],
] as const;

export function HomeProductShowcase() {
  const [active, setActive] = useState(0);
  const [split, setSplit] = useState(50);
  const [galleryPaused, setGalleryPaused] = useState(false);
  const tool = SHOWCASE_TOOLS[active];
  const visual = tool.id === "change-background" ? BACKGROUND_VISUAL : HOME_FEATURE_VISUALS[tool.id];
  return (
    <div className="commerce-showcase">
      <section className="commerce-showcase__section" aria-labelledby="commerce-showcase-title">
        <header className="commerce-showcase__head"><span className="commerce-eyebrow">A LITTLE AI. A LOT OF POSSIBILITIES.</span><h2 id="commerce-showcase-title">原图很普通？<br />下一张，可以很惊艳。</h2><p>从商品本身出发，让好想法变成看得见的好效果。</p></header>
        <div className="commerce-showcase__tabs" role="tablist" aria-label="创作效果">
          {SHOWCASE_TOOLS.map((item, index) => <button key={item.id} id={`showcase-tab-${item.id}`} type="button" role="tab" aria-selected={active === index} aria-controls="commerce-showcase-panel" tabIndex={active === index ? 0 : -1} onClick={() => { setActive(index); setSplit(50); }} onKeyDown={(event) => {
            const next = event.key === "ArrowRight" ? (active + 1) % SHOWCASE_TOOLS.length : event.key === "ArrowLeft" ? (active + SHOWCASE_TOOLS.length - 1) % SHOWCASE_TOOLS.length : event.key === "Home" ? 0 : event.key === "End" ? SHOWCASE_TOOLS.length - 1 : undefined;
            if (next !== undefined) { event.preventDefault(); setActive(next); setSplit(50); document.getElementById(`showcase-tab-${SHOWCASE_TOOLS[next].id}`)?.focus(); }
          }}>{item.label}<ArrowUpRight size={14} /></button>)}
        </div>
        <div className="commerce-showcase__panel" role="tabpanel" id="commerce-showcase-panel" aria-labelledby={`showcase-tab-${tool.id}`}>
          <div className="commerce-comparison">
            <div className="commerce-comparison__images" key={tool.id}>
              <img className="commerce-comparison__after" src={visual.primary.desktop.src} alt={`${tool.label}创作效果`} width={1374} height={1145} loading="lazy" />
              <img className="commerce-comparison__before" src={visual.input.desktop.src} style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }} alt={`${tool.label}商品原图`} width={1374} height={1145} loading="lazy" />
              <span className="commerce-comparison__label commerce-comparison__label--before">商品原图</span><span className="commerce-comparison__label commerce-comparison__label--after"><Sparkles size={12} /> 创作效果</span>
              <div className="commerce-comparison__divider" style={{ left: `${split}%` }} aria-hidden="true"><span>‹ ›</span></div>
              <input type="range" min={0} max={100} value={split} onChange={(event) => setSplit(Number(event.target.value))} aria-label="拖动查看原图与效果图" aria-valuetext={`原图显示 ${split}%，效果图显示 ${100 - split}%`} />
            </div>
            <span className="commerce-comparison__hint">左右拖动，看看变化 <span>↔</span></span>
          </div>
          <div className="commerce-showcase__copy" key={tool.id}><span className="commerce-eyebrow">0{active + 1} / PRODUCT TRANSFORMATION</span><h3>{tool.title}</h3><p>{tool.description}</p><Link className="commerce-button" href={tool.href}>试试{tool.label} <ArrowUpRight size={18} /></Link></div>
        </div>
      </section>
      <section className={`commerce-gallery${galleryPaused ? " is-paused" : ""}`} aria-labelledby="commerce-gallery-title">
        <div className="commerce-gallery__head"><div><span className="commerce-eyebrow">MORE THAN ONE GREAT SHOT</span><h2 id="commerce-gallery-title">每个品类，都有自己的高光。</h2></div><button type="button" onClick={() => setGalleryPaused(!galleryPaused)} aria-pressed={galleryPaused}>{galleryPaused ? "播放案例墙" : "暂停案例墙"}</button></div>
        <div className="commerce-gallery__window"><div className="commerce-gallery__track">{[0, 1].map((copy) => <div className="commerce-gallery__set" key={copy} aria-hidden={copy === 1 || undefined}>{GALLERY_IMAGES.map(([src, label], index) => <Link href="/inspiration" tabIndex={copy === 1 ? -1 : undefined} className={`commerce-gallery__image commerce-gallery__image--${index % 3}`} key={src}><img src={src} alt={copy ? "" : `${label}创作效果`} loading="lazy" width={380} height={430} /><span>{label}<ArrowUpRight size={16} /></span></Link>)}</div>)}</div></div>
        <Link className="commerce-text-link" href="/inspiration">去灵感专区看看 <ArrowRight size={16} /></Link>
      </section>
      <section className="commerce-value">
        <div className="commerce-value__art" aria-label="商品从单张主图到详情套图的创作效果"><div className="commerce-value__sheet"><span>01 / MAIN VISUAL</span><img src="/images/homepage-features/native-v2-webp/05-domestic-primary-desktop.webp" alt="电煮锅主图效果" width={1374} height={1145} loading="lazy" /></div><div className="commerce-value__sheet"><span>02 / PRODUCT DETAILS</span><img src="/images/homepage-features/native-v2-webp/04-detail-primary-desktop.webp" alt="随行杯详情图效果" width={1374} height={1145} loading="lazy" /></div><span className="commerce-value__seal"><Sparkles size={19} /> 从好图<br />到好生意</span></div>
        <div className="commerce-value__copy"><span className="commerce-eyebrow">CREATE MORE. MAKE IT YOURS.</span><h2>少一点反复，<br />多一点生意的可能。</h2><p>把精力留给选品、运营和品牌。让极光商绘，陪你把每一次上新的视觉做好。</p><ul><li><Check size={16} /><span><strong>让上新更从容</strong>主图、详情与场景素材，在同一处开始创作。</span></li><li><Check size={16} /><span><strong>让灵感多走一步</strong>从参考构图到商品细节，快速尝试不同表达。</span></li><li><Check size={16} /><span><strong>让每一份素材更有价值</strong>同一件商品，探索适合不同展示场景的视觉。</span></li></ul><Link className="commerce-text-link" href="/workspace/detail-pack">开始制作商品详情图 <ArrowRight size={17} /></Link></div>
      </section>
    </div>
  );
}

const CREATIVE_ROLES = [
  { role: "店铺运营", avatar: "operations", title: "我的每次上新，都想有好视觉", text: "我最在意商品能不能第一眼抓住人。主图把质感拍出来，详情再把卖点讲清楚，整套看起来统一，上新才更有底气。", tag: "主图 · 换背景" },
  { role: "服饰商家", avatar: "fashion", title: "我想把穿搭灵感，直接展示出来", text: "同一件衣服，我总想多试几种模特和场景。不只是让买家看清款式，更希望他们能想象，穿在自己身上是什么感觉。", tag: "模特 · 商品试穿" },
  { role: "品牌主理人", avatar: "brand", title: "我的商品，要有自己的表达", text: "看到好构图，我也会心动。但我更想保留自己商品的特点，把喜欢的氛围变成品牌自己的视觉，而不是千篇一律的套版。", tag: "参考图 · 一键模仿" },
  { role: "跨境卖家", avatar: "crossborder", title: "我想用一整套图，把商品讲明白", text: "我的主图要吸引注意，副图要说明细节，A+ 还要讲好使用场景。把这些内容放在一起规划，才更像是在完整地介绍一个商品。", tag: "亚马逊套图" },
  { role: "电商设计师", avatar: "designer", title: "我想把时间，留给更好的创意", text: "有了方向，我就想多试几步。换个背景、调整一个细节、参考一种光影，让 AI 帮我展开思路，我再把注意力放回商品和表达。", tag: "一句话改图" },
  { role: "家居商家", avatar: "home", title: "我卖的不只是物件，也是一种生活", text: "我希望商品走进合适的居家场景。自然的光、舒服的空间，让买家一眼就能想到，它放在自己家里会是什么样子。", tag: "场景主图" },
] as const;

export function HomeCreativeVoices() {
  const [paused, setPaused] = useState(false);
  return (
    <section className={`commerce-reviews${paused ? " is-paused" : ""}`} aria-labelledby="commerce-reviews-title">
      <header><span className="commerce-eyebrow">MADE FOR EVERY CREATIVE SELLER</span><h2 id="commerce-reviews-title">不同的生意，<br />同样期待下一张好图。</h2><p>以下为创作场景示意，用于说明不同岗位的视觉需求，并非真实客户评价。</p></header>
      <div className="commerce-reviews__window"><div className="commerce-reviews__track">
        {[0, 1].map((copy) => <div className="commerce-reviews__set" key={copy} aria-hidden={copy === 1 || undefined}>
          {CREATIVE_ROLES.map((review) => <article key={review.role}>
            <div className="commerce-reviews__stars"><Sparkles size={14} /> 创作场景示意</div>
            <h3>{review.title}</h3><p className="commerce-reviews__text">{review.text}</p>
            <div className="commerce-reviews__person"><img src={`/images/use-case-avatars/${review.avatar}.webp`} alt="" width={42} height={42} loading="lazy" /><div><strong>{review.role}</strong><small>{review.tag}</small></div></div>
          </article>)}
        </div>)}
      </div></div>
      <div className="commerce-reviews__foot"><button type="button" onClick={() => setPaused(!paused)} aria-pressed={paused}>{paused ? "播放创作场景" : "暂停创作场景"}</button></div>
    </section>
  );
}

export function HomeReplicaCardArt() {
  return <span className="home-feature-card__art commerce-replica-art" aria-hidden="true"><span className="commerce-replica-art__frame"><img src="/images/homepage-features/native-v2-webp/03-remix-primary-desktop.webp" alt="" width={1374} height={1145} loading="lazy" /><small>REFERENCE</small></span><span className="commerce-replica-art__frame"><img src="/images/homepage-features/native-v2-webp/04-detail-primary-desktop.webp" alt="" width={1374} height={1145} loading="lazy" /><small>MAKE IT YOURS</small></span><span className="commerce-replica-art__spark"><Sparkles size={21} /></span></span>;
}

export function HomeHomeFooter() {
  return (
    <footer className="home-showcase-footer">
      <section className="commerce-closing">
        <span className="commerce-eyebrow">YOUR NEXT GREAT VISUAL</span>
        <h2>下一张好图，<br />从你的商品开始。</h2>
        <Link className="commerce-button" href="/tools">找到你的创作工具 <ArrowRight size={19} /></Link>
        <span className="commerce-closing__flower" aria-hidden="true">✳</span>
      </section>
      <div className="home-showcase-footer__row"><Link href="/" aria-label="极光商绘首页"><BrandMark /></Link><p>让好商品，一眼出彩。</p><nav aria-label="页脚导航"><Link href="/help">帮助中心</Link><Link href="/legal/privacy">隐私政策</Link><Link href="/legal/terms">服务条款</Link></nav></div>
    </footer>
  );
}
