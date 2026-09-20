"""密钥加密存储。

数据库只存 Fernet 密文；明文只在构建 planner / provider 时短暂出现，
绝不进入 API 响应、日志或队列载荷。加密密钥优先取 SETTINGS_ENCRYPTION_KEY，
未配置时从 JWT_SECRET 派生（自用可接受，生产建议独立密钥）。
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _instance() -> Fernet:
    global _fernet
    if _fernet is None:
        settings = get_settings()
        if settings.settings_encryption_key:
            key = settings.settings_encryption_key.encode()
        else:
            derived = hashlib.sha256(settings.jwt_secret.encode()).digest()
            key = base64.urlsafe_b64encode(derived)
            logger.warning(
                "SETTINGS_ENCRYPTION_KEY 未配置，加密密钥已从 JWT_SECRET 派生；"
                "换 JWT_SECRET 会导致已存密钥全部无法解密，生产环境请配置独立密钥"
            )
        _fernet = Fernet(key)
    return _fernet


def encrypt_secret(value: str | None) -> str | None:
    """空值原样返回 None（表示「不覆盖」），非空加密为密文。"""
    if not value:
        return None
    return _instance().encrypt(value.encode()).decode()


def decrypt_secret(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _instance().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "密钥解密失败：加密密钥与写入时不一致（检查 SETTINGS_ENCRYPTION_KEY / JWT_SECRET）"
        ) from exc
