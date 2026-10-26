import { useShallow } from "zustand/react/shallow";
import { classNames } from "../classes";
import { PLATFORMS } from "../platforms";
import {
  openSavedGraph,
  removeSavedGraph,
  setView,
  useAppStore,
} from "../store";
import type { SavedGraphMeta } from "../types";
import styles from "./SideBar.module.css";
import Icon from "./ui/Icon";
const cx = classNames(styles);

export default function SideBar() {
  const state = useAppStore(
    useShallow((s) => ({
      view: s.view,
      activeGraphId: s.activeGraphId,
      savedGraphs: s.savedGraphs,
      savedGraphsError: s.savedGraphsError,
      platformsMeta: s.platformsMeta,
      platformsMetaError: s.platformsMetaError,
    })),
  );
  const items = PLATFORMS.map((p) => {
    const meta = state.platformsMeta.find((m) => m.id === p.id);
    return {
      ...p,
      statusColor: meta?.is_alive
        ? "#1e9e55"
        : meta?.has_credential
          ? "#d9a514"
          : "#c9cdd3",
      hasMeta: !!meta,
    };
  });
  function graphTitle(g: SavedGraphMeta) {
    const t = String(g.updated_at || "")
      .slice(5, 16)
      .replace("T", " ");
    return `${g.name}\n关键词「${g.keyword || "-"}」 · ${g.node_count} 用户 · ${g.edge_count} 条关系\n更新于 ${t}（点击调出，无需重新搜索）`;
  }
  async function removeGraph(g: SavedGraphMeta) {
    if (window.confirm(`确定删除图谱「${g.name}」吗？删除后不可恢复。`))
      await removeSavedGraph(g.id);
  }

  return (
    <>
      <aside className={cx("app-sidebar")}>
        <div className={cx("brand")}>
          <span className={cx("brand-icon")}>
            <Icon name="eye" size={17}></Icon>
          </span>
          <div className={cx("brand-text")}>
            <div className={cx("brand-name")}>{"Sight"}</div>
            <div className={cx("brand-sub")}>{"多平台数据监控"}</div>
          </div>
        </div>
        <nav className={cx("nav")}>
          <div className={cx("nav-label")}>{"平台"}</div>
          {items.map((p) => (
            <button
              key={p.id}
              className={cx("nav-item", { active: state.view === p.id })}
              onClick={() => {
                setView(p.id);
              }}
            >
              <span
                style={{ background: p.color }}
                className={cx("nav-dot")}
              ></span>
              <span className={cx("nav-name")}>{p.name}</span>
              <span
                style={{ background: p.statusColor }}
                title={
                  p.hasMeta
                    ? p.statusColor === "#1e9e55"
                      ? "凭证可用"
                      : p.statusColor === "#d9a514"
                        ? "凭证已失效"
                        : "未配置凭证"
                    : "检测中"
                }
                className={cx("nav-status")}
              ></span>
            </button>
          ))}
          <div className={cx("nav-label")}>{"分析"}</div>
          <button
            className={cx("nav-item", { active: state.view === "timeline" })}
            onClick={() => {
              setView("timeline");
            }}
          >
            <span className={cx("nav-dot nav-dot-icon")}>
              <Icon name="clock" size={14}></Icon>
            </span>
            <span className={cx("nav-name")}>{"活动时间线"}</span>
          </button>
          <button
            className={cx("nav-item", {
              active: state.view === "graph" && !state.activeGraphId,
            })}
            onClick={() => {
              setView("graph");
            }}
          >
            <span className={cx("nav-dot nav-dot-icon")}>
              <Icon name="users" size={14}></Icon>
            </span>
            <span className={cx("nav-name")}>{"关系图谱"}</span>
          </button>
          {state.savedGraphs.map((g) => (
            <button
              key={"graph-" + g.id}
              title={graphTitle(g)}
              className={cx("nav-item nav-graph", {
                active: state.view === "graph" && state.activeGraphId === g.id,
              })}
              onClick={() => {
                openSavedGraph(g.id);
              }}
            >
              <span className={cx("nav-dot nav-dot-icon nav-graph-icon")}>
                <Icon name="share2" size={11}></Icon>
              </span>
              <span className={cx("nav-name")}>{g.name}</span>
              <span
                title="删除该图谱"
                className={cx("nav-graph-del")}
                onClick={(event) => {
                  event.stopPropagation();
                  removeGraph(g);
                }}
              >
                <Icon name="x" size={11}></Icon>
              </span>
            </button>
          ))}
          {state.savedGraphsError ? (
            <div className={cx("nav-graph-err")}>{state.savedGraphsError}</div>
          ) : null}
        </nav>
        {state.platformsMetaError ? (
          <div className={cx("nav-graph-err")}>{state.platformsMetaError}</div>
        ) : null}
      </aside>
    </>
  );
}
