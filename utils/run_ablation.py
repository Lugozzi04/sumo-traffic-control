import argparse
import csv
import datetime as dt
import math
import os
import re
import selectors
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class DemandPreset:
    vehicles: int
    start_time: float
    end_time: float


@dataclass(frozen=True)
class Scenario:
    name: str
    flags: tuple[str, ...]


DEMANDS: dict[str, DemandPreset] = {
    "low": DemandPreset(vehicles=2000, start_time=0.0, end_time=3600.0),
    "medium": DemandPreset(vehicles=4000, start_time=0.0, end_time=3600.0),
    "high": DemandPreset(vehicles=7000, start_time=0.0, end_time=3600.0),
}

SCENARIOS: tuple[Scenario, ...] = (
    Scenario("mp_base", ()),
    Scenario("mp_switch_aware", ("--lost-time-aware", "--nmin-dynamic")),
    Scenario("mp_downstream_aware", ("--spillback", "--downstream-penalty")),
    Scenario("mp_fairness", ("--fairness",)),
    Scenario("mp_platoon_safe", ("--platoon-extension", "--spillback", "--downstream-penalty")),
    Scenario(
        "mp_all_on",
        (
            "--spillback",
            "--lost-time-aware",
            "--downstream-penalty",
            "--fairness",
            "--nmin-dynamic",
            "--platoon-extension",
        ),
    ),
)

STEP_PATTERN = re.compile(r"Step #([0-9]+(?:\.[0-9]+)?)")
RUN_DIR_PATTERN = re.compile(r"^run_(\d+)_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch ablation runner (seriale, con summary automatico)")
    parser.add_argument(
        "--maps",
        nargs="+",
        default=["manhattan6x6_100pc", "manhattan8x8_100pc"],
        help="Mappe da testare (cartelle in sumo_xml_files)",
    )
    parser.add_argument(
        "--demands",
        nargs="+",
        choices=sorted(DEMANDS.keys()),
        default=["low", "medium", "high"],
        help="Livelli di domanda",
    )
    parser.add_argument("--num-seeds", type=int, default=5, help="Numero seed popolazione per ogni mappa/domanda")
    parser.add_argument("--seed-start", type=int, default=1, help="Seed iniziale (incluso)")
    parser.add_argument("--step-length", type=float, default=1.0, help="Step simulation in secondi")
    parser.add_argument("--max-steps", type=int, default=5400, help="Tetto massimo simulazione (0 = nessun limite)")
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=15.0,
        help="Intervallo aggiornamento file progresso in secondi",
    )
    parser.add_argument(
        "--batch-name",
        default="",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--python-exe", default=sys.executable, help="Interprete python da usare per subprocess")
    args = parser.parse_args()
    if args.progress_interval <= 0:
        parser.error("--progress-interval deve essere > 0")
    return args


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]

    rank = (len(sorted_values) - 1) * (p / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[lower]

    weight = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * weight


def safe_mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def safe_std(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) >= 2 else 0.0


def run_command(cmd: list[str], cwd: Path) -> tuple[int, str]:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    combined = (result.stdout or "") + ("\n" if result.stdout and result.stderr else "") + (result.stderr or "")
    return result.returncode, combined


def run_runner_command_with_live_progress(
    cmd: list[str],
    cwd: Path,
    live_log_file: Path,
    progress_interval: float,
    on_tick,
) -> tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        bufsize=0,
    )

    if process.stdout is None:
        raise RuntimeError("Impossibile catturare output subprocess")

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)

    output_chunks: list[str] = []
    parse_tail = ""
    last_tick = 0.0
    start_time = time.time()
    latest_step: float | None = None

    def tick(force: bool = False) -> None:
        nonlocal last_tick
        now = time.time()
        if force or (now - last_tick) >= progress_interval:
            on_tick(latest_step, now - start_time)
            last_tick = now

    tick(force=True)
    with live_log_file.open("w", encoding="utf-8") as fd:
        while True:
            events = selector.select(timeout=1.0)
            for key, _ in events:
                stream = key.fileobj
                chunk_bytes = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
                if chunk_bytes:
                    chunk_text = chunk_bytes.decode("utf-8", errors="replace")
                    fd.write(chunk_text)
                    fd.flush()
                    output_chunks.append(chunk_text)
                    parse_text = parse_tail + chunk_text
                    for match in STEP_PATTERN.finditer(parse_text):
                        latest_step = float(match.group(1))
                    parse_tail = parse_text[-64:]

            if process.poll() is not None:
                remainder_bytes = process.stdout.read() or b""
                if remainder_bytes:
                    remainder = remainder_bytes.decode("utf-8", errors="replace")
                    fd.write(remainder)
                    fd.flush()
                    output_chunks.append(remainder)
                    parse_text = parse_tail + remainder
                    for match in STEP_PATTERN.finditer(parse_text):
                        latest_step = float(match.group(1))
                break

            tick(force=False)

    selector.unregister(process.stdout)
    tick(force=True)
    return process.returncode, "".join(output_chunks)


