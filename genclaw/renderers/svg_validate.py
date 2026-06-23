"""自由形式 SVG 源码的轻量静态校验(ADR 0005)。

这是 code-as-brush 的第一道关卡:LLM 写裸 ``<svg>`` 源码,我们渲它。SVG
是 markup(渲染时不执行 JS),所以一个静态白名单基本能覆盖主要风险面,无
需完整执行沙箱。

安全债(ADR 0005,刻意延后):这不是一个硬化过的沙箱。它只是「本地、单
机、输入来自可信 LLM provider」场景的尽力静态过滤,而不是匿名公网输入
的防线。它会拦掉明显的 vector(script / 外部引用 / foreignObject / event
handler),但不是安全边界。执行沙箱 ADR 落地之前,不要把这个放到公网上。
"""

# 中文补充说明：
# 策略很简单:三道过滤
#   1) 关键词模式:拦 <script / <foreignObject / javascript: / on*= / DOCTYPE
#      这些是「典型 XSS / XXE」向量,基本能挡掉 99% 的攻击面
#   2) tag 白名单:用 _TAG_RE 把所有 <tag 抠出来,不在 _ALLOWED_TAGS 就拒;
#      留了「SVG filter primitives + 一些文本节点」之类的常见无害元素
#   3) 引用白名单:href / url() 必须是同文档 "#id",不允许 http/file/data
# 这是「filter not sandbox」,所以用 SVG 而不是 HTML:HTML/Three.js 路径
# 必须用渲染时隔离(见 code.py 注释),SVG 这里静态就能拦。

from __future__ import annotations

import re

# 生成出来的 SVG 允许出现的 tag。其它一律拒。
_ALLOWED_TAGS = {
    "svg", "g", "defs", "title", "desc", "style",
    "rect", "circle", "ellipse", "line", "polyline", "polygon", "path",
    "text", "tspan", "textpath",
    "lineargradient", "radialgradient", "stop", "pattern", "clippath", "mask",
    "filter", "fegaussianblur", "feoffset", "feblend", "femerge", "femergenode",
    "fecolormatrix", "fecomposite", "feflood", "use", "symbol", "marker",
    # 更多纯渲染的 SVG filter primitive(无 script,安全)
    "fedropshadow", "femorphology", "fespecularlighting", "fediffuselighting",
    "fepointlight", "fedistantlight", "fespotlight", "feturbulence",
    "fedisplacementmap", "fetile", "feimage", "fecomponenttransfer",
    "fefunca", "fefuncr", "fefuncg", "fefuncb", "feconvolvematrix",
    "lineargradient", "radialgradient", "switch", "metadata", "title", "desc",
    "tspan", "textpath", "lineargradient",
}

# 全文档任何位置出现都拒的子串(大小写不敏感)。覆盖 script 执行、外部
# 资源引用、嵌入外来内容。
_FORBIDDEN_PATTERNS = [
    r"<script",            # 内嵌脚本
    r"<foreignobject",     # 任意嵌入 HTML
    r"<iframe",
    r"<image[\s>]",        # 外部光栅引用(xlink:href 指向网络/文件)
    r"javascript:",        # javascript: URL
    r"\bon\w+\s*=",        # 事件处理器:onload=、onclick=、...
    r"<!entity",           # XML 实体定义(XXE / billion laughs)
    r"<!doctype",          # DOCTYPE(实体 vector)
    r"data:text/html",     # html data URI
]

# href / url() 值收窄:只允许同文档引用("#id")
_HREF_RE = re.compile(r'(?:xlink:href|href)\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)
_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)", re.IGNORECASE)
_TAG_RE = re.compile(r"<\s*([a-zA-Z][\w:-]*)")


class SVGValidationError(ValueError):
    """自由形式 SVG 源码没通过静态校验。"""


def validate_svg(source: str) -> str:
    """校验自由形式 SVG ``source``;通过就原样返回。

    失败时抛 :class:`SVGValidationError`,携带第一个找到的问题。这是静
    态过滤,不是沙箱(见模块 docstring / ADR 0005)。
    """
    if not source or not source.strip():
        raise SVGValidationError("empty SVG source")

    low = source.lower()

    if "<svg" not in low:
        raise SVGValidationError("source does not contain an <svg> root element")

    for pat in _FORBIDDEN_PATTERNS:
        if re.search(pat, low):
            raise SVGValidationError(f"forbidden content matched pattern: {pat!r}")

    # tag 白名单
    for match in _TAG_RE.finditer(low):
        # 剥掉 namespace 前缀(允许形如 "sodipodi:something" 之类)
        tag = match.group(1).split(":")[-1]
        if tag not in _ALLOWED_TAGS:
            raise SVGValidationError(f"disallowed tag: <{tag}>")

    # 引用必须留在文档内(无 http(s)/file/data 等网络拉取)
    for ref in _HREF_RE.findall(source) + _URL_RE.findall(source):
        r = ref.strip()
        if r and not r.startswith("#"):
            raise SVGValidationError(
                f"external reference not allowed: {ref!r} (only in-document '#id' refs)"
            )

    return source
