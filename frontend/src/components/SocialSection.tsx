import { Fragment } from "react";
import { classNames } from "../classes";
import { PLATFORM_MAP } from "../platforms";
import { setUid } from "../store";
import type { PlatformId, Profile, User } from "../types";
import styles from "./SocialSection.module.css";
import Icon from "./ui/Icon";
import UserAvatar from "./ui/UserAvatar";
const cx = classNames(styles);

export default function SocialSection({
  platformId,
  profile = null,
  follows = [],
  followers = [],
}: {
  platformId: PlatformId;
  profile?: Profile | null;
  follows?: User[];
  followers?: User[];
}) {
  const platform = PLATFORM_MAP[platformId],
    MAX = 20;
  const e = profile?.extra || {};
  const followsCountOnly = follows.length
    ? 0
    : Number(e.follow_count ?? e.mFollowNum) || 0;
  const followersCountOnly = followers.length
    ? 0
    : Number(e.fan_count ?? e.mFansNum) || 0;
  const panels = [
    { icon: "user", label: "关注", list: follows, countOnly: followsCountOnly },
    {
      icon: "users",
      label: "粉丝",
      list: followers,
      countOnly: followersCountOnly,
    },
  ];
  function goUser(user: User) {
    const uid = String(user.sec_uid || user.uid || user.uin || "");
    if (uid) setUid(platformId, uid);
  }

  return (
    <>
      <div className={cx("social")}>
        {panels.map((p) => (
          <div key={p.label} className={cx("card social-panel")}>
            <div className={cx("panel-head")}>
              <Icon name={p.icon} size={13}></Icon> {p.label}{" "}
              <span className={cx("panel-count")}>
                {p.list.length || p.countOnly || ""}
              </span>
            </div>
            {p.list.length ? (
              <Fragment>
                {p.list.slice(0, MAX).map((u, i) => (
                  <button
                    key={i}
                    className={cx("social-row")}
                    onClick={() => {
                      goUser(u);
                    }}
                  >
                    <UserAvatar
                      src={u.avatarUrl}
                      name={u.nickname}
                      size={32}
                      color={platform.color}
                    ></UserAvatar>
                    <span className={cx("s-main")}>
                      <span className={cx("s-name")}>
                        {u.nickname || "未知"}
                      </span>
                      {u.signature ? (
                        <span className={cx("s-sig")}>{u.signature}</span>
                      ) : null}
                    </span>
                  </button>
                ))}
                {p.list.length > MAX ? (
                  <div className={cx("social-more")}>
                    {"仅显示前 "}
                    {MAX}
                    {" 个"}
                  </div>
                ) : null}
              </Fragment>
            ) : p.countOnly ? (
              <div className={cx("social-note")}>
                {" 共 "}
                {p.countOnly}
                {" 人，加密账号暂无法获取列表 "}
              </div>
            ) : (
              <div className={cx("social-note")}>{"暂无数据"}</div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
