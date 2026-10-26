import { Fragment } from "react";
import { classNames } from "../../classes";
import CookieModal from "../CookieModal";
import styles from "../ViewGraph.module.css";
import type { GraphScope } from "./scope";
const cx = classNames(styles);
export function GraphFooter({ scope }: { scope: GraphScope }) {
  const {
    result,
    cookieModal,
    hiddenCount,
    nodeCount,
    edgeCount,
    sameCount,
    followsCount,
    manualCount,
    onCookieSaved,
    setCookieOpen,
    restoreHidden,
  } = scope;

  return (
    <>
      {result ? (
        <div className={cx("vg-foot")}>
          <span>
            {" 已搜索 "}
            <b>{result.searched?.length ?? result.platforms.length}</b>
            {" 个平台 · "}
            <b>{nodeCount}</b>
            {" 个用户 · "}
            <b>{edgeCount}</b>
            {" 条关系（同名 "}
            {sameCount}
            {" · 关注 "}
            {followsCount}
            {manualCount ? (
              <Fragment>
                {" · 手动同人 "}
                {manualCount}
              </Fragment>
            ) : null}
            {"） "}
            {hiddenCount ? (
              <button
                title="把手动隐藏的节点恢复显示"
                className={cx("vg-restore")}
                onClick={() => {
                  restoreHidden();
                }}
              >
                {"已排除 "}
                {hiddenCount}
                {" 个节点，点击还原"}
              </button>
            ) : null}
          </span>
          <span className={cx("vg-foot-tip")}>
            {"滚轮缩放 · 拖拽节点/画布 · 点击节点展开社交关系"}
          </span>
        </div>
      ) : null}
      <CookieModal
        open={cookieModal.open}
        platform={cookieModal.platform}
        onClose={() => {
          setCookieOpen(false);
        }}
        onSaved={() => {
          onCookieSaved();
        }}
      ></CookieModal>
    </>
  );
}
