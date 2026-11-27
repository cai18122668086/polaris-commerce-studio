/* MG components for supplement motion graphics (W4, v3).
 * Runs in headless Chromium with anime.js 4.5.0 (MIT) as the global `anime`.
 * Input: window.MG_INPUT = {component, params, style, duration_ms, width, height}
 * Output: window.mgSeek(ms) renders the exact state at ms (deterministic).
 * Palette comes only from the style tokens (no blue / purple).
 */
(function () {
  "use strict";
  const { createTimeline } = anime;
  const I = window.MG_INPUT;
  const S = I.style;
  const D = I.duration_ms;
  const OUT = 260; // exit duration
  const root = document.getElementById("mg");
  root.style.width = I.width + "px";
  root.style.height = I.height + "px";
  const counters = [];

  function el(tag, cls, text, parent) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    (parent || root).appendChild(node);
    return node;
  }

  function card(extra) {
    const c = el("div", "card " + (extra || ""));
    c.style.background = S.bg;
    c.style.color = S.fg;
    return c;
  }

  function enterExit(tl, target, from) {
    tl.add(target, { opacity: [0, 1], translateY: [from || 48, 0], duration: 480, ease: "outCubic" }, 0);
    tl.add(target, { opacity: [1, 0], translateY: [0, -16], duration: OUT, ease: "inCubic" }, Math.max(600, D - OUT));
  }

  const BUILD = {
    data_callout(p, tl) {
      const c = card("pad");
      const row = el("div", "row", null, c);
      const num = el("span", "num", "0", row);
      num.style.color = S.accent;
      if (p.unit) el("span", "unit", p.unit, row);
      if (p.label) el("div", "label", p.label, c);
      const line = el("div", "rule", null, c);
      line.style.background = S.line;
      enterExit(tl, c);
      const target = parseFloat(String(p.value).replace(/[^0-9.]/g, ""));
      if (isFinite(target) && /^[0-9.]+$/.test(p.value)) {
        const decimals = (String(p.value).split(".")[1] || "").length;
        const o = { v: 0 };
        tl.add(o, { v: target, duration: 640, ease: "outQuint" }, 140);
        counters.push(() => { num.textContent = o.v.toFixed(decimals); });
      } else {
        num.textContent = p.value;
        tl.add(num, { opacity: [0, 1], scale: [0.9, 1], duration: 420, ease: "outCubic" }, 140);
      }
      tl.add(line, { width: ["0%", "100%"], duration: 420, ease: "outCubic" }, 420);
    },
    feature_card(p, tl) {
      const c = card("pad feature");
      const bar = el("div", "bar", null, c);
      bar.style.background = S.accent;
      const body = el("div", "fbody", null, c);
      const t = el("div", "ftitle", p.title, body);
      if (p.desc) {
        const d = el("div", "fdesc", p.desc, body);
        d.style.color = S.sub;
        tl.add(d, { opacity: [0, 1], translateX: [-16, 0], duration: 380, ease: "outCubic" }, 300);
      }
      enterExit(tl, c);
      tl.add(bar, { scaleY: [0, 1], duration: 420, ease: "outCubic" }, 120);
      tl.add(t, { opacity: [0, 1], translateX: [-16, 0], duration: 380, ease: "outCubic" }, 200);
    },
    checklist(p, tl) {
      const c = card("pad");
      const step = Math.min(420, (D - 900) / p.items.length);
      p.items.forEach((text, i) => {
        const row = el("div", "check", null, c);
        const box = el("span", "tick", null, row);
        box.innerHTML = '<svg viewBox="0 0 40 40"><path d="M8 21 L17 30 L33 11" fill="none" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
        const path = box.querySelector("path");
        path.setAttribute("stroke", S.accent);
        path.style.strokeDasharray = "40";
        el("span", "ctext", text, row);
        const at = 260 + i * step;
        tl.add(row, { opacity: [0, 1], translateX: [-20, 0], duration: 320, ease: "outCubic" }, at);
        tl.add(path, { strokeDashoffset: [40, 0], duration: 300, ease: "outCubic" }, at + 120);
      });
      enterExit(tl, c);
    },
    compare_split(p, tl) {
      const c = card("pad split");
      const left = el("div", "half", null, c);
      const mid = el("div", "mid", null, c);
      mid.style.background = S.line;
      const right = el("div", "half", null, c);
      if (p.left_label) { const l = el("div", "hlabel", p.left_label, left); l.style.color = S.sub; }
      el("div", "hval", p.left, left);
      if (p.right_label) { const r = el("div", "hlabel", p.right_label, right); r.style.color = S.sub; }
      const rv = el("div", "hval", p.right, right);
      rv.style.color = S.accent;
      enterExit(tl, c);
      tl.add(left, { opacity: [0, 1], translateX: [-40, 0], duration: 420, ease: "outCubic" }, 160);
      tl.add(right, { opacity: [0, 1], translateX: [40, 0], duration: 420, ease: "outCubic" }, 420);
      tl.add(mid, { scaleY: [0, 1], duration: 360, ease: "outCubic" }, 620);
    },
    step_progress(p, tl) {
      const c = card("pad steps");
      const track = el("div", "track", null, c);
      track.style.background = S.sub;
      const fill = el("div", "fill", null, track);
      fill.style.background = S.accent;
      const nodes = el("div", "nodes", null, c);
      const n = p.steps.length;
      const step = Math.min(520, (D - 900) / n);
      p.steps.forEach((text, i) => {
        const node = el("div", "node", null, nodes);
        const dot = el("span", "dot", String(i + 1), node);
        dot.style.borderColor = S.accent;
        el("span", "nlabel", text, node);
        const at = 300 + i * step;
        tl.add(node, { opacity: [0.25, 1], duration: 280, ease: "outCubic" }, at);
        tl.add(dot, { backgroundColor: [S.bg, S.accent], color: [S.fg, S.bg], duration: 280, ease: "outCubic" }, at);
      });
      tl.add(fill, { width: ["0%", "100%"], duration: Math.max(400, step * (n - 1)), ease: "inOutCubic" }, 300);
      enterExit(tl, c);
    },
    quote_card(p, tl) {
      const c = card("pad quote");
      const mark = el("div", "qmark", "“", c);
      mark.style.color = S.accent;
      const text = el("div", "qtext", p.text, c);
      if ([...p.text].length > 12) text.style.fontSize = "52px";
      enterExit(tl, c);
      tl.add(mark, { opacity: [0, 1], scale: [0.6, 1], duration: 360, ease: "outCubic" }, 120);
      tl.add(text, { opacity: [0, 1], translateY: [20, 0], duration: 460, ease: "outCubic" }, 300);
    },
    price_tag(p, tl) {
      const c = card("pad price");
      const row = el("div", "row", null, c);
      const yen = el("span", "yen", "¥", row);
      yen.style.color = S.accent;
      const v = el("span", "pval", String(p.price).replace(/^[¥￥]/, ""), row);
      v.style.color = S.accent;
      if (p.note) { const n = el("div", "pnote", p.note, c); n.style.color = S.sub; }
      tl.add(c, { opacity: [0, 1], translateY: [-60, 0], duration: 520, ease: "outQuint" }, 0);
      tl.add(c, { opacity: [1, 0], duration: OUT, ease: "inCubic" }, Math.max(600, D - OUT));
    },
    title_reveal(p, tl) {
      root.style.background = S.bg;
      const wrap = el("div", "tr");
      const mask = el("div", "trmask", null, wrap);
      const text = el("div", "trtext", p.text, mask);
      text.style.color = S.fg;
      text.style.fontSize = Math.min(112, Math.floor(880 / [...p.text].length)) + "px";
      const rule = el("div", "trrule", null, wrap);
      rule.style.background = S.accent;
      tl.add(root, { opacity: [0, 1], duration: 200, ease: "linear" }, 0);
      tl.add(text, { translateY: ["105%", "0%"], letterSpacing: ["0.08em", "0em"], duration: 520, ease: "outCubic" }, 120);
      tl.add(rule, { width: ["0px", "220px"], duration: 420, ease: "outCubic" }, 420);
      tl.add(root, { opacity: [1, 0], duration: 240, ease: "inCubic" }, Math.max(700, D - 240));
    },
  };

  const tl = createTimeline({ autoplay: false, duration: D });
  BUILD[I.component](I.params, tl);
  // Pin the timeline length so seek(ms) maps 1:1 to the display window.
  tl.add({ x: 0 }, { x: 1, duration: 1 }, D - 1);

  window.mgSeek = function (ms) {
    tl.seek(Math.max(0, Math.min(D, ms)));
    for (const update of counters) update();
    return true;
  };
  const sample = root.textContent || "极光";
  window.mgReady = Promise.all([
    document.fonts.load("40px MGTitle", sample),
    document.fonts.load("40px MGBody", sample),
  ]).then(() => document.fonts.ready).then(() => {
    window.mgSeek(0);
    return [...document.fonts].map((f) => f.family + ":" + f.status);
  });
})();
