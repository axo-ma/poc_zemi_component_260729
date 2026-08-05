from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from zemi import env, toml
from zemi.playbook import Arsenal, Assistant, Llama, Model, download


CONFIG_PATH = (
    env.path.comp
    / "tests"
    / "playbook_arsenal"
    / "test_playbook_arsenal_router_mode.toml"
)


class TomlTests(unittest.TestCase):
    def test_load_preserves_plain_dicts_lists_and_references(self) -> None:
        config = toml.load(CONFIG_PATH)

        self.assertIs(type(config), dict)
        self.assertIs(type(config["arsenal"]), dict)
        self.assertIs(type(config["arsenal"]["llamas"]), list)
        self.assertEqual(
            config["text_reference"],
            "@comp/tests/zemi_toml/prefixes/plain-text.txt",
        )
        self.assertEqual(
            config["arsenal"]["llamas"][0]["models"][0]["assistants"][0][
                "prefix"
            ],
            "@comp/tests/zemi_toml/prefixes/qwen-system.md",
        )

    def test_load_rejects_duplicate_names(self) -> None:
        path = self._write_temp_toml(
            "[[items]]\nname = 'same'\n[[items]]\nname = 'same'\n"
        )

        with self.assertRaisesRegex(ValueError, "повторяющееся имя 'same'"):
            toml.load(path)

    def test_load_rejects_missing_zemi_reference(self) -> None:
        path = self._write_temp_toml(
            "reference = '@comp/does-not-exist-for-toml-test.txt'\n"
        )

        with self.assertRaisesRegex(FileNotFoundError, "не существует"):
            toml.load(path)

    def _write_temp_toml(self, content: str) -> Path:
        env.path.tmp.mkdir(parents=True, exist_ok=True)
        path = env.path.tmp / f"zemi-toml-test-{id(self)}.toml"
        path.write_text(content, encoding="utf-8")
        self.addCleanup(path.unlink, missing_ok=True)
        return path


class ArsenalObjectTreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = toml.load(CONFIG_PATH)
        self.arsenal = Arsenal(self.config)

    def test_builds_named_runtime_tree(self) -> None:
        primary = self.arsenal.llamas["primary"]
        qwen = primary.models["qwen"]
        assistant = qwen.assistants["assistant"]

        self.assertIsInstance(primary, Llama)
        self.assertIsInstance(qwen, Model)
        self.assertIsInstance(assistant, Assistant)
        self.assertIs(primary, self.arsenal.llamas[0])
        self.assertIs(qwen, primary.models[0])
        self.assertIs(assistant, qwen.assistants[0])
        self.assertEqual(primary.host, "127.0.0.1")
        self.assertEqual(qwen.alias, "qwen3.5-4b")
        self.assertEqual(
            assistant.prefix,
            "@comp/tests/zemi_toml/prefixes/qwen-system.md",
        )

    def test_runtime_tree_wraps_but_does_not_replace_raw_config(self) -> None:
        primary = self.arsenal.llamas.primary

        self.assertIs(type(self.arsenal.config), dict)
        self.assertIs(type(self.arsenal.config["arsenal"]["llamas"]), list)
        self.assertIs(primary.config, self.config["arsenal"]["llamas"][0])

    def test_model_runtime_and_download_have_separate_modules(self) -> None:
        self.assertEqual(Assistant.__module__, "zemi.playbook.arsenal_objects")
        self.assertEqual(Model.__module__, "zemi.playbook.arsenal_objects")
        self.assertEqual(Llama.__module__, "zemi.playbook.arsenal_objects")
        self.assertEqual(Arsenal.__module__, "zemi.playbook.arsenal")
        self.assertEqual(download.__module__, "zemi.playbook.arsenal_download")


class ArsenalDownloadTests(unittest.TestCase):
    @patch("zemi.playbook.arsenal_download.download_model")
    @patch("zemi.playbook.arsenal_download.download_llama")
    def test_download_builds_runtime_tree(
        self,
        download_llama_mock,
        download_model_mock,
    ) -> None:
        download_llama_mock.return_value = Path("llama")
        download_model_mock.return_value = Path("model.gguf")

        with redirect_stdout(StringIO()):
            result = download(
                "@comp/tests/playbook_arsenal/"
                "test_playbook_arsenal_router_mode.toml"
            )

        self.assertIsInstance(result, Arsenal)
        self.assertEqual(len(result.llamas), 2)
        self.assertEqual(download_llama_mock.call_count, 2)
        self.assertEqual(download_model_mock.call_count, 4)


if __name__ == "__main__":
    unittest.main()
