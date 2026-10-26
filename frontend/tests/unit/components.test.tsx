import { StrictMode } from "react";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { LogBuffer, useLogs } from "../../src/hooks/useLogs";
import QrLoginModal from "../../src/components/QrLoginModal";
import DetailModal from "../../src/components/DetailModal";
import Modal from "../../src/components/ui/Modal";
import { openDetail, useAppStore } from "../../src/store";
const ok = (data: unknown) => new Response(JSON.stringify({ code: 200, data }));
class FakeEventSource {
  static CLOSED = 2;
  static instances: FakeEventSource[] = [];
  readyState = 0;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  close = vi.fn(() => {
    this.readyState = 2;
  });
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
}
describe("component lifetimes", () => {
  it("keeps one SSE connection through StrictMode and closes it on unmount", async () => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation(() =>
          Promise.resolve(ok({ entries: [], last_seq: 0 })),
        ),
    );
    const rendered = renderHook(() => useLogs(), {
      wrapper: ({ children }) => <StrictMode>{children}</StrictMode>,
    });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    rendered.unmount();
    expect(FakeEventSource.instances[0].close).toHaveBeenCalledTimes(1);
  });
  it("deduplicates logs, bounds memory and recognizes backend restarts", () => {
    const buffer = new LogBuffer();
    const entry = { boot: "a", seq: 1, ts: "12:00", text: "hello" };
    buffer.ingest([entry, entry]);
    expect(buffer.entries).toHaveLength(1);
    buffer.ingest(
      Array.from({ length: 2100 }, (_, i) => ({ ...entry, seq: i + 2 })),
    );
    expect(buffer.entries).toHaveLength(2000);
    buffer.ingest([{ ...entry, boot: "b", seq: 1 }]);
    expect(buffer.entries).toHaveLength(1);
    expect(buffer.boot).toBe("b");
  });
  it("falls back to log polling and does not poll after unmount", async () => {
    vi.useFakeTimers();
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    const fetch = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(ok({ entries: [], last_seq: 0 })),
      );
    vi.stubGlobal("fetch", fetch);
    const rendered = renderHook(() => useLogs());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const source = FakeEventSource.instances[0];
    expect(source).toBeDefined();
    await act(async () => {
      source.readyState = 2;
      source.onerror?.();
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(fetch.mock.calls.length).toBeGreaterThan(2);
    rendered.unmount();
    const count = fetch.mock.calls.length;
    await vi.advanceTimersByTimeAsync(4000);
    expect(fetch).toHaveBeenCalledTimes(count);
  });
  it("starts one QR session in StrictMode, cancels polling and stops the server session", async () => {
    const fetch = vi.fn((url: string) =>
      Promise.resolve(
        ok(
          url.includes("/status")
            ? { status: "qr_ready", qr_code: "test" }
            : {},
        ),
      ),
    );
    vi.stubGlobal("fetch", fetch);
    const close = vi.fn();
    const rendered = render(
      <StrictMode>
        <QrLoginModal open onClose={close} />
      </StrictMode>,
    );
    await screen.findByText("请用手机 QQ 扫一扫登录");
    expect(
      fetch.mock.calls.filter(([url]) => url.endsWith("/start")),
    ).toHaveLength(1);
    fireEvent.click(screen.getByTitle("关闭 (Esc)"));
    expect(close).toHaveBeenCalledTimes(1);
    rendered.unmount();
    await waitFor(() =>
      expect(fetch.mock.calls.some(([url]) => url.endsWith("/stop"))).toBe(
        true,
      ),
    );
  });
  it("does not show a delayed detail response after changing the selected item", async () => {
    let resolve!: (r: Response) => void;
    const old = new Promise<Response>((r) => (resolve = r));
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.includes("/old")
          ? old
          : Promise.resolve(ok({ title: "新内容", items: [] })),
      ),
    );
    useAppStore.setState({ detailModal: { platform: "netease", id: "old" } });
    const rendered = render(<DetailModal />);
    act(() => openDetail("netease", "new"));
    await screen.findByText("新内容");
    await act(async () => resolve(ok({ title: "旧内容", items: [] })));
    expect(screen.queryByText("旧内容")).not.toBeInTheDocument();
    rendered.unmount();
    useAppStore.setState({ detailModal: null });
  });
  it("only closes the top modal on Escape", () => {
    const a = vi.fn(),
      b = vi.fn();
    render(
      <>
        <Modal open title="outer" onClose={a} />
        <Modal open title="inner" onClose={b} />
      </>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(b).toHaveBeenCalledTimes(1);
    expect(a).not.toHaveBeenCalled();
  });
});
