import { Fragment, useEffect } from "react";
import { classNames } from "../../classes";
import Icon from "../ui/Icon";
import styles from "../ViewGraph.module.css";
import type { GraphScope } from "./scope";
const cx = classNames(styles);
export function GraphToolbar({ scope }: { scope: GraphScope }) {
  const {
    keyword,
    loading,
    disabledPlatforms,
    platformKeywords,
    editingPlatform,
    editVal,
    graphName,
    saving,
    expandLimit,
    viewFilter,
    layoutMode,
    frozen,
    bulk,
    bulkMsg,
    remark,
    remarkMsg,
    forceParams,
    chipPlatforms,
    presentPlatforms,
    nodeCount,
    doSearch,
    commitKeyword,
    cancelEditKeyword,
    togglePlatform,
    startEditKeyword,
    setExpandLimit,
    toggleFreeze,
    relayout,
    exportPng,
    persistGraph,
    setLayoutMode,
    bulkExpand,
    stopBulk,
    remarkNodes,
    setKeyword,
    setGraphName,
    setEditVal,
    setViewFilter,
    setRepulsion,
    setGravity,
    setEdgeLength,
    state,
  } = scope;

  useEffect(() => {
    if (editingPlatform)
      document
        .querySelector<HTMLInputElement>(`[data-pid="${editingPlatform}"]`)
        ?.focus();
  }, [editingPlatform]);
  return (
    <>
      <div className={cx("vg-toolbar")}>
        <div className={cx("vg-field")}>
          <Icon name="search" size={14} className={cx("vg-icon")}></Icon>
          <input
            value={keyword}
            placeholder="输入关键词，跨平台搜索用户生成关系图"
            className={cx("vg-input")}
            onChange={(event) => {
              setKeyword(event.currentTarget.value);
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter") return;
              doSearch();
            }}
          ></input>
          <button
            disabled={loading || !keyword.trim()}
            className={cx("btn btn-sm vg-btn")}
            onClick={() => {
              doSearch();
            }}
          >
            {loading ? "搜索中" : "生成关系图"}
          </button>
        </div>
        <div className={cx("vg-field vg-name-field")}>
          <Icon name="share2" size={14} className={cx("vg-icon")}></Icon>
          <input
            value={graphName}
            placeholder="图谱名称，留空则用关键词"
            title="生成成功后按此名称保存到侧边栏；同名图谱会被覆盖更新"
            className={cx("vg-input")}
            onChange={(event) => {
              setGraphName(event.currentTarget.value);
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter") return;
              doSearch();
            }}
          ></input>
        </div>
        <div className={cx("vg-chips")}>
          {chipPlatforms.map((p) => (
            <span
              key={p.id}
              title={
                p.noCookie
                  ? p.name +
                    "：未配置 Cookie，搜索大概率失败（点击停用/启用该平台；铅笔可设专属搜索词）"
                  : disabledPlatforms.includes(p.id)
                    ? "点击启用该平台（铅笔可设专属搜索词）"
                    : "点击停用该平台（铅笔可设专属搜索词）"
              }
              className={cx("vg-chip", {
                off: disabledPlatforms.includes(p.id),
              })}
            >
              {editingPlatform === p.id ? (
                <Fragment>
                  <span
                    style={{ background: p.color }}
                    className={cx("vg-chip-dot")}
                  ></span>
                  <input
                    value={editVal}
                    data-pid={p.id}
                    placeholder={`搜索词，留空用主关键词`}
                    className={cx("vg-chip-kw")}
                    onChange={(event) => {
                      setEditVal(event.currentTarget.value);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        commitKeyword(p.id);
                      } else if (event.key === "Escape") {
                        event.preventDefault();
                        cancelEditKeyword();
                      }
                    }}
                    onBlur={() => {
                      commitKeyword(p.id);
                    }}
                  ></input>
                </Fragment>
              ) : (
                <Fragment>
                  <span
                    className={cx("vg-chip-click")}
                    onClick={() => {
                      togglePlatform(p.id);
                    }}
                  >
                    <span
                      style={{
                        background: p.noCookie ? "transparent" : p.color,
                      }}
                      className={cx("vg-chip-dot", { hollow: p.noCookie })}
                    ></span>
                    {p.name}
                  </span>
                  {platformKeywords[p.id] ? (
                    <span
                      title={p.name + " 专属搜索词：" + platformKeywords[p.id]}
                      className={cx("vg-chip-ov")}
                    >
                      {platformKeywords[p.id]}
                    </span>
                  ) : null}
                  <button
                    title={"设置 " + p.name + " 专属搜索词（该平台搜别的词）"}
                    className={cx("vg-chip-edit")}
                    onClick={() => {
                      startEditKeyword(p.id);
                    }}
                  >
                    <Icon name="edit" size={10}></Icon>
                  </button>
                </Fragment>
              )}
            </span>
          ))}
        </div>
        <div className={cx("vg-ctls")}>
          <label
            className={cx("vg-ctl", { dim: layoutMode === "layer" || frozen })}
          >
            <span>
              {"斥力 "}
              {forceParams.repulsion}
            </span>
            <input
              value={forceParams.repulsion}
              type="range"
              min="50"
              max="800"
              step="10"
              disabled={layoutMode === "layer" || frozen}
              onChange={(event) => {
                setRepulsion(Number(event.currentTarget.value));
              }}
            ></input>
          </label>
          <label
            className={cx("vg-ctl", { dim: layoutMode === "layer" || frozen })}
          >
            <span>
              {"引力 "}
              {forceParams.gravity.toFixed(2)}
            </span>
            <input
              value={forceParams.gravity}
              type="range"
              min="0"
              max="0.5"
              step="0.01"
              disabled={layoutMode === "layer" || frozen}
              onChange={(event) => {
                setGravity(Number(event.currentTarget.value));
              }}
            ></input>
          </label>
          <label
            className={cx("vg-ctl", { dim: layoutMode === "layer" || frozen })}
          >
            <span>
              {"边长 "}
              {forceParams.edgeLength}
            </span>
            <input
              value={forceParams.edgeLength}
              type="range"
              min="30"
              max="300"
              step="10"
              disabled={layoutMode === "layer" || frozen}
              onChange={(event) => {
                setEdgeLength(Number(event.currentTarget.value));
              }}
            ></input>
          </label>
          <label
            title="单次展开一个用户时，关注/粉丝各最多拉取多少人（10~500）；达上限且对方还有更多人时，可再次展开"
            className={cx("vg-ctl vg-ctl-num")}
          >
            <span>
              {"每次展开上限 "}
              {expandLimit}
            </span>
            <input
              type="number"
              value={expandLimit}
              min="10"
              max="500"
              step="10"
              onChange={(event) => {
                setExpandLimit(event.currentTarget.value);
              }}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                setExpandLimit(event.currentTarget.value);
                event.currentTarget.blur();
              }}
            ></input>
          </label>
          <button
            disabled={!nodeCount || layoutMode === "layer"}
            title={
              frozen
                ? "解除停放：节点从当前位置继续自动收敛（也可切回分层布局）"
                : "停放：冻结当前布局，之后节点不再自动运动，可拖拽手动摆放"
            }
            className={cx("btn btn-sm", { "btn-primary": frozen })}
            onClick={() => {
              toggleFreeze();
            }}
          >
            <Icon name={frozen ? "play" : "pause"} size={13}></Icon>{" "}
            {frozen ? "恢复" : "停放"}
          </button>
          <button
            disabled={!nodeCount}
            title="重新随机布局并收敛"
            className={cx("btn btn-sm")}
            onClick={() => {
              relayout();
            }}
          >
            <Icon name="refresh" size={13}></Icon>
            {" 重排 "}
          </button>
          <button
            disabled={!nodeCount}
            className={cx("btn btn-sm")}
            onClick={() => {
              exportPng();
            }}
          >
            <Icon name="external" size={13}></Icon>
            {" 导出图片 "}
          </button>
          <button
            disabled={!nodeCount || saving}
            title="把当前图（含已展开的社交关系）保存到侧边栏；同名图谱直接覆盖更新"
            className={cx("btn btn-sm")}
            onClick={() => {
              persistGraph();
            }}
          >
            {saving ? (
              <span className={cx("spinner spinner-sm")}></span>
            ) : (
              <Icon name="check" size={13}></Icon>
            )}
            {state.activeGraphId ? "更新图谱" : "保存图谱"}
          </button>
        </div>
        <div className={cx("vg-toolbar2")}>
          <div className={cx("vg-group")}>
            <span className={cx("vg-group-label")}>{"视图"}</span>
            <button
              className={cx("vg-chip", { on: viewFilter === "all" })}
              onClick={() => {
                setViewFilter("all");
              }}
            >
              {"全部"}
            </button>
            {presentPlatforms.map((p) => (
              <button
                key={p.id}
                title={"只看" + p.name + "的子图"}
                className={cx("vg-chip", { on: viewFilter === p.id })}
                onClick={() => {
                  setViewFilter(viewFilter === p.id ? "all" : p.id);
                }}
              >
                <span
                  style={{ background: p.color }}
                  className={cx("vg-chip-dot")}
                ></span>
                {p.name}
              </button>
            ))}
          </div>
          <div className={cx("vg-group")}>
            <span className={cx("vg-group-label")}>{"布局"}</span>
            <div className={cx("vg-seg")}>
              <button
                className={cx({ on: layoutMode === "force" })}
                onClick={() => {
                  setLayoutMode("force");
                }}
              >
                {"力导向"}
              </button>
              <button
                title="按平台分区排布，关键词居中"
                className={cx({ on: layoutMode === "layer" })}
                onClick={() => {
                  setLayoutMode("layer");
                }}
              >
                {"分层"}
              </button>
            </div>
          </div>
          <div className={cx("vg-group")}>
            <button
              disabled={!nodeCount}
              title={
                viewFilter === "all"
                  ? "对当前图所有用户节点展开关注+粉丝（每人每方向限 20 人）；执行中再点可追加其他节点/平台"
                  : "对当前筛选视图下的用户节点展开关注+粉丝（每人每方向限 20 人）"
              }
              className={cx("btn btn-sm", { "btn-primary": !bulk.busy })}
              onClick={() => {
                bulkExpand();
              }}
            >
              {bulk.busy ? (
                <span className={cx("spinner spinner-sm")}></span>
              ) : null}
              {bulk.busy
                ? `展开中 (${bulk.done}/${bulk.total})，点击追加`
                : "一键展开"}
            </button>
            {bulk.busy ? (
              <button
                title="停止当前图还在排队的展开任务（已在执行的照常完成）"
                className={cx("btn btn-sm")}
                onClick={() => {
                  stopBulk();
                }}
              >
                {" 停止 "}
              </button>
            ) : null}
            {bulkMsg ? (
              <span className={cx("vg-bulk-msg")}>{bulkMsg}</span>
            ) : null}
            <button
              disabled={!nodeCount || remark.busy}
              title="重新拉取图内每个节点的粉丝数/认证标记，修正旧图的大V判定（旧图灰化不准时使用）"
              className={cx("btn btn-sm")}
              onClick={() => {
                remarkNodes();
              }}
            >
              {remark.busy ? (
                <span className={cx("spinner spinner-sm")}></span>
              ) : null}
              {remark.busy ? "重新标记中…" : "重新标记"}
            </button>
            {remarkMsg && !remark.busy ? (
              <span className={cx("vg-bulk-msg")}>{remarkMsg}</span>
            ) : null}
          </div>
        </div>
      </div>
    </>
  );
}
