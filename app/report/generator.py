"""
报告生成器

从 DataStore 读取历史快照，生成各类数据报告。
"""
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.data.store import DataStore

CST = timezone(timedelta(hours=8))


class ReportGenerator:
    """数据报告生成器"""

    def __init__(self, store: DataStore = None):
        self.store = store or DataStore()

    # ==================== 用户概览报告 ====================

    def user_overview(self, platform: str, uid: str) -> dict:
        """
        生成用户概览报告（最新状态 + 简要变化）

        Returns:
            {
                platform, uid,
                profile: {...},          # 最新资料
                content_lists: [...],    # 内容列表
                history_top5: [...],     # 历史排行 Top5
                recent_changes: [...]    # 最近变化
            }
        """
        profile = self.store.get_latest_snapshot(platform, uid, "profile")
        playlists = self.store.get_latest_snapshot(platform, uid, "playlists")
        records = self.store.get_latest_snapshot(platform, uid, "records")

        report = {
            "platform": platform,
            "uid": uid,
            "generated_at": datetime.now(CST).isoformat(),
            "profile": profile,
            "content_lists_count": len(playlists) if playlists else 0,
            "records_all_count": (
                len(records.get("allTime", [])) if records else 0
            ),
            "records_week_count": (
                len(records.get("weekly", [])) if records else 0
            ),
        }

        # 最近变化
        changes = self.store.compare_snapshots(platform, uid, "profile")
        report["profile_changes"] = changes

        return report

    # ==================== 变化趋势报告 ====================

    def trend_report(
        self,
        platform: str,
        uid: str,
        data_type: str,
        since: str = None,
    ) -> dict:
        """
        生成趋势报告 - 展示某类数据随时间的数值变化

        Args:
            platform: 平台
            uid: 用户 ID
            data_type: 数据类型
            since: 起始时间（ISO 字符串）

        Returns:
            {
                platform, uid, data_type,
                snapshots: [{time, values}, ...],
                trend_summary: {...}
            }
        """
        snapshots = self.store.get_snapshots(
            platform, uid, data_type, since=since, limit=200
        )

        if not snapshots:
            return {
                "platform": platform,
                "uid": uid,
                "data_type": data_type,
                "has_data": False,
            }

        # 提取关键数值字段的时间序列
        numeric_keys = self._extract_numeric_keys(snapshots[0])
        time_series = {k: [] for k in numeric_keys}

        for snap in reversed(snapshots):  # 从旧到新
            t = snap.get("_snapshot_time", "")
            for key in numeric_keys:
                val = self._get_nested(snap, key)
                time_series[key].append({"time": t, "value": val})

        # 计算变化概要
        trend_summary = {}
        for key, series in time_series.items():
            if len(series) >= 2:
                first_val = series[0]["value"]
                last_val = series[-1]["value"]
                if isinstance(first_val, (int, float)) and isinstance(last_val, (int, float)):
                    diff = last_val - first_val
                    trend_summary[key] = {
                        "first": first_val,
                        "last": last_val,
                        "diff": diff,
                        "direction": "up" if diff > 0 else ("down" if diff < 0 else "stable"),
                    }

        return {
            "platform": platform,
            "uid": uid,
            "data_type": data_type,
            "has_data": True,
            "snapshots_count": len(snapshots),
            "time_series": time_series,
            "trend_summary": trend_summary,
        }

    # ==================== 全平台汇总报告 ====================

    def cross_platform_report(self, uid_map: dict[str, str]) -> dict:
        """
        跨平台汇总报告

        Args:
            uid_map: {platform_id: uid} 映射

        Returns:
            各平台用户关键指标对比
        """
        platforms_summary = {}
        for platform, uid in uid_map.items():
            profile = self.store.get_latest_snapshot(platform, uid, "profile")
            if profile:
                platforms_summary[platform] = {
                    "nickname": profile.get("nickname", ""),
                    "followers": profile.get("extra", {}).get("followeds", 0) or profile.get("extra", {}).get("follower_count", 0),
                    "following": profile.get("extra", {}).get("follows", 0) or profile.get("extra", {}).get("following_count", 0),
                    "content_count": profile.get("extra", {}).get("playlistCount", 0) or profile.get("extra", {}).get("video_count", 0),
                    "is_vip": profile.get("is_vip", False),
                    "level": profile.get("level", 0),
                    "snapshot_time": profile.get("_snapshot_time", ""),
                }

        return {
            "generated_at": datetime.now(CST).isoformat(),
            "platforms": platforms_summary,
        }

    # ==================== 辅助方法 ====================

    @staticmethod
    def _extract_numeric_keys(data: dict, prefix: str = "") -> set:
        """递归提取所有数值型字段的路径"""
        keys = set()
        for k, v in data.items():
            if k.startswith("_"):
                continue
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                keys.add(full)
            elif isinstance(v, dict):
                keys.update(ReportGenerator._extract_numeric_keys(v, full))
        return keys

    @staticmethod
    def _get_nested(data: dict, path: str):
        """按路径获取嵌套字典的值"""
        keys = path.split(".")
        val = data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return None
        return val
