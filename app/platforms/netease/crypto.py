"""
网易云音乐 /weapi/ 接口加密模块

实现双层 AES-128-CBC 加密 + RSA 密钥加密，
完全模拟网易云前端 JavaScript 的加密逻辑。
"""
import base64
import binascii
import json
import random

from Crypto.Cipher import AES

# ==================== 常量（来自网易云 JS） ====================

FIXED_KEY = "0CoJUm6Qyw8W8jud"   # AES 第一层固定密钥
IV = "0102030405060708"            # AES 固定 IV

RSA_EXPONENT = "010001"            # RSA 公钥指数
RSA_MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725"
    "152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312"
    "ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424"
    "d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
)


def _pad(text: str) -> str:
    """PKCS7 填充"""
    pad_len = 16 - len(text) % 16
    return text + chr(pad_len) * pad_len


def aes_encrypt(text: str, key: str, iv: str = IV) -> str:
    """
    AES-128-CBC 加密

    Args:
        text: 明文字符串
        key: 16 字节密钥
        iv: 16 字节初始向量

    Returns:
        Base64 编码的密文
    """
    padded = _pad(text)
    cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))
    encrypted = cipher.encrypt(padded.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def rsa_encrypt(text: str) -> str:
    """
    RSA 加密（模拟网易云 JS 实现）

    步骤：反转字符串 → 转十六进制 → 大数幂模运算

    Args:
        text: 要加密的文本（16 位随机密钥）

    Returns:
        256 字符的十六进制字符串
    """
    reversed_text = text[::-1]
    hex_str = binascii.hexlify(reversed_text.encode("utf-8")).decode("utf-8")
    num = int(hex_str, 16)
    result = pow(num, int(RSA_EXPONENT, 16), int(RSA_MODULUS, 16))
    return format(result, "x").zfill(256)


def encrypt_request(data: dict) -> dict:
    """
    生成 weapi 请求所需的加密参数

    加密流程：
    1. JSON 序列化请求数据
    2. 第一层 AES 加密（固定密钥 FIXED_KEY）
    3. 生成随机 16 字符密钥
    4. 第二层 AES 加密（随机密钥）
    5. RSA 加密随机密钥 → encSecKey

    Args:
        data: 请求参数字典

    Returns:
        {"params": "...", "encSecKey": "..."}
    """
    json_text = json.dumps(data, separators=(",", ":"))

    # 生成第二层随机密钥
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    sec_key = "".join(random.choices(chars, k=16))

    # 双层 AES 加密
    first_pass = aes_encrypt(json_text, FIXED_KEY)
    second_pass = aes_encrypt(first_pass, sec_key)

    # RSA 加密随机密钥
    enc_sec_key = rsa_encrypt(sec_key)

    return {
        "params": second_pass,
        "encSecKey": enc_sec_key,
    }
