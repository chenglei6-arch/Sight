import { useShallow } from "zustand/react/shallow";
import { classNames } from "../classes";
import { PLATFORM_MAP } from "../platforms";
import {
  isPlatformId,
  openAccountModal,
  queueSummary,
  refreshCurrentView,
  setAutoRefresh,
  toggleTerminal,
  useAppStore,
} from "../store";
import styles from "./TopBar.module.css";
import Icon from "./ui/Icon";
const cx = classNames(styles);

export default function TopBar() {
  const state = useAppStore(
    useShallow((s) => ({
      view: s.view,
      data: s.data,
      timeline: s.timeline,
      autoRefresh: s.autoRefresh,
      terminalOpen: s.terminalOpen,
      queues: s.queues,
    })),
  );
  const platform = PLATFORM_MAP[state.view];
  const title =
    platform?.name ||
    ({ timeline: "活动时间线", graph: "关系图谱" } as Record<string, string>)[
      state.view
    ] ||
    "Sight";
  const queueInfo = queueSummary(state.queues);
  const data = isPlatformId(state.view) ? state.data[state.view] : null;
  const updatedAt =
    state.view === "timeline"
      ? state.timeline.fetchedAt
      : data?.loaded
        ? data.fetchedAt
        : null;
  const busy =
    state.view === "timeline" ? state.timeline.loading : !!data?.loading;

  return (
    <>
      <header className={cx("topbar")}>
        <div className={cx("topbar-title")}>
          <span
            style={platform ? { background: platform.color } : {}}
            className={cx("title-dot")}
          ></span>{" "}
          {title}
        </div>
        <div className={cx("topbar-right")}>
          {updatedAt ? (
            <span className={cx("topbar-updated")}>
              {"更新于 "}
              {updatedAt.toLocaleTimeString("zh-CN", { hour12: false })}
            </span>
          ) : null}
          <label
            title="每 5 分钟自动刷新当前视图"
            className={cx("topbar-switch")}
          >
            <span>{"自动刷新"}</span>
            <span className={cx("switch")}>
              <input
                checked={state.autoRefresh}
                type="checkbox"
                onChange={(event) => {
                  setAutoRefresh(event.currentTarget.checked);
                }}
              ></input>
              <span className={cx("track")}></span>
            </span>
          </label>
          <button
            title="终端面板：运行日志与任务队列"
            className={cx("btn terminal-btn", { active: state.terminalOpen })}
            onClick={() => {
              toggleTerminal();
            }}
          >
            <Icon name="terminal" size={13}></Icon>
            {" 终端 "}
            {queueInfo.paused > 0 ? (
              <span className={cx("term-badge err")}>{queueInfo.paused}</span>
            ) : queueInfo.busy > 0 ? (
              <span className={cx("term-badge")}>{queueInfo.busy}</span>
            ) : null}
          </button>
          <button
            title="配置各平台 Cookie 与多账号池（多账号并行查询加速）"
            className={cx("btn")}
            onClick={() => {
              openAccountModal(platform?.id || "");
            }}
          >
            <Icon name="users" size={13}></Icon>
            {" 账号 "}
          </button>
          <button
            disabled={busy}
            className={cx("btn")}
            onClick={() => {
              refreshCurrentView();
            }}
          >
            <Icon
              name="refresh"
              size={13}
              className={cx({ spinning: busy })}
            ></Icon>
            {" 刷新 "}
          </button>
        </div>
      </header>
    </>
  );
}
