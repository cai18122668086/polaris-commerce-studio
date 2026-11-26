"""全站浅色（石膏灰白）生成器。

与 scripts/ember-dark-gen.py 共用同一套 CSS 解析，只换颜色映射：把现有浅色样式里的每一条颜色声明，
按石膏灰白色板换算后输出到 `.theme-plaster`（挂在 <html> 上）作用域下。明度基本保持，不反转：
  * 纯白                              -> 纯白（卡片、面板）
  * 浅灰（明度 90–99.5）              -> 暖中性浅灰，整体压暗一点，和石膏底色 #eeedea 同一族
  * 其余中性色、文字                  -> 暖中性色，明度略降，正文更稳
  * 蓝、紫、青、青柠等彩色             -> 中等明度的实色变成墨色 #1a1a19（主按钮、链接、选中态），浅色底变成浅灰
  * 暖色（红/橙/琥珀）                -> 熔光色系，按白底调整明度
  * 绿色（成功状态）                  -> 原样保留
  * 阴影                              -> 去掉原来的藏青色调，改成暖中性
圆角、按钮胶囊、字重收轻与熔光版一致（同一套规则）。
输出：
  * app/plaster.generated.css                  —— 全局样式（app/*.css）的映射
  * 每个 *.module.css 末尾的 plaster:start/end 块 —— 该模块的映射（:global(.theme-plaster) 作用域）
浅色样式改动后重新运行即可：python3 -I scripts/plaster-gen.py .
"""
import colorsys, importlib.util, os, sys

ROOT = sys.argv[1]
_spec = importlib.util.spec_from_file_location('ember_dark_gen', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ember-dark-gen.py'))
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

INK = (26, 26, 25)        # #1a1a19
HUE = 45 / 360            # 石膏色的暖中性色相
lstar, from_lstar, fmt = gen.lstar, gen.from_lstar, gen.fmt


def lightness(L):
    if L >= 99.5:
        return 100
    if L >= 90:
        return 88.5 + (L - 90) * (8.5 / 9.5)
    return max(9.5, L * 0.97)


def neutral(L, a):
    if L >= 99.5:
        return fmt(255, 255, 255, a)
    return fmt(*from_lstar(lightness(L), HUE, 0.05), a)


def conv(r, g, b, a, role):
    h, _, _ = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    hue, L = h * 360, lstar(r, g, b)
    chroma = max(r, g, b) - min(r, g, b)
    if role == 'shadow':
        return fmt(255, 255, 255, a) if L > 70 else fmt(30, 27, 22, a)
    warm = chroma > 40 and (hue < 50 or hue > 340)
    green = chroma > 40 and 85 <= hue <= 175
    if green:
        return fmt(r, g, b, a)
    if warm:
        if L >= 80:
            return fmt(*from_lstar(min(97, L), 24 / 360, 0.7), a)
        return fmt(*from_lstar(max(42, min(L, 56)), 16 / 360 if hue < 30 or hue > 340 else 30 / 360, 0.85), a)
    if chroma > 40:  # 蓝、紫、青、青柠……一律去色
        if a is not None and a < 0.35:
            return fmt(*INK, round(a * 0.75, 3))
        if L >= 80:
            return neutral(min(L, 97), a)
        return fmt(*INK, a)
    return neutral(L, a)


gen.conv = conv
gen.SCOPE = '.theme-plaster'
gen.START, gen.END = gen.THEME_BLOCKS[1]
gen.OUT = os.path.join(ROOT, 'app/plaster.generated.css')
gen.HEADER = ('/* 全站浅色（石膏灰白）——由 scripts/plaster-gen.py 从现有浅色样式自动映射生成，请勿手改。\n'
              '   手调覆盖写在 app/plaster.css。 */\n')
gen.run()
