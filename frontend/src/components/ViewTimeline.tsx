import { Fragment } from "react";
import { errorMessage } from "../api";
import { classNames } from "../classes";
import { PLATFORM_MAP, platformColor } from "../platforms";
import {
  deleteTimelineEntry,
  loadTimeline,
  setEditEntry,
  setTimelineSource,
  timelineUidPairs,
  useAppStore,
} from "../store";
import type { TimelineEntry } from "../types";
import { fmtDate, fmtTimeHM } from "../utils";
import Icon from "./ui/Icon";
import styles from "./ViewTimeline.module.css";
const cx = classNames(styles);

export default function ViewTimeline() {
  const t = useAppStore((s) => s.timeline);
  // Subscribe to targets as well so the empty-state list tracks edits.
  useAppStore((s) => s.uids);
  function entryGroup(e: TimelineEntry) {
    if (e.time_str !== undefined) {
      const date = (e.time_str || "").split(" ")[0];
      if (date) return { key: date, label: date, tone: "" };
      const suffix = e.time_suffix || "";
      if (suffix === "首次采集")
        return { key: "first", label: "首次采集", tone: "first" };
      if (suffix.startsWith("至少从"))
        return { key: "ongoing", label: "持续进行", tone: "ongoing" };
      return { key: "unknown", label: "时间未知", tone: "unknown" };
    }
    const ts = Number(e.timestamp) || 0,
      date = ts ? fmtDate(ts) : (e.created_at || "").slice(0, 10);
    return date
      ? { key: date, label: date, tone: "" }
      : { key: "unknown", label: "时间未知", tone: "unknown" };
  }
  function entryDisplay(e: TimelineEntry) {
    const platformName =
      e.platform_name || PLATFORM_MAP[e.platform]?.name || e.platform;
    if (e.time_str !== undefined)
      return {
        platformName,
        time: (e.time_str || "").split(" ")[1] || "",
        suffix: e.time_suffix || "",
      };
    const ts = Number(e.timestamp) || 0;
    return {
      platformName,
      time: ts ? fmtTimeHM(ts) : (e.created_at || "").slice(11, 16),
      suffix: "",
    };
  }
  const groups: Array<{
    key: string;
    label: string;
    tone: string;
    entries: Array<
      TimelineEntry & { _display: ReturnType<typeof entryDisplay> }
    >;
  }> = [];
  for (const entry of t.entries) {
    const group = entryGroup(entry);
    let current = groups[groups.length - 1];
    if (!current || current.key !== group.key) {
      current = { ...group, entries: [] };
      groups.push(current);
    }
    current.entries.push({ ...entry, _display: entryDisplay(entry) });
  }
  function suffixClass(suffix: string) {
    return suffix === "时间未知" || suffix === "首次采集"
      ? "s-unknown"
      : suffix.startsWith("至少从")
        ? "s-ongoing"
        : "s-range";
  }
  async function removeEntry(entry: TimelineEntry) {
    if (!entry.id || !window.confirm("确定删除这条时间线记录吗？")) return;
    try {
      await deleteTimelineEntry(entry.id);
    } catch (e) {
      window.alert(`删除失败：${errorMessage(e)}`);
    }
  }

  return (
    <>
      <div className={cx("content-narrow")}>
        <div className={cx("tl-head")}>
          <div className={cx("seg")}>
            <button
              className={cx("seg-btn", { active: t.source === "live" })}
              onClick={() => {
                setTimelineSource("live");
              }}
            >
              {" 实时对比 "}
            </button>
            <button
              className={cx("seg-btn", { active: t.source === "stored" })}
              onClick={() => {
                setTimelineSource("stored");
              }}
            >
              {" 历史记录 "}
            </button>
          </div>
          <span className={cx("tl-desc")}>
            {t.source === "live"
              ? "对比两次采集之间的快照差异，推断变化发生的时间窗口"
              : "查看已持久化的时间线条目，可编辑修正"}
          </span>
        </div>
        {t.error === "NO_UIDS" ? (
          <div className={cx("empty-state card")}>
            <span className={cx("empty-icon")}>
              <Icon name="clock" size={34}></Icon>
            </span>
            <div className={cx("empty-title")}>{"还没有可分析的目标用户"}</div>
            <div>
              {
                "先到各平台页搜索并设置要关注的用户，采集到两批快照后这里就会出现活动时间线"
              }
            </div>
          </div>
        ) : t.loading ? (
          <div className={cx("page-loading")}>
            <span className={cx("spinner")}></span>
            {" 正在"}
            {t.source === "live" ? "对比快照" : "读取历史记录"}
            {"… "}
          </div>
        ) : t.error ? (
          <div className={cx("card error-card")}>
            <span className={cx("empty-icon")}>
              <Icon name="alert" size={32}></Icon>
            </span>
            <div className={cx("empty-title")}>{"时间线加载失败"}</div>
            <div className={cx("tl-err")}>{t.error}</div>
            <button
              className={cx("btn")}
              onClick={() => {
                loadTimeline({ force: true });
              }}
            >
              {"重试"}
            </button>
          </div>
        ) : !t.entries.length ? (
          <div className={cx("empty-state card")}>
            <span className={cx("empty-icon")}>
              <Icon name="inbox" size={34}></Icon>
            </span>
            <div className={cx("empty-title")}>{"暂无活动记录"}</div>
            <div>
              {" 已监控平台："}
              {timelineUidPairs()
                .map((p) => p.split(":")[0])
                .join("、") || "无"}
              <br></br>
              {
                " 平台数据采集后会自动写入快照，检测到变化（听歌、关注、发布等）就会出现在这里 "
              }
            </div>
            <button
              className={cx("btn btn-primary")}
              onClick={() => {
                loadTimeline({ force: true });
              }}
            >
              <Icon name="refresh" size={13}></Icon>
              {" 重新检查 "}
            </button>
          </div>
        ) : (
          <div className={cx("card timeline")}>
            {groups.map((g) => (
              <Fragment key={g.key}>
                <div className={cx("tl-date", "tone-" + g.tone)}>
                  <Icon name={g.tone ? "clock" : "calendar"} size={12}></Icon>{" "}
                  {g.label}
                </div>
                {g.entries.map((e, i) => (
                  <div
                    key={(e.id || i) + "-" + e.summary}
                    className={cx("tl-entry")}
                  >
                    <span
                      style={{ background: platformColor(e.platform) }}
                      className={cx("tl-dot")}
                    ></span>
                    <div className={cx("tl-body")}>
                      <div className={cx("tl-meta")}>
                        <span className={cx("tl-platform")}>
                          <span
                            style={{ background: platformColor(e.platform) }}
                            className={cx("pl-dot")}
                          ></span>{" "}
                          {e._display.platformName}
                        </span>
                        <span className={cx("tl-type")}>{e.event_type}</span>
                        <span className={cx("tl-time")}>{e._display.time}</span>
                        {e._display.suffix &&
                        e._display.suffix !== e._display.time ? (
                          <span
                            className={cx(
                              "tl-suffix",
                              suffixClass(e._display.suffix),
                            )}
                          >
                            {e._display.suffix}
                          </span>
                        ) : null}
                      </div>
                      <div className={cx("tl-summary")}>{e.summary}</div>
                      {e.detail ? (
                        <div className={cx("tl-detail")}>{e.detail}</div>
                      ) : null}
                      {t.source === "stored" && e.id ? (
                        <div className={cx("tl-actions")}>
                          <button
                            className={cx("btn btn-sm")}
                            onClick={() => {
                              setEditEntry({
                                id: e.id!,
                                summary: e.summary || "",
                                detail: e.detail || "",
                              });
                            }}
                          >
                            <Icon name="edit" size={11}></Icon>
                            {" 编辑 "}
                          </button>
                          <button
                            title="删除此条记录"
                            className={cx("btn btn-sm btn-danger-ghost")}
                            onClick={() => {
                              removeEntry(e);
                            }}
                          >
                            <Icon name="trash" size={11}></Icon>
                            {" 删除 "}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                ))}
              </Fragment>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
