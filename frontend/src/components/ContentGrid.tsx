import { Fragment } from "react";
import { classNames } from "../classes";
import { PLATFORM_MAP, splitTitle } from "../platforms";
import { openDetail } from "../store";
import type { ContentItem, PlatformId } from "../types";
import { fmtDuration, fmtEventTime, fmtNum } from "../utils";
import styles from "./ContentGrid.module.css";
import Icon from "./ui/Icon";
const cx = classNames(styles);

export default function ContentGrid({
  platformId,
  items = [],
}: {
  platformId: PlatformId;
  items?: ContentItem[];
}) {
  const platform = PLATFORM_MAP[platformId],
    kind = platform.contentKind,
    shown = items.slice(0, 60);
  function charName(it: ContentItem) {
    return splitTitle(it.title).name;
  }
  function mediaMeta(it: ContentItem) {
    const parts: string[] = [];
    if (it.view_count) parts.push(`${fmtNum(it.view_count)} 播放`);
    if (kind === "video") {
      if (it.extra?.danmaku_count)
        parts.push(`${fmtNum(it.extra.danmaku_count)} 弹幕`);
      if (it.extra?.length) parts.push(it.extra.length);
    } else {
      if (it.extra?.digg_count) parts.push(`${fmtNum(it.extra.digg_count)} 赞`);
      if (it.extra?.comment_count)
        parts.push(`${fmtNum(it.extra.comment_count)} 评论`);
      if (it.extra?.duration) parts.push(fmtDuration(it.extra.duration));
    }
    return parts;
  }
  function onCardClick(it: ContentItem) {
    if (kind === "playlist" && platform.hasDetail) {
      openDetail(platformId, it.item_id);
      return;
    }
    const link = platform.itemLink(it);
    if (link) window.open(link, "_blank", "noopener");
  }

  return (
    <>
      {items.length ? (
        <div className={cx("content-grid", "kind-" + kind)}>
          {kind === "playlist" ? (
            <Fragment>
              {shown.map((it) => (
                <button
                  key={it.item_id}
                  className={cx("citem")}
                  onClick={() => {
                    onCardClick(it);
                  }}
                >
                  <span
                    style={{ background: platform.color + "14" }}
                    className={cx("cover")}
                  >
                    {it.cover_url ? (
                      <img
                        src={it.cover_url}
                        referrerPolicy="no-referrer"
                        loading="lazy"
                        alt=""
                        onError={(event) => {
                          event.currentTarget.style.display = "none";
                        }}
                      ></img>
                    ) : null}
                  </span>
                  <span className={cx("ci-body")}>
                    <span title={it.title} className={cx("ci-title")}>
                      {it.title || "未命名歌单"}
                    </span>
                    <span className={cx("ci-meta")}>
                      {it.count || 0}
                      {" 首 "}
                      {it.view_count ? (
                        <Fragment>
                          {" · "}
                          {fmtNum(it.view_count)}
                          {" 次播放"}
                        </Fragment>
                      ) : null}
                    </span>
                    <span className={cx("ci-sub")}>
                      {it.is_owner === false ? "收藏" : "创建"}{" "}
                      {it.creator ? (
                        <Fragment>
                          {" · "}
                          {it.creator}
                        </Fragment>
                      ) : null}
                    </span>
                  </span>
                  {platform.itemLink(it) ? (
                    <Icon
                      name="external"
                      size={12}
                      className={cx("ci-link")}
                    ></Icon>
                  ) : null}
                </button>
              ))}
            </Fragment>
          ) : kind === "video" || kind === "work" || kind === "note" ? (
            <Fragment>
              {shown.map((it) => (
                <button
                  key={it.item_id}
                  className={cx("citem media")}
                  onClick={() => {
                    onCardClick(it);
                  }}
                >
                  <span
                    style={{ background: platform.color + "14" }}
                    className={cx("cover wide")}
                  >
                    {it.cover_url ? (
                      <img
                        src={it.cover_url}
                        referrerPolicy="no-referrer"
                        loading="lazy"
                        alt=""
                        onError={(event) => {
                          event.currentTarget.style.display = "none";
                        }}
                      ></img>
                    ) : null}
                  </span>
                  <span className={cx("ci-body")}>
                    <span title={it.title} className={cx("ci-title")}>
                      {it.title || "无标题"}
                    </span>
                    <span className={cx("ci-meta")}>
                      {mediaMeta(it).join(" · ")}
                    </span>
                    <span className={cx("ci-sub")}>
                      {it.create_time
                        ? fmtEventTime(Number(it.create_time))
                        : ""}
                    </span>
                  </span>
                </button>
              ))}
            </Fragment>
          ) : kind === "post" ? (
            <Fragment>
              {shown.map((it) => (
                <div key={it.item_id} className={cx("citem post")}>
                  <span className={cx("ci-body")}>
                    <span title={it.title} className={cx("ci-title post-text")}>
                      {it.title || "（无文字）"}
                    </span>
                    <span className={cx("ci-meta")}>
                      {it.create_time ? (
                        <Fragment>
                          {fmtEventTime(Number(it.create_time))}
                        </Fragment>
                      ) : null}
                      {it.extra?.source ? (
                        <Fragment>
                          {" · 来自"}
                          {it.extra.source}
                        </Fragment>
                      ) : null}
                    </span>
                    <span className={cx("ci-sub")}>
                      {it.extra?.reposts_count ? (
                        <Fragment>
                          {fmtNum(it.extra.reposts_count)}
                          {" 转发"}
                        </Fragment>
                      ) : null}
                      {it.extra?.comments_count ? (
                        <Fragment>
                          {" · "}
                          {fmtNum(it.extra.comments_count)}
                          {" 评论"}
                        </Fragment>
                      ) : null}
                      {it.extra?.attitudes_count ? (
                        <Fragment>
                          {" · "}
                          {fmtNum(it.extra.attitudes_count)}
                          {" 赞"}
                        </Fragment>
                      ) : null}
                      {it.extra?.is_retweet ? (
                        <span className={cx("tag retweet")}>{"转发"}</span>
                      ) : null}
                    </span>
                  </span>
                </div>
              ))}
            </Fragment>
          ) : kind === "character" ? (
            <Fragment>
              {shown.map((it, i) => (
                <div key={it.item_id || i} className={cx("citem character")}>
                  <span
                    style={{ background: platform.color + "14" }}
                    className={cx("cover char")}
                  >
                    {it.cover_url ? (
                      <img
                        src={it.cover_url}
                        referrerPolicy="no-referrer"
                        loading="lazy"
                        alt=""
                        onError={(event) => {
                          event.currentTarget.style.display = "none";
                        }}
                      ></img>
                    ) : null}
                  </span>
                  <span className={cx("ci-body")}>
                    <span className={cx("ci-title")}>{charName(it)}</span>
                    <span className={cx("ci-meta")}>
                      {it.extra?.level ? (
                        <Fragment>
                          {"Lv."}
                          {it.extra.level}
                        </Fragment>
                      ) : null}
                      {it.extra?.element ? (
                        <Fragment>
                          {" · "}
                          {it.extra.element}
                        </Fragment>
                      ) : null}
                      {Number(it.extra?.constellation) > 0 ? (
                        <Fragment>
                          {" · "}
                          {it.extra?.constellation}
                          {"命"}
                        </Fragment>
                      ) : null}
                    </span>
                    {it.extra?.weapon_name ? (
                      <span className={cx("ci-sub")}>
                        {it.extra.weapon_name}{" "}
                        {it.extra.weapon_level ? (
                          <Fragment>
                            {" Lv."}
                            {it.extra.weapon_level}
                          </Fragment>
                        ) : null}
                      </span>
                    ) : null}
                  </span>
                </div>
              ))}
            </Fragment>
          ) : null}
        </div>
      ) : (
        <div className={cx("empty-inline")}>
          {"暂无"}
          {platform.contentLabel}
        </div>
      )}
    </>
  );
}
