import { test, expect } from "@playwright/test";
import { installMockApi } from "./fixtures";

test("archive queries are on demand, paginate and reset for a new UID", async ({ page }) => {
  await installMockApi(page);
  let requests = 0;
  await page.route("**/api/bilibili/archives?*", async (route) => {
    requests++;
    const url = new URL(route.request().url());
    const source = url.searchParams.get("source");
    if (source === "danmakus") {
      await route.fulfill({ status: 502, json: { code: -1, message: "[Danmakus] 上游限流" } });
      return;
    }
    const number = Number(url.searchParams.get("page"));
    await route.fulfill({ json: { code: 200, data: {
      source_name: "Aicu · 评论", source_url: "https://www.aicu.cc/reply?uid=100",
      page: number, total: 21, total_unit: "条", has_more: number === 1,
      truncated: false, cached: false, fetched_at: 1793000000000,
      notice: "第三方存档可能延迟、缺失或已失效；查询不到不代表没有相关活动。",
      events: [{ event_id: `aicu:${number}`, event_type: "评论", content: `第 ${number} 页示例评论`, timestamp: 1790000000000, url: "https://www.bilibili.com/video/av123#reply12" }],
    } } });
  });
  await page.goto("/#/bilibili");
  const section = page.getByRole("region", { name: "评论与弹幕存档" });
  await expect(section).toBeVisible();
  expect(requests).toBe(0);
  await section.getByRole("button", { name: "查询存档" }).click();
  await expect(section.getByText("第 1 页示例评论")).toBeVisible();
  await section.getByRole("button", { name: "下一页" }).click();
  await expect(section.getByText("第 2 页示例评论")).toBeVisible();
  await expect(section.getByRole("button", { name: "下一页" })).toBeDisabled();
  await section.screenshot({ path: "test-results/archives-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await section.scrollIntoViewIfNeeded();
  await section.screenshot({ path: "test-results/archives-mobile.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await section.getByRole("combobox").selectOption("danmakus");
  await section.getByRole("button", { name: "查询存档" }).click();
  await expect(section.getByRole("alert")).toHaveText("[Danmakus] 上游限流");
  await page.setViewportSize({ width: 1440, height: 1000 });
  const input = page.locator("main input").first();
  await input.fill("456");
  await input.press("Enter");
  await expect(page.locator("main").getByText("UID 456", { exact: true })).toBeVisible();
  await expect(section.getByRole("alert")).toHaveCount(0);
  await expect(section.getByRole("combobox")).toHaveValue("aicu_reply");
  expect(requests).toBe(3);
});
