import { Fragment, useEffect, useRef, useState } from "react";
import { errorMessage } from "../api";
import { classNames } from "../classes";
import { PLATFORM_MAP } from "../platforms";
import {
  clearPlatformCache,
  loadPlatform,
  openQrLogin,
  useAppStore,
} from "../store";
import type { PlatformId } from "../types";
import ContentGrid from "./ContentGrid";
import BilibiliArchives from "./BilibiliArchives";
import EventSection from "./EventSection";
import ProfileCard from "./ProfileCard";
import RecordSection from "./RecordSection";
import SearchBox from "./SearchBox";
import SocialSection from "./SocialSection";
import Icon from "./ui/Icon";
import styles from "./ViewPlatform.module.css";
const cx = classNames(styles);

export default function ViewPlatform({
  platformId,
}: {
  platformId: PlatformId;
}) {
  const d = useAppStore((s) => s.data[platformId]),
    uid = useAppStore((s) => s.uids[platformId]);
  const state = { view: platformId },
    platform = PLATFORM_MAP[platformId];
  const isInitialLoading = d.loading && !d.loaded,
    hasFailed = !!d.error && !d.loaded,
    partialWarnings = d.loaded ? d.errors : [];
  const [clearing, setClearing] = useState(false),
    [clearMsg, setClearMsg] = useState(""),
    [clearIsError, setClearIsError] = useState(false);
  const alive = useRef(true),
    timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
    };
  }, []);
  async function clearCache() {
    if (clearing) return;
    setClearing(true);
    setClearMsg("");
    try {
      const stats = await clearPlatformCache(platformId);
      if (!alive.current) return;
      const parts = [];
      if (stats.adapters_dropped)
        parts.push(`适配器缓存 ×${stats.adapters_dropped}`);
      for (const [name, n] of Object.entries(stats.cleared || {})) {
        if (n) parts.push(`${name} ${n} 条`);
      }
      if (stats.search_cache_cleared)
        parts.push(`搜索缓存 ${stats.search_cache_cleared} 条`);
      setClearMsg(
        parts.length
          ? `已清理：${parts.join("、")}，数据已重新拉取`
          : "缓存已清理，数据已重新拉取",
      );
      setClearIsError(false);
    } catch (e) {
      if (alive.current) {
        setClearMsg("清理失败：" + errorMessage(e));
        setClearIsError(true);
      }
    } finally {
      if (alive.current) {
        setClearing(false);
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setClearMsg(""), 6000);
      }
    }
  }
  const sectionIcon: Record<string, string> = {
    playlist: "grid",
    video: "play",
    work: "play",
    post: "edit",
    character: "user",
  };

  return (
    <>
      <div className={cx("content-narrow")}>
        {!uid ? (
          <div className={cx("empty-state card setup-card")}>
            <span className={cx("empty-icon")}>
              <Icon name="user" size={34}></Icon>
            </span>
            <div className={cx("empty-title")}>
              {"设置 "}
              {platform.name}
              {" 目标用户"}
            </div>
            <div className={cx("setup-hint")}>{platform.uidHint}</div>
            <SearchBox
              platformId={state.view}
              className={cx("setup-search")}
            ></SearchBox>
          </div>
        ) : isInitialLoading ? (
          <div className={cx("page-loading")}>
            <span className={cx("spinner")}></span>
            {" 正在加载 "}
            {platform.name}
            {" 数据，首次可能需要十几秒… "}
          </div>
        ) : hasFailed ? (
          <div className={cx("card error-card")}>
            <span className={cx("empty-icon")}>
              <Icon name="alert" size={32}></Icon>
            </span>
            <div className={cx("empty-title")}>{"数据加载失败"}</div>
            <div className={cx("error-msg")}>{d.error}</div>
            <div className={cx("error-hint")}>
              {"可能触发了平台反爬限制，稍后重试通常可以恢复"}
            </div>
            <button
              className={cx("btn btn-primary")}
              onClick={() => {
                loadPlatform(state.view, { force: true });
              }}
            >
              <Icon name="refresh" size={13}></Icon>
              {" 重试 "}
            </button>
          </div>
        ) : (
          <Fragment>
            <div className={cx("view-head")}>
              <SearchBox platformId={state.view}></SearchBox>
              <div className={cx("head-actions")}>
                {platform.hasQrLogin ? (
                  <button
                    title="扫码登录后可查看登录账号的关注列表"
                    className={cx("btn")}
                    onClick={() => {
                      openQrLogin();
                    }}
                  >
                    <Icon name="scan" size={13}></Icon>
                    {" 扫码查关注 "}
                  </button>
                ) : null}
                <button
                  disabled={clearing}
                  title="清空该平台的内存缓存（适配器缓存、关系图搜索缓存）并绕过快照强制重新拉取数据"
                  className={cx("btn")}
                  onClick={() => {
                    clearCache();
                  }}
                >
                  {clearing ? (
                    <span className={cx("spinner spinner-sm")}></span>
                  ) : (
                    <Icon name="trash" size={13}></Icon>
                  )}
                  {clearing ? "清理中" : "清理缓存"}
                </button>
              </div>
            </div>
            {clearMsg ? (
              <p className={cx("clear-msg", { "clear-msg-err": clearIsError })}>
                {clearMsg}
              </p>
            ) : null}
            {partialWarnings.length ? (
              <div className={cx("banner banner-warn")}>
                <Icon
                  name="alert"
                  size={15}
                  style={{ flexShrink: "0", marginTop: "1px" }}
                ></Icon>
                <div>
                  {" 部分模块加载失败，已展示可用数据： "}
                  {partialWarnings.map((e, i) => (
                    <div key={i} className={cx("warn-line")}>
                      {e}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            {d.profile ? (
              <ProfileCard
                platformId={state.view}
                profile={d.profile}
              ></ProfileCard>
            ) : null}
            <div className={cx("section-title")}>
              <Icon
                name={sectionIcon[platform.contentKind] || "grid"}
                size={15}
              ></Icon>{" "}
              {platform.contentLabel}{" "}
              <span className={cx("count")}>
                {"("}
                {d.playlists.length}
                {")"}
              </span>
            </div>
            <ContentGrid
              platformId={state.view}
              items={d.playlists}
            ></ContentGrid>
            {platform.hasRecords && d.records ? (
              <Fragment>
                <div className={cx("section-title")}>
                  <Icon name="chart" size={15}></Icon>
                  {" 听歌排行 "}
                </div>
                <RecordSection records={d.records}></RecordSection>
                {!(d.records.allTime || []).length &&
                !(d.records.weekly || []).length ? (
                  <div className={cx("empty-inline")}>
                    {" 暂无听歌数据（需要该用户的网易云凭证） "}
                  </div>
                ) : null}
              </Fragment>
            ) : null}
            {platform.hasEvents ? (
              <Fragment>
                <div className={cx("section-title")}>
                  <Icon name="activity" size={15}></Icon>
                  {" 最近动态 "}
                  <span className={cx("count")}>
                    {"("}
                    {d.events.length}
                    {")"}
                  </span>
                </div>
                {d.events.length ? (
                  <EventSection events={d.events}></EventSection>
                ) : (
                  <div className={cx("empty-inline")}>{"暂无动态"}</div>
                )}
              </Fragment>
            ) : null}
            {platform.hasSocial ? (
              <Fragment>
                <div className={cx("section-title")}>
                  <Icon name="users" size={15}></Icon>
                  {" 社交关系 "}
                </div>
                <SocialSection
                  platformId={state.view}
                  profile={d.profile}
                  follows={d.follows}
                  followers={d.followers}
                ></SocialSection>
              </Fragment>
            ) : null}
          </Fragment>
        )}
        {platformId === "bilibili" && uid ? (
          <BilibiliArchives key={uid} uid={uid} />
        ) : null}
      </div>
    </>
  );
}
