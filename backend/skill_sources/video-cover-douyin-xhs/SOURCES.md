# 来源与授权（2026-11-28 调研）

本 skill 的规则改编自两个 MIT 许可的开源项目；许可证原文见 `LICENSE-THIRD-PARTY.md`。
没有明确许可证的仓库只看了公开介绍，**没有复制任何原文**。

## 采用（MIT，可商用改编）

| 项目 | 链接 | 许可证 | 锁定版本 | 我们取了什么 |
|---|---|---|---|---|
| JimLiu/baoyu-skills · baoyu-cover-image | https://github.com/JimLiu/baoyu-skills/tree/main/skills/baoyu-cover-image | MIT（Copyright (c) 2026 Jim Liu） | `bf1ff076e25f8da4a339eb1c8cf03361fea5ea4c`，skill 版本 1.117.5 | 「五维度」出图法（构图类型 / 配色 / 渲染 / 文字密度 / 情绪强度）与按内容信号自动选择的规则；「标题必须用原文，不得改写」；留白 40–60%、标题区预留、单一视觉焦点的构图原则。改写为中文并按短视频真人口播场景收窄。 |
| alextangson/autocrew · cover-generator / xhs-cover-review | https://github.com/alextangson/autocrew/tree/main/skills | MIT（Copyright (c) 2026 alextangson） | `d0bd1420065419320accb8e5b6351789d5a1c6ea` | 真人封面「身份锁定」（以真实帧为唯一身份真值、禁止改脸型/眼距/鼻唇比例）；「字不得穿过脸」；候选必须是**不同结构**而不是换色；三视图验收（整图 / 人脸 100% 裁切 / 200px 缩略图）；不出水印、Logo、网址。 |
| alextangson/autocrew · 平台封面实测 | https://github.com/alextangson/autocrew/blob/main/docs/research/2026-09-27-platform-cover-surfaces.md | MIT（同上） | 同上 | 抖音 / 小红书主页网格实测：都以竖 3:4 为主封面；抖音主页网格底部约 20% 高渐变 + 左下播放数；小红书卡片比例夹在 3:4–4:3 之间。用于决定封面比例、底部安全区和「我的作品」网格观感。 |

## 与来源不同的地方（有意改动）

- **文字一律程序排版**。两个来源都禁止用 Pillow/Canvas 覆盖文字、要求模型直接出字；我们的任务书要求「封面上的字与标题一字不差」，模型出中文字不可靠，所以反过来：**AI 只出无字底图，标题由 Pillow 用站内字体排版**，再做逐字与遮脸核对。
- 只出竖版 **3:4（1080×1440）**；抖音横封面（4:3）这期不做。
- 每条视频默认 **2 个候选**（来源是 3 个），两个候选必须用不同版式。
- 人物来自视频关键帧（YuNet 人脸检测挑帧），不是用户上传的形象照。
- 颜色约束：主色调不得为蓝 / 紫（站点规则），点缀色用暖色。

## 只参考、未复制（无许可证）

| 项目 | 链接 | 情况 |
|---|---|---|
| cclank/xhs-cover-skill | https://github.com/cclank/xhs-cover-skill | 无 LICENSE，只读介绍 |
| Vivixiao980/xhs-cover-skill | https://github.com/Vivixiao980/xhs-cover-skill | 仓库无 LICENSE 文件（聚合站标 MIT，以仓库为准） |
| vivy-yi/xiaohongshu-skills（cover-design） | https://github.com/vivy-yi/xiaohongshu-skills | 无 LICENSE |
| freestylefly/xiaohongshu-skills | https://github.com/freestylefly/xiaohongshu-skills | 无 LICENSE |
| 0x00000003/douyin-cover-builder | https://github.com/0x00000003/douyin-cover-builder | 无 LICENSE |

另看过 SamurAIGPT/Generative-Media-Skills 的 rednote-cover（MIT），内容是调用其自家 muapi 接口的薄封装，规则价值低，未采用。
