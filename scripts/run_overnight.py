"""
BA2 Overnight-Runner
====================
Fuehrt experiment.py N-mal hintereinander aus und speichert pro Lauf eine CSV.

Ausfuehren:
  python scripts/run_overnight.py          # 15 Laeufe (Standard)
  python scripts/run_overnight.py 30       # 30 Laeufe
"""

import subprocess
import sys
import time
from datetime import datetime, timedelta

N_RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 15
PAUSE_BETWEEN_RUNS_S = 30  # kurze Pause damit Services sich stabilisieren

script = [sys.executable, "scripts/experiment.py"]


def fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S")


def main():
    start = datetime.now()
    print("=" * 55)
    print(f"  Overnight-Runner: {N_RUNS} Laeufe")
    print(f"  Start: {fmt_time(start)}")
    print("=" * 55)

    failed = 0
    for i in range(N_RUNS):
        run_start = datetime.now()
        print(f"\n{'=' * 55}")
        print(f"  LAUF {i + 1}/{N_RUNS}  [{fmt_time(run_start)}]")
        print(f"{'=' * 55}")

        result = subprocess.run(script)

        if result.returncode != 0:
            failed += 1
            print(f"  WARNUNG: Lauf {i + 1} mit Fehler beendet (returncode={result.returncode})")

        if i < N_RUNS - 1:
            print(f"\n  Pause {PAUSE_BETWEEN_RUNS_S}s ...")
            time.sleep(PAUSE_BETWEEN_RUNS_S)

    end = datetime.now()
    elapsed = end - start
    print(f"\n{'=' * 55}")
    print(f"  Fertig: {N_RUNS} Laeufe, {failed} Fehler")
    print(f"  Laufzeit: {str(elapsed).split('.')[0]}")
    print(f"  Ende: {fmt_time(end)}")
    print(f"{'=' * 55}")
    print(f"  Auswertung: python scripts/visualize.py")
    print(f"  Statistik:  python scripts/aggregate.py")


if __name__ == "__main__":
    main()
