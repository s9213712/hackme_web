import subprocess

import pytest

from services.remote_downloads import RemoteDownloadError, download_magnet_with_aria2


def test_magnet_download_reports_aria2_log_tail(monkeypatch):
    def fake_run(cmd, **kwargs):
        log_path = cmd[cmd.index("--log") + 1]
        assert "--bt-stop-timeout=120" in cmd
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write("notice\n")
            fh.write("errorCode=19 URI=magnet:?xt=urn:btih:bad\n")
            fh.write("Tracker returned failure reason\n")
        return subprocess.CompletedProcess(cmd, 19, stdout="If there are any errors, then see the log file.", stderr="")

    monkeypatch.setattr("services.remote_downloads.shutil.which", lambda name: "/usr/bin/aria2c")
    monkeypatch.setattr("services.remote_downloads.subprocess.run", fake_run)

    with pytest.raises(RemoteDownloadError) as exc:
        download_magnet_with_aria2("magnet:?xt=urn:btih:bad")

    message = str(exc.value)
    assert "BT/magnet 下載失敗" in message
    assert "Tracker returned failure reason" in message
    assert "If there are any errors" not in message