def parse_runner_log_path(output_text: str) -> Path:
    match = re.search(r"Log salvato in:\s*(.+)", output_text)
    if not match:
        raise RuntimeError("Output runner non contiene il path del log finale")
    return Path(match.group(1).strip())


def parse_vehicle_log(log_file: Path) -> dict[str, float]:
    wait_values: list[float] = []
    travel_values: list[float] = []
    speed_values: list[float] = []
    co2_values: list[float] = []
    fuel_values: list[float] = []

    with log_file.open("r", newline="", encoding="utf-8") as fd:
        reader = csv.DictReader(fd, delimiter=";")
        for row in reader:
            wait_values.append(float(row["waiting_time_s"]))
            travel_values.append(float(row["travel_time_s"]))
            speed_values.append(float(row["mean_speed_mps"]))
            co2_values.append(float(row["co2_g"]))
            fuel_values.append(float(row["fuel_g"]))

    return {
        "vehicles_count": float(len(wait_values)),
        "mean_wait_s": safe_mean(wait_values),
        "p95_wait_s": percentile(wait_values, 95.0),
        "mean_travel_s": safe_mean(travel_values),
        "p95_travel_s": percentile(travel_values, 95.0),
        "mean_speed_mps": safe_mean(speed_values),
        "mean_co2_g": safe_mean(co2_values),
        "mean_fuel_g": safe_mean(fuel_values),
    }


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fd:
        writer = csv.DictWriter(fd, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    sep = ["---"] * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def format_ts(epoch_seconds: float) -> str:
    return dt.datetime.fromtimestamp(epoch_seconds).strftime("%Y-%m-%d %H:%M:%S")


def allocate_run_directory(ablation_root: Path) -> tuple[str, Path]:
    runs_root = ablation_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)

    max_index = 0
    for child in runs_root.iterdir():
        if not child.is_dir():
            continue
        match = RUN_DIR_PATTERN.match(child.name)
        if not match:
            continue
        max_index = max(max_index, int(match.group(1)))

    run_index = max_index + 1
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_id = f"run_{run_index:04d}_{timestamp}"
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_id, run_dir


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def write_atomic_text(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def preflight_checks(args: argparse.Namespace, root: Path) -> None:
    import_cmd = [args.python_exe, "-c", "import traci, sumolib, yaml; print('python deps ok')"]
    code, output = run_command(import_cmd, root)
    if code != 0:
        raise RuntimeError(
            "Preflight fallito: dipendenze python mancanti nell'interprete selezionato.\n"
            f"Comando: {' '.join(import_cmd)}\n"
            f"Output:\n{output}"
        )

    sumo_cmd = ["sumo", "--version"]
    code, output = run_command(sumo_cmd, root)
    if code != 0:
        raise RuntimeError(
            "Preflight fallito: comando 'sumo' non disponibile nel PATH.\n"
            "Installa/carica SUMO prima del batch.\n"
            f"Output:\n{output}"
        )

    missing_maps: list[str] = []
    for map_name in args.maps:
        cfg = root / "sumo_xml_files" / map_name / f"{map_name}.sumocfg"
        if not cfg.exists():
            missing_maps.append(str(cfg))
    if missing_maps:
        raise RuntimeError("Preflight fallito: mappe non trovate:\n" + "\n".join(missing_maps))


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]

    ablation_root = root / "logs" / "ablation"
    ablation_root.mkdir(parents=True, exist_ok=True)
    run_id, batch_dir = allocate_run_directory(ablation_root)
    populations_dir = batch_dir / "populations"
    runs_dir = batch_dir / "runs"
    populations_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    if args.batch_name.strip():
        print("[info] --batch-name ignorato: ora il nome run e' sempre progressivo+timestamp")
    write_atomic_text(ablation_root / "latest_run.txt", f"{run_id}\n{batch_dir}\n")

    config = {
        "run_id": run_id,
        "run_dir": str(batch_dir),
        "maps": args.maps,
        "demands": args.demands,
        "num_seeds": args.num_seeds,
        "seed_start": args.seed_start,
        "step_length": args.step_length,
        "max_steps": args.max_steps,
        "progress_interval": args.progress_interval,
        "python_exe": args.python_exe,
        "demand_presets": {
            key: {
                "vehicles": DEMANDS[key].vehicles,
                "start_time": DEMANDS[key].start_time,
                "end_time": DEMANDS[key].end_time,
            }
            for key in args.demands
        },
        "scenarios": [{"name": scenario.name, "flags": list(scenario.flags)} for scenario in SCENARIOS],
    }
    with (batch_dir / "config_resolved.yaml").open("w", encoding="utf-8") as fd:
        yaml.safe_dump(config, fd, sort_keys=False)

    seed_values = [args.seed_start + offset for offset in range(args.num_seeds)]
    total_runs = len(args.maps) * len(args.demands) * len(seed_values) * len(SCENARIOS)
    current_run = 0

    run_rows: list[dict] = []
    script_start = time.time()
    script_start_label = format_ts(script_start)
    progress_yaml_file = ablation_root / "progress.yaml"
    progress_txt_file = ablation_root / "progress.txt"
    current_activity = "inizializzazione"
    current_run_id = ""
    current_run_started_at: float | None = None
    current_run_step: float | None = None
    current_run_meta: tuple[str, str, int, str] | None = None

    def write_progress_files(status: str, error_message: str = "") -> None:
        status_label = {
            "running": "IN_CORSO",
            "completed": "COMPLETATO",
            "completed_with_errors": "COMPLETATO_CON_ERRORI",
            "failed": "ERRORE",
            "stopped": "INTERROTTO",
        }.get(status, status.upper())

        now = time.time()
        runs_done = len(run_rows)
        runs_success = sum(1 for row in run_rows if row["status"] == "ok")
        runs_failed = sum(1 for row in run_rows if row["status"] != "ok")
        remaining_runs = max(0, total_runs - runs_done)
        avg_run_seconds = safe_mean([float(row["wall_seconds"]) for row in run_rows]) if run_rows else 0.0
        eta_seconds = avg_run_seconds * remaining_runs if avg_run_seconds > 0 else None

        run_elapsed = (now - current_run_started_at) if current_run_started_at is not None else None
        run_progress_pct: float | None = None
        if args.max_steps > 0 and current_run_step is not None:
            run_progress_pct = min(100.0, max(0.0, (current_run_step / float(args.max_steps)) * 100.0))

        next_update = format_ts(now + args.progress_interval) if status == "running" else "n/a"
        payload = {
            "status": status_label,
            "run_id": run_id,
            "run_dir": str(batch_dir),
            "started_at": script_start_label,
            "last_update": format_ts(now),
            "next_update_expected": next_update,
            "update_interval_seconds": args.progress_interval,
            "elapsed_batch_seconds": round(now - script_start, 3),
            "eta_remaining_hms": format_eta(eta_seconds),
            "total_runs": total_runs,
            "runs_done": runs_done,
            "runs_success": runs_success,
            "runs_failed": runs_failed,
            "current_activity": current_activity,
            "current_run_id": current_run_id,
            "current_run_elapsed_seconds": round(run_elapsed, 3) if run_elapsed is not None else None,
            "current_run_step": current_run_step,
            "current_run_progress_pct": round(run_progress_pct, 2) if run_progress_pct is not None else None,
            "current_run_meta": {
                "map": current_run_meta[0],
                "demand": current_run_meta[1],
                "seed": current_run_meta[2],
                "scenario": current_run_meta[3],
            }
            if current_run_meta is not None
            else None,
            "error_message": error_message,
        }

        write_atomic_text(progress_yaml_file, yaml.safe_dump(payload, sort_keys=False))
        text_lines = [
            f"stato: {status_label}",
            f"run: {run_id}",
            f"cartella risultati: {batch_dir}",
            f"inizio simulazione: {script_start_label}",
            f"ultimo aggiornamento: {payload['last_update']}",
            f"prossimo aggiornamento atteso entro: {payload['next_update_expected']} (ogni {args.progress_interval:.1f}s)",
            f"attivita corrente: {current_activity}",
            f"run completati: {runs_done}/{total_runs} (ok={runs_success}, fail={runs_failed})",
            f"tempo batch trascorso: {format_eta(now - script_start)}",
            f"stima tempo rimanente: {payload['eta_remaining_hms']}",
            f"run corrente: {current_run_id or 'n/a'}",
            f"run corrente elapsed: {round(run_elapsed, 1) if run_elapsed is not None else 'n/a'} s",
            f"run corrente step: {current_run_step if current_run_step is not None else 'n/a'}",
            f"run corrente progresso: {f'{run_progress_pct:.2f}%' if run_progress_pct is not None else 'n/a'}",
        ]
        if error_message:
            text_lines.append(f"errore: {error_message}")
        write_atomic_text(progress_txt_file, "\n".join(text_lines) + "\n")

    write_progress_files(status="running")
    try:
        current_activity = "preflight dipendenze/mappe"
        write_progress_files(status="running")
        preflight_checks(args, root)

        for map_name in args.maps:
            for demand_name in args.demands:
                demand = DEMANDS[demand_name]
                for pop_seed in seed_values:
                    current_activity = f"generazione popolazione {map_name}/{demand_name}/seed{pop_seed}"
                    current_run_id = ""
                    current_run_meta = None
                    current_run_started_at = None
                    current_run_step = None
                    write_progress_files(status="running")

                    population_file = populations_dir / f"{map_name}_{demand_name}_seed{pop_seed}.yaml"
                    generate_cmd = [
                        args.python_exe,
                        "generate_population.py",
                        "-n",
                        map_name,
                        "-o",
                        str(population_file),
                        "-N",
                        str(demand.vehicles),
                        "--start-time",
                        str(demand.start_time),
                        "--end-time",
                        str(demand.end_time),
                        "--seed",
                        str(pop_seed),
                    ]
                    generate_code, generate_output = run_command(generate_cmd, root)
                    if generate_code != 0:
                        raise RuntimeError(
                            f"Errore generazione popolazione {population_file}\n{generate_output}"
                        )

                    for scenario in SCENARIOS:
                        current_run += 1
                        case_id = f"{map_name}__{demand_name}__seed{pop_seed}__{scenario.name}"
                        current_run_id = case_id
                        current_run_meta = (map_name, demand_name, pop_seed, scenario.name)
                        current_run_started_at = time.time()
                        current_run_step = None
                        current_activity = f"esecuzione {current_run}/{total_runs}"
                        write_progress_files(status="running")

                        print(f"[{current_run}/{total_runs}] {case_id}")

                        cmd = [
                            args.python_exe,
                            "runner.py",
                            "-n",
                            map_name,
                            "-p",
                            str(population_file),
                            "--controller",
                            "mp",
                            "--step-length",
                            str(args.step_length),
                        ]
                        if args.max_steps > 0:
                            cmd.extend(["--max-steps", str(args.max_steps)])
                        cmd.extend(scenario.flags)

                        run_dir = runs_dir / case_id
                        run_dir.mkdir(parents=True, exist_ok=True)
                        live_log_file = run_dir / "stdout_stderr.log"

                        def on_runner_tick(step_value: float | None, _elapsed_seconds: float) -> None:
                            nonlocal current_run_step
                            current_run_step = step_value
                            write_progress_files(status="running")

                        wall_start = time.time()
                        return_code, output_text = run_runner_command_with_live_progress(
                            cmd=cmd,
                            cwd=root,
                            live_log_file=live_log_file,
                            progress_interval=args.progress_interval,
                            on_tick=on_runner_tick,
                        )
                        wall_seconds = time.time() - wall_start

                        base_row = {
                            "run_id": case_id,
                            "map": map_name,
                            "demand": demand_name,
                            "pop_seed": pop_seed,
                            "scenario": scenario.name,
                            "flags": " ".join(scenario.flags),
                            "population_file": str(population_file),
                            "status": "ok" if return_code == 0 else "fail",
                            "wall_seconds": round(wall_seconds, 3),
                        }

                        if return_code != 0:
                            base_row.update(
                                {
                                    "log_file": "",
                                    "vehicles_count": 0,
                                    "mean_wait_s": 0.0,
                                    "p95_wait_s": 0.0,
                                    "mean_travel_s": 0.0,
                                    "p95_travel_s": 0.0,
                                    "mean_speed_mps": 0.0,
                                    "mean_co2_g": 0.0,
                                    "mean_fuel_g": 0.0,
                                }
                            )
                            run_rows.append(base_row)
                            write_progress_files(status="running")
                            continue

                        log_file = parse_runner_log_path(output_text)
                        if not log_file.is_absolute():
                            log_file = (root / log_file).resolve()
                        if not log_file.exists():
                            raise RuntimeError(f"Log file non trovato: {log_file}")

                        copied_log_file = run_dir / "vehicle_metrics.csv"
                        copied_log_file.write_text(log_file.read_text(encoding="utf-8"), encoding="utf-8")
                        metrics = parse_vehicle_log(log_file)
                        try:
                            logs_root = (root / "logs").resolve()
                            if log_file.resolve().is_relative_to(logs_root):
                                log_file.unlink(missing_ok=True)
                        except OSError:
                            pass

                        base_row.update(
                            {
                                "log_file": str(copied_log_file),
                                "vehicles_count": int(metrics["vehicles_count"]),
                                "mean_wait_s": round(metrics["mean_wait_s"], 6),
                                "p95_wait_s": round(metrics["p95_wait_s"], 6),
                                "mean_travel_s": round(metrics["mean_travel_s"], 6),
                                "p95_travel_s": round(metrics["p95_travel_s"], 6),
                                "mean_speed_mps": round(metrics["mean_speed_mps"], 6),
                                "mean_co2_g": round(metrics["mean_co2_g"], 6),
                                "mean_fuel_g": round(metrics["mean_fuel_g"], 6),
                            }
                        )
                        run_rows.append(base_row)
                        current_run_started_at = None
                        current_run_step = None
                        write_progress_files(status="running")
    except KeyboardInterrupt:
        current_activity = "interrotto da utente"
        write_progress_files(status="stopped", error_message="interrotto da tastiera (CTRL+C)")
        raise
    except Exception as exc:
        current_activity = "errore batch"
        write_progress_files(status="failed", error_message=str(exc))
        raise

    current_activity = "aggregazione risultati"
    write_progress_files(status="running")

    run_results_file = batch_dir / "run_results.csv"
    run_fields = [
        "run_id",
        "map",
        "demand",
        "pop_seed",
        "scenario",
        "flags",
        "population_file",
        "status",
        "wall_seconds",
        "log_file",
        "vehicles_count",
        "mean_wait_s",
        "p95_wait_s",
        "mean_travel_s",
        "p95_travel_s",
        "mean_speed_mps",
        "mean_co2_g",
        "mean_fuel_g",
    ]
    write_csv(run_results_file, run_rows, run_fields)

    ok_rows = [row for row in run_rows if row["status"] == "ok"]
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for row in ok_rows:
        key = (str(row["map"]), str(row["demand"]), str(row["scenario"]))
        grouped.setdefault(key, []).append(row)

    summary_rows: list[dict] = []
    for (map_name, demand_name, scenario_name), rows in sorted(grouped.items()):
        wait_means = [float(row["mean_wait_s"]) for row in rows]
        wait_p95 = [float(row["p95_wait_s"]) for row in rows]
        travel_means = [float(row["mean_travel_s"]) for row in rows]
        travel_p95 = [float(row["p95_travel_s"]) for row in rows]
        speed_means = [float(row["mean_speed_mps"]) for row in rows]
        completion_counts = [float(row["vehicles_count"]) for row in rows]

        summary_rows.append(
            {
                "map": map_name,
                "demand": demand_name,
                "scenario": scenario_name,
                "runs": len(rows),
                "avg_mean_wait_s": round(safe_mean(wait_means), 6),
                "std_mean_wait_s": round(safe_std(wait_means), 6),
                "avg_p95_wait_s": round(safe_mean(wait_p95), 6),
                "avg_mean_travel_s": round(safe_mean(travel_means), 6),
                "std_mean_travel_s": round(safe_std(travel_means), 6),
                "avg_p95_travel_s": round(safe_mean(travel_p95), 6),
                "avg_mean_speed_mps": round(safe_mean(speed_means), 6),
                "avg_vehicles_count": round(safe_mean(completion_counts), 2),
            }
        )

    summary_file = batch_dir / "summary_by_group.csv"
    summary_fields = [
        "map",
        "demand",
        "scenario",
        "runs",
        "avg_mean_wait_s",
        "std_mean_wait_s",
        "avg_p95_wait_s",
        "avg_mean_travel_s",
        "std_mean_travel_s",
        "avg_p95_travel_s",
        "avg_mean_speed_mps",
        "avg_vehicles_count",
    ]
    write_csv(summary_file, summary_rows, summary_fields)

    by_map_demand: dict[tuple[str, str], dict[str, dict]] = {}
    for row in summary_rows:
        key = (str(row["map"]), str(row["demand"]))
        by_map_demand.setdefault(key, {})[str(row["scenario"])] = row

    delta_rows: list[dict] = []
    for (map_name, demand_name), scenarios in sorted(by_map_demand.items()):
        baseline = scenarios.get("mp_base")
        if baseline is None:
            continue
        base_wait = float(baseline["avg_mean_wait_s"])
        base_travel = float(baseline["avg_mean_travel_s"])

        for scenario_name, row in sorted(scenarios.items()):
            wait = float(row["avg_mean_wait_s"])
            travel = float(row["avg_mean_travel_s"])
            wait_delta = ((wait - base_wait) / base_wait * 100.0) if base_wait > 0 else 0.0
            travel_delta = ((travel - base_travel) / base_travel * 100.0) if base_travel > 0 else 0.0
            delta_rows.append(
                {
                    "map": map_name,
                    "demand": demand_name,
                    "scenario": scenario_name,
                    "avg_mean_wait_s": row["avg_mean_wait_s"],
                    "avg_mean_travel_s": row["avg_mean_travel_s"],
                    "wait_delta_vs_base_pct": round(wait_delta, 4),
                    "travel_delta_vs_base_pct": round(travel_delta, 4),
                }
            )

    delta_file = batch_dir / "summary_vs_base.csv"
    delta_fields = [
        "map",
        "demand",
        "scenario",
        "avg_mean_wait_s",
        "avg_mean_travel_s",
        "wait_delta_vs_base_pct",
        "travel_delta_vs_base_pct",
    ]
    write_csv(delta_file, delta_rows, delta_fields)

    md_lines = [f"# Ablation Summary - {run_id}", ""]
    failed_runs = [row for row in run_rows if row["status"] != "ok"]
    md_lines.append(f"- Total runs: {len(run_rows)}")
    md_lines.append(f"- Successful runs: {len(ok_rows)}")
    md_lines.append(f"- Failed runs: {len(failed_runs)}")
    md_lines.append("")

    for (map_name, demand_name), scenarios in sorted(by_map_demand.items()):
        rows_md: list[list[str]] = []
        for scenario_name, row in sorted(
            scenarios.items(), key=lambda item: float(item[1]["avg_mean_wait_s"])
        ):
            matching_delta = next(
                (
                    d
                    for d in delta_rows
                    if d["map"] == map_name and d["demand"] == demand_name and d["scenario"] == scenario_name
                ),
                None,
            )
            wait_delta = (
                f"{matching_delta['wait_delta_vs_base_pct']:+.2f}%"
                if matching_delta is not None
                else "n/a"
            )
            travel_delta = (
                f"{matching_delta['travel_delta_vs_base_pct']:+.2f}%"
                if matching_delta is not None
                else "n/a"
            )
            rows_md.append(
                [
                    scenario_name,
                    f"{float(row['avg_mean_wait_s']):.2f}",
                    wait_delta,
                    f"{float(row['avg_mean_travel_s']):.2f}",
                    travel_delta,
                    f"{float(row['avg_p95_wait_s']):.2f}",
                    f"{float(row['avg_p95_travel_s']):.2f}",
                    f"{float(row['avg_mean_speed_mps']):.2f}",
                    str(row["runs"]),
                ]
            )

        md_lines.append(f"## {map_name} - {demand_name}")
        md_lines.append(
            markdown_table(
                [
                    "Scenario",
                    "MeanWait[s]",
                    "DeltaWait",
                    "MeanTravel[s]",
                    "DeltaTravel",
                    "P95Wait[s]",
                    "P95Travel[s]",
                    "MeanSpeed[m/s]",
                    "Runs",
                ],
                rows_md,
            )
        )
        md_lines.append("")

    (batch_dir / "summary.md").write_text("\n".join(md_lines), encoding="utf-8")

    current_activity = "batch completato"
    current_run_id = ""
    current_run_meta = None
    current_run_started_at = None
    current_run_step = None
    if failed_runs and len(failed_runs) == len(run_rows):
        write_progress_files(
            status="failed",
            error_message="tutti i run sono falliti; controlla stdout_stderr.log dei run e le dipendenze SUMO/TraCI",
        )
    elif failed_runs:
        write_progress_files(status="completed_with_errors")
    else:
        write_progress_files(status="completed")

    print(f"\nRun completato: {run_id}")
    print(f"- Cartella run:     {batch_dir}")
    print(f"- Run-level results: {run_results_file}")
    print(f"- Summary by group: {summary_file}")
    print(f"- Summary vs base:  {delta_file}")
    print(f"- Markdown report:  {batch_dir / 'summary.md'}")
    print(f"- Progress (ultimo run): {ablation_root / 'progress.txt'}")
    print(f"- Puntatore latest:      {ablation_root / 'latest_run.txt'}")


if __name__ == "__main__":
    main()
