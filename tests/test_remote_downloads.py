import pytest

from services.remote_downloads import (
    RemoteDownloadError,
    download_magnet_with_aria2,
    validate_remote_url,
    validate_torrent_file_trackers,
)


def test_magnet_download_reports_aria2_log_tail(monkeypatch):
    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.returncode = None
            self.stdout = ""
            self.stderr = ""
            log_path = cmd[cmd.index("--log") + 1]
            assert "--bt-stop-timeout=120" in cmd
            assert "--enable-dht=false" in cmd
            assert "--enable-peer-exchange=false" in cmd
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write("notice\n")
                fh.write("errorCode=19 URI=magnet:?xt=urn:btih:bad\n")
                fh.write("Tracker returned failure reason\n")

        def poll(self):
            self.returncode = 19
            return self.returncode

        def communicate(self, timeout=None):
            return "If there are any errors, then see the log file.", ""

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr("services.remote_downloads.shutil.which", lambda name: "/usr/bin/aria2c")
    monkeypatch.setattr("services.remote_downloads.subprocess.Popen", FakePopen)

    with pytest.raises(RemoteDownloadError) as exc:
        download_magnet_with_aria2("magnet:?xt=urn:btih:bad")

    message = str(exc.value)
    assert "BT/magnet 下載失敗" in message
    assert "Tracker returned failure reason" in message
    assert "If there are any errors" not in message


def test_bt_download_kills_when_temp_size_exceeds_limit(monkeypatch):
    class SlowPopen:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.returncode = None
            log_path = cmd[cmd.index("--log") + 1]
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write("downloading\n")
            payload = cmd[cmd.index("--dir") + 1] + "/large.bin"
            with open(payload, "wb") as fh:
                fh.write(b"x" * 2048)

        def poll(self):
            return None

        def communicate(self, timeout=None):
            self.returncode = -9
            return "", ""

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr("services.remote_downloads.shutil.which", lambda name: "/usr/bin/aria2c")
    monkeypatch.setattr("services.remote_downloads.subprocess.Popen", SlowPopen)

    with pytest.raises(RemoteDownloadError) as exc:
        download_magnet_with_aria2("magnet:?xt=urn:btih:bad", max_bytes=1024)

    assert "超過容量限制" in str(exc.value)


def test_magnet_trackers_reject_private_hosts(monkeypatch):
    def fake_getaddrinfo(host, port, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", int(port or 80)))]

    monkeypatch.setattr("services.remote_downloads.socket.getaddrinfo", fake_getaddrinfo)

    with pytest.raises(RemoteDownloadError, match="localhost"):
        validate_remote_url("magnet:?xt=urn:btih:abc&tr=http%3A%2F%2Flocalhost%3A8080%2Fannounce")


def test_torrent_file_trackers_reject_private_hosts(tmp_path, monkeypatch):
    def fake_getaddrinfo(host, port, **kwargs):
        return [(2, 1, 6, "", ("10.0.0.5", int(port or 80)))]

    torrent = tmp_path / "bad.torrent"
    torrent.write_bytes(
        b"d8:announce31:http://tracker.example/announce4:infod4:name4:test12:piece lengthi16384e6:pieces0:ee"
    )
    monkeypatch.setattr("services.remote_downloads.socket.getaddrinfo", fake_getaddrinfo)

    with pytest.raises(RemoteDownloadError, match="localhost"):
        validate_torrent_file_trackers(torrent)
