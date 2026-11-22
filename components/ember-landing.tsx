"use client";

/* 首页（熔光落地页）。2026-11-22 由已通过的 landing 原型移植：
   网点光带首屏 + 浮动作品卡 + 输入框演示、从原图到成图（滚动固定）、换背景对比、能力卡片、案例墙、结尾。
   不使用蓝色、紫色或蓝紫渐变；减少动效偏好下全部静止。 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type ReactNode } from "react";

import styles from "./ember-landing.module.css";

const c = (names: string) => names.split(" ").filter(Boolean).map((n) => styles[n] ?? n).join(" ");
const IMG = (k: string) => `/images/landing/${k}.webp`;
type Vars = CSSProperties & Record<`--${string}`, string | number>;

const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const seg = (p: number, a: number, b: number) => clamp((p - a) / (b - a));
const ease = (t: number) => 1 - Math.pow(1 - t, 3);
const prefersReduced = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const finePointer = () => typeof window !== "undefined" && window.matchMedia("(pointer: fine)").matches;

/* 全页共享的「暂停动效」开关 */
const pauseListeners = new Set<() => void>();
let pausedNow = false;
const isPaused = () => pausedNow;
function setPausedAll(v: boolean) { pausedNow = v; pauseListeners.forEach((fn) => fn()); }
const subscribePause = (fn: () => void) => { pauseListeners.add(fn); return () => { pauseListeners.delete(fn); }; };
const usePaused = () => useSyncExternalStore(subscribePause, isPaused, () => false);

/* 进入视野时加 .in（data-reveal 元素与 .acc 下划线） */
function useReveal(root: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = root.current; if (!el) return;
    el.classList.add(styles.js);
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add(styles.in); io.unobserve(e.target); } }), { threshold: .18, rootMargin: "0px 0px -6% 0px" });
    el.querySelectorAll(`[data-reveal], .${styles.h2}`).forEach((n) => io.observe(n));
    return () => io.disconnect();
  }, [root]);
}

function Icons() {
  return (
    <svg className={styles.icons} aria-hidden="true">
      <symbol id="el-arrow" viewBox="0 0 16 16"><path d="M4.5 11.5l7-7M5.5 4.5h6v6" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></symbol>
      <symbol id="el-spark" viewBox="0 0 16 16"><path d="M8 1.5c.6 3.3 1.9 4.6 5.2 5.2-3.3.6-4.6 1.9-5.2 5.2-.6-3.3-1.9-4.6-5.2-5.2 3.3-.6 4.6-1.9 5.2-5.2z" fill="currentColor" /></symbol>
      <symbol id="el-img" viewBox="0 0 16 16"><rect x="2" y="2.5" width="12" height="11" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.3" /><path d="M2.5 11l3.3-3.2 2.7 2.6 1.8-1.7 3.2 3" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" /></symbol>
      <symbol id="el-pause" viewBox="0 0 16 16"><path d="M5.5 3.5v9M10.5 3.5v9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></symbol>
      <symbol id="el-play" viewBox="0 0 16 16"><path d="M5 3.3v9.4L12.5 8z" fill="currentColor" /></symbol>
      <symbol id="el-lr" viewBox="0 0 16 16"><path d="M6 4L2 8l4 4M10 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></symbol>
    </svg>
  );
}
const Use = ({ id, style }: { id: string; style?: CSSProperties }) => <svg style={style} aria-hidden="true"><use href={`#el-${id}`} /></svg>;

/* ---------- WebGL 熔光网点：流动光带 + 鼠标点亮（带渐隐光尾） ---------- */
const NL = 14;
const FRAG = `precision highp float;
uniform vec2 r; uniform float t; uniform float k; uniform float yc; uniform float th;
uniform vec3 L[${NL}];
float h(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float n(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(h(i),h(i+vec2(1,0)),f.x),mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x),f.y);}
float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<5;i++){v+=a*n(p);p*=2.03;a*=.5;}return v;}
vec3 ramp(float e){
  vec3 col=vec3(.043);
  col=mix(col,vec3(.30,.045,.02),smoothstep(.02,.25,e));
  col=mix(col,vec3(.70,.18,.04),smoothstep(.22,.55,e));
  col=mix(col,vec3(.93,.46,.16),smoothstep(.5,.85,e));
  col=mix(col,vec3(1.,.80,.62),smoothstep(.88,1.35,e));
  return col;
}
float bandE(vec2 uv,float asp,float tt){
  float x=uv.x*asp;
  float c=yc+.085*sin(x*1.15+tt*3.1)+.05*sin(x*2.6-tt*2.3)+(fbm(vec2(x*1.1,tt*1.3))-.5)*.16;
  float w=th*(1.+.35*sin(x*.8+tt*2.)+.3*(fbm(vec2(x*1.7+3.,tt))-.5));
  float d=(uv.y-c)/w;
  float sw=fbm(vec2(x*2.2-tt*3.5,uv.y*4.+tt*1.5));
  return exp(-d*d*1.5)*(.55+.6*sw)+exp(-d*d*10.)*.5;
}
void main(){
  vec2 uv=gl_FragCoord.xy/r; float asp=r.x/r.y; float tt=t*.055;
  float cell=3.;
  vec2 g=floor(gl_FragCoord.xy/cell); vec2 f=fract(gl_FragCoord.xy/cell)-.5;
  vec2 cuv=(g+.5)*cell/r;
  float v=bandE(cuv,asp,tt)*.62;
  float lit=0.;
  for(int i=0;i<${NL};i++){
    vec2 dp=cuv-L[i].xy; dp.x*=asp;
    float rho=i==0?.011:.007;
    lit+=L[i].z*exp(-dot(dp,dp)/rho);
  }
  lit=min(lit,1.1);
  float e0=v*k+lit*.82+.015;
  float rad=min(sqrt(clamp(e0,0.,1.1))*.5,.4);
  float dotm=smoothstep(rad+.08,rad-.06,length(f));
  float e=e0*dotm*1.15+v*k*.06;
  vec3 col=ramp(e);
  col+=(h(gl_FragCoord.xy+fract(t*7.))-.5)*.03;
  gl_FragColor=vec4(col,1.);
}`;

