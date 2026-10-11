import json
import sqlite3
from unittest.mock import MagicMock
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import moni
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

    def test_invalid_worker_and_repeat_values_are_usage_errors(self):
        path = self.config({"checks": []})
        self.assertEqual(moni.main(["check", str(path), "--workers", "0"]), 2)
        self.assertEqual(moni.main(["check", str(path), "--repeat", "0"]), 2)


if __name__ == "__main__":
    unittest.main()
