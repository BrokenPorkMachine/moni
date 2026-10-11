import json
import os
import sqlite3
from unittest.mock import MagicMock
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import moni
import api
import agent
import components
import history
import notifier


class MoniTests(unittest.TestCase):
    def config(self, value):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "moni.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_load_config_rejects_invalid_type(self):
        with self.assertRaises(moni.ConfigError):
            moni.load_config(self.config({"checks": [{"name": "x", "type": "udp"}]}))

    def test_check_metadata_and_duplicate_validation(self):
        checks = moni.load_config(
            self.config({"checks": [{"name": "x", "type": "tcp", "host": "localhost", "port": 80,
                                      "group": "ops", "tags": ["critical"]}]})
        )
        self.assertEqual(checks[0]["group"], "ops")
        self.assertEqual(checks[0]["tags"], ["critical"])
        duplicate = self.config({"checks": [{"name": "x", "type": "tcp", "host": "localhost", "port": 80,
                                               "tags": ["ops", "ops"]}]})
        with self.assertRaises(moni.ConfigError):
            moni.load_config(duplicate)

    def test_select_checks_filters_group_and_tags(self):
        checks = [
            {"name": "a", "group": "ops", "tags": ["critical", "tcp"]},
            {"name": "b", "group": "public", "tags": ["critical"]},
        ]
        selected = moni.select_checks(checks, group="ops", tags=["critical"])
        self.assertEqual([check["name"] for check in selected], ["a"])

    def test_json_result_includes_metadata(self):
        result = moni.CheckResult("health", "http", True, 1.0, group="ops", tags=("critical",))
        encoded = json.loads(moni.render([result], True))
        self.assertEqual(encoded[0]["group"], "ops")
        self.assertEqual(encoded[0]["tags"], ["critical"])

    def test_json_log_formatter_is_structured(self):
        record = moni.logging.LogRecord("moni", moni.logging.INFO, __file__, 1, "selected %d checks", (2,), None)
        encoded = json.loads(moni.JsonLogFormatter().format(record))
        self.assertEqual(encoded["level"], "info")
        self.assertEqual(encoded["message"], "selected 2 checks")

    def test_api_health_and_checks_endpoints(self):
        store = api.StateStore()
        store.replace([{"name": "health", "ok": True}, {"name": "db", "ok": False}])
        handler_type = api.make_handler(store)
        handler = handler_type.__new__(handler_type)
        handler.path = "/health"
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.do_GET()
        payload = json.loads(handler.wfile.write.call_args.args[0])
        self.assertEqual(payload, {"checks": 2, "ok": False})
        handler.path = "/checks"
        handler.do_GET()
        self.assertEqual(len(json.loads(handler.wfile.write.call_args.args[0])["checks"]), 2)

    def test_api_rejects_non_loopback_host(self):
        with self.assertRaises(ValueError):
            api.create_server("0.0.0.0", 0, api.StateStore())

    def test_api_requires_and_checks_bearer_token(self):
        store = api.StateStore()
        handler_type = api.make_handler(store, "secret")
        handler = handler_type.__new__(handler_type)
        handler.path = "/health"
        handler.headers = {"Authorization": "Bearer wrong"}
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.do_GET()
        self.assertEqual(handler.send_response.call_args.args[0], 401)

    def test_local_agent_reports_stable_capabilities(self):
        info = agent.local_agent("edge-1")
        self.assertEqual(info.as_dict(), {
            "name": "edge-1",
            "version": "0.1.0",
            "capabilities": ["http", "tcp", "history", "webhook"],
        })
        with self.assertRaises(ValueError):
            agent.local_agent(" ")

    def test_agent_secret_references_environment(self):
        with patch.dict(os.environ, {"MONI_EDGE_SECRET": "secret"}, clear=True):
            self.assertEqual(moni.parse_agent_secrets(["edge-1=MONI_EDGE_SECRET"]), {"edge-1": "secret"})
        with self.assertRaises(moni.ConfigError):
            moni.parse_agent_secrets(["edge-1=UNSET"])
        with self.assertRaises(moni.ConfigError):
            moni.parse_agent_secrets(["edge-1=MONI_EDGE_SECRET", "edge-1=MONI_EDGE_SECRET"])

    def test_agent_report_signature_and_replay_protection(self):
        info = agent.local_agent("edge-1")
        report = agent.create_report(info, [{"name": "health", "ok": True}], report_id="r1", sent_at=100.0, nonce="n1")
        signature = agent.sign_report(report, "secret")
        coordinator = agent.Coordinator({"edge-1": "secret"})
        coordinator.accept(report, signature, now=100.0)
        self.assertEqual(coordinator.snapshot()[0]["report_id"], "r1")
        with self.assertRaises(agent.ReportError):
            coordinator.accept(report, signature, now=100.0)

    def test_agent_report_rejects_forgery_and_stale_timestamp(self):
        info = agent.local_agent("edge-1")
        report = agent.create_report(info, [], report_id="r1", sent_at=100.0, nonce="n1")
        coordinator = agent.Coordinator({"edge-1": "secret"})
        with self.assertRaises(agent.ReportError):
            coordinator.accept(report, agent.sign_report(report, "wrong"), now=100.0)
        with self.assertRaises(agent.ReportError):
            coordinator.accept(report, agent.sign_report(report, "secret"), now=401.0)

    def test_report_endpoint_accepts_signed_agent_report(self):
        info = agent.local_agent("edge-1")
        report = agent.create_report(info, [], report_id="r1", sent_at=100.0, nonce="n1")
        coordinator = agent.Coordinator({"edge-1": "secret"})
        handler_type = api.make_handler(api.StateStore(), coordinator=coordinator)
        handler = handler_type.__new__(handler_type)
        handler.path = "/reports"
        handler.headers = {"X-Moni-Signature": agent.sign_report(report, "secret"), "Content-Length": str(len(json.dumps(report)))}
        handler.rfile = MagicMock()
        handler.rfile.read.return_value = json.dumps(report).encode()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        with patch("agent.time.time", return_value=100.0):
            handler.do_POST()
        self.assertEqual(handler.send_response.call_args.args[0], 202)

    def test_agents_endpoint_exposes_coordinator_reports(self):
        info = agent.local_agent("edge-1")
        report = agent.create_report(info, [], report_id="r1", sent_at=100.0, nonce="n1")
        coordinator = agent.Coordinator({"edge-1": "secret"})
        coordinator.accept(report, agent.sign_report(report, "secret"), now=100.0)
        handler_type = api.make_handler(api.StateStore(), coordinator=coordinator)
        handler = handler_type.__new__(handler_type)
        handler.path = "/agents"
        handler.headers = {}
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.do_GET()
        payload = json.loads(handler.wfile.write.call_args.args[0])
        self.assertEqual(payload["agents"][0]["agent"]["name"], "edge-1")

    def test_environment_references_expand_without_logging_values(self):
        path = self.config(
            {"checks": [{"name": "${MONI_NAME}", "type": "http", "url": "${MONI_URL}"}]}
        )
        with patch.dict(os.environ, {"MONI_NAME": "private-service", "MONI_URL": "https://internal.test"}, clear=False):
            checks = moni.load_config(path)
        self.assertEqual(checks[0]["name"], "private-service")
        self.assertEqual(checks[0]["url"], "https://internal.test")

    def test_environment_default_and_missing_variable(self):
        path = self.config(
            {"checks": [{"name": "health", "type": "http", "url": "https://${MONI_HOST:-example.com}"}]}
        )
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(moni.load_config(path)[0]["url"], "https://example.com")
            missing = self.config(
                {"checks": [{"name": "${MONI_SECRET}", "type": "http", "url": "https://example.com"}]}
            )
            with self.assertRaises(moni.ConfigError) as error:
                moni.load_config(missing)
        self.assertIn("MONI_SECRET", str(error.exception))
        self.assertNotIn("super-secret", str(error.exception))

    def test_reload_config_preserves_active_config_on_error(self):
        current = [{"name": "healthy", "type": "tcp", "host": "localhost", "port": 80}]
        invalid = self.config({"checks": [{"name": "broken", "type": "udp"}]})
        with patch.object(moni.LOGGER, "error") as log:
            self.assertIs(moni.reload_config(invalid, current), current)
        log.assert_called_once()

    def test_reload_config_replaces_valid_config(self):
        current = [{"name": "old", "type": "tcp", "host": "localhost", "port": 80}]
        replacement = self.config({"checks": [{"name": "new", "type": "tcp", "host": "localhost", "port": 81}]})
        self.assertEqual(moni.reload_config(replacement, current)[0]["name"], "new")

    def test_validate_command(self):
        path = self.config({"checks": [{"name": "x", "type": "tcp", "host": "localhost", "port": 80}]})
        self.assertEqual(moni.main(["validate", str(path)]), 0)

    def test_version_is_defined(self):
        self.assertEqual(moni.VERSION, "0.1.0")

    def test_http_result_passes_expected_status(self):
        class Response:
            status = 204
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, count): return b""
        with patch("moni.urlopen", return_value=Response()):
            output = moni.run_http({"name": "health", "type": "http", "url": "https://test", "expected_status": 204})
        self.assertTrue(output.ok)
        self.assertEqual(output.status, 204)

    def test_http_error_is_a_failed_check(self):
        with patch("moni.urlopen", side_effect=OSError("offline")):
            output = moni.run_http({"name": "health", "type": "http", "url": "https://test"})
        self.assertFalse(output.ok)
        self.assertIn("offline", output.error)

    def test_http_timeout_is_a_failed_check(self):
        with patch("moni.urlopen", side_effect=TimeoutError("timed out")):
            output = moni.run_http({"name": "health", "type": "http", "url": "https://test"})
        self.assertFalse(output.ok)
        self.assertIn("timed out", output.error)

    def test_malformed_config_file_is_a_usage_error(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(moni.main(["validate", str(path)]), 2)

    def test_failed_check_returns_failure_exit_code(self):
        path = self.config({"checks": [{"name": "down", "type": "tcp", "host": "127.0.0.1", "port": 9}]})
        failed = moni.CheckResult("down", "tcp", False, 1.0, error="refused")
        with patch("moni.run_checks", return_value=[failed]):
            self.assertEqual(moni.main(["check", str(path)]), 1)

    def test_repeat_mode_stops_cleanly_on_keyboard_interrupt(self):
        path = self.config({"checks": []})
        with patch("moni.run_checks", return_value=[]), patch(
            "moni.time.sleep", side_effect=KeyboardInterrupt
        ):
            self.assertEqual(moni.main(["check", str(path), "--repeat", "1"]), 0)

    def test_history_records_results(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "state" / "history.sqlite"
        results = [
            moni.CheckResult("health", "http", True, 12.5, status=200),
            moni.CheckResult("db", "tcp", False, 5.0, error="refused"),
        ]
        history.record_results(path, results, checked_at=123.0)
        database = sqlite3.connect(path)
        try:
            rows = database.execute(
                "SELECT checked_at, name, ok, status, error FROM observations ORDER BY id"
            ).fetchall()
        finally:
            database.close()
        self.assertEqual(rows, [(123.0, "health", 1, 200, None), (123.0, "db", 0, None, "refused")])

    def test_recent_history_is_newest_first(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "history.sqlite"
        history.record_results(path, [moni.CheckResult("old", "tcp", True, 1.0)], checked_at=10.0)
        history.record_results(path, [moni.CheckResult("new", "tcp", False, 2.0)], checked_at=20.0)
        rows = history.recent_observations(path, 1)
        self.assertEqual(rows[0]["name"], "new")
        self.assertFalse(rows[0]["ok"])

    def test_prune_history_keeps_newest_rows(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "history.sqlite"
        for checked_at in (1.0, 2.0, 3.0):
            history.record_results(path, [moni.CheckResult(str(checked_at), "tcp", True, 1.0)], checked_at=checked_at)
        self.assertEqual(history.prune_observations(path, 2), 1)
        self.assertEqual([row["name"] for row in history.recent_observations(path, 5)], ["3.0", "2.0"])

    def test_history_command_supports_json_and_limit_validation(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "history.sqlite"
        history.record_results(path, [moni.CheckResult("health", "http", True, 4.0)], checked_at=10.0)
        with patch("sys.stdout.write") as write:
            self.assertEqual(moni.main(["history", str(path), "--json"]), 0)
        self.assertIn('"name": "health"', write.call_args.args[0])
        self.assertEqual(moni.main(["history", str(path), "--limit", "0"]), 2)

    def test_history_returns_initial_and_changed_state_transitions(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "history.sqlite"
        first = history.record_results(
            path, [moni.CheckResult("health", "http", True, 1.0)], checked_at=10.0
        )
        second = history.record_results(
            path, [moni.CheckResult("health", "http", False, 2.0, error="down")], checked_at=20.0
        )
        self.assertIsNone(first[0].previous_ok)
        self.assertFalse(first[0].changed)
        self.assertEqual(second[0].previous_ok, True)
        self.assertTrue(second[0].changed)
        self.assertEqual(second[0].changed_at, 20.0)

    def test_webhook_ignores_initial_state(self):
        transition = history.StateTransition("health", "http", None, True, 10.0)
        with patch("notifier.urlopen") as send:
            self.assertTrue(notifier.send_transitions("https://hook", [transition]))
        send.assert_not_called()

    def test_webhook_retries_changed_state(self):
        class Response:
            status = 204
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, count): return b""
        transition = history.StateTransition("health", "http", True, False, 20.0)
        with patch("notifier.urlopen", side_effect=[OSError("offline"), Response()]) as send, patch(
            "notifier.time.sleep"
        ) as pause:
            self.assertTrue(notifier.send_transitions("https://hook", [transition], attempts=2))
        self.assertEqual(send.call_count, 2)
        pause.assert_called_once_with(0.25)

    def test_webhook_requires_history(self):
        path = self.config({"checks": []})
        self.assertEqual(moni.main(["check", str(path), "--webhook", "https://hook"]), 2)

    def test_webhook_rejects_non_http_urls(self):
        path = self.config({"checks": []})
        self.assertFalse(notifier.valid_webhook_url("file:///tmp/hook"))
        self.assertEqual(
            moni.main(["check", str(path), "--history", "/tmp/moni-history.sqlite", "--webhook", "file:///tmp/hook"]),
            2,
        )

    def test_webhook_failure_returns_failure_exit_code(self):
        path = self.config({"checks": []})
        transition = history.StateTransition("health", "http", True, False, 20.0)
        result = moni.CheckResult("health", "http", True, 1.0)
        with patch("moni.run_checks", return_value=[result]), patch(
            "moni.history.record_results", return_value=[transition]
        ), patch("moni.notifier.send_transitions", return_value=False):
            self.assertEqual(
                moni.main(["check", str(path), "--history", "/tmp/moni-history.sqlite", "--webhook", "https://hook"]),
                1,
            )

    def test_check_can_write_history(self):
        config = self.config({"checks": []})
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database = Path(directory.name) / "history.sqlite"
        with patch("moni.run_checks", return_value=[]):
            self.assertEqual(moni.main(["check", str(config), "--history", str(database)]), 0)
        connection = sqlite3.connect(database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 0)
        finally:
            connection.close()

    def test_tcp_check_passes_when_connection_succeeds(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        with patch("moni.socket.create_connection", return_value=connection) as connect:
            result = moni.run_tcp({"name": "socket", "type": "tcp", "host": "127.0.0.1", "port": 5432})
        self.assertTrue(result.ok)
        connect.assert_called_once_with(("127.0.0.1", 5432), timeout=5.0)

    def test_mixed_checks_keep_config_order(self):
        checks = [
            {"name": "first", "type": "tcp", "host": "127.0.0.1", "port": 1},
            {"name": "second", "type": "tcp", "host": "127.0.0.1", "port": 2},
        ]
        with patch("moni.run_check", side_effect=lambda check: moni.CheckResult(check["name"], "tcp", True, 1.0)):
            results = moni.run_checks(checks)
        self.assertEqual([item.name for item in results], ["first", "second"])

    def test_component_executor_preserves_order(self):
        checks = [{"name": "first"}, {"name": "second"}]
        with patch("components.as_completed", side_effect=lambda futures: reversed(list(futures))):
            results = components.ThreadedCheckExecutor(
                lambda check: moni.CheckResult(check["name"], "tcp", True, 1.0)
            ).run(checks, workers=2)
        self.assertEqual([item.name for item in results], ["first", "second"])

    def test_component_adapters_delegate_to_existing_services(self):
        result = moni.CheckResult("health", "http", True, 1.0)
        with patch("history.record_results", return_value=["transition"]) as record:
            self.assertEqual(components.SQLiteObservationStore().record(Path("history.db"), [result]), ["transition"])
            record.assert_called_once()
        with patch("notifier.send_transitions", return_value=True) as send:
            self.assertTrue(components.WebhookTransitionNotifier().send("https://hook", ["transition"]))
            send.assert_called_once()

    def test_invalid_worker_and_repeat_values_are_usage_errors(self):
        path = self.config({"checks": []})
        self.assertEqual(moni.main(["check", str(path), "--workers", "0"]), 2)
        self.assertEqual(moni.main(["check", str(path), "--repeat", "0"]), 2)


if __name__ == "__main__":
    unittest.main()
