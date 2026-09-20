from functools import lru_cache

from app.llm_config import ResolvedLlmConfig
from app.providers.base import EditRequest, GenerateRequest, ImageProvider, ProviderError
from app.providers.mock import MockImageProvider


@lru_cache(maxsize=32)
def get_image_provider(config: ResolvedLlmConfig) -> ImageProvider:
    """按解析后的配置选择实现，以配置本身为缓存键。

    配置任一字段变化都会生成新实例——这就是「页面改配置、免重启生效」
    的机制。旧实例由 LRU 淘汰，其 httpx 连接随 GC 关闭。
    新增平台只需在此登记，调用方无需改动。
    """
    name = config.image_provider

    if name == "mock":
        return MockImageProvider()
    if name == "dashscope":
        from app.providers.dashscope import DashScopeImageProvider

        return DashScopeImageProvider()
    if name == "openai":
        from app.providers.openai_images import OpenAIImagesProvider

        return OpenAIImagesProvider(config)

    raise ProviderError(f"未知的 image_provider：{name}")


__all__ = [
    "EditRequest",
    "GenerateRequest",
    "ImageProvider",
    "ProviderError",
    "get_image_provider",
]
