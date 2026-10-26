import { describe, it, expect, vi } from "vitest";
import { api } from "../../src/api";
describe("API contract", () => {
  it("keeps optional query fields out, encodes UIDs, forwards cancellation", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ code: 200, data: { ok: true } })),
      );
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    expect(
      await api.get(
        "/test",
        { uid: "用户:1", empty: "", none: undefined, zero: 0 },
        controller.signal,
      ),
    ).toEqual({ ok: true });
    const [url, init] = fetch.mock.calls[0];
    expect(new URL(url, "http://localhost").searchParams.get("uid")).toBe(
      "用户:1",
    );
    expect(url).not.toContain("empty");
    expect(url).toContain("zero=0");
    expect(init.signal).toBe(controller.signal);
  });
  it("preserves server errors and reports invalid JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ code: -1, message: "[抖音] 2096" }), {
            status: 400,
          }),
        )
        .mockResolvedValueOnce(new Response("bad gateway", { status: 502 })),
    );
    await expect(api.get("/test")).rejects.toThrow("[抖音] 2096");
    await expect(api.get("/test")).rejects.toThrow("服务响应异常 (502)");
  });
});
