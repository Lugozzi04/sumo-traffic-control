#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_run_dir(cli_run_dir: str) -> Path:
    if cli_run_dir:
        run_dir = Path(cli_run_dir).expanduser().resolve()
        if not run_dir.exists():
            raise FileNotFoundError(f"Run dir non trovata: {run_dir}")
        return run_dir

    latest_file = project_root() / "logs" / "ablation" / "latest_run.txt"
    if not latest_file.exists():
        raise FileNotFoundError(f"File latest run non trovato: {latest_file}")

    lines = [line.strip() for line in latest_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"{latest_file} e' vuoto")

    if len(lines) >= 2 and lines[1] != "n/a":
        run_dir = Path(lines[1]).expanduser().resolve()
    else:
        run_id = lines[0]
        run_dir = (project_root() / "logs" / "ablation" / "runs" / run_id).resolve()

    if not run_dir.exists():
        raise FileNotFoundError(f"Run dir non trovata: {run_dir}")
    return run_dir


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as fd:
        return list(csv.DictReader(fd))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mostra rapidamente gli scenari vincenti per ogni mappa/domanda")
    parser.add_argument("--run-dir", default="", help="Path run specifico (default: ultimo run)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = resolve_run_dir(args.run_dir)
    summary_file = run_dir / "summary_by_group.csv"
    delta_file = run_dir / "summary_vs_base.csv"

    if not summary_file.exists():
        raise FileNotFoundError(f"File non trovato: {summary_file}")
    if not delta_file.exists():
        raise FileNotFoundError(f"File non trovato: {delta_file}")

    summary_rows = load_csv(summary_file)
    delta_rows = load_csv(delta_file)
    delta_map: dict[tuple[str, str, str], dict[str, str]] = {
        (row["map"], row["demand"], row["scenario"]): row for row in delta_rows
    }

    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in summary_rows:
        grouped[(row["map"], row["demand"])].append(row)

    winners: list[dict[str, str]] = []
    wins_by_scenario: dict[str, int] = defaultdict(int)

    for (map_name, demand_name), rows in sorted(grouped.items()):
        best = min(rows, key=lambda r: float(r["avg_mean_wait_s"]))
        delta = delta_map.get((map_name, demand_name, best["scenario"]), {})
        winner = {
            "map": map_name,
            "demand": demand_name,
            "scenario": best["scenario"],
            "wait": f"{float(best['avg_mean_wait_s']):.2f}",
            "travel": f"{float(best['avg_mean_travel_s']):.2f}",
            "delta_wait": f"{float(delta.get('wait_delta_vs_base_pct', '0')):+.2f}",
            "delta_travel": f"{float(delta.get('travel_delta_vs_base_pct', '0')):+.2f}",
        }
        winners.append(winner)
        wins_by_scenario[best["scenario"]] += 1

    print(f"Run dir: {run_dir}")
    print("")
    print("Vincitore per gruppo (criterio: wait medio minimo)")
    print("MAP                    DEMAND   SCENARIO             WAIT[s]  DELTA_WAIT[%]  TRAVEL[s]  DELTA_TRAVEL[%]")
    for w in winners:
        print(
            f"{w['map'][:22]:22} {w['demand'][:7]:7} {w['scenario'][:20]:20} "
            f"{w['wait']:>7} {w['delta_wait']:>14} {w['travel']:>10} {w['delta_travel']:>16}"
        )

    print("")
    print("Classifica scenari per numero di vittorie")
    for scenario, count in sorted(wins_by_scenario.items(), key=lambda item: (-item[1], item[0])):
        print(f"- {scenario}: {count} vittorie")


if __name__ == "__main__":
    main()
