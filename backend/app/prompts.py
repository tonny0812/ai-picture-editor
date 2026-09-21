"""提示词模板的变量语法与渲染。

语法：`{{name}}` 必填、`{{name:默认值}}` 选填。

之所以单独抽一个纯函数模块：模板渲染既要给前端做实时预览、又要给后端做提交前
校验，实现必须能两边共用同一套规则（否则会出现"预览是这样、提交变那样"）。
"""

import re

# {{name}} 或 {{name:默认值}}；默认值里不允许出现 } 与 :
_VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*([^{}]*?)\s*)?\}\}")


class MissingVariable(ValueError):
    """必填变量没给值也没有默认值。"""


def extract_variables(template: str) -> list[str]:
    """按出现顺序取出模板里的变量名（去重、保序）。"""
    names: list[str] = []
    for match in _VARIABLE.finditer(template or ""):
        name = match.group(1)
        if name not in names:
            names.append(name)
    return names


def defaults_of(template: str) -> dict[str, str]:
    """取出模板里写在语法上的默认值，没有默认值的变量不出现在结果里。"""
    values: dict[str, str] = {}
    for match in _VARIABLE.finditer(template or ""):
        default = match.group(2)
        if default:
            values[match.group(1)] = default
    return values


def render_template(template: str, values: dict[str, str] | None = None) -> str:
    """渲染模板；必填变量缺失时抛 MissingVariable。

    渲染后会做一次轻量清理：变量留空容易产生连续的逗号与空白，原样丢给网关
     waste 不说，还会稀释有效描述。
    """
    supplied = {key: (value or "").strip() for key, value in (values or {}).items()}
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name, raw_default = match.group(1), match.group(2)
        value = supplied.get(name) or ""
        if not value:
            # 有 {{x:}} 这种"默认值为空"的写法即视为选填；连冒号都没有才是必填
            if raw_default is None:
                missing.append(name)
                return ""
            value = raw_default.strip()
        return value

    rendered = _VARIABLE.sub(replace, template or "")
    if missing:
        raise MissingVariable("还有必填项没写：" + "、".join(missing))
    return tidy(rendered)


def tidy(text: str) -> str:
    """收拾渲染残留：连续逗号、孤立逗号、多余空白。"""
    # 中英文标点都可能是分隔符
    text = re.sub(r"[,，]{2,}", "，", text)
    text = re.sub(r"\s*[,，]\s*(?=\n|$)", "", text)
    text = re.sub(r"(?<!\S)[,，]\s*", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def strip_variables(template: str) -> str:
    """把所有占位符抹掉（用于生成"模板预览"，或把模板降级成普通文本）。"""
    return tidy(_VARIABLE.sub("", template or ""))
