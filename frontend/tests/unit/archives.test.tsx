import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BilibiliArchives from "../../src/components/BilibiliArchives";

const page = (number = 1) => ({
  source_name: "Aicu · 评论", source_url: "https://www.aicu.cc/reply?uid=123",
  page: number, total: 21, total_unit: "条", has_more: number === 1,
  truncated: false, events: [{ event_id: "aicu:1", content: `第 ${number} 页评论`, url: "https://www.bilibili.com/video/av1" }],
  cached: false, fetched_at: 1700000000000, notice: "第三方存档可能缺失",
});
const ok = (data: unknown) => new Response(JSON.stringify({ code: 200, data }));

describe("Bilibili archives", () => {
  it("only queries on demand, paginates and links to the record", async () => {
    const fetch = vi.fn((url: string) => Promise.resolve(ok(page(Number(new URL(url, "http://localhost").searchParams.get("page"))))));
    vi.stubGlobal("fetch", fetch);
    render(<BilibiliArchives uid="123" />);
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "查询存档" }));
    await screen.findByText("第 1 页评论");
    expect(fetch.mock.calls[0][0]).toContain("uid=123");
    expect(screen.getByRole("link", { name: "查看原始记录 ↗" })).toHaveAttribute("href", "https://www.bilibili.com/video/av1");
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("第 2 页评论");
    expect(fetch.mock.calls[1][0]).toContain("page=2");
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });

  it("ignores a stale response after changing source", async () => {
    let finish!: (response: Response) => void;
    const fetch = vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; }));
    vi.stubGlobal("fetch", fetch);
    render(<BilibiliArchives uid="123" />);
    fireEvent.click(screen.getByRole("button", { name: "查询存档" }));
    fireEvent.change(screen.getByRole("combobox", { name: "数据来源" }), { target: { value: "danmakus" } });
    await act(async () => { finish(ok(page())); });
    expect(screen.queryByText("第 1 页评论")).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "查询存档" })).toBeEnabled();
  });

  it("shows upstream errors as errors and can query again", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ code: -1, message: "Aicu 上游限流" }), { status: 502 })).mockResolvedValueOnce(ok(page()));
    vi.stubGlobal("fetch", fetch);
    render(<BilibiliArchives uid="123" />);
    fireEvent.click(screen.getByRole("button", { name: "查询存档" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("上游限流");
    expect(screen.queryByText(/该页暂无/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查询存档" }));
    await screen.findByText("第 1 页评论");
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});
