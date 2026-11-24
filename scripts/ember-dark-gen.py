"""全站暗色（熔光）生成器。

把现有浅色样式里的每一条颜色声明，按熔光色板换算后重新输出到 `.theme-ember`（挂在 <html> 上）作用域下：
  * 中性色、以及所有蓝/紫/青柠色      -> 暖中性色，明度反转（浅底变深底，深字变浅字）
  * 暖色（红/橙/琥珀）                -> ember 色系，明度按黑底调整
  * 阴影保持深色；浅色阴影变成极淡的白色细线
  * 玻璃质感（2026-11-22，按已通过的 studio 原型）：浅色底（白、浅灰、浅紫蓝底）不再变成实心深灰，
    而是半透明暖白，让 body 上的暖色光透出来；带 position:fixed/absolute/sticky 的底色变成近不透明玻璃 + 背景模糊；
    按钮类选择器圆角改成胶囊，卡片类圆角略放大；字重统一收轻（600 以上 → 500，大标题 → 400），与原型一致
输出：
  * app/ember-dark.generated.css     —— 全局样式（app/*.css）的暗色映射
  * 每个 *.module.css 末尾的 ember-dark:start/end 块 —— 该模块的暗色映射（:global(.theme-ember) 作用域）
    （components/video-studio/ 除外：那里的样式自带暗色，见 OWN_DARK_DIRS）
浅色样式改动后重新运行即可：python3 -I scripts/ember-dark-gen.py .
"""
import colorsys, glob, os, re, sys

ROOT = sys.argv[1]
OUT = os.path.join(ROOT, 'app/ember-dark.generated.css')
OWN = {'app/ember-dark.generated.css', 'app/ember-dark.css', 'app/home-ember-dark.css', 'app/ember-studio.css'}
SCOPE = '.theme-ember'
GLOBAL_EXCLUDE = ':where(:not([data-video-studio]))'
START, END = '/* ember-dark:start — 由 scripts/ember-dark-gen.py 生成，请勿手改 */', '/* ember-dark:end */'
OLD_MARKERS = [('/* home-ember-dark:start — 由 scripts/home-dark-gen.py 生成，请勿手改 */', '/* home-ember-dark:end */')]

# ---------- colour maths ----------
def srgb2lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def lstar(r, g, b):
    y = 0.2126 * srgb2lin(r / 255) + 0.7152 * srgb2lin(g / 255) + 0.0722 * srgb2lin(b / 255)
    return 116 * (y ** (1 / 3) if y > 0.008856 else 7.787 * y + 16 / 116) - 16

def from_lstar(target, hue, sat):
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        r, g, b = (x * 255 for x in colorsys.hls_to_rgb(hue, mid, sat))
        if lstar(r, g, b) < target:
            lo = mid
        else:
            hi = mid
    return tuple(round(x * 255) for x in colorsys.hls_to_rgb(hue, (lo + hi) / 2, sat))

def inv(L):
    # white 100 -> 4 (#0b0b0b), 97 -> 7, 90 -> 15 (hairline), ink 10 -> 92 (#edeae4), 50 -> 58
    if L >= 50:
        return 58 - (L - 50) * (54 / 50) if L < 88 else 17 - (L - 88) * (13 / 12)
    return 92 - (L - 22) * (34 / 28) if L > 22 else 92  # 最深的墨色（主按钮、正文）都映射成接近白色的 #edeae4

WARM = 34 / 360
def map_rgb(r, g, b, role):
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    hue = h * 360
    L = lstar(r, g, b)
    chroma = max(r, g, b) - min(r, g, b)
    if role == 'shadow':
        return (255, 255, 255, 0.10) if L > 70 else (0, 0, 0, None)
    warm = chroma > 40 and (hue < 50 or hue > 340)
    if warm:  # keep ember family, adapt lightness for a black page
        target = 62 if L < 75 else 20
        return from_lstar(target, 18 / 360 if hue < 30 or hue > 340 else 34 / 360, 0.95) + (None,)
    return from_lstar(inv(L), WARM, 0.06 if chroma > 6 else 0.04) + (None,)

def fmt(r, g, b, a):
    if a is None or a >= 0.999:
        return '#%02x%02x%02x' % (r, g, b)
    return 'rgb(%d %d %d / %s)' % (r, g, b, ('%.3f' % a).rstrip('0').rstrip('.'))

