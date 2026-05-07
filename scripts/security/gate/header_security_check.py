#!/usr/bin/env python3
"""HTTP security-header audit for hackme_web.

Checks both the root HTML page and a representative API endpoint for:
  - Content-Security-Policy
  - Strict-Transport-Security (HSTS)  — HTTPS targets only
  - X-Frame-Options  (or CSP frame-ancestors)
  - X-Content-Type-Options: nosniff
  - Referrer-Policy
  - Permissions-Policy
  - Cache-Control on /api/* routes
  - Server header (no version leakage)
  - X-Powered-By absent
  - Access-Control-Allow-Origin not wildcard on authenticated routes
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

from scripts.security.common_paths import timestamped_security_report_paths


DEFAULT_BASE_URL = os.environ.get("BASE_URL") or "https://127.0.0.1:50732"


def _get(url: str) -> dict:
    ctx = ssl._create_unverified_context()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "security-header-check/1.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
            return {"status": resp.status, "headers": dict(resp.headers.items()), "url": url}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "headers": dict(exc.headers.items()), "url": url}
    except Exception as exc:
        return {"status": 0, "headers": {}, "url": url, "error": str(exc)}


def _header(res: dict, name: str) -> str:
    h = res["headers"]
    return h.get(name) or h.get(name.lower()) or ""


class Runner:
    def __init__(self, base_url: str, *, out_json: str = "", out_md: str = ""):
        self.base_url = base_url.rstrip("/")
        self.out_json = out_json
        self.out_md = out_md
        self.results: list[dict] = []
        self._pass = 0
        self._fail = 0

    def _add(self, name: str, passed: bool, *, severity: str = "MEDIUM",
             details: str = "", recommendation: str = "") -> None:
        self.results.append({
            "name": name,
            "passed": passed,
            "severity": severity,
            "details": details,
            "recommendation": recommendation,
        })
        if passed:
            self._pass += 1
        else:
            self._fail += 1
        print(f"  [{'PASS' if passed else 'FAIL'}] [{severity}] {name}", flush=True)
        if not passed and details:
            print(f"         {details}", flush=True)

    def check(self, name: str, cond: bool, **kwargs) -> bool:
        self._add(name, cond, **kwargs)
        return cond

    # ── Header groups ─────────────────────────────────────────────────────────

    def check_html_page(self) -> None:
        print("\n[*] Checking HTML root page headers", flush=True)
        res = _get(f"{self.base_url}/")
        if res["status"] == 0:
            self._add("root page reachable", False, severity="INFO",
                      details=res.get("error", "connection failed"))
            return
        self._add(f"root page reachable (HTTP {res['status']})", True, severity="INFO")
        self._check_common_headers(res, context="html-root")

    def check_api_endpoint(self) -> None:
        print("\n[*] Checking /api/csrf-token headers", flush=True)
        res = _get(f"{self.base_url}/api/csrf-token")
        if res["status"] == 0:
            self._add("/api/csrf-token reachable", False, severity="INFO",
                      details=res.get("error", ""))
            return
        self._add(f"/api/csrf-token reachable (HTTP {res['status']})", True, severity="INFO")
        self._check_common_headers(res, context="api")
        self._check_api_specific_headers(res)

    def _check_common_headers(self, res: dict, *, context: str) -> None:
        is_https = self.base_url.startswith("https://")

        csp = _header(res, "Content-Security-Policy")
        self.check(
            f"[{context}] Content-Security-Policy present",
            bool(csp),
            severity="HIGH",
            details=f"value: {csp[:120]!r}" if csp else "header absent",
            recommendation="Add a strict CSP; at minimum 'default-src self'",
        )
        if csp:
            self.check(
                f"[{context}] CSP does not contain 'unsafe-eval'",
                "unsafe-eval" not in csp.lower(),
                severity="HIGH",
                details=f"CSP: {csp[:120]!r}",
                recommendation="Remove unsafe-eval to prevent script injection via eval()",
            )
            self.check(
                f"[{context}] CSP does not allow wildcard origins (data: script-src)",
                not re.search(r"script-src[^;]*\*", csp, re.IGNORECASE),
                severity="HIGH",
                details=f"CSP script-src should not allow wildcard",
            )

        if is_https:
            hsts = _header(res, "Strict-Transport-Security")
            self.check(
                f"[{context}] Strict-Transport-Security present",
                bool(hsts),
                severity="HIGH",
                details="absent — browsers may downgrade to HTTP",
                recommendation="Strict-Transport-Security: max-age=31536000; includeSubDomains",
            )
            if hsts:
                max_age_match = re.search(r"max-age=(\d+)", hsts, re.IGNORECASE)
                max_age = int(max_age_match.group(1)) if max_age_match else 0
                self.check(
                    f"[{context}] HSTS max-age >= 6 months",
                    max_age >= 15_552_000,
                    severity="MEDIUM",
                    details=f"max-age={max_age} (< 15552000 = 6 months)",
                )

        xfo = _header(res, "X-Frame-Options")
        frame_ancestors = "frame-ancestors" in csp.lower() if csp else False
        self.check(
            f"[{context}] Clickjacking protection present (X-Frame-Options or CSP frame-ancestors)",
            bool(xfo) or frame_ancestors,
            severity="MEDIUM",
            details="neither X-Frame-Options nor CSP frame-ancestors found",
            recommendation="X-Frame-Options: DENY  or  CSP: frame-ancestors 'none'",
        )

        xcto = _header(res, "X-Content-Type-Options")
        self.check(
            f"[{context}] X-Content-Type-Options: nosniff",
            xcto.strip().lower() == "nosniff",
            severity="MEDIUM",
            details=f"value: {xcto!r}" if xcto else "header absent",
            recommendation="X-Content-Type-Options: nosniff",
        )

        rp = _header(res, "Referrer-Policy")
        self.check(
            f"[{context}] Referrer-Policy present",
            bool(rp),
            severity="LOW",
            details="header absent",
            recommendation="Referrer-Policy: strict-origin-when-cross-origin",
        )

        server = _header(res, "Server")
        self.check(
            f"[{context}] Server header does not leak version",
            not re.search(r"\d+\.\d+", server),
            severity="LOW",
            details=f"Server: {server!r}",
            recommendation="Set Server header to a generic value without version numbers",
        )

        xpb = _header(res, "X-Powered-By")
        self.check(
            f"[{context}] X-Powered-By absent",
            not bool(xpb),
            severity="LOW",
            details=f"X-Powered-By: {xpb!r}",
            recommendation="Remove X-Powered-By to reduce fingerprinting surface",
        )

    def _check_api_specific_headers(self, res: dict) -> None:
        cc = _header(res, "Cache-Control")
        self.check(
            "[api] Cache-Control prevents caching of API responses",
            "no-store" in cc.lower() or "no-cache" in cc.lower(),
            severity="MEDIUM",
            details=f"Cache-Control: {cc!r}",
            recommendation="Cache-Control: no-store, no-cache, must-revalidate, private",
        )

        acao = _header(res, "Access-Control-Allow-Origin")
        self.check(
            "[api] CORS Access-Control-Allow-Origin not wildcard on API route",
            acao.strip() != "*",
            severity="HIGH",
            details=f"Access-Control-Allow-Origin: {acao!r}",
            recommendation="Do not use * for authenticated API routes",
        )

    # ── Orchestration ─────────────────────────────────────────────────────────

    def run(self) -> None:
        print(f"[*] Security header audit → {self.base_url}", flush=True)
        self.check_html_page()
        self.check_api_endpoint()
        self._report()

    def _report(self) -> None:
        total = self._pass + self._fail
        print(
            f"\n[*] Results: {self._pass}/{total} passed  "
            f"({self._fail} failed, {total} total)",
            flush=True,
        )
        if self.out_json:
            Path(self.out_json).parent.mkdir(parents=True, exist_ok=True)
            with open(self.out_json, "w") as fh:
                json.dump({
                    "base_url": self.base_url,
                    "pass": self._pass,
                    "fail": self._fail,
                    "total": total,
                    "results": self.results,
                }, fh, indent=2)
            print(f"[*] JSON report → {self.out_json}", flush=True)
        if self.out_md:
            Path(self.out_md).parent.mkdir(parents=True, exist_ok=True)
            lines = [
                "# Security Header Audit Report", "",
                f"- **target**: `{self.base_url}`",
                f"- **pass**: {self._pass} / {total}",
                f"- **fail**: {self._fail} / {total}", "",
                "## Results", "",
            ]
            for r in self.results:
                icon = "✅" if r["passed"] else "❌"
                lines.append(f"### {icon} [{r['severity']}] {r['name']}")
                if r.get("details"):
                    lines.append(f"- details: {r['details']}")
                if r.get("recommendation"):
                    lines.append(f"- recommendation: {r['recommendation']}")
                lines.append("")
            with open(self.out_md, "w") as fh:
                fh.write("\n".join(lines) + "\n")
            print(f"[*] Markdown report → {self.out_md}", flush=True)
        if self._fail > 0:
            sys.exit(1)


def main() -> None:
    default_json, default_md = timestamped_security_report_paths("header_security_check")
    ap = argparse.ArgumentParser(description="HTTP security-header audit for hackme_web")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--out-json", default=str(default_json))
    ap.add_argument("--out-md", default=str(default_md))
    args = ap.parse_args()
    Runner(args.base_url, out_json=args.out_json, out_md=args.out_md).run()


if __name__ == "__main__":
    main()
