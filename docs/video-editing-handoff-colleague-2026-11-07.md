# 极光商绘视频工作室接手说明

更新于 2026-11-20。交接以 Polaris Commerce Studio 的 `main` 为代码入口，本次核对的基准提交为 `2d1a450afafdebd54335c105d2a4eebe5338a489`。线上实际运行版本在首次验收前由部署负责人确认。[GitHub 主线](https://github.com/cai18122668086/polaris-commerce-studio/tree/main)

## 目前可以接着做什么

- 视频工作室支持文案、配音、数字人口播，以及把现有口播或上传的视频送入智能剪辑。仓库已包含字幕对齐、模板编排、成片渲染、任务进度、作品预览和下载的实现。
- 11 月 19 日合入了必火模板默认配乐、剪辑音效与画面事件对齐、数字人口播动作调整。涉及这些功能时，以现有实现和对应 PR 为准。[必火默认配乐 #197](https://github.com/cai18122668086/polaris-commerce-studio/pull/197) · [剪辑音效 #198](https://github.com/cai18122668086/polaris-commerce-studio/pull/198) · [数字人动作 #199](https://github.com/cai18122668086/polaris-commerce-studio/pull/199)

## 开始接手

1. 先确认自己的 GitHub 账号能读取仓库，从 `main` 拉取代码。按根目录 README 安装前端依赖、运行 `npm run dev`，并准备本地后端。先在约定的测试环境验收剪辑链路。[本地开发说明](../README.md#本地开发)
2. 请交接人确认测试账号、工作区和视频空间权限。网站入口是 [视频工作室](https://www.tengliapi.xyz/video-studio)。当前源码按服务端校验的已验证邮箱控制视频空间访问，仓库权限和视频空间权限要分别开通。[访问控制代码](../backend/app/video_studio_access.py)
3. 本地调试剪辑时，将 `compose.editing.yaml` 与基础 Compose 一起使用。先用 `POLARIS_EDITING_ASR_HOST` 指向约定的对齐模型目录，再运行 `docker compose -f compose.yaml -f compose.editing.yaml config` 检查配置。测试自动规划时按环境配置启用 `POLARIS_VIDEO_EDITING_PLANNING_ENABLED`。需要原生动效时再准备依赖绑定和只读挂载。模型、素材和配置来源由交接人提供。[本地剪辑配置](../compose.editing.yaml) · [原生动效依赖配置](../compose.editing-dependencies.yaml)
4. 请交接人给出团队共享目录的访问方式，先准备一条获准使用的原口播、对应配音或原声、参考成片及模板名称。优先使用视频工作室现有作品。需要离线调试时可用作品导出的「剪辑材料」ZIP，按清单核对视频、配音和确认稿。团队共享目录地址由交接人提供。[必火模板素材说明](bihuo-video-materials-2026-11-14.md) · [素材导出与接口](video-studio-editing-api-v1.md)

## 第一条验收

1. 用测试账号打开视频工作室，选一条现有口播进入智能剪辑，或在智能剪辑里上传一条已授权的测试视频。
2. 选一个必火模板，生成并预览成片。对照原声检查字幕有无漏句、重复或错位，确认花字和音效跟着画面事件出现，配乐音量不压过口播。
3. 刷新后从「我的作品」找回原任务，预览并下载成片。记录环境、部署版本、模板、任务 ID 和成片链接。任务结果尚未确认时，先查询原任务状态。

## 从哪里改

- 视频工作室入口与智能剪辑界面。[视频工作室路由](../app/video-studio) · [剪辑工作区](../components/video-studio/editing-workspace.tsx)
- 剪辑任务、作品与产物下载，以及规划和渲染进程。[任务接口](../backend/app/video_editing_task_routes.py) · [规划进程](../backend/app/video_editing_planning_worker.py) · [渲染进程](../backend/app/video_editing_worker.py)
- 必火模板编排、字幕恢复、音效和配乐。[必火模板实现](../backend/app/bihuo_suite) · [字幕恢复](../backend/app/video_editing_suite_caption_repair.py) · [音效](../backend/app/video_editing_suite_sound.py) · [配乐](../backend/app/video_editing_suite_music.py)
- 部署和回滚。请部署负责人给出当前部署记录、镜像版本和对应的 Git 提交，发布演练从仓库的部署脚本开始。[整合发布说明](video-integrated-release-2026-11-11.md) · [视频工作室部署](../deploy/video_studio)

如需把这项任务交给 AI，先提供本页、实际任务范围和相关 PR，再按上面的代码入口定位。