HEX = re.compile(r'#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])')
RGB = re.compile(r'rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)\s*(?:[,/]\s*([\d.]+%?))?\s*\)')
ALL = re.compile(r'(?P<hex>' + HEX.pattern + r')|(?P<rgb>' + RGB.pattern + r')|(?<![\w-])(?P<name>white|black)(?![\w-])')
NAMED = {'white': (255, 255, 255), 'black': (0, 0, 0), '#fff': (255, 255, 255)}

def conv(r, g, b, a, role):
    # 半透明深色铺底（遮罩、图片上的暗角）在暗色下仍是深色，不反转
    if role == 'scrim' and a is not None and a >= 0.25 and lstar(r, g, b) < 25:
        return fmt(0, 0, 0, min(1, a * 1.25))
    if role == 'scrim':
        role = 'paint'
        # 彩色实底（原来的紫/蓝/青柠色按钮、强调卡片，配白字）→ 接近白色的实底，白字会同步反转成深色
        h, l, s_ = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        hue, L = h * 360, lstar(r, g, b)
        if max(r, g, b) - min(r, g, b) > 40 and 50 <= hue <= 335 and 25 <= L <= 65 and (a is None or a > 0.6):
            return fmt(0xe6, 0xe2, 0xdb, a)
        warm_ = max(r, g, b) - min(r, g, b) > 40 and (hue < 50 or hue > 340)
        if not warm_ and L >= 80:
            return glass(L, a)
    nr, ng, nb, na = map_rgb(r, g, b, role)
    if na is not None:
        a = (a if a is not None else 1) * (na / 1)
    elif role == 'shadow' and a is not None:
        a = min(1, a * 1.8)
    return fmt(nr, ng, nb, a)

OVERLAY = [False]  # 当前规则是浮层（fixed/absolute/sticky）
def glass(L, a):
    if OVERLAY[0]:
        base = 0.86 if L >= 95 else 0.9
        return fmt(21, 20, 19, base if a is None else min(1, base * max(a, 0.6)))
    k = 0.04 if L >= 99.5 else 0.025 if L >= 95 else 0.06 if L >= 88 else 0.09
    return fmt(255, 250, 244, k * (1 if a is None else a))

def map_value(v, role):
    def hx(m):
        s = m.group(1)
        full = ''.join(c * 2 for c in s) if len(s) in (3, 4) else s
        r, g, b = (int(full[i:i + 2], 16) for i in (0, 2, 4))
        a = int(full[6:8], 16) / 255 if len(full) == 8 else None
        return conv(r, g, b, a, role)
    def rg(m):
        r, g, b = (float(m.group(i)) for i in (1, 2, 3))
        a = m.group(4)
        if a is not None:
            a = float(a[:-1]) / 100 if a.endswith('%') else float(a)
        return conv(r, g, b, a, role)
    # one pass, so an already-mapped colour is never mapped a second time
    def any_(m):
        if m.group('hex'):
            return hx(HEX.match(m.group(0)))
        if m.group('rgb'):
            return rg(RGB.match(m.group(0)))
        return conv(*NAMED[m.group('name')], None, role)
    return ALL.sub(any_, v)

COLOR_PROPS = re.compile(r'^(color|background(-color|-image)?|border(-(top|right|bottom|left|block|inline)(-start|-end)?)?(-color)?|'
                         r'outline(-color)?|box-shadow|text-shadow|fill|stroke|caret-color|text-decoration(-color)?|'
                         r'column-rule(-color)?|accent-color|--[\w-]+|filter|-webkit-text-fill-color|scrollbar-color)$')
HAS_COLOR = re.compile(r'#[0-9a-fA-F]{3,8}(?![\w-])|rgba?\(|(?<![\w-])(white|black)(?![\w-])')

# ---------- tiny CSS walker ----------
def strip_comments(s):
    return re.sub(r'/\*.*?\*/', '', s, flags=re.S)

