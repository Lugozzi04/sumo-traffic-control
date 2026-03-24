import argparse
import time
from pathlib import Path

import traci

from src.controllers.fixed_time import FixedTimeController
from src.controllers.max_pressure import MaxPressureController
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
    parser.add_argument("--controller", choices=["fixed", "mp"], default="fixed", help="Controller semaforico")
    parser.add_argument("--gui", action="store_true", help="Usa sumo-gui invece di sumo")
    parser.add_argument("--step-length", type=float, default=1.0, help="Durata step simulazione in secondi")
    parser.add_argument("--repeat", type=int, default=1, help="Ripeti l'esperimento e media i risultati")
    parser.add_argument("--max-steps", type=int, default=0, help="Stop anticipato (0 = nessun limite)")
    parser.add_argument("--min-green", type=float, default=10.0, help="Minimo tempo di verde per phase hold")
    parser.add_argument("--max-green", type=float, default=120.0, help="Massimo tempo di verde prima di forzare rivalutazione")
    parser.add_argument("--switch-epsilon", type=float, default=0.0, help="Margine minimo di pressione per cambiare fase")
    parser.add_argument("--lost-time-aware", action="store_true", help="Abilita isteresi proporzionale al costo di switch (yellow+all-red)")
    parser.add_argument("--lost-time-sat-flow", type=float, default=0.5, help="Flusso di saturazione equivalente in veicoli/s (riusato da LTA e Nmin dinamico)")
    parser.add_argument("--lost-time-gain", type=float, default=1.0, help="Guadagno del margine di isteresi lost-time-aware")
    parser.add_argument("--fairness", action="store_true", help="Abilita fairness con impatience saturata")
    parser.add_argument("--fairness-mu", type=float, default=5.0, help="Peso massimo del bonus fairness")
    parser.add_argument("--fairness-w-half", type=float, default=30.0, help="Secondi per avere il 50%% del bonus fairness")
    parser.add_argument("--downstream-penalty", action="store_true", help="Abilita penalita continua downstream nel calcolo pressione")
    parser.add_argument("--downstream-beta", type=float, default=5.0, help="Peso della penalita downstream (P -= beta * occ_down)")
    parser.add_argument("--downstream-alpha", type=float, default=0.5, help="Fattore EMA downstream per la penalita [0-1]")
    parser.add_argument("--platoon-extension", action="store_true", help="Abilita estensione verde per arrivi in platoon")
    parser.add_argument("--platoon-headway-threshold", type=float, default=2.0, help="Soglia headway media [s] per riconoscere un platoon")
    parser.add_argument("--platoon-gap-out-seconds", type=float, default=2.5, help="Se non passa nessuno per questo tempo il platoon termina")
    parser.add_argument("--platoon-max-extra-green", type=float, default=8.0, help="Massima estensione verde extra per attivazione fase [s]")
    parser.add_argument("--platoon-guard-occ", type=float, default=0.85, help="Soglia guardia downstream occupazione [0-1] per consentire estensione")
    parser.add_argument("--nmin-dynamic", action="store_true", help="Abilita minimo servizio dinamico dopo ogni switch fase")
    parser.add_argument("--nmin-alpha", type=float, default=1.0, help="Guadagno Nmin dinamico rispetto al costo di switch")
    parser.add_argument("--nmin-floor", type=int, default=2, help="Numero minimo di veicoli equivalenti da servire per attivazione")
    parser.add_argument("--nmin-empty-release-seconds", type=float, default=2.0, help="Rilascio anticipato se la fase resta vuota per questo tempo")
    parser.add_argument("--spillback", action="store_true", help="Abilita vincolo hard anti-spillback sui rami a valle (solo controller MP)")
    parser.add_argument("--spillback-on", type=float, default=0.90, help="Soglia ON occupazione downstream [0-1]")
    parser.add_argument("--spillback-off", type=float, default=0.75, help="Soglia OFF occupazione downstream [0-1]")
    parser.add_argument("--spillback-min-halts", type=int, default=1, help="Min veicoli fermi richiesti per attivare blocco")
    parser.add_argument("--spillback-alpha", type=float, default=0.5, help="Fattore EMA occupazione downstream [0-1]")

    args = parser.parse_args()
    if not 0.0 <= args.spillback_off <= args.spillback_on <= 1.0:
        parser.error("Richiesto: 0 <= --spillback-off <= --spillback-on <= 1")
    if args.spillback_min_halts < 0:
        parser.error("--spillback-min-halts deve essere >= 0")
    if not 0.0 <= args.spillback_alpha <= 1.0:
        parser.error("--spillback-alpha deve essere nel range [0, 1]")
    if args.lost_time_sat_flow < 0:
        parser.error("--lost-time-sat-flow deve essere >= 0")
    if (args.lost_time_aware or args.nmin_dynamic) and args.lost_time_sat_flow <= 0:
        parser.error("--lost-time-sat-flow deve essere > 0 se abiliti --lost-time-aware e/o --nmin-dynamic")
    if args.lost_time_gain < 0:
        parser.error("--lost-time-gain deve essere >= 0")
    if args.fairness_mu < 0:
        parser.error("--fairness-mu deve essere >= 0")
    if args.fairness_w_half < 0:
        parser.error("--fairness-w-half deve essere >= 0")
    if args.downstream_beta < 0:
        parser.error("--downstream-beta deve essere >= 0")
    if not 0.0 <= args.downstream_alpha <= 1.0:
        parser.error("--downstream-alpha deve essere nel range [0, 1]")
    if args.platoon_headway_threshold < 0:
        parser.error("--platoon-headway-threshold deve essere >= 0")
    if args.platoon_gap_out_seconds < 0:
        parser.error("--platoon-gap-out-seconds deve essere >= 0")
    if args.platoon_max_extra_green < 0:
        parser.error("--platoon-max-extra-green deve essere >= 0")
    if not 0.0 <= args.platoon_guard_occ <= 1.0:
        parser.error("--platoon-guard-occ deve essere nel range [0, 1]")
    if args.nmin_alpha < 0:
        parser.error("--nmin-alpha deve essere >= 0")
    if args.nmin_floor < 0:
        parser.error("--nmin-floor deve essere >= 0")
    if args.nmin_empty_release_seconds < 0:
        parser.error("--nmin-empty-release-seconds deve essere >= 0")
    return args


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


