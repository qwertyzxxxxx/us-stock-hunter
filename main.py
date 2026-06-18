#!/usr/bin/env python3
"""
market-hunter — US Stock Daily Scanner
Usage:
  python main.py scan-us         Run the US stock scan now
  python main.py evaluate-us     Evaluate historical signal returns
  python main.py report-us       Print the signal performance report
  python main.py schedule        Start the daily scheduler (blocks)
"""
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("market_hunter")


def cmd_scan():
    from market_hunter.scanner import run_us_scan
    print("\n🔍 Running US stock scan...\n")
    results = run_us_scan(notify=True)
    if not results:
        print("❌ Scan failed. Check logs for details.")
        return

    print(f"\n✅ Scan complete in {results['duration_seconds']}s")
    print(f"   Scanned: {results['total_scanned']} stocks")
    print(f"   Signals: {results['total_signals']} total\n")

    print("🏆 Top 20 by Score:")
    for i, s in enumerate(results["top20"], 1):
        strats = ", ".join(s.get("strategies", []))
        strat_str = f" [{strats}]" if strats else ""
        print(f"  {i:2}. {s['symbol']:<7} Score:{s['total_score']:5.1f}  "
              f"${s['close_price']:.2f}  {s.get('sector', '')[:25]}{strat_str}")

    print("\n📐 Top 5 MA60 Reclaim Pullback:")
    for i, s in enumerate(results["ma60_reclaim"], 1):
        print(f"  {i}. {s['symbol']:<7} Score:{s['total_score']:5.1f}  ${s['close_price']:.2f}")

    print("\n📈 Top 5 Strong Trend Pullback:")
    for i, s in enumerate(results["strong_trend"], 1):
        print(f"  {i}. {s['symbol']:<7} Score:{s['total_score']:5.1f}  ${s['close_price']:.2f}")

    print("\n🚀 Top 5 New High Breakout:")
    for i, s in enumerate(results["new_high"], 1):
        print(f"  {i}. {s['symbol']:<7} Score:{s['total_score']:5.1f}  ${s['close_price']:.2f}")

    print()


def cmd_evaluate():
    from market_hunter.evaluator import run_evaluation
    print("\n📊 Evaluating historical signals...\n")
    result = run_evaluation()
    print(f"✅ Done: {result['evaluated']} evaluated, {result['skipped']} skipped "
          f"(out of {result['total']} pending)\n")


def cmd_report():
    from market_hunter.report import print_report
    print_report()


def cmd_schedule():
    from market_hunter.scheduler.runner import start_scheduler
    from market_hunter.config import SCHEDULER_HOUR_MY, SCHEDULER_MINUTE_MY, SCHEDULER_TZ
    print(f"\n⏰ Starting scheduler — US scan runs daily at "
          f"{SCHEDULER_HOUR_MY:02d}:{SCHEDULER_MINUTE_MY:02d} {SCHEDULER_TZ}")
    print("Press Ctrl+C to stop.\n")
    start_scheduler()


COMMANDS = {
    "scan-us": cmd_scan,
    "evaluate-us": cmd_evaluate,
    "report-us": cmd_report,
    "schedule": cmd_schedule,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("Available commands:")
        for cmd in COMMANDS:
            print(f"  python main.py {cmd}")
        sys.exit(1)

    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
