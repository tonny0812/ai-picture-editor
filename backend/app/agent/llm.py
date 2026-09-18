from functools import lru_cache

from langchain_core.utils.function_calling import convert_to_openai_function
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.tools import SPECS, ToolSpec

# 图像模型必须走 DashScope 原生接口，纯文本的规划模型可用 OpenAI 兼容模式
_COMPATIBLE_PATH = "/compatible-mode/v1"


class PlannerUnavailable(Exception):
    """规划模型未配置或不可用。"""


def _schema_of(spec: ToolSpec) -> dict:
    function = convert_to_openai_function(spec.params)
    function["name"] = spec.name
    function["description"] = spec.description

    parameters = function.get("parameters", {})
    for hidden in spec.agent_hidden:
        parameters.get("properties", {}).pop(hidden, None)
    parameters["required"] = [
        name for name in parameters.get("required", []) if name not in spec.agent_hidden
    ]
    return {"type": "function", "function": function}


@lru_cache
def planner():
    """绑定全部已注册工具的规划模型。工具增减无需改动此处。

    base_url 支持任意 OpenAI 兼容网关：配置 PLANNER_BASE_URL 后原样使用
    （需自带 /v1 前缀），否则回退百炼的 compatible-mode 路径。
    API key 同理：PLANNER_API_KEY 优先，缺失再退回 DASHSCOPE_API_KEY。
    """
    settings = get_settings()
    api_key = settings.planner_api_key or settings.dashscope_api_key
    if not api_key:
        raise PlannerUnavailable(
            "未配置 PLANNER_API_KEY / DASHSCOPE_API_KEY，对话指令不可用"
        )

    base_url = settings.planner_base_url or (
        f"{settings.dashscope_base_url}{_COMPATIBLE_PATH}"
    )

    model = ChatOpenAI(
        model=settings.planner_model,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        timeout=settings.planner_timeout,
        max_retries=settings.planner_max_retries,
    )
    return model.bind_tools([_schema_of(spec) for spec in SPECS])
