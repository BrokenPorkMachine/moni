import json
from unittest.mock import MagicMock
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import moni


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
