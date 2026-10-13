"""零依赖的项目根 ``.env`` 自动加载器。

本模块让 ReportVerify 的两条启动路径（Web ``webapi/app.py`` 与命令行
``cli.py``）在读取 ``REPORT_VERIFY_LLM_*`` 运行配置前，先把项目根目录下的
``.env`` 文件加载进 ``os.environ``。它不引入任何第三方依赖（不使用
python-dotenv），只做最小化、安全的 ``KEY=VALUE`` 解析。

安全契约：

- **绝不覆盖**已存在的真实环境变量：只有当某个 KEY 尚未出现在
  ``os.environ`` 时才写入。进程注入的真实凭据永远优先。
- **绝不回显任何 value**：文件缺失时安全返回，解析异常被吞掉，且无论是日志、
  print 还是异常消息都不会包含任何行内容或 value（尤其 API key / user key）。
- 仅解析简单的 ``KEY=VALUE`` 行；忽略空行与以 ``#`` 开头的注释行；去除 key /
  value 的首尾空白与可选的成对引号（``"..."`` 或 ``'...'``）。

本模块不校验变量语义，也不构造 :class:`~report_verify.llm.config.LLMSettings`；
它只负责把 ``.env`` 的键值补进环境，后续由 ``LLMSettings.from_env()`` 解释。
"""
from __future__ import annotations

import os
from pathlib import Path


def _project_root() -> Path:
    """返回 ``report_verify`` 与 ``webapi`` 的共同父目录（项目根）。

    本文件位于 ``<root>/report_verify/env_bootstrap.py``，因此其父目录的父目录
    即为项目根。
    """

    return Path(__file__).resolve().parent.parent


def _strip_optional_quotes(value: str) -> str:
    """去除成对的首尾引号；不成对或无引号时原样返回。"""

    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_line(line: str) -> tuple[str, str] | None:
    """把单行解析为 ``(key, value)``；空行/注释/非法行返回 ``None``。

    该函数绝不抛出，也绝不把行内容写入任何异常或日志。
    """

    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if "=" not in stripped:
        return None
    key, _, raw_value = stripped.partition("=")
    key = key.strip()
    if not key:
        return None
    value = _strip_optional_quotes(raw_value.strip())
    return key, value


def load_project_env(dotenv_path: str | os.PathLike[str] | None = None) -> None:
    """把项目根 ``.env`` 中尚未设置的键补入 ``os.environ``。

    参数:
        dotenv_path: 可选的显式 ``.env`` 路径（主要用于测试）。缺省时定位项目
            根目录下的 ``.env``。

    行为:
        - 文件不存在时安全返回，不抛异常。
        - 逐行解析 ``KEY=VALUE``，忽略空行与 ``#`` 注释，去首尾空白与成对引号。
        - 仅当 KEY 尚未存在于 ``os.environ`` 时写入（不覆盖真实环境变量）。
        - 任何读取/解析异常都被吞掉，且不打印或记录任何 value。
    """

    try:
        path = Path(dotenv_path) if dotenv_path is not None else _project_root() / ".env"
        if not path.is_file():
            return
        # 用宽松的错误处理读取，避免个别字节问题触发异常回显文件内容。
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            parsed = _parse_line(line)
            if parsed is None:
                continue
            key, value = parsed
            # 已存在的真实环境变量优先，绝不覆盖。
            if key not in os.environ:
                os.environ[key] = value
    except Exception:
        # 安全吞掉任何异常：绝不让 .env 加载影响启动，也绝不回显 value。
        return
