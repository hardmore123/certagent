"""零依赖 ``.env`` 自动加载器 :func:`load_project_env` 的单元测试。

这些测试只使用占位值和临时目录；不读取、不复制、不打印任何真实密钥，也不
访问项目根真实 ``.env`` 的内容。每个用例都在隔离的 ``os.environ`` 副本上运行，
避免污染其它测试。
"""
from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from report_verify.env_bootstrap import load_project_env

# 占位值，仅用于断言解析/覆盖行为；不是任何真实密钥。
_PLACEHOLDER_API_KEY = "PLACEHOLDER-API-KEY-DO-NOT-USE"
_PLACEHOLDER_USER_KEY = "PLACEHOLDER-USER-KEY-DO-NOT-USE"


def _write_env(directory: str, content: str) -> str:
    path = Path(directory) / ".env"
    path.write_text(content, encoding="utf-8")
    return str(path)


class ParseTests(unittest.TestCase):
    def test_parses_simple_key_value_pairs(self):
        with TemporaryDirectory() as tmp:
            env_path = _write_env(tmp, (
                "REPORT_VERIFY_LLM_MODE=candidate\n"
                f"REPORT_VERIFY_LLM_API_KEY={_PLACEHOLDER_API_KEY}\n"
                "REPORT_VERIFY_LLM_MODEL=configured-model\n"
            ))
            with mock.patch.dict(os.environ, {}, clear=True):
                load_project_env(env_path)
                self.assertEqual(os.environ["REPORT_VERIFY_LLM_MODE"], "candidate")
                self.assertEqual(
                    os.environ["REPORT_VERIFY_LLM_API_KEY"], _PLACEHOLDER_API_KEY
                )
                self.assertEqual(
                    os.environ["REPORT_VERIFY_LLM_MODEL"], "configured-model"
                )

    def test_ignores_comments_and_blank_lines(self):
        with TemporaryDirectory() as tmp:
            env_path = _write_env(tmp, (
                "# 这是注释，不应被解析\n"
                "\n"
                "   \n"
                "  # 带前导空白的注释\n"
                "REPORT_VERIFY_LLM_MODE=explain\n"
            ))
            with mock.patch.dict(os.environ, {}, clear=True):
                load_project_env(env_path)
                self.assertEqual(os.environ.get("REPORT_VERIFY_LLM_MODE"), "explain")
                # 注释里的 '#' 内容不应产生任何键。
                self.assertNotIn("# 这是注释，不应被解析", os.environ)

    def test_strips_whitespace_and_paired_quotes(self):
        with TemporaryDirectory() as tmp:
            env_path = _write_env(tmp, (
                '  REPORT_VERIFY_LLM_MODEL  =  "quoted-model"  \n'
                "REPORT_VERIFY_LLM_BASE_URL='https://approved.example/v1'\n"
                "REPORT_VERIFY_LLM_USER_KEY=\"unpaired-quote\n"
            ))
            with mock.patch.dict(os.environ, {}, clear=True):
                load_project_env(env_path)
                self.assertEqual(
                    os.environ["REPORT_VERIFY_LLM_MODEL"], "quoted-model"
                )
                self.assertEqual(
                    os.environ["REPORT_VERIFY_LLM_BASE_URL"],
                    "https://approved.example/v1",
                )
                # 不成对的引号原样保留（不误删）。
                self.assertEqual(
                    os.environ["REPORT_VERIFY_LLM_USER_KEY"], '"unpaired-quote'
                )

    def test_value_containing_equals_is_preserved(self):
        with TemporaryDirectory() as tmp:
            env_path = _write_env(
                tmp, "REPORT_VERIFY_LLM_BASE_URL=https://h/v1?a=b&c=d\n"
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                load_project_env(env_path)
                self.assertEqual(
                    os.environ["REPORT_VERIFY_LLM_BASE_URL"],
                    "https://h/v1?a=b&c=d",
                )

    def test_line_without_equals_is_ignored(self):
        with TemporaryDirectory() as tmp:
            env_path = _write_env(tmp, (
                "THIS_LINE_HAS_NO_EQUALS\n"
                "REPORT_VERIFY_LLM_MODE=candidate\n"
            ))
            with mock.patch.dict(os.environ, {}, clear=True):
                load_project_env(env_path)
                self.assertNotIn("THIS_LINE_HAS_NO_EQUALS", os.environ)
                self.assertEqual(os.environ["REPORT_VERIFY_LLM_MODE"], "candidate")


class NoOverrideTests(unittest.TestCase):
    def test_existing_environment_variables_are_not_overridden(self):
        with TemporaryDirectory() as tmp:
            env_path = _write_env(tmp, (
                f"REPORT_VERIFY_LLM_API_KEY={_PLACEHOLDER_API_KEY}\n"
                "REPORT_VERIFY_LLM_MODE=candidate\n"
            ))
            preexisting = {
                "REPORT_VERIFY_LLM_API_KEY": "REAL-ENV-WINS",
            }
            with mock.patch.dict(os.environ, preexisting, clear=True):
                load_project_env(env_path)
                # 已存在的真实环境变量优先，绝不覆盖。
                self.assertEqual(
                    os.environ["REPORT_VERIFY_LLM_API_KEY"], "REAL-ENV-WINS"
                )
                # 未存在的 KEY 才写入。
                self.assertEqual(os.environ["REPORT_VERIFY_LLM_MODE"], "candidate")

    def test_empty_string_env_var_is_still_treated_as_present(self):
        with TemporaryDirectory() as tmp:
            env_path = _write_env(tmp, f"REPORT_VERIFY_LLM_MODEL={_PLACEHOLDER_USER_KEY}\n")
            with mock.patch.dict(
                os.environ, {"REPORT_VERIFY_LLM_MODEL": ""}, clear=True
            ):
                load_project_env(env_path)
                # 键已存在（即便空串）就不覆盖。
                self.assertEqual(os.environ["REPORT_VERIFY_LLM_MODEL"], "")


class MissingFileTests(unittest.TestCase):
    def test_missing_file_returns_safely(self):
        with TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "does-not-exist.env")
            with mock.patch.dict(os.environ, {}, clear=True):
                # 不应抛异常，也不应写入任何键。
                load_project_env(missing)
                self.assertEqual(dict(os.environ), {})

    def test_directory_path_returns_safely(self):
        with TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=True):
                # 目录不是普通文件：安全返回。
                load_project_env(tmp)
                self.assertEqual(dict(os.environ), {})

    def test_default_project_root_discovery_does_not_raise(self):
        # 不传路径时应定位项目根 .env；无论存在与否都不得抛异常。
        with mock.patch.dict(os.environ, dict(os.environ), clear=False):
            load_project_env()


