# 智能剪辑对标候选版 · 2026-11-12

工作树 C:/Users/a1726/Desktop/cyh/tengli/worktrees/bihuo-editing-20261112，分支 codex/bihuo-editing-20261112，基线c737518。未改旧主目录或替换用户3018/8018服务，未部署线上。

## 范围与反馈

先在内置浏览器审计必火智能剪辑，重排前端，成套编排动效；收到命名素材先全文规划固定台词词点，不逐帧API规划。用户已认可分组推进与B01/B02 v4实际效果，并要求继续整套；随后明确要求加速，停止像素级反复量测。

24.04秒参考是Downloads/20261112_114714_cov1111-1041.mp4；53.052秒参考是微信10a37fa..._raw.mp4。151727..._raw.mp4为52.24秒干净原片，不是第二条剪辑参考。

对标已审计登录后的原片、模板库、素材管理、音乐、封面、文字名片、参考稿、历史和缺原片提交。账号算力不足，未提交付费生成，成功结果编辑页未验证。没有上传用户私人原片到对标。账号找到五份原录屏，成片确认四次资料接管link/upload/style/result，pull不能冒认原片使用。

## 代码结果

主页面白底三栏、素材与模板弹窗、历史搜索和单一开始按钮；技术诊断退出主流程。普通上传默认无字幕，已有字幕在更多选项声明，Apple前后端拒绝烧字原片。一次明确开始连续保存、识别、准备、单次规划、预览，改输入撤销自动链，刷新不恢复付费意图。

参考稿绑定识别任务与缓存签名，不伪造确认稿来源。旧模板配乐支持模板/降低/关闭并冻结；Apple明确为口播原声。Apple主副标题、名片、自动封面或无封面均进真实任务；长文字自然换行，超容量明确失败。

新准备使用cohesive-suite/1，同系列机制选择，取消至少5种/优先10种配额，允许单种复用。素材基于全文及名称说明检索，单次模型规划固定真实词ID，渲染无视觉API规划。旧请求来源校验兼容新增可选文件，并正确区分新cohesive全文schema与旧compact协议。

backend/app/apple_minimal/是独立版本运行时，video_editing_apple_contracts.py负责词ID计划与编译，video_editing_apple_pipeline.py复用队列、预览、高清确认。新机制未伪装为旧132组，46份原冻结模板未改。

## Motion与真实产物

同事motion.json声明motiongit-template草案，实际是Python/浏览器/Hypit工程包，不是视频编码。新包沿用组件、参数、配方和adapter组织；第三方MotionGit客户端导入未验证，本轮没有迁移Remotion。

工程 C:/Users/a1726/Desktop/cyh/剪辑/智能剪辑对标_20261112/apple-minimal-suite。

- 完整10组对比：http://127.0.0.1:8768/reviews/complete/index.html
- 52.24秒资料版：render/complete/business-v2/final.mp4
- 26.24秒新人物/内容要点版：render/complete/points-v2/final.mp4
- 候选代码包和两条预览：delivery/apple-minimal-motion-candidate.zip

3类画面、5类图文，B03/B04保留0.24秒接力。实际解码原录屏，独立RGBA图层，口播不变速。A无干净原人物源，使用干净B人物作应用。字体和缓动近似，参考BGM/FX未复刻或听审，仅9:16实际编码。

技能00/01/扩展02通过实际命令，03仍active。两组v4用户认可绑定真实SHA，不能扩成所有内容的认可；完整组合为候选，不伪造04–09通过。

## 验证

TypeScript、production build、8项前端行为测试通过。新合同15项、glue6项及原任务/规划/目录测试通过；另64项来源、原生采用、素材、样例与交付恢复回归通过。改动Python的ruff/mypy通过。日志 C:/tl/bihuo-editing-20261112/apple-integration-final-build.log。

