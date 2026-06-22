# -*- coding: utf-8 -*-
"""
纯 Python a_bogus 生成器 - 生产版本

集成到 utils/request.py 使用
"""
import json
import random
from pathlib import Path

# 全局加载映射表（只加载一次）
_ROOT = Path(__file__).parent / "data"
_MAPPING_FILE_FULL = _ROOT / "time_mapping_full.json"
_MAPPING_FILE_SAMPLE = _ROOT / "time_mapping_sample.json"
_TIME_MAP = None
_SORTED_TIMES = None
_KEYSTREAM = None

def _load_data():
    """懒加载数据"""
    global _TIME_MAP, _SORTED_TIMES, _KEYSTREAM

    if _TIME_MAP is None:
        # 优先使用完整映射表，不存在则用示例表
        if _MAPPING_FILE_FULL.exists():
            mapping_file = _MAPPING_FILE_FULL
        elif _MAPPING_FILE_SAMPLE.exists():
            mapping_file = _MAPPING_FILE_SAMPLE
            print("[WARNING] 使用示例映射表（100样本），覆盖有限。运行 lib/reverse/incremental_build.py 扩展。")
        else:
            raise FileNotFoundError(
                "映射表文件不存在！\n"
                "请运行: python lib/reverse/incremental_build.py 生成映射表"
            )

        TIME_MAP = json.load(open(mapping_file))
        _TIME_MAP = {int(k): v for k, v in TIME_MAP.items()}
        _SORTED_TIMES = sorted(_TIME_MAP.keys())

        # 加载 keystream
        keystream_file = _ROOT / "FIXED_keystream.json"
        _KEYSTREAM = json.load(open(keystream_file))['bb_keystream']

# s4 编码表
S4_TABLE = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"


def lookup_bb(timestamp):
    """查表获取 bb（最近邻插值）"""
    _load_data()

    if timestamp in _TIME_MAP:
        return _TIME_MAP[timestamp]

    # 超出范围，用边界值
    if timestamp < _SORTED_TIMES[0]:
        return _TIME_MAP[_SORTED_TIMES[0]]
    if timestamp > _SORTED_TIMES[-1]:
        return _TIME_MAP[_SORTED_TIMES[-1]]

    # 二分查找最近的
    left, right = 0, len(_SORTED_TIMES) - 1
    while right - left > 1:
        mid = (left + right) // 2
        if _SORTED_TIMES[mid] < timestamp:
            left = mid
        else:
            right = mid

    t1, t2 = _SORTED_TIMES[left], _SORTED_TIMES[right]
    closer = t1 if abs(timestamp - t1) < abs(timestamp - t2) else t2
    return _TIME_MAP[closer]


def s4_encode(data):
    """s4 base64 编码"""
    result = []
    i = 0
    while i < len(data):
        if i + 2 < len(data):
            b1, b2, b3 = data[i], data[i+1], data[i+2]
            result.append(S4_TABLE[(b1 >> 2) & 0x3f])
            result.append(S4_TABLE[((b1 << 4) | (b2 >> 4)) & 0x3f])
            result.append(S4_TABLE[((b2 << 2) | (b3 >> 6)) & 0x3f])
            result.append(S4_TABLE[b3 & 0x3f])
            i += 3
        elif i + 1 < len(data):
            b1, b2 = data[i], data[i+1]
            result.append(S4_TABLE[(b1 >> 2) & 0x3f])
            result.append(S4_TABLE[((b1 << 4) | (b2 >> 4)) & 0x3f])
            result.append(S4_TABLE[(b2 << 2) & 0x3f])
            i += 2
        else:
            b1 = data[i]
            result.append(S4_TABLE[(b1 >> 2) & 0x3f])
            result.append(S4_TABLE[(b1 << 4) & 0x3f])
            i += 1
    return ''.join(result)


def generate_abogus(url, timestamp):
    """
    纯 Python 生成 a_bogus

    Args:
        url: 完整 URL
        timestamp: 毫秒时间戳

    Returns:
        192 长度的 a_bogus 字符串
    """
    _load_data()

    # 1. 查表获取 bb
    bb = bytearray(lookup_bb(timestamp))

    # 2. XOR keystream
    encrypted = bytearray(len(bb))
    for i in range(len(bb)):
        encrypted[i] = bb[i] ^ _KEYSTREAM[i % len(_KEYSTREAM)]

    # 3. 添加随机头（4 字节）
    random_head = bytearray([random.randint(0, 255) for _ in range(4)])
    final = random_head + encrypted

    # 4. s4 编码
    return s4_encode(final)