class NoLeakTests(unittest.TestCase):
    def test_no_value_is_printed_or_logged(self):
        with TemporaryDirectory() as tmp:
            env_path = _write_env(tmp, (
                f"REPORT_VERIFY_LLM_API_KEY={_PLACEHOLDER_API_KEY}\n"
                f"REPORT_VERIFY_LLM_USER_KEY={_PLACEHOLDER_USER_KEY}\n"
            ))
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, {}, clear=True):
                with redirect_stdout(out), redirect_stderr(err):
                    load_project_env(env_path)
            combined = out.getvalue() + err.getvalue()
            self.assertNotIn(_PLACEHOLDER_API_KEY, combined)
            self.assertNotIn(_PLACEHOLDER_USER_KEY, combined)
            self.assertEqual(combined, "")

    def test_parse_exception_is_swallowed_without_value_in_message(self):
        # 让 read_text 抛出一个包含占位 value 的异常，验证它被吞掉且不外泄。
        secret_bearing_error = OSError(f"boom {_PLACEHOLDER_API_KEY}")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "report_verify.env_bootstrap.Path.read_text",
                side_effect=secret_bearing_error,
            ), mock.patch(
                "report_verify.env_bootstrap.Path.is_file", return_value=True
            ):
                with redirect_stdout(out), redirect_stderr(err):
                    # 不应向外抛异常。
                    load_project_env("whatever.env")
            self.assertEqual(dict(os.environ), {})
        combined = out.getvalue() + err.getvalue()
        self.assertNotIn(_PLACEHOLDER_API_KEY, combined)


class OffModeTests(unittest.TestCase):
    def test_absent_env_keeps_mode_off_semantics(self):
        # 空 .env 不写入任何键；下游 LLMSettings.from_env 将默认 mode=off。
        with TemporaryDirectory() as tmp:
            env_path = _write_env(tmp, "# 只有注释\n\n")
            with mock.patch.dict(os.environ, {}, clear=True):
                load_project_env(env_path)
                self.assertNotIn("REPORT_VERIFY_LLM_MODE", os.environ)


if __name__ == "__main__":
    unittest.main()
