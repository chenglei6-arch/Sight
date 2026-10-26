# Sight 前端

React 19 + TypeScript（strict）+ Zustand + Vite + ECharts。运行环境：Node.js 22.12+。

```bash
npm ci
npm run dev        # http://127.0.0.1:5173，/api 代理到 Flask 5001
npm run typecheck  # 检查应用及测试代码类型
npm test           # Vitest + React Testing Library
npx playwright install chromium  # 首次运行浏览器测试时安装
npm run test:e2e   # 固定接口数据，不访问真实平台或改动现有凭证
npm run build     # 先检查类型，再输出到 ../app/web，由 Flask 托管
```

`npm run preview` 可检查静态构建；API 联调使用 Flask 页面或开发服务器。

## 代码组织

- `src/store.ts`：Zustand 应用状态、目标用户、平台数据加载、hash 导航及应用轮询。组件通过 selector 订阅，更新统一走导出的 action。`initStore()` 返回完整的清理函数。
- `src/api.ts` / `src/types.ts`：带泛型和 AbortSignal 的请求封装，以及按后端实际字段定义的类型。接口失败保持原始错误信息，聚合接口的部分失败单独展示。
- `src/platforms.ts`：七个平台的渲染配置，与适配器返回字段对应。
- `src/components/graph/`：图谱控制器及不可变展示快照、关系算法、ECharts 渲染、队列和保存恢复模块；工具栏、画布、节点卡片、状态条各自为 React 组件。
- `src/hooks/useLogs.ts`：日志缓冲、SSE 重连及轮询降级。弹窗的扫码轮询由扫码组件拥有。
- `src/style.css` 保留公共设计样式，组件样式使用 CSS Modules；ECharts tooltip 的 `g-tip-*` 类显式声明为全局。

图谱模块按需加载。开发模式仍可通过 `window.__vgChart` 检查图表，离开页面时自动清除。

## 兼容与异步约定

保留 `#/平台`、`#/timeline`、`#/graph` 路径；UID、终端偏好、展开上限及图谱游标沿用既有 localStorage 键，也支持读取旧 `monitor_uids`。

切换目标、时间线来源和图谱时取消请求或校验版本；卸载时释放轮询、监听器、SSE、ResizeObserver 和图表。StrictMode 保持启用，避免依赖只挂载一次的副作用。

已保存图谱继续使用原有 REST 载荷，保留未知元数据、关键词覆盖、展开/互查/隐藏标记及进度。保存请求串行执行，同名图谱待保存的多次变化合并为最新快照；切换页面不会把旧响应的 ID 写入新图谱。

测试位于 `tests/unit` 和 `tests/e2e`，覆盖请求竞态、资源清理、旧数据兼容、图谱队列分页与去重，以及七个平台、时间线、账号、扫码、日志和图谱的浏览器交互。测试输出目录已加入 Git 忽略规则。