def build_controller(name: str, args: argparse.Namespace):
    if name == "mp":
        return MaxPressureController(
            min_green=args.min_green,
            max_green=args.max_green,
            switch_epsilon=args.switch_epsilon,
            lost_time_aware=args.lost_time_aware,
            lost_time_sat_flow=args.lost_time_sat_flow,
            lost_time_gain=args.lost_time_gain,
            fairness=args.fairness,
            fairness_mu=args.fairness_mu,
            fairness_w_half=args.fairness_w_half,
            downstream_penalty=args.downstream_penalty,
            downstream_beta=args.downstream_beta,
            downstream_alpha=args.downstream_alpha,
            platoon_extension=args.platoon_extension,
            platoon_headway_threshold=args.platoon_headway_threshold,
            platoon_gap_out_seconds=args.platoon_gap_out_seconds,
            platoon_max_extra_green=args.platoon_max_extra_green,
            platoon_guard_occ=args.platoon_guard_occ,
            nmin_dynamic=args.nmin_dynamic,
            nmin_alpha=args.nmin_alpha,
            nmin_floor=args.nmin_floor,
            nmin_empty_release_seconds=args.nmin_empty_release_seconds,
            hard_spillback=args.spillback,
            spillback_on=args.spillback_on,
            spillback_off=args.spillback_off,
            spillback_min_halts=args.spillback_min_halts,
            spillback_alpha=args.spillback_alpha,
        )
    return FixedTimeController()


def run_once(args: argparse.Namespace, population_file: Path) -> dict:
    population = load_population(population_file)
    validate_population_routes(args.map_name, population)
    generate_vehicle_types_file(vehicletypes_path(), population)

    start_sumo(args.map_name, args.gui, args.step_length)
    add_vehicles_to_simulation(population)

    controller = build_controller(args.controller, args)
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
