import { test, expect, type Page } from "@playwright/test";
import { ids, installMockApi, graphNode } from "./fixtures";
import type { GraphNode } from "../../src/types";
test.beforeEach(async ({ page }) => {
  await installMockApi(page);
});
test("server errors, retry and partial-module warnings stay visible", async ({
  page,
}) => {
  let fail = true;
  await page.route("**/api/weibo/all?*", (route) =>
    fail
      ? route.fulfill({ json: { code: -1, message: "[微博] Cookie 已失效" } })
      : route.fallback(),
  );
  await page.goto("/#/weibo");
  await expect(
    page.getByText("[微博] Cookie 已失效", { exact: true }),
  ).toBeVisible();
  await page.waitForLoadState("networkidle");
  fail = false;
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByText("测试用户-weibo", { exact: true })).toBeVisible();
  await page.route("**/api/bilibili/all?*", (route) =>
    route.fulfill({
      json: { code: 200, data: { _errors: ["[哔哩哔哩] 关注接口限流"] } },
    }),
  );
  await page.getByRole("button", { name: /^哔哩哔哩/ }).click();
  await page.getByRole("button", {name:"刷新",exact:true}).click();
  await expect(
    page.getByText("[哔哩哔哩] 关注接口限流", { exact: true }),
  ).toBeVisible();
});
for (const id of ids)
  test(`platform ${id} keeps profile and query interactions`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`/#/${id}`);
    await expect(
      page.getByText(`测试用户-${id}`, { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("这是用于界面回归的公开资料示例", { exact: true }),
    ).toBeVisible();
    const input = page.locator("main input").first();
    const uid =
      id === "genshin"
        ? "987654321"
        : id === "xhs"
          ? "5d8c00000000000010000456"
          : "456";
    await input.fill(uid);
    await input.press("Enter");
    await expect(
      page.locator("main").getByText(`UID ${uid}`, { exact: true }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  });
test("search, content detail and platform state reset", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByText("测试用户-netease", { exact: true }),
  ).toBeVisible();
  const input = page.locator("main input").first();
  await input.fill("昵称");
  await input.press("Enter");
  await page.getByRole("button", { name: /搜索结果甲/ }).click();
  await expect(page.getByText("UID 201", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /测试内容/ }).click();
  await expect(page.getByRole("dialog")).toHaveText(/测试歌单详情/);
  await expect(page.getByText("详情歌曲", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: /^哔哩哔哩/ }).click();
  await expect(
    page.getByText("测试用户-bilibili", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("main input").first()).toHaveValue("");
});
test("timeline editing and deletion preserve the REST contract", async ({
  page,
}) => {
  await page.goto("/#/timeline");
  await page.getByRole("button", { name: "历史记录", exact: true }).click();
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator("textarea").first().fill("修正后的记录");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText("修正后的记录", { exact: true })).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "删除", exact: true }).click();
  await expect(page.getByText("暂无活动记录", { exact: true })).toBeVisible();
});
test("account add/test/disable/delete and QR login", async ({ page }) => {
  await page.goto("/#/qqmusic");
  await expect(
    page.getByText("测试用户-qqmusic", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "账号", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByPlaceholder("备注名（可选，如：小号1）").fill("测试小号");
  await dialog
    .getByPlaceholder("粘贴另一个账号的 Cookie，添加后与主账号并行查询")
    .fill("session=mock");
  await dialog.getByRole("button", { name: "添加账号", exact: true }).click();
  await expect(dialog.getByText("测试小号", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "测试", exact: true }).click();
  await expect(dialog.getByText(/可用（登录：测试账号）/)).toBeVisible();
  await dialog.getByRole("button", { name: "停用", exact: true }).click();
  await expect(dialog.getByText("已停用", { exact: true })).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await dialog
    .locator("button")
    .filter({ has: page.locator("svg") })
    .last()
    .click();
  await expect(dialog.getByText("测试小号", { exact: true })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "扫码查关注", exact: true }).click();
  await expect(
    page.getByText("请用手机 QQ 扫一扫登录", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("扫码关注示例", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
});
test("terminal logs fall back to polling and queue tab stays usable", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "终端", exact: true }).click();
  await expect(
    page.getByText("[netease] 资料加载完成", { exact: true }),
  ).toBeVisible();
  await page.getByPlaceholder("过滤：平台 / 状态 / 关键字…").fill("missing");
  await expect(page.getByText("没有匹配的日志", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "任务队列", exact: true }).click();
  await expect(page.getByText("空闲", { exact: true })).toBeVisible();
  await page.getByTitle("收起面板").click();
});
async function clickNode(page: Page, node: GraphNode) {
  await page.evaluate((node) => {
    const chart = (
      window as unknown as {
        __vgChart: { trigger: (event: string, data: unknown) => void };
      }
    ).__vgChart;
    chart.trigger("click", { dataType: "node", data: { raw: node } });
  }, node);
}
test("graph restore, manual identity, hide/restore, layouts, expansion and export", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#/graph");
  await expect(page.getByText("3", { exact: true })).toBeVisible();
  await expect(page.locator("canvas")).toBeVisible();
  await page
    .getByTitle("设置 网易云音乐 专属搜索词（该平台搜别的词）", { exact: true })
    .click();
  await expect(page.locator('input[data-pid="netease"]')).toBeFocused();
  await page.locator('input[data-pid="netease"]').fill("取消编辑");
  await page.keyboard.press("Escape");
  await expect(
    page.getByTitle("网易云音乐 专属搜索词：专属昵称", { exact: true }),
  ).toBeVisible();
  const first = graphNode("netease", "1", "示例"),
    second = graphNode("bilibili", "2", "示例");
  await clickNode(page, first);
  await expect(page.getByText("UID：1", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "标记同人", exact: true }).click();
  await clickNode(page, second);
  await expect(
    page.getByText("已手动标记同人：示例 ↔ 示例", { exact: true }),
  ).toBeVisible();
  await clickNode(page, first);
  await page.getByRole("button", { name: "不看", exact: true }).click();
  await page
    .getByRole("button", { name: "已排除 1 个节点，点击还原", exact: true })
    .click();
  await page.getByRole("button", { name: "分层", exact: true }).click();
  await page.getByRole("button", { name: "力导向", exact: true }).click();
  await page.getByRole("button", { name: "停放", exact: true }).click();
  await expect(page.getByText(/布局已停放：/)).toBeVisible();
  await page.getByRole("button", { name: "恢复", exact: true }).click();
  await page.getByRole("button", { name: "一键展开", exact: true }).click();
  await expect(
    page.getByText("全图展开完成：新增 1 人 · 1 条关注边 · 互查命中 0 条", {
      exact: true,
    }),
  ).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出图片", exact: true }).click();
  expect((await download).suggestedFilename()).toContain("sight-关系图");
  const keyword = page.getByPlaceholder("输入关键词，跨平台搜索用户生成关系图");
  await keyword.fill("新关键词");
  await page.getByPlaceholder("图谱名称，留空则用关键词").fill("新图谱");
  await page.getByRole("button", { name: "生成关系图", exact: true }).click();
  await expect(
    page.getByText("已保存为「新关键词」，可在侧边栏随时调出", { exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
