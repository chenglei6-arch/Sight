import { Fragment, useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { api, errorMessage } from "../api";
import { classNames } from "../classes";
import { useLogs } from "../hooks/useLogs";
import { platformColor, platformName } from "../platforms";
import {
  queueSummary,
  refreshQueues,
  setTerminalTab,
  toggleTerminal,
  useAppStore,
} from "../store";
import type { ExpandTask, LogEntry, QueueStatus } from "../types";
import styles from "./TerminalPanel.module.css";
import Icon from "./ui/Icon";
const cx = classNames(styles);

export default function TerminalPanel() {
  const state = useAppStore(
      useShallow((s) => ({
        terminalOpen: s.terminalOpen,
        terminalTab: s.terminalTab,
        queues: s.queues,
      })),
    ),
    tab = state.terminalTab;
  const { entries, paused, setPaused, clearLogs } = useLogs();
  const [filter, setFilter] = useState(""),
    [copied, setCopied] = useState(false),
    [copyError, setCopyError] = useState(""),
    [unread, setUnread] = useState(0),
    [resuming, setResuming] = useState(""),
    [resumeError, setResumeError] = useState("");
  const logBox = useRef<HTMLDivElement>(null),
    pinned = useRef(true),
    previous = useRef<LogEntry[]>([]),
    copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined),
    alive = useRef(true);
  const filteredEntries = entries.filter(
    (e) =>
      !filter.trim() ||
      e.text.toLowerCase().includes(filter.trim().toLowerCase()) ||
      (e.source || "").toLowerCase().includes(filter.trim().toLowerCase()),
  );
  function scrollToBottom() {
    const el = logBox.current;
    if (el) el.scrollTop = el.scrollHeight;
    pinned.current = true;
    setUnread(0);
  }
  function onScroll() {
    const el = logBox.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    if (pinned.current) setUnread(0);
  }
  useEffect(() => {
    const last = previous.current.at(-1);
    if (pinned.current) scrollToBottom();
    else if (last)
      setUnread(
        (n) =>
          n +
          entries.filter((e) => e.boot === last.boot && e.seq > last.seq)
            .length,
      );
    previous.current = entries;
  }, [entries]);
  useEffect(() => {
    if (state.terminalOpen && pinned.current) scrollToBottom();
  }, [state.terminalOpen, tab]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      clearTimeout(copyTimer.current);
    };
  }, []);
  async function copyLogs() {
    try {
      await navigator.clipboard.writeText(
        filteredEntries.map((e) => `[${e.ts}] ${e.text}`).join("\n"),
      );
      if (!alive.current) return;
      setCopied(true);
      setCopyError("");
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(false), 1200);
    } catch (e) {
      if (!alive.current) return;
      setCopyError("复制失败：" + errorMessage(e));
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopyError(""), 2500);
    }
  }
  const summary = queueSummary(state.queues);
  async function resumeQueue(platform: string) {
    setResuming(platform || "all");
    try {
      await api.post("/graph/expand/resume", platform ? { platform } : {});
      await refreshQueues();
      if (alive.current) setResumeError("");
    } catch (e) {
      if (alive.current) setResumeError("恢复失败：" + errorMessage(e));
    } finally {
      if (alive.current) setResuming("");
    }
  }
  function queueState(q: QueueStatus) {
    if (q.paused)
      return { label: "已熔断", cls: "st-paused", title: q.pause_reason };
    if (q.running > 0)
      return { label: `运行中 ×${q.running}`, cls: "st-running", title: "" };
    if (q.pending > 0)
      return { label: `排队 ${q.pending}`, cls: "st-pending", title: "" };
    return { label: "空闲", cls: "st-idle", title: "" };
  }
  function accText(t: ExpandTask) {
    const parts = [];
    if (t.account_map) {
      if (t.account_map.follows?.length)
        parts.push(`关注←${t.account_map.follows.join("、")}`);
      if (t.account_map.followers?.length)
        parts.push(`粉丝←${t.account_map.followers.join("、")}`);
      if (t.account_map.intercheck?.length)
        parts.push(`互查←${t.account_map.intercheck.join("、")}`);
      if (parts.length) return parts.join(" · ");
    }
    return t.accounts?.length ? t.accounts.join("、") : "分配账号中…";
  }
  function showQueueLogs() {
    setTerminalTab("logs");
    setFilter("");
  }

  return (
    <>
      <aside className={cx("terminal-panel", { open: state.terminalOpen })}>
        <div className={cx("terminal-inner")}>
          <div className={cx("terminal-head")}>
            <div className={cx("terminal-tabs")}>
              <button
                className={cx("t-tab", { active: tab === "logs" })}
                onClick={() => {
                  setTerminalTab("logs");
                }}
              >
                {" 运行日志 "}
              </button>
              <button
                className={cx("t-tab", {
                  active: tab === "queue",
                  warn: summary.paused > 0,
                })}
                onClick={() => {
                  setTerminalTab("queue");
                }}
              >
                {" 任务队列 "}
                {summary.busy > 0 ? (
                  <span className={cx("tab-badge")}>{summary.busy}</span>
                ) : summary.paused > 0 ? (
                  <span className={cx("tab-badge err")}>{"!"}</span>
                ) : null}
              </button>
            </div>
            <button
              title="收起面板"
              className={cx("t-close")}
              onClick={() => {
                toggleTerminal(false);
              }}
            >
              <Icon name="x" size={14}></Icon>
            </button>
          </div>
          {tab === "logs" ? (
            <Fragment>
              <div className={cx("terminal-toolbar")}>
                <input
                  value={filter}
                  type="text"
                  placeholder="过滤：平台 / 状态 / 关键字…"
                  className={cx("t-filter")}
                  onChange={(event) => {
                    setFilter(event.currentTarget.value);
                  }}
                ></input>
                <button
                  title={paused ? "已暂停接收，点击恢复" : "接收中，点击暂停"}
                  className={cx("t-btn", { on: !paused })}
                  onClick={() => {
                    setPaused(!paused);
                  }}
                >
                  <Icon name={paused ? "play" : "pause"} size={13}></Icon>
                </button>
                <button
                  title="清屏（仅本地显示）"
                  className={cx("t-btn")}
                  onClick={() => {
                    clearLogs();
                  }}
                >
                  <Icon name="trash" size={13}></Icon>
                </button>
                <button
                  title={
                    copyError || (copied ? "已复制" : "复制当前显示的日志")
                  }
                  className={cx("t-btn")}
                  onClick={() => {
                    copyLogs();
                  }}
                >
                  <Icon name={copied ? "check" : "edit"} size={13}></Icon>
                </button>
              </div>
              <div
                ref={logBox}
                className={cx("log-box")}
                onScroll={() => {
                  onScroll();
                }}
              >
                {copyError ? (
                  <div className={cx("log-line lv-error")}>
                    <span className={cx("log-text")}>{copyError}</span>
                  </div>
                ) : null}
                {!filteredEntries.length ? (
                  <div className={cx("log-empty")}>
                    {filter
                      ? "没有匹配的日志"
                      : "暂无日志，触发一次数据刷新试试"}
                  </div>
                ) : null}
                {filteredEntries.map((e) => (
                  <div key={e.seq} className={cx("log-line", `lv-${e.level}`)}>
                    <span className={cx("log-ts")}>{e.ts}</span>
                    {e.source &&
                    e.source !== "console" &&
                    e.source !== "stderr" ? (
                      <span
                        style={{
                          color: platformColor(e.source.replace("fetch:", "")),
                        }}
                        className={cx("log-src")}
                      >
                        {e.source}
                      </span>
                    ) : null}
                    <span className={cx("log-text")}>{e.text}</span>
                  </div>
                ))}
              </div>
              {unread > 0 ? (
                <button
                  className={cx("new-badge")}
                  onClick={() => {
                    scrollToBottom();
                  }}
                >
                  {" ↓ "}
                  {unread}
                  {" 条新日志 "}
                </button>
              ) : null}
            </Fragment>
          ) : (
            <Fragment>
              <div className={cx("queue-summary")}>
                <span>
                  {"排队 "}
                  <b className={cx({ hot: summary.pending > 0 })}>
                    {summary.pending}
                  </b>
                </span>
                <span>
                  {"执行中 "}
                  <b className={cx({ hot: summary.running > 0 })}>
                    {summary.running}
                  </b>
                </span>
                <span>
                  {"熔断 "}
                  <b className={cx({ err: summary.paused > 0 })}>
                    {summary.paused}
                  </b>
                </span>
                {summary.paused > 0 ? (
                  <button
                    disabled={resuming === "all"}
                    className={cx("t-btn resume-all")}
                    onClick={() => {
                      resumeQueue("");
                    }}
                  >
                    <Icon name="refresh" size={13}></Icon>
                    {" 全部恢复 "}
                  </button>
                ) : null}
              </div>
              {resumeError ? (
                <div className={cx("log-line lv-error")}>
                  <span className={cx("log-text")}>{resumeError}</span>
                </div>
              ) : null}
              <div className={cx("queue-list")}>
                {state.queues.map((q) => (
                  <Fragment key={q.platform}>
                    <div className={cx("queue-row")}>
                      <span
                        style={{ background: platformColor(q.platform) }}
                        className={cx("q-dot")}
                      ></span>
                      <span className={cx("q-name")}>
                        {platformName(q.platform)}
                      </span>
                      <span
                        title={queueState(q).title}
                        className={cx("q-state", queueState(q).cls)}
                      >
                        {queueState(q).label}
                      </span>
                      <span
                        title={`账号池 ${q.accounts} 个 · 任务间隔 ${q.interval}s`}
                        className={cx("q-meta")}
                      >
                        {q.accounts}
                        {" 账号 "}
                      </span>
                      {q.paused ? (
                        <button
                          disabled={resuming === q.platform}
                          title="解除熔断，恢复该平台队列"
                          className={cx("t-btn")}
                          onClick={() => {
                            resumeQueue(q.platform);
                          }}
                        >
                          <Icon name="refresh" size={13}></Icon>
                        </button>
                      ) : null}
                    </div>
                    {q.running_tasks?.length || q.pending_tasks?.length ? (
                      <div className={cx("q-tasks")}>
                        {(q.running_tasks || []).map((t) => (
                          <div
                            key={`r${t.id}`}
                            className={cx("q-task q-task-run")}
                          >
                            <span className={cx("spinner spinner-sm")}></span>
                            <span
                              title={`${t.nickname || t.uid}（${q.platform}:${t.uid}）`}
                              className={cx("q-task-name")}
                            >
                              {t.nickname || t.uid}
                            </span>
                            <span
                              title={accText(t)}
                              className={cx("q-task-acc")}
                            >
                              {accText(t)}
                            </span>
                          </div>
                        ))}
                        {(q.pending_tasks || []).map((t) => (
                          <div key={`p${t.id}`} className={cx("q-task")}>
                            <Icon name="clock" size={11}></Icon>
                            <span
                              title={`${t.nickname || t.uid}（${q.platform}:${t.uid}）`}
                              className={cx("q-task-name")}
                            >
                              {t.nickname || t.uid}
                            </span>
                          </div>
                        ))}
                        {q.pending > (q.pending_tasks?.length || 0) ? (
                          <div className={cx("q-task q-task-more")}>
                            {" …还有 "}
                            {q.pending - (q.pending_tasks?.length || 0)}
                            {" 个在排队 "}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </Fragment>
                ))}
                {!state.queues.length ? (
                  <div className={cx("log-empty")}>{"队列状态加载中…"}</div>
                ) : null}
              </div>
              <div className={cx("queue-hint")}>
                {
                  " 熔断 = 平台队列连续失败 5 次后自动暂停；配置 Cookie 后可点恢复。 "
                }
                <a
                  href="#"
                  onClick={(event) => {
                    event.preventDefault();
                    showQueueLogs();
                  }}
                >
                  {"查看相关日志 →"}
                </a>
              </div>
            </Fragment>
          )}
        </div>
      </aside>
    </>
  );
}
