import { Fragment, useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { classNames } from "../classes";
import { PLATFORM_MAP } from "../platforms";
import { closeDetail, useAppStore } from "../store";
import type { ContentDetail } from "../types";
import { fmtDuration, fmtNum } from "../utils";
import styles from "./DetailModal.module.css";
import Icon from "./ui/Icon";
import Modal from "./ui/Modal";
const cx = classNames(styles);

export default function DetailModal() {
  const modal = useAppStore((s) => s.detailModal),
    state = { detailModal: modal },
    open = !!modal;
  const platform = modal ? PLATFORM_MAP[modal.platform] : null;
  const [detail, setDetail] = useState<ContentDetail | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    setDetail(null);
    setError("");
    if (!modal) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    api
      .get<ContentDetail>(
        `/${modal.platform}/playlist/${encodeURIComponent(modal.id)}`,
        undefined,
        controller.signal,
      )
      .then((data) => {
        if (!controller.signal.aborted) setDetail(data);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorMessage(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [modal]);
  function items(value: ContentDetail) {
    return value.items || [];
  }
  function artistOf(song: NonNullable<ContentDetail["items"]>[number]) {
    return song.artist || song.singer || "";
  }
  function linkOf() {
    return modal && platform ? platform.itemLink({ item_id: modal.id }) : "";
  }

  return (
    <>
      <Modal
        open={open}
        title={detail?.title || "内容详情"}
        onClose={() => {
          closeDetail();
        }}
      >
        {loading ? (
          <div style={{ padding: "40px 0" }} className={cx("page-loading")}>
            <span className={cx("spinner")}></span>
            {" 加载详情… "}
          </div>
        ) : error ? (
          <div className={cx("detail-error")}>
            <Icon name="alert" size={22}></Icon> {error}
          </div>
        ) : detail ? (
          <Fragment>
            <div className={cx("detail-meta")}>
              <span>
                {detail.count ?? items(detail).length}
                {" 项"}
              </span>
              {detail.viewCount ? (
                <Fragment>
                  <span className={cx("sep")}>{"·"}</span>
                  <span>
                    {fmtNum(detail.viewCount)}
                    {" 次播放"}
                  </span>
                </Fragment>
              ) : null}
              {detail.subscribedCount ? (
                <Fragment>
                  <span className={cx("sep")}>{"·"}</span>
                  <span>
                    {fmtNum(detail.subscribedCount)}
                    {" 收藏"}
                  </span>
                </Fragment>
              ) : null}
              {linkOf() ? (
                <a
                  href={linkOf()}
                  target="_blank"
                  rel="noopener"
                  className={cx("detail-link")}
                >
                  <Icon name="external" size={12}></Icon>
                  {" 在 "}
                  {platform?.name}
                  {" 打开 "}
                </a>
              ) : null}
            </div>
            {detail.description ? (
              <p className={cx("detail-desc")}>{detail.description}</p>
            ) : null}
            {items(detail).length ? (
              <div className={cx("song-list")}>
                {items(detail)
                  .slice(0, 100)
                  .map((s, i) => (
                    <div key={s.id || i} className={cx("song-row")}>
                      <span className={cx("song-index")}>{i + 1}</span>
                      <span className={cx("song-main")}>
                        <span className={cx("song-title")}>
                          {s.title || "未知"}
                        </span>
                        {artistOf(s) || s.album ? (
                          <span className={cx("song-sub")}>
                            {artistOf(s)}
                            {s.album ? (
                              <Fragment>
                                {" · "}
                                {s.album}
                              </Fragment>
                            ) : null}
                          </span>
                        ) : null}
                      </span>
                      {s.duration ? (
                        <span className={cx("song-dur")}>
                          {fmtDuration(s.duration)}
                        </span>
                      ) : null}
                    </div>
                  ))}
              </div>
            ) : (
              <div className={cx("detail-empty")}>
                {"该内容没有可展示的条目"}
              </div>
            )}
          </Fragment>
        ) : null}
      </Modal>
    </>
  );
}
