"""Generate a homepage-scoped dark (熔光) override sheet from the existing light CSS.

Every colour declaration in a rule that can affect the homepage is re-emitted under
`.app-shell--home`, with its colours mapped into the 熔光 palette:
  * neutrals and all cool / lime / lilac hues  -> warm neutrals with inverted lightness
  * warm saturated hues (red/orange/amber)      -> ember family, lightness adapted
  * shadows stay dark; light shadow colours become faint white hairlines
usage: python3 -I home_dark_gen.py <repo> <out.css>
"""
import colorsys, os, re, sys

ROOT, OUT = sys.argv[1], sys.argv[2]
CSS_FILES = ['app/globals.css', 'app/focus-inspired.css', 'app/commerce-theme.css',
             'app/commerce-surfaces.css', 'app/commerce-workspaces.css', 'app/commerce-forms.css',
             'app/commerce-readability.css', 'app/showcase-cases.css']
ENTRY = ['app/page.tsx', 'components/app-shell.tsx']
SCOPE = '.app-shell--home'

# ---------- collect words used by the homepage component tree ----------
def resolve(spec, base):
    if spec.startswith('@/'):
        p = os.path.join(ROOT, spec[2:])
    elif spec.startswith('.'):
        p = os.path.normpath(os.path.join(os.path.dirname(base), spec))
    else:
        return None
    for cand in (p, p + '.tsx', p + '.ts', os.path.join(p, 'index.tsx'), os.path.join(p, 'index.ts')):
        if os.path.isfile(cand):
            return cand
    return None

modules = set()
seen, stack, words = set(), [os.path.join(ROOT, e) for e in ENTRY], set()
IMP = re.compile(r'''(?:import|from)\s*(?:[^'"]*?from\s*)?['"]([^'"]+)['"]''')
while stack:
    f = stack.pop()
    if f in seen:
        continue
    seen.add(f)
    src = open(f, encoding='utf-8').read()
    words.update(re.findall(r'[A-Za-z][\w-]*', src))
    for spec in IMP.findall(src):
        if spec.endswith('.module.css'):
            mp = os.path.join(ROOT, spec[2:]) if spec.startswith('@/') else os.path.normpath(os.path.join(os.path.dirname(f), spec))
            if os.path.isfile(mp):
                modules.add(mp)
            continue
        r = resolve(spec, f)
        if r and r.endswith(('.tsx', '.ts')):
            stack.append(r)
words.discard('')

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
    return 92 - L * (34 / 50) if L > 10 else 92

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
    nr, ng, nb, na = map_rgb(r, g, b, role)
    if na is not None:
        a = (a if a is not None else 1) * (na / 1)
    elif role == 'shadow' and a is not None:
        a = min(1, a * 1.8)
    return fmt(nr, ng, nb, a)

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

CLASS = re.compile(r'\.(-?[A-Za-z_][\w-]*)')
ELEM_ONLY = re.compile(r'^[a-z0-9\s>+~:\-\(\)\[\]="\'*,_.]*$')

MODULE_MODE = [False]
def scope_selector(sel):
    sel = sel.strip()
    if MODULE_MODE[0]:
        if not sel or sel.startswith((':root', 'html', 'body', '::')) or 'app-shell--home' in sel:
            return None
        return ':global(.app-shell--home) ' + sel
    if not sel or sel.startswith((':root', 'html', 'body', '::')) or '@' in sel:
        return None
    classes = CLASS.findall(sel)
    if classes:
        if not any(c in words for c in classes if not c.startswith(('is-', 'has-'))):
            return None
    elif not re.match(r'^(a|button|input|textarea|select|h[1-6]|p|small|strong|em|label|code|kbd|hr|svg|img)\b', sel):
        return None
    if SCOPE in sel:
        return sel
    if re.search(r'\.app-shell(?![\w-])', sel):
        return re.sub(r'\.app-shell(?![\w-])', '.app-shell' + SCOPE, sel, count=1)
    return SCOPE + ' ' + sel

def decls(body):
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
        out.append(f'{p}:{map_value(v.strip(), role)}')
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
        ds = decls(body)
        if ds:
            rule = ','.join(sels) + '{' + ';'.join(ds) + '}'
            emitted.append(f'{wrap}{{{rule}}}' if wrap else rule)

for f in CSS_FILES:
    walk(strip_comments(open(os.path.join(ROOT, f), encoding='utf-8').read()))

START, END = '/* home-ember-dark:start — 由 scripts/home-dark-gen.py 生成，请勿手改 */', '/* home-ember-dark:end */'
MODULE_MODE[0] = True
for mp in sorted(modules):
    src = open(mp, encoding='utf-8').read()
    base = re.sub(re.escape(START) + r'.*?' + re.escape(END) + r'\n?', '', src, flags=re.S).rstrip('\n') + '\n'
    emitted_before = len(emitted)
    walk(strip_comments(base))
    block = emitted[emitted_before:]
    del emitted[emitted_before:]
    new = base + ('\n' + START + '\n' + '\n'.join(block) + '\n' + END + '\n' if block else '')
    if new != src:
        open(mp, 'w', encoding='utf-8').write(new)
    print('module', os.path.relpath(mp, ROOT), len(block))
MODULE_MODE[0] = False

with open(OUT, 'w', encoding='utf-8') as fh:
    fh.write('/* 首页暗色（熔光）——由 scripts/home-dark-gen.py 从现有浅色样式自动映射生成，请勿手改。\n'
             '   手调覆盖写在 app/home-ember-dark.css。 */\n')
    fh.write('\n'.join(emitted) + '\n')
print('component files:', len(seen), 'rules:', len(emitted), 'bytes:', os.path.getsize(OUT))
