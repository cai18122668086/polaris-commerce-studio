"""视频空间暗色（熔光）映射：复用 scripts/ember-dark-gen.py 的换色规则，只处理 components/video-studio 下的样式模块。

全站生成器会改写所有 *.module.css 和 app/ember-dark.generated.css，那是前端改版线程的范围；
视频线只需要自己的模块，所以这里只取其换色函数，按同样的 ember-dark:start/end 标记写回。
视频样式改动后重新运行：python3 -I scripts/video-ember-dark.py .
"""
import glob, os, re, sys

ROOT = sys.argv[1]
GEN = os.path.join(ROOT, 'scripts/ember-dark-gen.py')
src = open(GEN, encoding='utf-8').read()
ns = {'__name__': 'ember_dark_rules'}
sys.argv = [GEN, ROOT]
exec(compile(src[:src.index('\nORDER = ')], GEN, 'exec'), ns)

ns['MODULE_MODE'][0] = True
# 手调层（选择器里已经带 .theme-ember 的规则）本身就是暗色值，不能再换算一遍，否则生成块会排在后面把手调覆盖。
# 石膏灰白的手调规则（.theme-plaster）同理跳过：那是浅色主题自己的值。
_scope = ns['scope_selector']
ns['scope_selector'] = lambda sel: None if any(t in sel for t in ns['THEME_SCOPES']) else _scope(sel)
emitted, walk, strip = ns['emitted'], ns['walk'], ns['strip_comments']
START, END, OLD = ns['START'], ns['END'], ns['OLD_MARKERS']
# 石膏灰白块（scripts/plaster-gen.py 生成）不是源样式：换算前摘掉，写回时原样接在暗色块后面。
PLASTER = ns['THEME_BLOCKS'][1]
mods = sorted(glob.glob(os.path.join(ROOT, 'components/video-studio/*.module.css')))
for mp in mods:
    text = open(mp, encoding='utf-8').read()
    base = text
    pm = re.search(re.escape(PLASTER[0]) + r'.*?' + re.escape(PLASTER[1]), base, flags=re.S)
    for a, b in OLD + [(START, END), PLASTER]:
        base = re.sub(r'\n?' + re.escape(a) + r'.*?' + re.escape(b) + r'\n?', '\n', base, flags=re.S)
    base = base.rstrip('\n') + '\n'
    before = len(emitted)
    walk(strip(base))
    block = emitted[before:]
    del emitted[before:]
    new = base + ('\n' + START + '\n' + '\n'.join(block) + '\n' + END + '\n' if block else '')
    new += '\n' + pm.group(0) + '\n' if pm else ''
    if new != text:
        open(mp, 'w', encoding='utf-8').write(new)
    print(os.path.relpath(mp, ROOT), len(block))
