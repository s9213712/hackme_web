import importlib
import sys


def test_runtime_output_capture_creates_server_log_and_buffer(tmp_path):
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    import services.core.runtime_output as runtime_output

    runtime_output = importlib.reload(runtime_output)
    log_path = tmp_path / "logs" / "server.log"
    try:
        runtime_output.install_runtime_output_capture(log_path)
        print("runtime capture smoke")
        sys.stdout.flush()

        payload = runtime_output.get_runtime_output(limit=10)
        lines = [item["line"] for item in payload["lines"]]
        log_text = log_path.read_text(encoding="utf-8")

        assert log_path.exists()
        assert any("runtime capture smoke" in line for line in lines)
        assert "runtime capture smoke" in log_text
        assert "capture installed" not in log_text
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr


def test_runtime_output_capture_decodes_bytes_without_repr_noise(tmp_path):
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    import services.core.runtime_output as runtime_output

    runtime_output = importlib.reload(runtime_output)
    log_path = tmp_path / "logs" / "server.log"
    try:
        runtime_output.install_runtime_output_capture(log_path)
        sys.stdout.write(b"binary smoke line\n")
        sys.stdout.flush()

        payload = runtime_output.get_runtime_output(limit=10)
        lines = [item["line"] for item in payload["lines"]]
        log_text = log_path.read_text(encoding="utf-8")

        assert any("binary smoke line" == line for line in lines)
        assert "binary smoke line" in log_text
        assert "b'binary smoke line" not in log_text
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
