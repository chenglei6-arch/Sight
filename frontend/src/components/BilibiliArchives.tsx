import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import type { ActivityEvent } from "../types";
import { fmtEventTime } from "../utils";
import EventSection from "./EventSection";
import styles from "./BilibiliArchives.module.css";

type ArchiveSource = "aicu_reply" | "aicu_danmaku" | "danmakus";
interface ArchivePage {
  source_name: string;
  source_url: string;
  page: number;
  total: number;
  total_unit: string;
  has_more: boolean;
  truncated: boolean;
  events: ActivityEvent[];
  cached: boolean;
  fetched_at: number;
  notice: string;
}

export default function BilibiliArchives({ uid }: { uid: string }) {
  const [source, setSource] = useState<ArchiveSource>("aicu_reply");
  const [result, setResult] = useState<ArchivePage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  async function load(page = 1) {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const data = await api.get<ArchivePage>(
        "/bilibili/archives",
        { uid, source, page, page_size: 20 },
        current.signal,
      );
      if (!current.signal.aborted) setResult(data);
    } catch (e) {
      if (!current.signal.aborted) setError(errorMessage(e));
    } finally {
      if (!current.signal.aborted) setLoading(false);
    }
  }

  return (
    <section className={styles.section} aria-label="评论与弹幕存档">
      <h3 className={styles.title}>评论与弹幕存档</h3>
      <p className={styles.hint}>
        按需查询 Aicu / Danmakus 的第三方存档，数据可能延迟或缺失。
      </p>
      <div className={styles.controls}>
        <label className={styles.label}>
          数据来源
          <select
            className={styles.select}
            value={source}
            onChange={(event) => {
              controller.current?.abort();
              setSource(event.target.value as ArchiveSource);
              setResult(null);
              setError("");
              setLoading(false);
            }}
          >
            <option value="aicu_reply">Aicu · 评论</option>
            <option value="aicu_danmaku">Aicu · 视频弹幕</option>
            <option value="danmakus">Danmakus · 直播弹幕与互动</option>
          </select>
        </label>
        <button className="btn btn-primary" disabled={loading} onClick={() => load()}>
          {loading ? "查询中…" : "查询存档"}
        </button>
        <a href={`https://www.aicu.cc/reply?uid=${encodeURIComponent(uid)}`} target="_blank" rel="noopener noreferrer">
          Aicu 原站
        </a>
        <a href={`https://danmakus.com/user/${encodeURIComponent(uid)}`} target="_blank" rel="noopener noreferrer">
          Danmakus 原站
        </a>
      </div>
      <div aria-live="polite" aria-busy={loading}>
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
        {result ? (
          <>
            <div className={styles.summary}>
              <span>
                {result.source_name} · 第 {result.page} 页 · 本页 {result.events.length} 条
                {result.total >= 0 ? ` · 上游共 ${result.total} ${result.total_unit}` : ""}
              </span>
              <span>{result.cached ? "缓存" : "获取"}于 {fmtEventTime(result.fetched_at)}</span>
            </div>
            {result.events.length ? (
              <EventSection key={`${source}:${result.page}`} events={result.events} showLinks />
            ) : (
              <p className={styles.hint}>该页暂无存档记录，不能据此判断用户是否有相关活动。</p>
            )}
            {result.truncated ? (
              <p className={styles.hint}>本页记录较多，仅展示最新 500 条，可前往原站查看。</p>
            ) : null}
            <div className={styles.pagination}>
              <button className="btn" disabled={loading || result.page <= 1} onClick={() => load(result.page - 1)}>上一页</button>
              <span>第 {result.page} 页</span>
              <button className="btn" disabled={loading || !result.has_more} onClick={() => load(result.page + 1)}>下一页</button>
              <a href={result.source_url} target="_blank" rel="noopener noreferrer">查看来源</a>
            </div>
            <p className={styles.hint}>{result.notice}</p>
          </>
        ) : null}
      </div>
    </section>
  );
}
