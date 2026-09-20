from functools import lru_cache

from langchain_core.utils.function_calling import convert_to_openai_function
from langchain_openai import ChatOpenAI

from app.llm_config import ResolvedLlmConfig
from app.tools import SPECS, ToolSpec


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


@lru_cache(maxsize=16)
def get_planner(config: ResolvedLlmConfig):
    """绑定全部已注册工具的规划模型，以配置为缓存键。

    配置热生效的关键：页面改配置 → resolve 产生新 ResolvedLlmConfig →
    本函数缓存未命中 → 按新配置实例化。base_url / key 的兜底链已在
    配置解析层（services/llm_config._finalize）完成。
    """
    if not config.planner_api_key:
        raise PlannerUnavailable("未配置规划模型 API Key，对话指令不可用")

    model = ChatOpenAI(
        model=config.planner_model,
        api_key=config.planner_api_key,
        base_url=config.planner_base_url,
        temperature=0,
        timeout=config.planner_timeout,
        max_retries=config.planner_max_retries,
    )
    return model.bind_tools([_schema_of(spec) for spec in SPECS])
