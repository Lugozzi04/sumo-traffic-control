import argparse
import time
from pathlib import Path

import traci

from src.controllers.fixed_time import FixedTimeController
from src.controllers.smart_template import SmartTemplateController
from src.metrics import aggregate_runs, write_metrics_csv, MetricsCollector
from src.paths import logs_dir, sumocfg_path, vehicletypes_path
from src.population import (
    add_vehicles_to_simulation,
    generate_vehicle_types_file,
    load_population,
    validate_population_routes,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Runner template per simulazioni SUMO")
    parser.add_argument("-n", "--map-name", dest="map_name", required=True, help="Nome scenario (cartella in sumo_xml_files)")
    parser.add_argument("-p", "--population-file", dest="population_file", required=True, help="YAML popolazione")
    parser.add_argument("--controller", choices=["fixed", "smart"], default="fixed", help="Controller semaforico")
    parser.add_argument("--gui", action="store_true", help="Usa sumo-gui invece di sumo")
    parser.add_argument("--step-length", type=float, default=1.0, help="Durata step simulazione in secondi")
    parser.add_argument("--repeat", type=int, default=1, help="Ripeti l'esperimento e media i risultati")
    parser.add_argument("--max-steps", type=int, default=0, help="Stop anticipato (0 = nessun limite)")
    return parser.parse_args()


def start_sumo(map_name: str, gui: bool, step_length: float) -> None:
    cfg = sumocfg_path(map_name)
    binary = "sumo-gui" if gui else "sumo"
    traci.start(
        [
            binary,
            "-c",
            str(cfg),
            "--step-length",
            str(step_length),
            "--waiting-time-memory",
            "3000",
            "--start",
            "--quit-on-end",
        ]
    )


def build_controller(name: str):
    if name == "smart":
        return SmartTemplateController()
    return FixedTimeController()


def run_once(args: argparse.Namespace, population_file: Path) -> dict:
    population = load_population(population_file)
    validate_population_routes(args.map_name, population)
    generate_vehicle_types_file(vehicletypes_path(), population)

    start_sumo(args.map_name, args.gui, args.step_length)
    add_vehicles_to_simulation(population)

    controller = build_controller(args.controller)
    controller.attach_to_all_traffic_lights()

    metrics = MetricsCollector()
    active_vehicles = set()

    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        controller.step()

        active_vehicles.update(traci.simulation.getDepartedIDList())
        active_vehicles.difference_update(traci.simulation.getArrivedIDList())

        metrics.capture_step(active_vehicles, traci.simulation.getDeltaT())

        if args.max_steps > 0 and traci.simulation.getTime() >= args.max_steps:
            break

    traci.close()
    return metrics.snapshot()


def main() -> None:
    args = parse_args()
    population_file = Path(args.population_file)
    all_runs = []

    for index in range(args.repeat):
        print(f"[run {index + 1}/{args.repeat}] Avvio simulazione...")
        all_runs.append(run_once(args, population_file))

    merged = aggregate_runs(all_runs)
    logs_dir().mkdir(parents=True, exist_ok=True)

    ts = int(time.time())
    output = logs_dir() / f"log_{args.map_name}_{args.controller}_{ts}.csv"
    write_metrics_csv(output, merged)
    print(f"Log salvato in: {output}")


if __name__ == "__main__":
    main()