function startBand(canvas: HTMLCanvasElement, opts: { yc: number; th: number; k?: () => number; seed?: number }, isPaused: () => boolean) {
  const gl = canvas.getContext("webgl", { antialias: false, premultipliedAlpha: false, powerPreference: "low-power" });
  if (!gl) return null;
  const sh = (type: number, src: string) => { const s = gl.createShader(type)!; gl.shaderSource(s, src); gl.compileShader(s); return s; };
  const pr = gl.createProgram()!;
  gl.attachShader(pr, sh(gl.VERTEX_SHADER, "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}"));
  gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, FRAG));
  gl.linkProgram(pr);
  if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) return null;
  gl.useProgram(pr);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(pr, "p"); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const U = (n: string) => gl.getUniformLocation(pr, n);
  const u = { r: U("r"), t: U("t"), k: U("k"), yc: U("yc"), th: U("th"), L: U("L") };
  const reduce = prefersReduced();
  const scale = .5; let w = 0, hgt = 0, visible = true, raf = 0, tAcc = opts.seed || 0, last = performance.now(), dead = false;
  const cur = { x: .5, y: .5, tx: .5, ty: .5, s: 0, ts: 0 };
  const trail: { x: number; y: number; s: number }[] = []; const buf = new Float32Array(NL * 3);
  const resize = () => { const b = canvas.getBoundingClientRect(); w = Math.max(1, Math.round(b.width * scale)); hgt = Math.max(1, Math.round(b.height * scale)); canvas.width = w; canvas.height = hgt; gl.viewport(0, 0, w, hgt); };
  resize(); addEventListener("resize", resize);
  const draw = (now: number) => {
    if (dead) return;
    const dt = Math.min(64, now - last); last = now;
    if (!isPaused() && !reduce) tAcc += dt / 1000;
    const a = 1 - Math.pow(.0005, dt / 1000);
    cur.x += (cur.tx - cur.x) * a * 1.6; cur.y += (cur.ty - cur.y) * a * 1.6; cur.s += (cur.ts - cur.s) * a;
    const fade = Math.exp(-dt / 480);
    for (const p of trail) p.s *= fade;
    while (trail.length && trail[0].s < .02) trail.shift();
    buf.fill(0); buf[0] = cur.x; buf[1] = cur.y; buf[2] = cur.s;
    trail.slice(-(NL - 1)).forEach((p, i) => { buf[3 + i * 3] = p.x; buf[4 + i * 3] = p.y; buf[5 + i * 3] = p.s; });
    gl.uniform2f(u.r, w, hgt); gl.uniform1f(u.t, tAcc);
    gl.uniform1f(u.k, opts.k ? opts.k() : 1); gl.uniform1f(u.yc, opts.yc); gl.uniform1f(u.th, opts.th);
    gl.uniform3fv(u.L, buf);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    raf = visible && !document.hidden ? requestAnimationFrame(draw) : 0;
  };
  const start = () => { if (!raf && !dead) { last = performance.now(); raf = requestAnimationFrame(draw); } };
  const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible) start(); }, { rootMargin: "100px" });
  io.observe(canvas);
  const onVis = () => { if (!document.hidden && visible) start(); };
  document.addEventListener("visibilitychange", onVis);
  const host = canvas.parentElement!;
  let lx = -1, ly = -1;
  const onMove = (e: PointerEvent) => {
    const b = canvas.getBoundingClientRect();
    const x = (e.clientX - b.left) / b.width, y = 1 - (e.clientY - b.top) / b.height;
    if (cur.ts === 0) { cur.x = x; cur.y = y; }
    cur.tx = x; cur.ty = y; cur.ts = 1;
    const dx = (x - lx) * b.width, dy = (y - ly) * b.height;
    if (!reduce && dx * dx + dy * dy > 18 * 18) { trail.push({ x, y, s: .8 }); lx = x; ly = y; }
    start();
  };
  const onLeave = () => { cur.ts = 0; };
  host.addEventListener("pointermove", onMove);
  host.addEventListener("pointerleave", onLeave);
  start();
  return () => {
    dead = true; cancelAnimationFrame(raf); io.disconnect();
    removeEventListener("resize", resize); document.removeEventListener("visibilitychange", onVis);
    host.removeEventListener("pointermove", onMove); host.removeEventListener("pointerleave", onLeave);
  };
}

/* ---------- 首屏 ---------- */
const PHRASES = ["白色身体乳，浴室晨光，天猫主图 5 张", "全价猫粮，木地板午后暖光，详情套图 8 张", "降噪耳机，石材桌面，换一个高级场景"];
const FLOAT = [
  { cls: "fc1 far", depth: 1, d: ".7s", k: "olay-model", alt: "身体乳模特主图", b: "身体乳", s: "主图 · 1:1.4" },
  { cls: "fc2", depth: 2, d: ".85s", k: "cat-scene", alt: "猫粮场景图", b: "猫粮", s: "场景 · 1:1" },
  { cls: "fc3 far", depth: 1.1, d: ".75s", k: "serum-arch", alt: "精华液拱门场景", b: "精华液", s: "换背景" },
  { cls: "fc4", depth: 2.2, d: ".9s", k: "phones-after", alt: "耳机石材桌面场景", b: "耳机", s: "详情 03" },
];

