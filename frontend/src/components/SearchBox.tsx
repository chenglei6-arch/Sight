import { useEffect, useRef, useState } from "react";
import { errorMessage } from "../api";
import { classNames } from "../classes";
import { PLATFORM_MAP } from "../platforms";
import { searchUsers, setUid, useAppStore } from "../store";
import type { PlatformId, User } from "../types";
import styles from "./SearchBox.module.css";
import Icon from "./ui/Icon";
import UserAvatar from "./ui/UserAvatar";
const cx = classNames(styles);

export default function SearchBox({
  platformId,
  className = "",
}: {
  platformId: PlatformId;
  className?: string;
}) {
  const platform = PLATFORM_MAP[platformId],
    uid = useAppStore((s) => s.uids[platformId]);
  const [keyword, setKeyword] = useState(""),
    [searching, setSearching] = useState(false),
    [results, setResults] = useState<User[]>([]),
    [dropdownOpen, setDropdownOpen] = useState(false),
    [searchError, setSearchError] = useState("");
  const root = useRef<HTMLDivElement>(null),
    request = useRef<AbortController | null>(null);
  useEffect(() => {
    function outside(event: MouseEvent) {
      if (!root.current?.contains(event.target as Node)) setDropdownOpen(false);
    }
    document.addEventListener("mousedown", outside);
    return () => {
      document.removeEventListener("mousedown", outside);
      request.current?.abort();
    };
  }, []);
  function selectUid(value: string) {
    request.current?.abort();
    setSearching(false);
    setUid(platformId, value);
    setDropdownOpen(false);
    setResults([]);
  }
  function select(value: string, nickname?: string) {
    selectUid(value);
    setKeyword(nickname || "");
  }
  function clearTarget() {
    selectUid("");
    setKeyword("");
  }
  async function onEnter() {
    const kw = keyword.trim();
    if (!kw) return;
    if (platform.looksLikeUid(kw)) {
      selectUid(kw);
      return;
    }
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setSearching(true);
    setSearchError("");
    setResults([]);
    setDropdownOpen(true);
    try {
      const list = await searchUsers(platformId, kw, controller.signal);
      if (controller.signal.aborted) return;
      const users = Array.isArray(list) ? list : [];
      setResults(users);
      if (users.length === 1)
        select(platform.resultUid(users[0]), users[0].nickname);
    } catch (e) {
      if (!controller.signal.aborted) setSearchError(errorMessage(e));
    } finally {
      if (request.current === controller && !controller.signal.aborted)
        setSearching(false);
    }
  }

  return (
    <>
      <div ref={root} className={cx("searchbox", className)}>
        <div className={cx("sb-field")}>
          <Icon name="search" size={14} className={cx("sb-icon")}></Icon>
          <input
            value={keyword}
            placeholder={platform.searchPlaceholder}
            title={platform.uidHint}
            className={cx("sb-input")}
            onChange={(event) => {
              setKeyword(event.currentTarget.value);
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter") return;
              onEnter();
            }}
            onFocus={() => {
              results.length && setDropdownOpen(true);
            }}
          ></input>
          <button
            disabled={searching || !keyword.trim()}
            className={cx("btn btn-sm sb-btn")}
            onClick={() => {
              onEnter();
            }}
          >
            {searching ? "搜索中" : "搜索"}
          </button>
        </div>
        {uid ? (
          <span title={"当前目标：" + uid} className={cx("sb-uid")}>
            {uid.length > 18 ? uid.slice(0, 16) + "…" : uid}{" "}
            <button
              title="清除目标用户"
              className={cx("sb-uid-x")}
              onClick={() => {
                clearTarget();
              }}
            >
              <Icon name="x" size={10}></Icon>
            </button>
          </span>
        ) : null}
        {dropdownOpen ? (
          <div className={cx("sb-dropdown card")}>
            {searching ? (
              <div className={cx("sb-note")}>
                <span className={cx("spinner spinner-sm")}></span>
                {"搜索中…"}
              </div>
            ) : searchError ? (
              <div className={cx("sb-note sb-err")}>{searchError}</div>
            ) : !results.length ? (
              <div className={cx("sb-note")}>
                {" 无结果"}
                <span className={cx("sb-hint")}>
                  {"（"}
                  {platform.uidHint}
                  {"）"}
                </span>
              </div>
            ) : null}
            {results.slice(0, 12).map((u, i) => (
              <button
                key={i}
                className={cx("sb-item")}
                onClick={() => {
                  select(platform.resultUid(u), u.nickname);
                }}
              >
                <UserAvatar
                  src={u.avatarUrl}
                  name={u.nickname}
                  size={30}
                  color={platform.color}
                ></UserAvatar>
                <span className={cx("sb-item-main")}>
                  <span className={cx("sb-item-name")}>
                    {u.nickname || "未知用户"}
                  </span>
                  {u.signature ? (
                    <span className={cx("sb-item-sig")}>{u.signature}</span>
                  ) : null}
                </span>
                <span className={cx("sb-item-uid")}>
                  {platform.resultUid(u)}
                </span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </>
  );
}
