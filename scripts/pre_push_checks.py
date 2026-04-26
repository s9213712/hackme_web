#!/usr/bin/env python3
import argparse
import os
import pathlib
import py_compile
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import ssl

ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER = ROOT / "server.py"
SMOKE = ROOT / "tests" / "smoke_suite.py"


def iter_python_files():
    for rel in ("server.py", "routes", "services", "scripts", "tests"):
        path = ROOT / rel
        if path.is_file() and path.suffix == ".py":
            yield path
        elif path.is_dir():
            for item in sorted(path.rglob("*.py")):
                yield item


def compile_python():
    for path in iter_python_files():
        py_compile.compile(str(path), doraise=True)
    print("[compile] python syntax OK")


def find_free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def probe(base_url):
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(base_url + "/", method="GET")
    with urllib.request.urlopen(req, timeout=3, context=ctx) as resp:
        return resp.status == 200


def wait_for_server(base_urls, deadline=20):
    started = time.time()
    last_error = None
    while time.time() - started < deadline:
        for base_url in base_urls:
            try:
                if probe(base_url):
                    return base_url
            except Exception as exc:
                last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"server did not become ready: {last_error}")


def run_smoke(base_url):
    subprocess.run([sys.executable, str(SMOKE), "--base-url", base_url, "--suite", "all"], cwd=str(ROOT), check=True)


def assert_data_protection(runtime_root):
    db_path = runtime_root / "database" / "database.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT nickname, real_name, id_number, phone FROM users WHERE username='smokeprobe'"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise RuntimeError("smokeprobe registration row not found")
    plaintext_values = {
        "nickname": "smoke-nick",
        "real_name": "Smoke Probe",
        "id_number": "A123456789",
        "phone": "+886912345678",
    }
    for key, plain in plaintext_values.items():
        if row[key] == plain:
            raise RuntimeError(f"PII field {key} stored in plaintext")

    chat_dir = runtime_root / "chats"
    chat_files = sorted(chat_dir.glob("room_*.jsonl"))
    if not chat_files:
        raise RuntimeError("no chat transcript files were generated")
    transcript = chat_files[-1].read_text(encoding="utf-8")
    if "smoke secret message" in transcript or "\"content\"" in transcript or "\"sender\"" in transcript:
        raise RuntimeError("chat transcript sidecar still contains plaintext content")
    print("[data] encrypted PII and sealed chat transcript checks passed")


def start_server(runtime_root, port):
    env = os.environ.copy()
    env.update({
        "HTML_LEARNING_DB_DIR": str(runtime_root / "database"),
        "HTML_LEARNING_LOG_DIR": str(runtime_root / "logs"),
        "HTML_LEARNING_CHAT_DIR": str(runtime_root / "chats"),
        "HTML_LEARNING_ANCHOR_DIR": str(runtime_root / "anchors"),
        "HTML_LEARNING_HOST": "127.0.0.1",
        "HTML_LEARNING_PORT": str(port),
        "PYTHONUNBUFFERED": "1",
    })
    for name in ("database", "logs", "chats", "anchors"):
        (runtime_root / name).mkdir(parents=True, exist_ok=True)
    log_file = open(runtime_root / "server.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(SERVER)], cwd=str(ROOT), env=env, stdout=log_file, stderr=subprocess.STDOUT)
    return proc, log_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ci", action="store_true")
    args = parser.parse_args()

    compile_python()

    runtime_root = pathlib.Path(tempfile.mkdtemp(prefix="html_learning_prepush_"))
    port = find_free_port()
    proc = None
    log_file = None
    try:
        proc, log_file = start_server(runtime_root, port)
        base_url = wait_for_server([f"https://127.0.0.1:{port}", f"http://127.0.0.1:{port}"])
        print(f"[server] ready at {base_url}")
        run_smoke(base_url)
        assert_data_protection(runtime_root)
        print("[smoke] functional + security suite passed")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if log_file is not None:
            log_file.close()
        if args.ci:
            shutil.rmtree(runtime_root, ignore_errors=True)


if __name__ == "__main__":
    main()
