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

## 新人物、新稿真实首版 · 同日追加

用户认可字幕修复后，要求换人物和稿件，真实剪一版验证接入。新建独立目录C:/tl/bihuo-editing-20261112/live-case-v1，通过SQLite备份复制本任务只读基线，不复用历史七次调用额度。8019改为此独立项目的真实手动服务；3018/8018未改。

新项目a5e7f950-4230-4cbc-a066-dd800779e7ac。115字新稿主题“新品上架前，商品图先检查这三件事”，使用公共数字人qy-model-255（尔东）、精英青年男声、1.1倍语速。通过网页确认生成，配音21.043438秒；因公共动作只有10.88秒，既有正向延长流程登记一次后生成口播。生成任务3d480748-d812-462d-9387-4d51fe5aa59c，真实新源SHA256为57b21573a5875dc620c42d74dd33712139f046ae5ae5fc4b06ce09755683f3b4。

网页上传两份命名素材“商品主图展示”“商品详情页展示”，采用既有官网公开案例。新口播及稿件自动带入剪辑页面，选择Apple模板后点击一次开始。实际流程：离线FunASR识别101词→免费准备→一次真实gpt-6.1-sol规划→自动创建渲染任务→实际1080×1920/25fps编码→预览→网页确认高清→网页下载。源记录kind=generation_task，未伪造上传来源；本次计划和字幕没有人工改写。

规划任务c6f58afc-1c6d-411a-a85f-2490c957d8fc，供应商响应resp_0f6fd527d8d7afac016af5c0945d1887d1b7a280176f2ec3c0，实际用量9537输入/2211输出/11748总token。四种收费阶段各实际提交一次：配音、动作登记、数字人口播、全文规划；没有额外规划、付费重试或逐帧API。金额未核实，不推算。

实测修复了本地手动服务两处接入问题：transport原来只允许旧overlay请求，现允许具有正确引擎与v2合同的新模板；规划worker自动持久化预览后，本地没有生产维护进程来消费出站队列，现包装规划worker自动投递其保存的queued预览，并提供显式--resume-preview恢复一个已保存预览。恢复本次af211118-2a44-402c-8d4e-2d96dccbc669没有再次调用模型或重建口播。7项手动服务回归和Ruff通过。生产Celery维护原有实现未改，不冒称完整生产基础设施验收。

真实首版为21.04秒、11组全片字幕，完整解码通过。网页实际下载到C:/Users/a1726/Downloads/af211118-2a44-402c-8d4e-2d96dccbc669-final.mp4，与服务端高清记录逐字节SHA一致，Range 206也通过。便于查看的副本为C:/tl/bihuo-editing-20261112/live-case-v1/新人物_新口播稿_自动剪辑首版.mp4。证据delivery-verification.json；review/contact.jpg来自实际编码帧，review/website-result.png为真实网页可下载状态。

这是链路通过而质量仍有问题的首版，不能记录为用户效果认可：主图在连续的“主图产品是否清楚”“核心卖点能不能一眼看懂”两句都有匹配，检索标为ambiguous，模型因此跳过，只用了详情素材（7.59秒起）；FunASR把“逐张核对”写成“主张核对”，并漏掉“是不是统一。检查完成”中间停顿，模型分句沿用了不佳边界。后续应先改善相邻分句的素材检索与口播参考稿校对，再谈稳定质量。此次保留自动首版和原始响应，不用人工改片掩盖实测结果；正式听审和用户审核仍待进行。

本机运行：python tools/tengli_manual_flow_runtime.py --root C:/tl/bihuo-editing-20261112/live-case-v1 --provider-env D:/Desktop/cyh/tengli/polaris-commerce-studio/backend/.env --examples C:/tl/bihuo-editing-20261112/examples --enable-user-submissions --port 8019。启动不提交付费任务；--resume-preview只恢复已保存的本地预览。预备新案例工具tools/prepare_apple_live_case.py不调用生成，仅下载公共人物原片和可选新建项目。

## 自动修复与关键词密度 · 同日追加

用户明确要求修复素材漏用、同音错字和分句，并用同一人物原片在自动链路复跑。候选版.3新增video_editing_reference_text.py：对参考稿和原ASR作逐单位比较，只接受长度一致、少量同读音替换；数字、名称、非同音或增删词不覆盖。按参考稿恢复标点，重建连续分句；词点保留真实ASR区间，原始asr-transcript.json和reference-reconciliation.json另存，生成新词ID并绑定父转录SHA。使用固定pypinyin 0.55.0，依赖加入editing/editing-zh/dev；确认稿仍不冒充用户已经人工校对。缓存签名纳入处理与词典版本，恢复时核验原ASR和自动纠错回执。

素材检索升级material-alignment/2，名称主题词加权，合并不跨句号、长停顿的相邻相关分句。主图的“先看主图，产品是否清楚，核心卖点能不能一眼看懂。”成为单个明确候选；详情同理。参考稿核对成功时，字幕结束位置约束到原稿分句，句号必须是字幕边界，避免把“是不是统一”与“检查完成”合在一起。

网页重新点击开始，真实ASR任务a98232c0-d44d-44c1-add3-9a40b3d0fd6c自动恢复共11处文字与标点差异（含1处主→逐）；时间轴不变。真实规划7750a072-2b38-4aea-8456-4db70efce596安排主图3.15秒、详情7.59秒，漏用列表为空，14条字幕全文覆盖，渲染4cabc09c-59d2-4865-b96e-e44478dcbeb4自动进入预览。用户随后指出大部分主字幕变蓝，此版强调质量不通过，保留作问题证据，不能据此扩大效果认可。

候选版.4移除“每个≥4字分句都必须标蓝”的规则，允许过渡句纯正文；新增video_editing_caption_emphasis.py。同一次规划给出关键词范围后，编译阶段自动限制每条/每行强调容量（约三分之一可读字符，短句允许两字，最多两个词），过大的强调范围只从模型原范围内收窄为实词，不能把未选内容凭空上色。每行记录emphasis_adjustments及强调/正文字数。原稿、分句、时点和配图不变，原供应商JSON不改，不在渲染阶段调模型。

复用同一自动核对转录，通过正式HTTP准备和generate(auto_preview=true)重新提交，未新增配音或人物生成。准备1ea52506-470e-4498-821e-4512d5f74bfa，真实规划143106ae-6e4c-4499-987e-4a46ad79a154，渲染9838cdc4-f8cf-423b-a00d-4b958cdc8876。当前21.04秒成片保留两份素材、正确“逐张核对”和完整分句；101个可读字中32个强调、69个普通正文（31.68%），片尾仍有重点词。原始响应、计划与实际输入快照可追溯，没有人工修改成片或字幕范围。实际编码联系图和校验在live-case-v1/sparse-fix-v3；SRT直接由同一编排字幕的实录时点和显示分句导出。

本轮三次完整测试集分别73项（强调、参考稿、素材、合同及glue）、71项（ASR、对齐、来源、校对与任务）、70项（规划、来源校验、模板目录）通过，共214项；改动运行模块Ruff和7文件mypy通过。最终本地真实服务PID33880、端口8019；前端3019。没有部署、推送或改变原3018/8018服务。

用户还询问SRT与直接用口播稿。已明确推荐“确认稿提供文字＋实际音频强制对齐提供词级时点→语义分句→SRT/渲染”。SRT是带起止时间的输出格式。现有video_editing_alignment.py已有本地FA能力，但本轮新默认实现是保守参考稿纠错和实录ASR词点复用，未冒称已切成独立强制对齐默认流程。FunASR官方支持音频+文本的对齐输入，见https://modelscope.github.io/FunASR/api.html 。
