#!/usr/bin/env python3
"""
Fauxnos Server Test Runner

Runs all test levels and outputs structured JSON results.

Usage:
    python3 tests/run_tests.py
    python3 tests/run_tests.py --level 1,2,3
    python3 tests/run_tests.py --json   # machine-readable JSON only

Exit codes:
    0 = all tests passed
    1 = one or more tests failed
"""

import sys
import os
import json
import argparse
from datetime import datetime, timezone

# Ensure tests/ is on the path
sys.path.insert(0, os.path.dirname(__file__))

import test_server_health
import test_api
import test_snapcast
import test_registration


def run_all_tests(levels=None):
    """Run all test modules and return list of result dicts."""
    all_results = []
    all_results.extend(test_server_health.run_all())
    all_results.extend(test_api.run_all())
    all_results.extend(test_snapcast.run_all())
    all_results.extend(test_registration.run_all())

    if levels is not None:
        all_results = [r for r in all_results if r["level"] in levels]

    return all_results


def format_results(results, host="localhost", json_only=False):
    """Format results as structured JSON output."""
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "tests": results,
    }

    if json_only:
        print(json.dumps(output, indent=2))
        return output

    # Human-readable output
    GREEN = "\033[0;32m"
    RED = "\033[0;31m"
    YELLOW = "\033[1;33m"
    BOLD = "\033[1m"
    NC = "\033[0m"

    print(f"\n{BOLD}Fauxnos Server Tests{NC}")
    print("=" * 60)

    current_level = None
    for r in results:
        if r["level"] != current_level:
            current_level = r["level"]
            level_names = {1: "L1 — Binaries & Files", 2: "L2 — Services",
                          3: "L3 — API", 4: "L4 — Integration"}
            print(f"\n{BOLD}{level_names.get(current_level, f'L{current_level}')}{NC}")

        status_color = GREEN if r["status"] == "pass" else RED
        status_icon = "✓" if r["status"] == "pass" else "✗"
        print(f"  {status_color}{status_icon}{NC} {r['name']}", end="")

        if r["message"]:
            print(f"\n    {YELLOW}→ {r['message']}{NC}", end="")
        if r["hint"] and r["status"] == "fail":
            print(f"\n    Hint: {r['hint']}", end="")
        print()

    print(f"\n{'=' * 60}")
    summary_color = GREEN if failed == 0 else RED
    print(f"{summary_color}{BOLD}{passed}/{len(results)} passed{NC}", end="")
    if failed > 0:
        print(f"  ({failed} failed)")
    else:
        print()
    print()

    # Also output JSON for machine parsing
    print(json.dumps(output, indent=2))
    return output


def main():
    parser = argparse.ArgumentParser(description="Fauxnos Server Test Runner")
    parser.add_argument("--level", help="Comma-separated levels to run (e.g. 1,2,3)")
    parser.add_argument("--json", action="store_true", help="JSON-only output (no color)")
    parser.add_argument("--host", default=os.uname().nodename, help="Hostname label for output")
    args = parser.parse_args()

    levels = None
    if args.level:
        try:
            levels = set(int(x.strip()) for x in args.level.split(","))
        except ValueError:
            print("--level must be comma-separated integers, e.g. 1,2,3", file=sys.stderr)
            sys.exit(2)

    results = run_all_tests(levels=levels)
    output = format_results(results, host=args.host, json_only=args.json)

    sys.exit(0 if output["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
