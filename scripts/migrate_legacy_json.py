#!/usr/bin/env python3
"""Migrate legacy JSON sidecar files into SQLite."""

import json
from server import migrate_legacy_json_to_db


def main():
    summary = migrate_legacy_json_to_db()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