def blocks(s):
    i, n = 0, len(s)
    while i < n:
        j = s.find('{', i)
        if j < 0:
            return
        prelude = s[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            if s[k] == '{': depth += 1
            elif s[k] == '}': depth -= 1
            k += 1
        yield prelude, s[j + 1:k - 1]
        i = k

def split_top(s, sep):
    out, depth, cur = [], 0, ''
    for ch in s:
        if ch in '([': depth += 1
        elif ch in ')]': depth -= 1
        if ch == sep and depth == 0:
            out.append(cur); cur = ''
        else:
            cur += ch
    out.append(cur)
    return out


MODULE_MODE = [False]
def scope_selector(sel):
    sel = sel.strip()
    if not sel or '@' in sel or sel.startswith(('from', 'to')) or re.match(r'^[\d.]+%$', sel):
        return None
    if SCOPE in sel:
        return sel
    if MODULE_MODE[0]:
        if sel.startswith((':root', 'html')):
            return None
        return ':global(' + SCOPE + ') ' + sel
    if sel.startswith(':root'):
        return SCOPE + sel[5:]
    if re.match(r'^html(?![\w-])', sel):
        return 'html' + SCOPE + sel[4:]
    return SCOPE + ' ' + sel

BUTTONISH = re.compile(r'(button|btn|cta|submit|primary|secondary|chip|pill|toggle|segment|badge|tag)', re.I)
NOT_BUTTON = re.compile(r'(card|panel|grid|image|img|thumb|preview|upload|drop|modal|dialog|sheet|menu|input|field|textarea|select|list|table|frame|canvas|editor|wrap|container|section|group)', re.I)
POSITIONED = re.compile(r'(?:^|;)\s*position\s*:\s*(fixed|absolute|sticky)', re.I)
def shape(prelude, body):
    extra = []
    bg = re.search(r'(?:^|;)\s*background(-color)?\s*:', ';' + body)
    m = re.search(r'(?:^|;)\s*border-radius\s*:\s*([\d.]+)px\s*(?:;|$)', ';' + body)
    last = [x.strip().split(' ')[-1] for x in prelude.split(',')]
    if m:
        r = float(m.group(1))
        if 0 < r <= 14 and all(BUTTONISH.search(x) and not NOT_BUTTON.search(x) for x in last):
            extra.append('border-radius:999px')
        elif bg and 6 <= r <= 16 and not any(BUTTONISH.search(x) for x in last):
            extra.append('border-radius:%dpx' % min(22, round(r * 1.35)))
    if bg and POSITIONED.search(';' + body):
        extra.append('-webkit-backdrop-filter:blur(24px) saturate(1.3)')
        extra.append('backdrop-filter:blur(24px) saturate(1.3)')
    return extra

WEIGHT = re.compile(r'(?:^|;)\s*font-weight\s*:\s*(bold|bolder|[6-9]00)\s*(?:!important)?\s*(?:;|$)', re.I)
SIZE_PX = re.compile(r'(?:^|;)\s*font-size\s*:\s*(?:clamp\([^,]+,[^,]+,\s*)?([\d.]+)(px|rem)', re.I)
def weight(body):
    if not WEIGHT.search(';' + body):
        return []
    m = SIZE_PX.search(';' + body)
    size = (float(m.group(1)) * (16 if m.group(2).lower() == 'rem' else 1)) if m else 0
    return ['font-weight:%d' % (400 if size >= 28 else 500)]

def decls(body, prelude=''):
    OVERLAY[0] = bool(POSITIONED.search(';' + body))
    out = []
    for d in split_top(body, ';'):
        if ':' not in d:
            continue
        p, v = d.split(':', 1)
        p = p.strip().lower()
        if not COLOR_PROPS.match(p) or not HAS_COLOR.search(v):
            continue
        if p == 'filter' and 'drop-shadow' not in v:
            continue
        role = 'shadow' if p in ('box-shadow', 'text-shadow', 'filter') or (p.startswith('--') and 'shadow' in p) else 'paint'
        if role == 'paint' and p.startswith('background'):
            role = 'scrim'
        out.append(f'{p}:{map_value(v.strip(), role)}')
    # background 简写会把同一规则里的 background-clip/size/position 等重置，需原样补回
    if any(d.startswith('background:') for d in out):
        for d in split_top(body, ';'):
            if ':' in d:
                p, v = d.split(':', 1)
                p = p.strip().lower()
                if re.match(r'^(-webkit-)?background-(clip|origin|size|position(-x|-y)?|repeat|attachment|blend-mode)$', p):
                    out.append(f'{p}:{v.strip()}')
    if out and prelude:
        out += shape(prelude, body)
    if prelude:
        out += weight(body)
    return out

emitted = []
def walk(css, wrap=None):
    for prelude, body in blocks(css):
        if prelude.startswith('@'):
            if prelude.startswith(('@media', '@supports', '@layer', '@container')):
                walk(body, prelude)
            continue
        if prelude.strip() == ':root' and not MODULE_MODE[0]:
            ds = [d for d in decls(body) if d.startswith('--')]
            if ds:
                rule = SCOPE + '{' + ';'.join(ds) + '}'
                emitted.append(f'{wrap}{{{rule}}}' if wrap else rule)
            continue
        sels = [s for s in (scope_selector(x) for x in split_top(prelude, ',')) if s]
        if not sels:
            continue
        ds = decls(body, prelude)
        if ds:
            rule = ','.join(sels) + '{' + ';'.join(ds) + '}'
            emitted.append(f'{wrap}{{{rule}}}' if wrap else rule)

emitted = []
def walk(css, wrap=None):
    for prelude, body in blocks(css):
        if prelude.startswith('@'):
            if prelude.startswith(('@media', '@supports', '@layer', '@container')):
                walk(body, prelude)
            continue
        sels = [s for s in (scope_selector(x) for x in split_top(prelude, ',')) if s]
        if not sels:
            continue
        ds = decls(body, prelude)
        if ds:
            rule = ','.join(sels) + '{' + ';'.join(ds) + '}'
            emitted.append(f'{wrap}{{{rule}}}' if wrap else rule)

ORDER = ['globals', 'focus-inspired', 'commerce-theme', 'commerce-surfaces', 'commerce-workspaces',
         'commerce-forms', 'commerce-readability', 'showcase-cases']
files = sorted((os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, 'app', '**', '*.css'), recursive=True)
                if not p.endswith('.module.css')),
               key=lambda p: (ORDER.index(os.path.basename(p)[:-4]) if os.path.basename(p)[:-4] in ORDER else 99, p))