export function EmberHero() {
  const hero = useRef<HTMLElement>(null);
  const band = useRef<HTMLCanvasElement>(null);
  const fallback = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLDivElement>(null);
  const go = useRef<HTMLAnchorElement>(null);
  const typed = useRef(false); // 用户自己输入过（不是打字演示）
  const router = useRouter();
  // 点「生成」：把用户写的描述带进创作首页（/create?prompt=…），预填到创作输入框
  const onGenerate = (event: React.MouseEvent<HTMLAnchorElement>) => {
    const text = typed.current ? (field.current?.innerText ?? "").trim() : "";
    if (!text) return;
    event.preventDefault();
    router.push(`/create?prompt=${encodeURIComponent(text.slice(0, 2000))}`);
  };
  const dots = useRef<HTMLDivElement>(null);
  const paused = usePaused();

  useEffect(() => {
    const el = hero.current!; const reduce = prefersReduced();
    const accT = setTimeout(() => el.querySelector(`.${styles.acc}`)?.classList.add(styles.in), 900);

    const stopBand = band.current ? startBand(band.current, { yc: .2, th: .15, k: () => 1 - clamp(scrollY / innerHeight) * .5, seed: 3 }, isPaused) : null;
    if (stopBand && fallback.current) fallback.current.style.opacity = "0";

    // 打字演示：点击后可以自己输入
    let typing = !reduce, alive = true, pi = 0;
    const f = field.current!, g = go.current!;
    const caret = () => { const s = document.createElement("span"); s.className = styles.caret; return s; };
    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
    (async () => {
      if (reduce) { f.textContent = PHRASES[0]; return; }
      await wait(1400);
      while (typing && alive) {
        const s = PHRASES[pi % PHRASES.length];
        for (let i = 1; i <= s.length && typing && alive; i++) { while (isPaused() && typing && alive) await wait(200); f.textContent = s.slice(0, i); f.append(caret()); await wait(55 + Math.random() * 45); }
        if (!typing || !alive) break;
        g.classList.remove(styles.flash); void g.offsetWidth; g.classList.add(styles.flash);
        await wait(2200);
        for (let i = s.length; i >= 0 && typing && alive; i--) { f.textContent = s.slice(0, i); f.append(caret()); await wait(14); }
        pi++; await wait(400);
      }
    })();
    const stopTyping = () => { if (!typing && f.isContentEditable) return; typing = false; typed.current = true; f.textContent = ""; f.contentEditable = "true"; f.focus(); };
    // 回车直接生成；Shift+回车换行；输入法组字时不触发
    const onKey = (e: KeyboardEvent) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); g.click(); } };
    f.addEventListener("pointerdown", stopTyping); f.addEventListener("focus", stopTyping); f.addEventListener("keydown", onKey);

    // 浮动卡：鼠标视差 + 滚动视差；整页网点跟随光标
    const cards = [...el.querySelectorAll<HTMLElement>(`.${styles.floatCard}`)];
    let mx = 0, my = 0, cmx = 0, cmy = 0, raf = 0;
    const cd = dots.current!; let cdx = innerWidth / 2, cdy = innerHeight / 2, ctx = cdx, cty = cdy;
    const onHero = (e: PointerEvent) => { mx = e.clientX / innerWidth - .5; my = e.clientY / innerHeight - .5; };
    const onMove = (e: PointerEvent) => { ctx = e.clientX; cty = e.clientY; cd.style.setProperty("--co", "1"); };
    const onLeaveDoc = () => cd.style.setProperty("--co", "0");
    const fine = finePointer();
    if (fine) { el.addEventListener("pointermove", onHero); addEventListener("pointermove", onMove, { passive: true }); document.documentElement.addEventListener("pointerleave", onLeaveDoc); }
    const frame = () => {
      const y = scrollY, vh = innerHeight;
      cdx += (ctx - cdx) * .2; cdy += (cty - cdy) * .2;
      cd.style.setProperty("--cx", cdx.toFixed(1) + "px"); cd.style.setProperty("--cy", cdy.toFixed(1) + "px");
      cmx += (mx - cmx) * .07; cmy += (my - cmy) * .07;
      if (y < vh * 1.4 && !reduce) cards.forEach((card) => { const d = +(card.dataset.depth || 1); card.style.setProperty("--px", (cmx * 26 * d).toFixed(2) + "px"); card.style.setProperty("--py", (cmy * 18 * d - y * .12 * d).toFixed(2) + "px"); });
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    return () => {
      alive = false; typing = false; cancelAnimationFrame(raf); clearTimeout(accT); stopBand?.();
      f.removeEventListener("pointerdown", stopTyping); f.removeEventListener("focus", stopTyping); f.removeEventListener("keydown", onKey);
      el.removeEventListener("pointermove", onHero); removeEventListener("pointermove", onMove); document.documentElement.removeEventListener("pointerleave", onLeaveDoc);
    };
  }, []);

  return (
    <div className={styles.root}>
      <Icons />
      <div className={styles.cursorDots} ref={dots} aria-hidden="true" />
      <section className={styles.hero} ref={hero} aria-labelledby="ember-hero-title">
        <div className={styles.bandFallback} ref={fallback} aria-hidden="true" />
        <canvas className={styles.band} ref={band} aria-hidden="true" />
        <div className={styles.grid} aria-hidden="true" />
        <div className={styles.heroUtil}>
          <button type="button" className={styles.iconBtn} aria-pressed={paused} aria-label={paused ? "播放动效" : "暂停动效"} title={paused ? "播放动效" : "暂停动效"} onClick={() => setPausedAll(!paused)}><Use id={paused ? "play" : "pause"} /></button>
        </div>
        <div className={c("wrap heroInner")}>
          <p className={styles.eyebrow} data-hero="" style={{ "--d": ".1s" } as Vars}><b>极光商绘</b> 为电商而生的 AI 创作空间</p>
          <h1 id="ember-hero-title"><span className={styles.line}><span>让好商品，</span></span><span className={styles.line}><span>一眼<span className={styles.acc}>出彩</span>。</span></span></h1>
          <p className={styles.sub} data-hero="" style={{ "--d": ".35s" } as Vars}>上传一张商品图，说一句想要的画面。<br />主图、详情页、场景图，几十秒成套出图。</p>
          <div className={styles.composer} data-hero="" style={{ "--d": ".5s" } as Vars}>
            <div className={styles.field} ref={field} role="textbox" tabIndex={0} aria-label="描述你想要的商品图" data-placeholder="描述你的商品和想要的画面…" spellCheck={false} />
            <div className={styles.row}>
              <span className={styles.chip}><Use id="img" />商品图</span>
              <span className={styles.chip}>天猫 · 主图</span>
              <span className={c("chip num")}>1:1</span>
              <span className={c("chip num")}>5 张</span>
              <Link className={c("btn btnWhite go")} ref={go} href="/create" onClick={onGenerate}><span className={styles.sheen} /><Use id="spark" style={{ width: 15, height: 15 }} />生成</Link>
            </div>
          </div>
        </div>
        {FLOAT.map((f) => (
          <figure key={f.k} className={c(`floatCard mat ${f.cls}`)} data-depth={f.depth} style={{ "--d": f.d } as Vars}>
            <img src={IMG(f.k)} alt={f.alt} /><figcaption><b>{f.b}</b><span>{f.s}</span></figcaption>
          </figure>
        ))}
        <div className={styles.heroFoot}>
          <div className={styles.logos} aria-label="支持的平台">
            <span>天猫</span><span>淘宝</span><span>京东</span><span>拼多多</span><span>抖音电商</span><span className={styles.num}>Amazon</span><span className={styles.num}>Shopify</span><span className={styles.num}>TikTok Shop</span>
          </div>
        </div>
      </section>
    </div>
  );
}