真实7.6秒队列v2记录 C:/tl/bihuo-editing-20261112/queue-verification-v2/queue-verification.json，完成prepare→一次本地fixture→实际1080/25fps编码→预览→确认高清→Range下载。pull对应完整“点击拉取参考商品…”句。外部模型调用0；这是链路验证，不证明真实模型匹配或ASR质量。“图片片”ASR错字保留披露；v1取错首句已标废弃。复跑 tools/verify_apple_queue.py。

45组件样本静态修复后RGBA一致；长短文、字体替换、透明边缘有真实检查。独立目录候选包运行记录 C:/tl/bihuo-editing-20261112/portable-candidate-v1/portable-review.json，不替代技能正式08验收。

## 本机服务与限制

前端 http://localhost:3019/video-studio/editing ，API8019使用独立克隆DB，无密钥，付费关闭。示例在本任务独立C:/tl/bihuo-editing-20261112/examples，原目录未改。

启动API：python tools/serve_editing_replay.py --run C:/tl/bihuo-editing-20261112/runtime --examples C:/tl/bihuo-editing-20261112/examples --port 8019

前端环境：VITE_LOCAL_DEV_AUTH=true、NEXT_PUBLIC_LOCAL_DEV_AUTH=true、VITE_API_PROXY_TARGET=http://127.0.0.1:8019。正式模型仍需沿用正式环境配置，未在隔离环境开启付费或复制密钥。

不声称对标全功能100%一致：AI配图生成、用户音乐上传/生成、用户封面上传尚未新接入。本轮完成主剪辑流程与可调用的成套候选模板。

## 字幕修复 · 同日追加

用户指出后半段字幕随机断词且不再标蓝。根因分别是示例工程前12.8秒之后的固定14字/2.8秒分块、有限关键词表，以及网站合同的16字/3秒分块。已取消新规划中的显示端截句，版本升级为1.0.0-candidate.2，规划合同为tengli.apple-suite-plan/2。

同一次全文规划必须给出全片字幕分句、可选自然换行和逐句1–2个重点词的真实词ID。服务端检查按顺序覆盖所有实录词一次、词法边界、数字单位/英文名称、每行容量、关键词归属及片尾覆盖。长分句最多两行同时显示；真实词时钟不改，跨画面时只改变正文字色，保留整句与蓝色词点。历史v1保留读取兼容，新生成必须v2，不增加规划调用或自动重试费用。

两条示例已重导出并完整解码，前述旧产物保留备查，当前入口自动转向reviews/complete-caption-fixed/index.html。当前52.24秒为render/complete/business-captions-v4/final.mp4（SHA256 bce06bb0ced406d7727e80b3a42c78c91ffc9f8f6d72d0adc9f8957526fd1999），26.24秒为render/complete/points-captions-v3/final.mp4。此次示例的20组字幕由人工按新生产合同编写，178个实录词全覆盖；纠正6处文本/标点并记录原词点与差异，未冒称为新模型输出。主画面机制、素材和口播时钟保持原配方。

逐句中点RGBA标蓝检查、实际编码帧和完整解码记录在reviews/caption-repair-v1/verification.json，实际编码联系图为encoded-contact.jpg。更新的独立作者包是delivery/apple-minimal-motion-caption-fixed.zip，SHA256 fb1bdddfcf27428d979e0e93fe3e9f699e811cfcfc413aaec1d73f09ca90c726。未把本次候选扩大为正式技能验收或用户认可。

37项字幕/合同/队列glue测试通过，4个改动运行模块ruff/mypy通过。真实7.6秒新合同队列记录C:/tl/bihuo-editing-20261112/queue-caption-verification-v3/queue-verification.json：一次本地协议fixture、25/25词覆盖、实际编码到高清确认及Range下载通过，外部模型调用0。正式付费模型的语义质量仍未在隔离环境验收。

网站独立examples目录已安装新的52秒例片，manifest的扩展审计字段放在caption_repair，不传给严格TemplateExample元数据模型。内置浏览器已验证原预览页转向、B05后半段视频完整播放和网站新示例52.24秒可播放。8019本任务API已重启载入新版；3018/8018保持原有服务，未部署线上。
