#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import shlex
from collections import OrderedDict
from pathlib import Path

import yaml


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


def load_run_rows(run_dir: Path) -> list[dict[str, str]]:
    run_results = run_dir / "run_results.csv"
    if not run_results.exists():
        raise FileNotFoundError(f"File non trovato: {run_results}")
    with run_results.open("r", newline="", encoding="utf-8") as fd:
        return list(csv.DictReader(fd))


def load_config(run_dir: Path) -> dict:
    config_file = run_dir / "config_resolved.yaml"
    if not config_file.exists():
        raise FileNotFoundError(f"File non trovato: {config_file}")
    with config_file.open("r", encoding="utf-8") as fd:
        data = yaml.safe_load(fd) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Formato non valido in {config_file}")
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mostra i comandi runner.py usati per avviare un run ablation"
    )
    parser.add_argument("--run-dir", required=True, help="Path run, es: ~/.../logs/ablation/runs/run_0012_...")
    parser.add_argument("--only-scenario", default="", help="Filtra una sola scenario (opzionale)")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Stampa il comando completo per ogni case (output lungo)",
    )
    return parser.parse_args()


def unique_preserve_order(values: list[str]) -> list[str]:
    return list(OrderedDict((value, None) for value in values).keys())


def build_full_command(
    *,
    python_exe: str,
    map_name: str,
    controller: str,
    population_file: str,
    step_length: str,
    output_log: Path,
    max_steps: int,
    flags_text: str,
) -> list[str]:
    flags = shlex.split(flags_text) if flags_text else []
    cmd = [
        python_exe,
        "runner.py",
        "-n",
        map_name,
        "-p",
        population_file,
        "--controller",
        controller,
        "--step-length",
        step_length,
        "--output-log",
        str(output_log),
    ]
    if max_steps > 0:
        cmd.extend(["--max-steps", str(max_steps)])
    cmd.extend(flags)
    return cmd


def main() -> None:
    args = parse_args()
    run_dir = resolve_run_dir(args.run_dir)
    config = load_config(run_dir)
    rows = load_run_rows(run_dir)

    step_length = str(config.get("step_length", 1.0))
    max_steps = int(config.get("max_steps", 0) or 0)
    python_exe = str(config.get("python_exe", "python3"))
    scenario_pack = str(config.get("scenario_pack", "n/a"))

    filtered_rows = rows
    if args.only_scenario:
        filtered_rows = [row for row in rows if row.get("scenario", "") == args.only_scenario]
        if not filtered_rows:
            print(f"Nessun case trovato per scenario '{args.only_scenario}'")
            return

    maps = unique_preserve_order([str(row.get("map", "")) for row in filtered_rows if row.get("map", "")])
    demands = unique_preserve_order([str(row.get("demand", "")) for row in filtered_rows if row.get("demand", "")])
    seeds = unique_preserve_order([str(row.get("pop_seed", "")) for row in filtered_rows if row.get("pop_seed", "")])
    scenarios = sorted({str(row.get("scenario", "")) for row in filtered_rows if row.get("scenario", "")})

    scenario_to_flags: dict[str, str] = {}
    scenario_to_controller: dict[str, str] = {}
    for row in filtered_rows:
        scenario_name = str(row.get("scenario", ""))
        if scenario_name and scenario_name not in scenario_to_flags:
            scenario_to_flags[scenario_name] = str(row.get("flags", "")).strip()
            scenario_to_controller[scenario_name] = str(row.get("controller", "mp")).strip() or "mp"

    print(f"Run dir: {run_dir}")
    print(f"Scenario pack: {scenario_pack}")
    print(f"python={python_exe}")
    print(f"step_length={step_length}  max_steps={max_steps}")
    print(f"maps={', '.join(maps)}")
    print(f"demands={', '.join(demands)}")
    print(f"seeds={', '.join(seeds)}")
    print(f"cases={len(filtered_rows)}  scenarios={len(scenarios)}")
    print("")

    print("Scenari e flag:")
    for scenario_name in scenarios:
        flags_text = scenario_to_flags.get(scenario_name, "")
        controller_name = scenario_to_controller.get(scenario_name, "mp")
        print(f"- {scenario_name}: controller={controller_name} flags={flags_text if flags_text else '(none)'}")
    print("")

    base_template = (
        f"{python_exe} runner.py -n <effective_map> -p <population_file.yaml> "
        f"--controller <controller> --step-length {step_length} "
        "--output-log <run_dir>/runs/<case_id>/vehicle_metrics.csv"
    )
    if max_steps > 0:
        base_template += f" --max-steps {max_steps}"

    print("Template comando (parte comune):")
    print(base_template)
    print("Parte variabile: <scenario_flags>")
    print("Per vedere tutti i comandi completi usa: --full")

    if not args.full:
        return

    print("")
    print("Comandi completi per ogni case:")
    for row in sorted(filtered_rows, key=lambda item: item.get("run_id", "")):
        run_id = row["run_id"]
        cmd = build_full_command(
            python_exe=python_exe,
            map_name=str(row.get("effective_map") or row["map"]),
            controller=str(row.get("controller") or "mp"),
            population_file=str(row["population_file"]),
            step_length=step_length,
            output_log=run_dir / "runs" / run_id / "vehicle_metrics.csv",
            max_steps=max_steps,
            flags_text=str(row.get("flags", "")).strip(),
        )
        print(f"- {run_id} ({row['scenario']}):")
        print(f"  {shlex.join(cmd)}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        pass
