#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
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


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def fmt(cells: list[str]) -> str:
        return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    sep = "-+-".join("-" * w for w in widths)
    lines = [fmt(headers), sep]
    lines.extend(fmt(row) for row in rows)
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stampa tabella ablation in formato leggibile da terminale")
    parser.add_argument("--run-dir", default="", help="Path run specifico (default: ultimo run)")
    parser.add_argument(
        "--sort-by",
        choices=["wait", "travel", "p95_wait", "p95_travel", "speed"],
        default="wait",
        help="Metrica usata per ordinare gli scenari in ogni gruppo",
    )
    parser.add_argument("--top", type=int, default=0, help="Mostra solo top N scenari per gruppo (0 = tutti)")
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

    sort_key = {
        "wait": "avg_mean_wait_s",
        "travel": "avg_mean_travel_s",
        "p95_wait": "avg_p95_wait_s",
        "p95_travel": "avg_p95_travel_s",
        "speed": "avg_mean_speed_mps",
    }[args.sort_by]
    reverse = args.sort_by == "speed"

    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in summary_rows:
        grouped.setdefault((row["map"], row["demand"]), []).append(row)

    print(f"Run dir: {run_dir}")
    print(f"Gruppi: {len(grouped)}")
    print(f"Ordinamento: {args.sort_by} ({'desc' if reverse else 'asc'})")
    print("")

    for map_name, demand_name in sorted(grouped.keys()):
        rows = grouped[(map_name, demand_name)]
        rows = sorted(rows, key=lambda r: float(r[sort_key]), reverse=reverse)
        if args.top > 0:
            rows = rows[: args.top]

        table_rows: list[list[str]] = []
        for rank, row in enumerate(rows, start=1):
            delta = delta_map.get((row["map"], row["demand"], row["scenario"]), {})
            table_rows.append(
                [
                    str(rank),
                    row["scenario"],
                    f"{float(row['avg_mean_wait_s']):.2f}",
                    f"{float(delta.get('wait_delta_vs_base_pct', '0')):+.2f}",
                    f"{float(row['avg_mean_travel_s']):.2f}",
                    f"{float(delta.get('travel_delta_vs_base_pct', '0')):+.2f}",
                    f"{float(row['avg_p95_wait_s']):.2f}",
                    f"{float(row['avg_p95_travel_s']):.2f}",
                    f"{float(row['avg_mean_speed_mps']):.2f}",
                    row["runs"],
                ]
            )

        print(f"=== {map_name} / {demand_name} ===")
        print(
            format_table(
                [
                    "Rank",
                    "Scenario",
                    "MeanWait[s]",
                    "DeltaWait[%]",
                    "MeanTravel[s]",
                    "DeltaTravel[%]",
                    "P95Wait[s]",
                    "P95Travel[s]",
                    "MeanSpeed[m/s]",
                    "Runs",
                ],
                table_rows,
            )
        )
        print("")


if __name__ == "__main__":
    main()
