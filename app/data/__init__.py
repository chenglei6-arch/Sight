"""
数据持久化模块

使用 SQLite 存储用户数据快照，支持：
- 保存/读取历史快照
- 按时间范围查询
- 数据变化对比
"""
from app.data.store import DataStore
