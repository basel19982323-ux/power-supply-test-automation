"""Headless entry point for the engine (no GUI).

    python cli.py --list                 # list available test types
    python cli.py --scan                 # list connected VISA instruments
    python cli.py --simulate             # run the default test with fake instruments
    python cli.py --test <id> --config path.yaml [--simulate] [--report]

The GUI (main.py) drives the exact same runner; this CLI is handy for smoke
tests, CI, and bench debugging.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config as configmod          # noqa: E402
from core.runner import run_test               # noqa: E402
from core.test_base import Callbacks           # noqa: E402
from core.verdict import counts_text           # noqa: E402
import testtypes                               # noqa: E402


# Exit code = overall result, so a script or CI job can act on it.
EXIT_CODES = {"PASS": 0, "FAIL": 1, "ERROR": 2, "NOT RUN": 3}
EXIT_REPORT_FAILED = 4      # --report was asked for but could not be written


def main(argv=None):
    p = argparse.ArgumentParser(description="Dynamic Load Test engine (headless).")
    p.add_argument("--list", action="store_true", help="list available test types")
    p.add_argument("--scan", action="store_true", help="list connected VISA instruments")
    p.add_argument("--test", default=testtypes.default_test().id, help="test type id")
    p.add_argument("--config", help="path to a config .yaml (default: the test's default)")
    p.add_argument("--simulate", "--dry-run", dest="simulate", action="store_true",
                   help="run with simulated instruments (no hardware)")
    p.add_argument("--report", action="store_true",
                   help="also write the Excel and PowerPoint reports into the run folder")
    args = p.parse_args(argv)

    if args.list:
        for tid, name, desc in testtypes.list_tests():
            print(f"  {tid:28} {name} - {desc}")
        return 0

    if args.scan:
        from core.visa import scan
        for r in scan():
            print(f"  {r['address']}\n      {r['idn']}")
        return 0

    test = testtypes.get_test(args.test)
    cfg_path = args.config or configmod.default_config_path(test.id)
    if os.path.exists(cfg_path):
        config = configmod.load_config(cfg_path)
    else:
        config = test.default_config()
        print(f"(no config at {cfg_path}; using built-in defaults)")

    callbacks = Callbacks(
        on_start=lambda n: print(f"\n=== {test.name}: {n} test points "
                                 f"({'SIMULATION' if args.simulate else 'LIVE'}) ==="),
        on_status=lambda m: print(m),
        prompt=lambda m: input(f"\n>>> {m} Press Enter... "),
    )
    result = run_test(test, config, simulate=args.simulate, callbacks=callbacks)

    print(f"\nRun folder: {result.run_dir}")
    print(f"Summary: {counts_text(result.summary)}")
    print(f"Overall result: {result.overall}")
    print(f"Run mode: {result.mode}")
    for w in result.warnings:              # safety: AC / load not confirmed off
        print(f"\n!!! {w}", file=sys.stderr)
    if result.error:
        print(f"Ended with error: {result.error}")
    if result.aborted:
        print("Run was aborted.")
    if not args.report:
        print("Next: generate a report from the Report tab, or run again with --report.")
        return EXIT_CODES.get(result.overall, 2)
    import reporting
    try:
        paths = reporting.generate(result.run_dir, test, config, rows=result.rows)
    except Exception as e:  # noqa: BLE001 - say so, and fail the exit code
        print(f"\n!!! The report could not be written: {type(e).__name__}: {e}",
              file=sys.stderr)
        return EXIT_REPORT_FAILED
    for kind, path in paths.items():
        print(f"Report ({kind}): {path}")
    return EXIT_CODES.get(result.overall, 2)


if __name__ == "__main__":
    raise SystemExit(main())
