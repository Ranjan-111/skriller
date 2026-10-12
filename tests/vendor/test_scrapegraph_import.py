"""Privacy regressions for the attributed ScrapeGraph-AI source snapshot."""

import importlib
import logging
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "third_party" / "scrapegraph-ai"
sys.path.insert(0, str(VENDOR))


class TelemetryIsolationTests(unittest.TestCase):
    def test_import_and_mock_graph_execution_are_inert_even_when_env_opts_in(self):
        script = """
import builtins, os, threading
from unittest.mock import patch
from urllib import request
os.environ['SCRAPEGRAPHAI_TELEMETRY_ENABLED'] = 'true'
with patch.object(builtins, 'open', side_effect=AssertionError('file I/O')), \\
     patch.object(request, 'urlopen', side_effect=AssertionError('network')), \\
     patch.object(threading.Thread, 'start', side_effect=AssertionError('thread')):
    import scrapegraphai
    from scrapegraphai.telemetry import telemetry as t
    assert not t.is_telemetry_enabled()
    t.g_telemetry_enabled = True
    assert not t.is_telemetry_enabled()
    t.log_graph_execution('mock', ['https://example.test/?token=SECRET'],
        'SECRET', {'x': 'string'}, 'mock', None, 'local', 0.1,
        content='PRIVATE HTML', response={'secret': 'SECRET'})
    t._send_telemetry({'secret': 'SECRET'})
    t._send_telemetry_threaded({'secret': 'SECRET'})
    assert t._load_config('/forbidden')['DEFAULT']['anonymous_id'] == 'disabled'
"""
        import os

        env = dict(os.environ, PYTHONPATH=str(VENDOR), PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(
            [sys.executable, "-c", script], check=False, env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SECRET", result.stdout + result.stderr)

    def test_invalid_telemetry_environment_value_is_redacted(self):
        import configparser

        from scrapegraphai.telemetry import telemetry as t

        config = configparser.ConfigParser()
        config["DEFAULT"] = {}
        with (
            patch.dict("os.environ", {"SCRAPEGRAPHAI_TELEMETRY_ENABLED": "SECRET"}),
            self.assertLogs(t.logger, level="WARNING") as captured,
        ):
            self.assertFalse(t._check_config_and_environ_for_telemetry_flag(False, config))
        self.assertNotIn("SECRET", "\n".join(captured.output))

    def test_optional_code_generation_modules_not_loaded_on_package_import(self):
        script = """
import sys
import scrapegraphai
import scrapegraphai.nodes
assert 'scrapegraphai.nodes.generate_code_node' not in sys.modules
assert 'scrapegraphai.utils.code_error_correction' not in sys.modules
"""
        import os

        result = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            env=dict(os.environ, PYTHONPATH=str(VENDOR)),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class ExtractionPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.FetchNode = importlib.import_module("scrapegraphai.nodes.fetch_node").FetchNode
        cls.GenerateAnswerNode = importlib.import_module(
            "scrapegraphai.nodes.generate_answer_node"
        ).GenerateAnswerNode

    def test_local_source_stays_in_result_but_not_logs(self):
        node = self.FetchNode("source", ["doc"], node_config={})
        page = "<html>PRIVATE PAGE token=SECRET</html>"
        with (
            patch("builtins.open", side_effect=AssertionError("unexpected file I/O")),
            patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")),
            self.assertLogs("scrapegraphai", level=logging.INFO) as captured,
        ):
            output = node.handle_local_source({}, page)
        self.assertEqual(output["doc"][0].page_content, page)
        self.assertNotIn("SECRET", "\n".join(captured.output))
        self.assertNotIn("PRIVATE PAGE", "\n".join(captured.output))

    def test_mocked_extraction_and_exception_do_not_log_credentials(self):
        class Chain:
            def invoke(self, inputs):
                self.inputs = inputs
                return {"company": "Acme"}

        chain = Chain()
        node = self.GenerateAnswerNode(
            "user_prompt & content", ["answer"], node_config={"llm_model": chain}
        )
        node.chain = chain
        self.assertEqual(
            node.process({"user_prompt": "Find companies", "content": "PRIVATE PAGE token=SECRET"})[
                "answer"
            ],
            {"company": "Acme"},
        )
        self.assertEqual(chain.inputs["content"], "PRIVATE PAGE token=SECRET")
        with (
            patch.object(chain, "invoke", side_effect=ValueError("PRIVATE PAGE token=SECRET")),
            self.assertLogs("scrapegraphai", level=logging.ERROR) as captured,
            self.assertRaises(ValueError),
        ):
            node.process({"user_prompt": "Find companies", "content": "PRIVATE PAGE"})
        self.assertNotIn("SECRET", "\n".join(captured.output))
        self.assertNotIn("PRIVATE PAGE", "\n".join(captured.output))

    def test_graph_result_content_is_redacted(self):
        from scrapegraphai.graphs.base_graph import BaseGraph

        graph = object.__new__(BaseGraph)
        graph.use_burr = False
        graph._execute_standard = lambda state: ({"answer": "PRIVATE PAGE token=SECRET"}, [])
        with self.assertLogs("scrapegraphai", level=logging.INFO) as captured:
            state, _ = graph.execute({})
        self.assertEqual(state["answer"], "PRIVATE PAGE token=SECRET")
        self.assertNotIn("SECRET", "\n".join(captured.output))
        self.assertNotIn("PRIVATE PAGE", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