for f in files:
    if f in OWN or f.startswith('app/home-ember-dark'):
        continue
    walk(strip_comments(open(os.path.join(ROOT, f), encoding='utf-8').read()))
    print('global', f)

MODULE_MODE[0] = True
# 视频空间（components/video-studio）的样式本身已按熔光暗色手调，文件里的 ember-dark 块来自视频分支，
# 不能再按“浅色 → 暗色”映射一遍（2026-11-25 集成时重跑导致深底深字）。整个目录跳过，块原样保留。
OWN_DARK_DIRS = ('/components/video-studio/',)
mods = [p for p in glob.glob(os.path.join(ROOT, '**', '*.module.css'), recursive=True)
        if '/node_modules/' not in p and '/dist/' not in p and '/.next/' not in p
        and not any(d in p.replace(os.sep, '/') for d in OWN_DARK_DIRS)]
for mp in sorted(mods):
    src = open(mp, encoding='utf-8').read()
    base = src
    if 'ember-dark:skip' in src:
        stripped = re.sub(r'\n?' + re.escape(START) + r'.*?' + re.escape(END) + r'\n?', '\n', src, flags=re.S)
        if stripped != src:
            open(mp, 'w', encoding='utf-8').write(stripped)
        continue
    for a, b in OLD_MARKERS + [(START, END)]:
        base = re.sub(r'\n?' + re.escape(a) + r'.*?' + re.escape(b) + r'\n?', '\n', base, flags=re.S)
    base = base.rstrip('\n') + '\n'
    before = len(emitted)
    walk(strip_comments(base))
    block = emitted[before:]
    del emitted[before:]
    new = base + ('\n' + START + '\n' + '\n'.join(block) + '\n' + END + '\n' if block else '')
    if new != src:
        open(mp, 'w', encoding='utf-8').write(new)
MODULE_MODE[0] = False
print('modules:', len(mods))

with open(OUT, 'w', encoding='utf-8') as fh:
    fh.write('/* 全站暗色（熔光）——由 scripts/ember-dark-gen.py 从现有浅色样式自动映射生成，请勿手改。\n'
             '   手调覆盖写在 app/ember-dark.css（全站）和 app/home-ember-dark.css（首页）。 */\n')
    # 全局映射不作用于视频空间：它挂 html[data-video-studio]，样式自带暗色（:where 不增加优先级）。
    fh.write(re.sub(r'\.theme-ember(?![\w-])', '.theme-ember' + GLOBAL_EXCLUDE, '\n'.join(emitted)) + '\n')
print('rules:', len(emitted), 'bytes:', os.path.getsize(OUT))
