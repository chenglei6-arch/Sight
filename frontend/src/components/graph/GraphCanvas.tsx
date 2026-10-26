import { useEffect, useRef } from "react";
import { classNames } from "../../classes";
import Icon from "../ui/Icon";
import styles from "../ViewGraph.module.css";
import type { GraphController } from "./controller";
import type { GraphScope } from "./scope";
const cx = classNames(styles);
export function GraphCanvas({
  scope,
  controller,
}: {
  scope: GraphScope;
  controller: GraphController;
}) {
  const {
    keyword,
    loading,
    error,
    result,
    lastSearched,
    linkSource,
    frozen,
    nodeCount,
    setLinkSource,
  } = scope;
  const stageEl = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled && stageEl.current)
        void controller.mount(stageEl.current).catch((error) => {
          controller.error = String(error);
          controller.publish();
        });
    });
    return () => {
      cancelled = true;
      controller.dispose();
    };
  }, [controller]);
  return (
    <>
      <div className={cx("vg-stage card")}>
        <div ref={stageEl} className={cx("vg-canvas")}></div>
        {!loading && !result && !error ? (
          <div className={cx("vg-note")}>
            <Icon name="users" size={28}></Icon>
            <p>{"输入关键词生成跨平台用户关系图"}</p>
            <p className={cx("vg-note-sub")}>
              {
                " 绿色粗线 = 互相关注；红色实线 = 跨平台完全同名（疑似同一人）；红色虚线 = 昵称相似；紫色实线 = 手动标记同人（点击连线解除）；"
              }
              <br></br>
              {
                " 蓝色箭头 = 单向关注（谁指向谁就是谁在关注谁）；灰色小点 = 粉丝 1000+ 或平台认证的公众账号/达人；"
              }
              <br></br>
              {
                ' 各平台昵称不同？点平台 chip 旁的铅笔给该平台设专属搜索词；信息卡里可"标记同人"手动关联跨平台账号；'
              }
              <br></br>
              {
                ' 悬浮在连线或节点上可查看关系说明；节点大小与粉丝数成反比（粉丝越多节点越小）；点击节点可在卡片中选择"不看"来排除干扰节点 '
              }
            </p>
          </div>
        ) : !loading && !result && error ? (
          <div className={cx("vg-note vg-err")}>
            <Icon name="alert" size={20}></Icon>
            <p>{error}</p>
          </div>
        ) : !loading && result && !nodeCount ? (
          <div className={cx("vg-note")}>
            <p>{"所有平台均无结果"}</p>
          </div>
        ) : null}
        {loading ? (
          <div className={cx("vg-loading-pill")}>
            <span className={cx("spinner spinner-sm")}></span>
            {"正在跨平台搜索「"}
            {keyword || lastSearched}
            {"」… "}
          </div>
        ) : null}
        {frozen ? (
          <div className={cx("vg-loading-pill vg-frozen-pill")}>
            <Icon name="pause" size={12}></Icon>
            {
              " 布局已停放：节点不再自动运动，可直接拖拽摆放；点击工具栏「恢复」继续收敛 "
            }
          </div>
        ) : null}
        {linkSource ? (
          <div className={cx("vg-loading-pill vg-link-pill")}>
            <Icon name="users" size={12}></Icon>
            {" 标记同人「"}
            {linkSource.nickname}
            {"」：点击图中另一账号完成连线（点它自己取消） "}
            <button
              className={cx("vg-link-cancel")}
              onClick={() => {
                setLinkSource(null);
              }}
            >
              {"取消"}
            </button>
          </div>
        ) : null}
        <GraphNodeCard scope={scope} />
      </div>
    </>
  );
}

import { GraphNodeCard } from "./GraphNodeCard";