/* ---------- 光带过渡 ---------- */
export function EmberSeam() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const s = ref.current!; let raf = 0;
    const tick = () => {
      const b = s.getBoundingClientRect(), vh = innerHeight;
      if (b.top < vh && b.bottom > 0) { const sp = clamp(1 - (b.top + b.height) / (vh + b.height)); s.style.setProperty("--sp", sp.toFixed(3)); s.style.setProperty("--sh", (.3 + Math.sin(sp * Math.PI) * .7).toFixed(3)); }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  return <div className={c("root seam")} ref={ref} aria-hidden="true"><i /><i /><i /></div>;
}

/* ---------- 从原图到成图（滚动固定） ---------- */
const STEPS = [["01", "上传原图", "手机随手拍也可以，商品完整清楚就行。"], ["02", "读懂卖点", "自动识别品类、成分、规格和适合的场景。"], ["03", "生成主图", "按平台规格出图，光影和质感一次到位。"], ["04", "铺开详情套图", "同一套视觉语言，延展出整套详情页。"]];
export function EmberStory() {
  const root = useRef<HTMLDivElement>(null);
  useReveal(root);
  useEffect(() => {
    const r = root.current!;
    const story = r.querySelector<HTMLElement>(`.${styles.story}`)!, steps = [...r.querySelectorAll<HTMLElement>(`.${styles.steps} li`)], stepsEl = r.querySelector<HTMLElement>(`.${styles.steps}`)!;
    const raw = r.querySelector<HTMLElement>("[data-s=raw]")!, scan = r.querySelector<HTMLElement>(`.${styles.scan}`)!, facts = [...r.querySelectorAll<HTMLElement>(`.${styles.fact}`)];
    const main = r.querySelector<HTMLElement>("[data-s=main]")!, dots = r.querySelector<HTMLElement>(`.${styles.dots}`)!, cap = r.querySelector<HTMLElement>(`.${styles.cap}`)!, fan = [...r.querySelectorAll<HTMLElement>(`.${styles.fan} .${styles.ph}`)];
    const cv = r.querySelector<HTMLElement>(`.${styles.canvas}`)!;
    let raf = 0;
    const tick = () => {
      const vh = innerHeight, sb = story.getBoundingClientRect();
      if (sb.top < vh && sb.bottom > 0) {
        let p: number;
        if (innerWidth > 960) p = clamp(-sb.top / (sb.height - vh));
        else { const cb = cv.getBoundingClientRect(); p = clamp((vh * .9 - cb.top) / (cb.height + vh * .5)); }
        const step = p < .22 ? 0 : p < .45 ? 1 : p < .72 ? 2 : 3;
        steps.forEach((li, i) => li.classList.toggle(styles.on, i === step));
        stepsEl.style.setProperty("--p", p.toFixed(3));
        const a = Math.max(seg(p, 0, .1), ease(clamp(1 - sb.top / vh)) * .9), sc = seg(p, .14, .44), out = seg(p, .46, .56);
        raw.style.opacity = (a * (1 - out)).toFixed(3);
        raw.style.transform = `translate3d(${-out * 40}%,${(1 - ease(a)) * 40}px,0) scale(${1 - out * .2}) rotate(${-3 + a * 3 - out * 8}deg)`;
        raw.style.filter = `blur(${out * 6}px)`;
        scan.style.setProperty("--sy", (sc * 100).toFixed(1) + "%"); scan.style.setProperty("--so", sc > 0 && sc < 1 ? "1" : "0");
        facts.forEach((f, i) => f.classList.toggle(styles.on, p > .2 + i * .055 && p < .5));
        const dv = seg(p, .46, .74), dvIn = seg(p, .44, .52), dvOut = seg(p, .78, .9);
        main.style.opacity = (dvIn * (1 - dvOut * .65)).toFixed(3);
        main.style.transform = `translate3d(0,${(1 - ease(dvIn)) * 60 - dvOut * 30}px,0) scale(${(.9 + ease(dvIn) * .1) * (1 - dvOut * .28)})`;
        main.querySelector("img")!.style.filter = `grayscale(${1 - dv}) blur(${(1 - dv) * 14}px) contrast(${.8 + dv * .2})`;
        dots.style.opacity = (1 - dv).toFixed(3);
        main.style.setProperty("--dp", dv.toFixed(3));
        cap.textContent = dv >= 1 ? "主图 · 完成" : "正在显影 " + Math.round(dv * 100) + "%";
        const f = seg(p, .78, .96);
        fan.forEach((el, i) => { const o = i - 1, e = ease(clamp(f * 1.2 - i * .1)); el.style.opacity = e.toFixed(3); el.style.transform = `translate3d(${o * e * 92}%,${(1 - e) * 80 + Math.abs(o) * e * 14 - e * 30}px,0) rotate(${o * e * 6}deg)`; el.style.zIndex = String(3 - Math.abs(o)); });
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  return (
    <div className={styles.root} ref={root}>
      <section className={styles.story} aria-labelledby="ember-story-title">
        <div className={c("stage wrap")}>
          <div>
            <p className={styles.eyebrow} data-reveal="">从原图到成图</p>
            <h2 className={styles.h2} id="ember-story-title" data-reveal="" style={{ "--i": 1 } as Vars}>一张随手拍，<br /><span className={styles.acc}>显影</span>成主图。</h2>
            <ol className={styles.steps}>
              {STEPS.map(([n, b, s], i) => <li key={n} className={i === 0 ? styles.on : undefined}><b><span className={styles.n}>{n}</span>{b}</b><span>{s}</span></li>)}
            </ol>
          </div>
          <div className={styles.canvas}>
            <div className={styles.layer}>
              <div className={styles.ph} data-s="raw" style={{ width: "34%" }}><img src={IMG("olay-raw")} alt="商品原图" /><span className={styles.tag}>原图 · 手机拍摄</span><div className={styles.scan} /></div>
              <div className={styles.facts}>
                <div className={c("fact l")} style={{ left: "9%", top: "22%" }}><span>品类</span><b>身体乳</b></div>
                <div className={c("fact l")} style={{ left: "6%", top: "52%" }}><span>核心成分</span><b>烟酰胺 · 色淡林</b></div>
                <div className={c("fact r")} style={{ right: "8%", top: "28%" }}><span>规格</span><b className={styles.num}>260 g</b></div>
                <div className={c("fact r")} style={{ right: "6%", top: "58%" }}><span>推荐场景</span><b>浴室晨光</b></div>
              </div>
              <div className={styles.develop} data-s="main" style={{ opacity: 0 }}><img src={IMG("olay-main")} alt="生成的主图" /><div className={styles.dots} /><span className={styles.cap}>正在显影</span><div className={styles.bar}><i /></div></div>
              <div className={styles.fan}>
                {["olay-detail-a", "olay-detail-b", "olay-detail-c"].map((k, i) => <div key={k} className={styles.ph} style={{ opacity: 0 }}><img src={IMG(k)} alt={`详情页 ${i + 1}`} /></div>)}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

/* ---------- 换背景对比 ---------- */
export function EmberCompare() {
  const root = useRef<HTMLDivElement>(null);
  const cmp = useRef<HTMLDivElement>(null);
  const [x, setX] = useState(50);
  useReveal(root);
  useEffect(() => {
    const el = cmp.current!; let user = false, t0 = 0, raf = 0; const reduce = prefersReduced();
    const set = (v: number) => setX(clamp(v, 0, 100));
    const fromEvt = (e: PointerEvent) => { const b = el.getBoundingClientRect(); set(((e.clientX - b.left) / b.width) * 100); };
    const down = (e: PointerEvent) => { user = true; el.setPointerCapture(e.pointerId); fromEvt(e); };
    const move = (e: PointerEvent) => { if (el.hasPointerCapture(e.pointerId)) fromEvt(e); };
    el.addEventListener("pointerdown", down); el.addEventListener("pointermove", move);
    // 第一次进入视野时自动左右扫一下
    const tick = () => {
      const b = el.getBoundingClientRect();
      if (!user && b.top < innerHeight * .8 && b.bottom > 0) {
        if (!t0) t0 = performance.now();
        const t = clamp((performance.now() - t0) / 2400);
        if (t < 1 && !reduce) set(50 + Math.sin(t * Math.PI * 2) * 28 * (1 - t)); else user = true;
      }
      if (!user) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); el.removeEventListener("pointerdown", down); el.removeEventListener("pointermove", move); };
  }, []);
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "ArrowLeft" || e.key === "ArrowRight") { setX((v) => clamp(v + (e.key === "ArrowLeft" ? -5 : 5), 0, 100)); e.preventDefault(); } };
  return (
    <div className={styles.root} ref={root}>
      <section className={c("compareSec wrap")} aria-labelledby="ember-compare-title">
        <div>
          <p className={styles.eyebrow} data-reveal="">换背景</p>
          <h2 className={styles.h2} id="ember-compare-title" data-reveal="" style={{ "--i": 1 } as Vars}>同一件商品，<br />换一张<span className={styles.acc}>好图</span>。</h2>
          <p className={styles.lead} data-reveal="" style={{ "--i": 2 } as Vars}>杂乱的桌面，换成石材与晨光。左右拖动，看看哪些变了、哪些没变。</p>
          <dl className={styles.kept} data-reveal="" style={{ "--i": 3 } as Vars}>
            <div><dt>保持不变</dt><dd>外形、材质、颜色与细节</dd></div>
            <div><dt>重新生成</dt><dd>场景、光线、阴影与氛围</dd></div>
            <div><dt>试一试</dt><dd><Link href="/workspace/product-image/change-background">打开更换背景 →</Link></dd></div>
          </dl>
        </div>
        <div className={styles.compare} ref={cmp} data-reveal="" style={{ "--i": 1, "--x": `${x}%` } as Vars} role="slider" aria-label="拖动对比原图与成图" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(x)} tabIndex={0} onKeyDown={onKey}>
          <img src={IMG("phones-before")} alt="原图：杂乱桌面上的耳机" />
          <img className={styles.after} src={IMG("phones-after")} alt="成图：石材桌面晨光场景" />
          <span className={c("lb lbL")}>原图</span><span className={c("lb lbR")}>成图</span>
          <div className={styles.handle}><span><Use id="lr" style={{ width: 16, height: 16 }} /></span></div>
        </div>
      </section>
    </div>
  );
}

/* ---------- 能力卡片（链接到真实功能） ---------- */
function Card({ cls, href, i, children, title, text }: { cls: string; href: string; i: number; children: ReactNode; title: string; text: string }) {
  const onMove = (e: React.PointerEvent<HTMLAnchorElement>) => { const b = e.currentTarget.getBoundingClientRect(); e.currentTarget.style.setProperty("--mx", e.clientX - b.left + "px"); e.currentTarget.style.setProperty("--my", e.clientY - b.top + "px"); };
  return (
    <Link className={c(`card ${cls}`)} href={href} data-reveal="" style={{ "--i": i } as Vars} onPointerMove={onMove}>
      {children}
      <span className={styles.arrow}><Use id="arrow" /></span>
      <div className={styles.copy}><h3>{title}</h3><p>{text}</p></div>
    </Link>
  );
}
const Fr = ({ k, cap }: { k: string; cap?: string }) => <figure className={styles.fr}><img src={IMG(k)} alt="" loading="lazy" />{cap && <figcaption>{cap}</figcaption>}</figure>;
export function EmberFeatures() {
  const root = useRef<HTMLDivElement>(null);
  useReveal(root);
  return (
    <div className={styles.root} ref={root}>
      <section className={c("features wrap")} aria-labelledby="ember-features-title">
        <p className={styles.eyebrow} data-reveal="">能力</p>
        <h2 className={styles.h2} id="ember-features-title" data-reveal="" style={{ "--i": 1 } as Vars}>一个工作台，<br />做完一整套<span className={styles.acc}>成图</span>。</h2>
        <div className={styles.bento}>
          <Card cls="cA" href="/workspace/domestic-main-image" i={0} title="主图套图" text="一次生成搜索主图和连续轮播图，按平台尺寸自动排好。">
            <div className={c("art grid4")}><Fr k="cat-hero" cap="01 · 搜索主图" /><Fr k="cat-fresh" cap="02 · 卖点" /><Fr k="cat-fat" cap="03 · 功效" /><Fr k="cat-chin" cap="04 · 场景" /></div>
          </Card>
          <Card cls="cB" href="/workspace/detail-pack" i={1} title="详情套图" text="卖点、成分和使用方式，整理成连贯的详情页。">
            <div className={c("art artRow")}><Fr k="olay-detail-b" /><Fr k="olay-detail-c" /><Fr k="olay-detail-a" /></div>
          </Card>
          <Card cls="cC" href="/style-replica" i={2} title="一键复刻" text="借同行的好构图，换成你自己的商品和卖点。">
            <div className={c("art artRow")}><Fr k="olay-raw2" cap="商品" /><span className={styles.mid}><Use id="arrow" /></span><Fr k="olay-model" cap="复刻成图" /></div>
          </Card>
          <Card cls="cD" href="/workspace/product-image/change-background" i={0} title="换背景" text="保留商品，只换场景和光线。">
            <div className={c("art full")}><img src={IMG("serum-arch")} alt="" loading="lazy" /></div>
          </Card>
          <Card cls="cE" href="/workspace/product-image/try-on" i={1} title="模特试穿" text="平铺图直接穿到模特身上。">
            <div className={c("art artRow")}><Fr k="cardigan" cap="平铺" /><span className={styles.mid}><Use id="arrow" /></span><Fr k="model-cardigan" cap="上身" /></div>
          </Card>
          <Card cls="cF" href="/workspace/local-edit" i={2} title="一句话改图" text="圈出局部，用一句话说清要改什么。">
            <div className={c("art artRow")}><figure className={styles.fr}><img src={IMG("bag-tan")} alt="" loading="lazy" /><span className={styles.ring} /><span className={styles.say}>把包身换成深棕色</span></figure></div>
          </Card>
        </div>
      </section>
    </div>
  );
}

/* ---------- 案例墙（点开从原位放大） ---------- */
const AR: Record<string, number> = { "olay-model": .707, "cat-hero": 1, "serum-arch": .8, "model-jeans": .75, "cat-fresh": 1, "olay-main": 1, "bag-tan": .75, "cat-freeze": .75, "phones-after": .75, "cat-scene": 1, "olay-detail-b": .73, "model-cardigan": .75, "cat-fat": 1, "serum-room": 1.5, "cat-chin": 1, "olay-detail-a": .585 };
const LABEL: Record<string, string> = { "olay-model": "身体乳 · 主图", "cat-hero": "猫粮 · 主图", "serum-arch": "精华 · 换背景", "model-jeans": "服饰 · 模特", "cat-fresh": "猫粮 · 卖点", "olay-main": "身体乳 · 主图", "bag-tan": "箱包 · 白底", "cat-freeze": "猫粮 · 详情", "phones-after": "耳机 · 场景", "cat-scene": "猫粮 · 场景", "olay-detail-b": "身体乳 · 详情", "model-cardigan": "服饰 · 试穿", "cat-fat": "猫粮 · 详情", "serum-room": "精华 · 场景", "cat-chin": "猫粮 · 卖点", "olay-detail-a": "身体乳 · 详情" };
const WALL1 = ["olay-model", "cat-hero", "serum-arch", "model-jeans", "cat-fresh", "olay-main", "bag-tan", "cat-freeze"];
const WALL2 = ["phones-after", "cat-scene", "olay-detail-b", "model-cardigan", "cat-fat", "serum-room", "cat-chin", "olay-detail-a"];
function Tiles({ list, dup }: { list: string[]; dup?: boolean }) {
  return <>{list.map((k) => { const [cat, kind] = LABEL[k].split(" · "); return <button key={k + (dup ? "-d" : "")} type="button" className={styles.tile} data-k={k} tabIndex={dup ? -1 : undefined} aria-hidden={dup || undefined}><img src={IMG(k)} alt={LABEL[k]} loading="lazy" style={{ width: Math.round(300 * AR[k]) }} /><span className={styles.tileCap}><b>{cat}</b><span>{kind}</span></span></button>; })}</>;
}
export function EmberCases() {
  const root = useRef<HTMLDivElement>(null);
  const paused = usePaused();
  useReveal(root);
  const onClick = (e: React.MouseEvent) => {
    const t = (e.target as HTMLElement).closest<HTMLElement>(`.${styles.tile}`); if (!t) return;
    const img = t.querySelector("img")!, r = img.getBoundingClientRect();
    const lb = document.createElement("div"); lb.className = styles.lightbox; lb.setAttribute("role", "dialog"); lb.setAttribute("aria-label", img.alt); lb.dataset.esPlain = "";
    const big = img.cloneNode() as HTMLImageElement; Object.assign(big.style, { left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px" });
    lb.append(big); document.body.append(lb); setPausedAll(true);
    const ratio = img.naturalWidth / img.naturalHeight || r.width / r.height;
    let H = innerHeight * .82, W = H * ratio; if (W > innerWidth * .86) { W = innerWidth * .86; H = W / ratio; }
    requestAnimationFrame(() => { lb.classList.add(styles.lightboxOn); Object.assign(big.style, { left: (innerWidth - W) / 2 + "px", top: (innerHeight - H) / 2 + "px", width: W + "px", height: H + "px" }); });
    const close = () => {
      const r2 = img.getBoundingClientRect(); lb.classList.remove(styles.lightboxOn);
      Object.assign(big.style, { left: r2.left + "px", top: r2.top + "px", width: r2.width + "px", height: r2.height + "px" });
      setTimeout(() => { lb.remove(); setPausedAll(false); t.focus({ preventScroll: true }); }, 560);
      removeEventListener("keydown", esc);
    };
    const esc = (ev: KeyboardEvent) => { if (ev.key === "Escape") close(); };
    lb.addEventListener("click", close); addEventListener("keydown", esc);
  };
  return (
    <div className={styles.root} ref={root}>
      <section className={c(`cases${paused ? " paused" : ""}`)} id="cases" aria-labelledby="ember-cases-title">
        <div className={c("wrap head")}>
          <div><p className={styles.eyebrow} data-reveal="">案例</p><h2 className={styles.h2} id="ember-cases-title" data-reveal="" style={{ "--i": 1 } as Vars}>每个品类，<br />都有自己的高光。</h2></div>
          <button type="button" className={c("btn btnGhost")} aria-pressed={paused} data-reveal="" style={{ "--i": 2 } as Vars} onClick={() => setPausedAll(!paused)}><Use id={paused ? "play" : "pause"} /><span>{paused ? "播放案例墙" : "暂停案例墙"}</span></button>
        </div>
        <div className={styles.marquee} onClick={onClick}>
          <div className={styles.track} style={{ "--dur": "80s" } as Vars}><Tiles list={WALL1} /><Tiles list={WALL1} dup /></div>
          <div className={c("track rev")} style={{ "--dur": "95s" } as Vars}><Tiles list={WALL2} /><Tiles list={WALL2} dup /></div>
        </div>
      </section>
    </div>
  );
}

/* ---------- 价格（按原型内容） ---------- */
const PLANS = [
  { name: "体验", price: "¥0", unit: " / 新用户", items: ["赠送创作积分", "主图与换背景", "标准清晰度下载"], cta: "免费开始", href: "/auth/register", pro: false },
  { name: "专业", price: "¥99", unit: " / 月", items: ["每月 1,200 积分", "全部 17 项能力", "详情套图与一键复刻", "高清下载，优先排队"], cta: "开通专业版", href: "/account#membership", pro: true },
  { name: "团队", price: "联系我们", unit: "", items: ["多人协作与权限", "品牌素材库", "批量出图与发票"], cta: "咨询方案", href: "/help", pro: false },
];
export function EmberPricing() {
  const root = useRef<HTMLDivElement>(null);
  useReveal(root);
  return (
    <div className={styles.root} ref={root}>
      <section className={c("pricing wrap")} id="pricing" aria-labelledby="ember-pricing-title">
        <p className={styles.eyebrow} data-reveal="">价格</p>
        <h2 className={styles.h2} id="ember-pricing-title" data-reveal="" style={{ "--i": 1 } as Vars}>按用量付费，<br />让每一张图都算得清<span className={styles.acc}>生意</span>。</h2>
        <div className={styles.plans}>
          {PLANS.map((p, i) => (
            <div key={p.name} className={c(`plan${p.pro ? " pro" : ""}`)} data-reveal="" style={{ "--i": i } as Vars}>
              <h3>{p.name}</h3>
              <div className={c(`price${p.unit ? " num" : ""}`)}>{p.price}{p.unit && <small>{p.unit}</small>}</div>
              <ul>{p.items.map((t) => <li key={t}>{t}</li>)}</ul>
              <Link className={c(`btn ${p.pro ? "btnEmber" : "btnGhost"}`)} href={p.href}>{p.cta}{p.pro && <Use id="arrow" />}</Link>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

/* ---------- 常见问题（按原型内容） ---------- */
const QA = [
  ["需要准备什么样的商品图？", "手机拍摄即可。商品完整、边缘清楚就好，背景杂乱也没关系，不需要先抠图或做白底。"],
  ["生成的图片能直接上架吗？", "可以。出图会按所选平台的尺寸和规格生成，下载后即可上传。商品的外形、文字和关键细节会尽量保持与原图一致。"],
  ["积分怎么计算？", "按成功生成的张数扣积分，生成失败不扣。不同能力的单价在创建任务前就会显示。"],
  ["我的商品图会被拿去做别的用途吗？", "不会。你上传的素材和生成结果只保存在你的工作区内，用于为你生成图片。"],
];
export function EmberFaq() {
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState<number | null>(null);
  useReveal(root);
  return (
    <div className={styles.root} ref={root}>
      <section className={c("faq wrap")} id="faq" aria-labelledby="ember-faq-title">
        <div>
          <p className={styles.eyebrow} data-reveal="">常见问题</p>
          <h2 className={styles.h2} id="ember-faq-title" data-reveal="" style={{ "--i": 1 } as Vars}>还有疑问？</h2>
          <p className={styles.lead} data-reveal="" style={{ "--i": 2 } as Vars}>找不到答案，可以在<Link href="/help">帮助中心</Link>联系我们。</p>
        </div>
        <div>
          {QA.map(([q, a], i) => (
            <div key={q} className={c(`qa${open === i ? " open" : ""}`)} data-reveal="" style={{ "--i": i } as Vars}>
              <button type="button" aria-expanded={open === i} aria-controls={`ember-qa-${i}`} onClick={() => setOpen(open === i ? null : i)}>{q}<span className={styles.pm} aria-hidden="true" /></button>
              <div className={styles.answer} id={`ember-qa-${i}`} role="region"><div><p>{a}</p></div></div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

/* ---------- 结尾 ---------- */
export function EmberFinal() {
  const root = useRef<HTMLDivElement>(null);
  const band = useRef<HTMLCanvasElement>(null);
  const word = useRef<HTMLDivElement>(null);
  useReveal(root);
  useEffect(() => {
    const stop = band.current ? startBand(band.current, { yc: .42, th: .17, k: () => .95, seed: 11 }, isPaused) : null;
    const sec = root.current!.querySelector<HTMLElement>(`.${styles.final}`)!; let raf = 0;
    const tick = () => { const fb = sec.getBoundingClientRect(); if (fb.top < innerHeight) word.current!.style.setProperty("--wp", clamp((innerHeight - fb.top) / fb.height).toFixed(3)); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    return () => { stop?.(); cancelAnimationFrame(raf); };
  }, []);
  return (
    <div className={styles.root} ref={root}>
      <section className={styles.final} aria-labelledby="ember-final-title">
        <canvas className={styles.band} ref={band} aria-hidden="true" />
        <div className={styles.wrap}>
          <h2 className={styles.h2} id="ember-final-title" data-reveal="">下一张主图，<br />让它一眼<span className={styles.acc}>出彩</span>。</h2>
          <div className={styles.cta} data-reveal="" style={{ "--i": 1 } as Vars}>
            <Link className={c("btn btnWhite")} href="/create">开始创作 <Use id="arrow" /></Link>
            <a className={c("btn btnGhost")} href="#cases">先看案例</a>
          </div>
        </div>
        <div className={styles.wordmark} ref={word} aria-hidden="true">POLARIS</div>
        <footer className={styles.footer}>
          <div className={c("wrap footerInner")}>
            <span>© 2026 极光商绘</span><span>让好商品，一眼出彩。</span>
            <nav aria-label="页脚"><Link href="/help">帮助中心</Link><Link href="/legal/privacy">隐私政策</Link><Link href="/legal/terms">服务条款</Link></nav>
          </div>
        </footer>
      </section>
    </div>
  );
}
