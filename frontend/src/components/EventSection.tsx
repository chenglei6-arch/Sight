import { useState } from "react";
import { classNames } from "../classes";
import type { ActivityEvent } from "../types";
import { fmtEventTime } from "../utils";
import styles from "./EventSection.module.css";
const cx = classNames(styles);

export default function EventSection({
  events = [],
  showLinks = false,
}: {
  events?: ActivityEvent[];
  showLinks?: boolean;
}) {
  const PAGE = 10;
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? events : events.slice(0, PAGE);
  function pics(ev: ActivityEvent) {
    return Array.isArray(ev.extra?.pics)
      ? ev.extra.pics.filter(Boolean).slice(0, 6)
      : [];
  }

  return (
    <>
      <div className={cx("card event-list")}>
        {shown.map((ev, i) => (
          <div key={ev.event_id || i} className={cx("event-row")}>
            <div className={cx("ev-side")}>
              <span className={cx("ev-time")}>
                {fmtEventTime(ev.timestamp) || "时间未知"}
              </span>
              {ev.event_type ? (
                <span className={cx("ev-type")}>{ev.event_type}</span>
              ) : null}
            </div>
            <div className={cx("ev-main")}>
              {ev.content ? (
                <div className={cx("ev-content")}>{ev.content}</div>
              ) : null}
              {ev.media_title ? (
                <div className={cx("ev-media")}>
                  {" 《"}
                  {ev.media_title}
                  {"》"}
                  {ev.media_artist ? (
                    <span className={cx("ev-artist")}>{ev.media_artist}</span>
                  ) : null}
                </div>
              ) : null}
              {showLinks && ev.url && /^https?:\/\//i.test(ev.url) ? (
                <a className={cx("ev-link")} href={ev.url} target="_blank" rel="noopener noreferrer">
                  查看原始记录 ↗
                </a>
              ) : null}
              {pics(ev).length ? (
                <div className={cx("ev-pics")}>
                  {pics(ev).map((p, j) => (
                    <img
                      key={j}
                      src={p}
                      referrerPolicy="no-referrer"
                      loading="lazy"
                      alt=""
                      onError={(event) => {
                        event.currentTarget.style.display = "none";
                      }}
                    ></img>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ))}
        {events.length > PAGE ? (
          <button
            className={cx("ev-more")}
            onClick={() => {
              setExpanded(!expanded);
            }}
          >
            {expanded ? "收起" : `展开其余 ${events.length - PAGE} 条`}
          </button>
        ) : null}
      </div>
    </>
  );
}
