# 底图提示词模板

代码只读取下面两条分隔线 `<!-- prompt -->` 之间的内容，用 `{占位符}` 填充。
结构参考 baoyu-cover-image base-prompt（MIT）与 autocrew identity-lock（MIT），按本项目改写。

<!-- prompt -->
Create a vertical 3:4 short-video cover photo (1080x1440) based on the reference video frame.

Identity lock: the person in the reference frame is the only source of identity. Keep the same face shape, facial proportions, eye spacing, nose and lips, hairstyle, glasses if any, and clothing. Do not slim the face, enlarge the eyes, change the expression or replace the person. Allowed: even skin tone, flattering soft key light and rim light, a cleaner and more attractive background, a slightly tighter or looser framing.

Composition ({type}): {type_rule}
Layout: {layout_rule}
Palette ({palette}): {palette_rule} The dominant color must not be blue, purple or a blue-purple gradient.
Mood ({mood}): {mood_rule}
Rendering: realistic photography, sharp focus on the person, natural skin texture, clean premium look, no heavy grain on the person.

Topic of the video (for atmosphere only, do not write it): {topic}

Strictly no text of any kind: no letters, no Chinese characters, no numbers, no captions, no subtitles, no logos, no watermarks, no app icons, no UI elements, no stickers, no QR codes. Keep the reserved title area clean, smooth and low in detail so that a headline can be placed there later.
<!-- prompt -->

## 各维度英文说明（代码按 key 读取）

| key | 文本 |
|---|---|
| type.hero | The person is the main subject, occupying about half to two thirds of the frame, against a simple background with gentle depth of field. |
| type.typography | Keep the person to one side or the lower part of the frame and leave a large clean area (at least 40% of the frame) for a headline. |
| type.scene | Keep a real-life environment with soft natural light that tells a story, but keep it uncluttered. |
| palette.warm | Cream white, beige and warm orange accents, soft warm light. |
| palette.elegant | Plaster off-white, warm grey and champagne gold accents, restrained and premium. |
| palette.earth | Olive green, terracotta and sand tones, natural daylight. |
| palette.vivid | Warm red, bright yellow and orange accents, high contrast but not harsh. |
| mood.bold | Slightly higher contrast and saturation, energetic. |
| mood.balanced | Normal contrast and saturation. |
| mood.subtle | Low contrast, muted colors, generous negative space. |
