import { Fragment } from "react";
import { classNames } from "../../classes";
import { PLATFORM_MAP } from "../../platforms";
import { fmtNum } from "../../utils";
import Icon from "../ui/Icon";
import UserAvatar from "../ui/UserAvatar";
import styles from "../ViewGraph.module.css";
import type { GraphScope } from "./scope";
const cx = classNames(styles);
export function GraphNodeCard({ scope }: { scope: GraphScope }) {
  const {
    selected,
    expandLimit,
    expandBusyIds,
    selectedId,
    selectedExpandMsg,
    selectedExpandMsgIsError,
    selectedProgText,
    selectedCounts,
    adoptTarget,
    startLinkFrom,
    hideSelectedNode,
    expandSocial,
    setSelected,
    homeUrl,
    canExpandMore,
    SOCIAL_SUPPORT,
  } = scope;

  return (
    <>
      {selected ? (
        <div className={cx("vg-info card")}>
          <button
            className={cx("vg-info-x")}
            onClick={() => {
              setSelected(null);
            }}
          >
            <Icon name="x" size={11}></Icon>
          </button>
          <div className={cx("vg-info-head")}>
            <UserAvatar
              src={selected.avatarUrl}
              name={selected.nickname}
              size={44}
              color={PLATFORM_MAP[selected.platform]?.color}
            ></UserAvatar>
            <div className={cx("vg-info-name")}>
              <div className={cx("vg-info-nick")}>
                {selected.nickname || "未知用户"}
              </div>
              <div className={cx("vg-info-plat")}>
                <span
                  style={{ background: PLATFORM_MAP[selected.platform]?.color }}
                  className={cx("vg-chip-dot")}
                ></span>{" "}
                {PLATFORM_MAP[selected.platform]?.name || selected.platform}{" "}
                {Number(selected.fans) > 0 ? (
                  <span className={cx("vg-info-fans")}>
                    {fmtNum(Number(selected.fans))}
                    {" 粉丝"}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
          <div className={cx("vg-info-uid")}>
            {"UID："}
            {selected.uid}
          </div>
          {selected.signature ? (
            <p className={cx("vg-info-sig")}>{selected.signature}</p>
          ) : null}
          {selectedCounts &&
          (selectedCounts.following || selectedCounts.followers) ? (
            <div className={cx("vg-info-soc")}>
              {" 图内关注 "}
              {selectedCounts.following}
              {" · 被关注 "}
              {selectedCounts.followers}
            </div>
          ) : null}
          <div className={cx("vg-info-actions")}>
            <button
              className={cx("btn btn-sm btn-primary")}
              onClick={() => {
                adoptTarget();
              }}
            >
              {"设为监测目标"}
            </button>
            {homeUrl(selected) ? (
              <a
                href={homeUrl(selected)}
                target="_blank"
                rel="noopener"
                className={cx("btn btn-sm")}
              >
                <Icon name="external" size={12}></Icon>
                {" 打开主页 "}
              </a>
            ) : null}
            <button
              title="把该账号与图中另一账号手动连为同一人（目标人物跨平台昵称不同时使用），点错可再点连线解除"
              className={cx("btn btn-sm")}
              onClick={() => {
                startLinkFrom(selected);
              }}
            >
              <Icon name="users" size={12}></Icon>
              {" 标记同人"}
            </button>
            <button
              title="把该节点从图中移除（认为价值不大），仅通过它连入图的子节点会一并排除；可随时点击下方计数还原"
              className={cx("btn btn-sm vg-btn-danger")}
              onClick={() => {
                hideSelectedNode();
              }}
            >
              <Icon name="x" size={12}></Icon>
              {" 不看"}
            </button>
          </div>
          {SOCIAL_SUPPORT[selected.platform] ? (
            <Fragment>
              <div className={cx("vg-info-actions")}>
                <button
                  disabled={expandBusyIds.has(selectedId)}
                  className={cx("btn btn-sm")}
                  onClick={() => {
                    expandSocial("both");
                  }}
                >
                  {expandBusyIds.has(selectedId) ? (
                    <span className={cx("spinner spinner-sm")}></span>
                  ) : null}
                  {expandBusyIds.has(selectedId)
                    ? "展开中…"
                    : canExpandMore(selected)
                      ? "继续展开"
                      : "一键展开"}
                </button>
              </div>
              <p className={cx("vg-info-tip")}>
                {selectedProgText ? (
                  <Fragment>
                    {selectedProgText}
                    {"；"}
                  </Fragment>
                ) : null}
                {" 拉取该用户的关注+粉丝（关注各最多 "}
                {expandLimit}
                {" 人），并自动互查邻居之间的关注关系；可同时展开多个节点 "}
              </p>
            </Fragment>
          ) : (
            <p className={cx("vg-info-tip")}>
              {"该平台暂不支持获取关注/粉丝列表"}
            </p>
          )}
          {selectedExpandMsg ? (
            <p
              className={cx("vg-info-msg", {
                "vg-info-err": selectedExpandMsgIsError,
              })}
            >
              {selectedExpandMsg}
            </p>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
