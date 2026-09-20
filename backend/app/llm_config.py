"""LLM 配置的运行时视图。

独立成叶子模块：providers 与 services 都要导入，但不能互相导入
（services 包初始化会拉起依赖 providers 的子模块）。这里只放纯数据
与纯函数，不碰数据库与网络。
"""

import dataclasses
import hashlib
from dataclasses import dataclass

# 规划模型走百炼的 OpenAI 兼容模式；base_url 留空时的兜底前缀
_COMPATIBLE_PATH = "/compatible-mode/v1"

PROVIDERS = ("mock", "dashscope", "openai")


@dataclass(frozen=True)
class ResolvedLlmConfig:
    """三层合并后的最终配置。

    frozen dataclass 本身可哈希，直接作为 provider / planner 缓存的键；
    任一字段变化都会生成新键，旧实例由 LRU 淘汰——配置热生效的关键。
    """

    planner_base_url: str = ""
    planner_api_key: str = ""
    planner_model: str = "qwen-plus"
    planner_timeout: float = 60.0
    planner_max_retries: int = 2
    images_base_url: str = ""
    images_api_key: str = ""
    images_model: str = ""
    images_sizes: str = ""
    image_provider: str = "mock"
    lock_image_provider: bool = False

    @property
    def fingerprint(self) -> str:
        """配置指纹，日志里用它说明当前生效的是哪套配置，不落任何密钥。"""
        raw = repr(tuple(getattr(self, field.name) for field in dataclasses.fields(self)))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def compatible_path() -> str:
    return _COMPATIBLE_PATH


def mask_secret(value: str | None) -> str:
    """密钥打码：只回前后各几个字符，中间用 ••••。空值返回空串。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return f"{value[:4]}••••{value[-2:]}"
