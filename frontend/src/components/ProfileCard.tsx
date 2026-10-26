import { Fragment } from "react";
import { classNames } from "../classes";
import { PLATFORM_MAP } from "../platforms";
import type { PlatformId, Profile } from "../types";
import styles from "./ProfileCard.module.css";
import UserAvatar from "./ui/UserAvatar";
const cx = classNames(styles);

export default function ProfileCard({
  platformId,
  profile,
}: {
  platformId: PlatformId;
  profile: Profile;
}) {
  const platform = PLATFORM_MAP[platformId];
  const badges = [platform.vipLabel?.(profile)].filter((v): v is string => !!v);
  const metaItems = platform.metaLine(profile),
    stats = platform.stats(profile),
    signature = (profile.signature || "").trim();

  return (
    <>
      <div className={cx("card profile")}>
        <UserAvatar
          src={profile.avatar_url}
          name={profile.nickname}
          size={62}
          color={platform.color}
        ></UserAvatar>
        <div className={cx("profile-main")}>
          <div className={cx("profile-name-row")}>
            <span className={cx("profile-name")}>
              {profile.nickname || "未知用户"}
            </span>
            {badges.map((b) => (
              <span key={b} className={cx("tag")}>
                {b}
              </span>
            ))}
          </div>
          <div className={cx("profile-meta")}>
            <span>
              {"UID "}
              {profile.uid}
            </span>
            {metaItems.map((m, i) => (
              <Fragment key={i}>
                <span className={cx("meta-sep")}>{"·"}</span>
                <span className={cx("meta-item")}>{m}</span>
              </Fragment>
            ))}
          </div>
          {signature ? (
            <div className={cx("profile-sig")}>{signature}</div>
          ) : null}
        </div>
        {stats.length ? (
          <div className={cx("profile-stats")}>
            {stats.map((s) => (
              <div key={s.label} className={cx("stat")}>
                <div className={cx("stat-value")}>{s.value}</div>
                <div className={cx("stat-label")}>{s.label}</div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </>
  );
}
