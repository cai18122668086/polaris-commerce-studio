# Polaris Commerce Studio

面向电商内容生产的前端产品原型。当前仓库完成《项目规划-新窗口交接.md》
定义的 Phase 0：产品外壳、规划页面、响应式布局与本地模拟数据。

## 当前范围

- 首页与工具入口
- 个人控制台
- 局部修改工作台
- 商品详情包工作台
- 任务中心
- 素材库
- 帮助中心
- 全局任务抽屉与状态展示

当前版本不接后端，不调用付费 API，不包含登录、支付或部署配置。

## 本地开发

需要 Node.js `>=22.13.0`。

```bash
npm install
npm run dev
```

默认访问 `http://localhost:3000`。

## 工程检查

```bash
npm run lint
npm run typecheck
npm run build
```

## 技术栈

- React 19
- Next.js App Router API
- vinext / Vite
- TypeScript
- Lucide Icons

所有业务内容均来自 `lib/mock-data.ts` 和页面内的本地模拟状态。
