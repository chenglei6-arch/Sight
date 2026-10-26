import { Fragment } from "react";
import { classNames } from "../classes";
import type { PlatformPayload } from "../types";
import { fmtNum } from "../utils";
import styles from "./RecordSection.module.css";
const cx = classNames(styles);

export default function RecordSection({
  records,
}: {
  records: NonNullable<PlatformPayload["records"]>;
}) {
  const allTime = records.allTime || [],
    weekly = records.weekly || [];
  const top3 = (index: number) => index < 3;

  return (
    <>
      <div className={cx("records")}>
        {allTime.length ? (
          <div className={cx("card record-panel")}>
            <div className={cx("panel-head")}>
              <i className={cx("dot dot-all")}></i>
              {"所有时间"}
            </div>
            {allTime.slice(0, 20).map((s, i) => (
              <div key={s.entry_id || i} className={cx("record-row")}>
                <span className={cx("rank", { top: top3(i) })}>{i + 1}</span>
                <span className={cx("r-main")}>
                  <span title={s.title} className={cx("r-title")}>
                    {s.title}
                  </span>
                  <span className={cx("r-sub")}>
                    {s.artist_or_uploader}
                    {s.album_or_category ? (
                      <Fragment>
                        {" · "}
                        {s.album_or_category}
                      </Fragment>
                    ) : null}
                  </span>
                </span>
                <span className={cx("r-count")}>
                  {fmtNum(s.play_count)}
                  {" 次"}
                </span>
              </div>
            ))}
          </div>
        ) : null}
        {weekly.length ? (
          <div className={cx("card record-panel")}>
            <div className={cx("panel-head")}>
              <i className={cx("dot dot-week")}></i>
              {"最近一周"}
            </div>
            {weekly.slice(0, 20).map((s, i) => (
              <div key={s.entry_id || i} className={cx("record-row")}>
                <span className={cx("rank", { top: top3(i) })}>{i + 1}</span>
                <span className={cx("r-main")}>
                  <span title={s.title} className={cx("r-title")}>
                    {s.title}
                  </span>
                  <span className={cx("r-sub")}>
                    {s.artist_or_uploader}
                    {s.album_or_category ? (
                      <Fragment>
                        {" · "}
                        {s.album_or_category}
                      </Fragment>
                    ) : null}
                  </span>
                </span>
                <span className={cx("r-count")}>
                  {fmtNum(s.play_count)}
                  {" 次"}
                </span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </>
  );
}
