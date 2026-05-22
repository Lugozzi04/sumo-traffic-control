import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
import tempfile

import traci

from src.controllers.fixed_time import FixedTimeController
from src.controllers.max_pressure import MaxPressureController
from src.metrics import aggregate_runs, write_metrics_csv, MetricsCollector
from src.paths import logs_dir, sumocfg_path, vehicletypes_path
from src.population import (
    add_vehicles_to_simulation,
    depart_speed_mode_for_profile,
    generate_vehicle_types_file,
    load_population,
    validate_population_routes,
)


SIM_RUN_PATTERN = re.compile(r"^sim_(\d+)_")


def allocate_simulation_output_dir() -> tuple[str, Path]:
    simulations_root = logs_dir() / "simulations"
    simulations_root.mkdir(parents=True, exist_ok=True)

    max_index = 0
    for child in simulations_root.iterdir():
        if not child.is_dir():
            continue
        match = SIM_RUN_PATTERN.match(child.name)
        if not match:
            continue
        max_index = max(max_index, int(match.group(1)))

    run_index = max_index + 1
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_id = f"sim_{run_index:04d}_{timestamp}"
    run_dir = simulations_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_id, run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Runner template per simulazioni SUMO")
    parser.add_argument("-n", "--map-name", dest="map_name", required=True, help="Nome scenario (cartella in sumo_xml_files)")
    parser.add_argument("-p", "--population-file", dest="population_file", required=True, help="YAML popolazione")
    parser.add_argument("--controller", choices=["fixed", "mp"], default="fixed", help="Controller semaforico")
    parser.add_argument("--gui", action="store_true", help="Usa sumo-gui invece di sumo")
    parser.add_argument("--step-length", type=float, default=1.0, help="Durata step simulazione in secondi")
    parser.add_argument("--repeat", type=int, default=1, help="Ripeti l'esperimento e media i risultati")
    parser.add_argument("--max-steps", type=int, default=0, help="Stop anticipato (0 = nessun limite)")
    parser.add_argument("--output-log", default="", help="Path CSV di output (opzionale)")
    parser.add_argument(
        "--driver-profile",
        choices=["default", "human_light"],
        default="default",
        help="Profilo guidatore globale applicato ai vType (default o human_light)",
    )
    parser.add_argument(
        "--human-light",
        action="store_true",
        help="Scorciatoia per --driver-profile human_light",
    )
    parser.add_argument("--min-green", type=float, default=10.0, help="Minimo tempo di verde per phase hold")
    parser.add_argument("--max-green", type=float, default=120.0, help="Massimo tempo di verde prima di forzare rivalutazione")
    parser.add_argument("--switch-epsilon", type=float, default=0.0, help="Margine minimo di pressione per cambiare fase")
    parser.add_argument(
        "--switch-epsilon-rel",
        type=float,
        default=0.0,
        help="Margine relativo additivo: eps_rel * |score_fase_corrente|",
    )
    parser.add_argument("--lost-time-aware", action="store_true", help="Abilita isteresi proporzionale al costo di switch (yellow+all-red)")
    parser.add_argument("--lost-time-sat-flow", type=float, default=0.5, help="Flusso di saturazione equivalente in veicoli/s (riusato da LTA e Nmin dinamico)")
    parser.add_argument("--lost-time-gain", type=float, default=1.0, help="Guadagno del margine di isteresi lost-time-aware")
    parser.add_argument("--program0-hybrid", action="store_true", help="Abilita MP_program0: in low segue program0, in high torna MP")
    parser.add_argument("--program0-load-ref", type=float, default=3.0, help="Densita' di domanda di riferimento per attivare il passaggio da program0 a MP")
    parser.add_argument("--program0-enter-mp-load", type=float, default=0.55, help="Soglia load per entrare in modalita' MP")
    parser.add_argument("--program0-exit-fixed-load", type=float, default=0.35, help="Soglia load per tornare alla modalita' fixed/program0")
    parser.add_argument("--program0-mode-streak", type=int, default=3, help="Numero minimo di step consecutivi oltre soglia per cambiare modalita'")
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
    parser.add_argument(
        "--nmin-min-green",
        type=float,
        default=-1.0,
        help="Minimo verde usato dal blocco Nmin (negativo = usa --min-green)",
    )
    parser.add_argument(
        "--nmin-demand-gain",
        type=float,
        default=0.0,
        help="Quota di domanda corrente inclusa in Nmin target (0 = off)",
    )
    parser.add_argument("--nmin-empty-release-seconds", type=float, default=2.0, help="Rilascio anticipato se la fase resta vuota per questo tempo")
    parser.add_argument("--spillback", action="store_true", help="Abilita vincolo hard anti-spillback sui rami a valle (solo controller MP)")
    parser.add_argument("--spillback-on", type=float, default=0.85, help="Soglia ON dello score downstream [0-1]")
    parser.add_argument("--spillback-off", type=float, default=0.70, help="Soglia OFF dello score downstream [0-1]")
    parser.add_argument("--spillback-min-halts", type=int, default=2, help="Min veicoli fermi richiesti per attivare blocco")
    parser.add_argument("--spillback-alpha", type=float, default=0.5, help="Fattore EMA occupazione downstream [0-1]")
    parser.add_argument(
        "--fixed-program-id",
        default="",
        help="Con controller fixed, forza questo programID TLS (es. 0). Vuoto = programma di default mappa",
    )
    parser.add_argument(
        "--fixed-main-green-seconds",
        type=float,
        default=0.0,
        help="Con controller fixed, forza durata [s] delle fasi principali verdi (0 = off)",
    )
    parser.add_argument(
        "--fixed-main-green-scale",
        type=float,
        default=1.0,
        help="Con controller fixed, scala durata fasi principali verdi (1.0 = off)",
    )

    args = parser.parse_args()
    if args.human_light:
        args.driver_profile = "human_light"
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
    if args.program0_load_ref <= 0:
        parser.error("--program0-load-ref deve essere > 0")
    if not 0.0 <= args.program0_enter_mp_load <= 1.0:
        parser.error("--program0-enter-mp-load deve essere nel range [0, 1]")
    if not 0.0 <= args.program0_exit_fixed_load <= 1.0:
        parser.error("--program0-exit-fixed-load deve essere nel range [0, 1]")
    if args.program0_exit_fixed_load > args.program0_enter_mp_load:
        parser.error("--program0-exit-fixed-load deve essere <= --program0-enter-mp-load")
    if args.program0_mode_streak < 1:
        parser.error("--program0-mode-streak deve essere >= 1")
    if args.switch_epsilon_rel < 0:
        parser.error("--switch-epsilon-rel deve essere >= 0")
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
    if args.nmin_min_green < 0 and args.nmin_min_green != -1.0:
        parser.error("--nmin-min-green deve essere >= 0 oppure -1")
    if args.nmin_demand_gain < 0:
        parser.error("--nmin-demand-gain deve essere >= 0")
    if args.nmin_empty_release_seconds < 0:
        parser.error("--nmin-empty-release-seconds deve essere >= 0")
    if args.fixed_main_green_seconds < 0:
        parser.error("--fixed-main-green-seconds deve essere >= 0")
    if args.fixed_main_green_scale <= 0:
        parser.error("--fixed-main-green-scale deve essere > 0")
    return args


def start_sumo(map_name: str, gui: bool, step_length: float, tripinfo_output: Path | None = None) -> None:
    cfg = sumocfg_path(map_name)
    binary = "sumo-gui" if gui else "sumo"
    cmd = [
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
    if tripinfo_output is not None:
        cmd.extend(["--tripinfo-output", str(tripinfo_output)])
    traci.start(cmd)


def build_controller(name: str, args: argparse.Namespace):
    if name == "mp":
        return MaxPressureController(
            min_green=args.min_green,
            max_green=args.max_green,
            switch_epsilon=args.switch_epsilon,
            switch_epsilon_rel=args.switch_epsilon_rel,
            lost_time_aware=args.lost_time_aware,
            lost_time_sat_flow=args.lost_time_sat_flow,
            lost_time_gain=args.lost_time_gain,
            program0_hybrid=args.program0_hybrid,
            program0_load_ref=args.program0_load_ref,
            program0_enter_mp_load=args.program0_enter_mp_load,
            program0_exit_fixed_load=args.program0_exit_fixed_load,
            program0_mode_streak=args.program0_mode_streak,
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
            nmin_min_green=args.nmin_min_green,
            nmin_demand_gain=args.nmin_demand_gain,
            nmin_empty_release_seconds=args.nmin_empty_release_seconds,
            hard_spillback=args.spillback,
            spillback_on=args.spillback_on,
            spillback_off=args.spillback_off,
            spillback_min_halts=args.spillback_min_halts,
            spillback_alpha=args.spillback_alpha,
        )
    return FixedTimeController(
        program_id=args.fixed_program_id,
        main_green_seconds=args.fixed_main_green_seconds,
        main_green_scale=args.fixed_main_green_scale,
    )


def run_once(args: argparse.Namespace, population_file: Path) -> tuple[dict, dict, dict]:
    population = load_population(population_file)
    validate_population_routes(args.map_name, population)
    generate_vehicle_types_file(
        vehicletypes_path(),
        population,
        driver_profile=args.driver_profile,
    )

    with tempfile.NamedTemporaryFile(prefix="sumo_tripinfo_", suffix=".xml", delete=False) as tmp_fd:
        tripinfo_path = Path(tmp_fd.name)

    metrics = MetricsCollector()
    controller = build_controller(args.controller, args)
    active_vehicles: set[str] = set()
    controller_stats: dict = {}
    run_summary: dict = {}

    try:
        start_sumo(args.map_name, args.gui, args.step_length, tripinfo_output=tripinfo_path)
        add_vehicles_to_simulation(
            population,
            depart_speed_mode=depart_speed_mode_for_profile(args.driver_profile),
        )

        controller.attach_to_all_traffic_lights()

        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            controller.step()

            active_vehicles.update(traci.simulation.getDepartedIDList())
            active_vehicles.difference_update(traci.simulation.getArrivedIDList())

            metrics.capture_step(active_vehicles, traci.simulation.getDeltaT())

            if args.max_steps > 0 and traci.simulation.getTime() >= args.max_steps:
                break

        if hasattr(controller, "get_runtime_stats"):
            try:
                controller_stats = controller.get_runtime_stats()
            except Exception:
                controller_stats = {}
    finally:
        try:
            traci.close()
        except Exception:
            pass
    try:
        run_summary = metrics.finalize_tripinfo(tripinfo_path, {vehicle.vehicle_id for vehicle in population})
        return metrics.snapshot(), controller_stats, run_summary
    finally:
        try:
            tripinfo_path.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass


def main() -> None:
    args = parse_args()
    population_file = Path(args.population_file)
    all_runs = []
    all_controller_stats = []
    all_run_summaries = []

    for index in range(args.repeat):
        print(f"[run {index + 1}/{args.repeat}] Avvio simulazione...")
        run_metrics, run_stats, run_summary = run_once(args, population_file)
        all_runs.append(run_metrics)
        all_controller_stats.append(run_stats)
        all_run_summaries.append(run_summary)

    merged = aggregate_runs(all_runs)
    if args.output_log:
        output = Path(args.output_log)
        output.parent.mkdir(parents=True, exist_ok=True)
        run_dir: Path | None = None
    else:
        _, run_dir = allocate_simulation_output_dir()
        output = run_dir / "vehicle_metrics.csv"

    write_metrics_csv(output, merged)
    write_sidecars = str(output) != "/dev/null"
    controller_stats_output = output.with_suffix(".controller_stats.json") if write_sidecars else None
    run_summary_output = output.with_suffix(".run_summary.json") if write_sidecars else None
    if write_sidecars and all_controller_stats and controller_stats_output is not None:
        mean_stats: dict[str, float] = {}
        keys = sorted({key for stats in all_controller_stats for key in stats.keys()})
        for key in keys:
            values = [float(stats.get(key, 0.0)) for stats in all_controller_stats]
            mean_stats[key] = sum(values) / float(len(values))
        controller_stats_payload = {
            "repeat": args.repeat,
            "controller": args.controller,
            "stats_mean": mean_stats,
            "stats_per_run": all_controller_stats,
        }
        controller_stats_output.write_text(json.dumps(controller_stats_payload, indent=2), encoding="utf-8")

    if write_sidecars and all_run_summaries and run_summary_output is not None:
        mean_summary: dict[str, float] = {}
        keys = sorted({key for summary in all_run_summaries for key in summary.keys()})
        for key in keys:
            values = [float(summary.get(key, 0.0)) for summary in all_run_summaries]
            mean_summary[key] = sum(values) / float(len(values))
        run_summary_payload = {
            "repeat": args.repeat,
            "summary_mean": mean_summary,
            "summary_per_run": all_run_summaries,
        }
        run_summary_output.write_text(json.dumps(run_summary_payload, indent=2), encoding="utf-8")

    if run_dir is not None:
        run_info = {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "map_name": args.map_name,
            "population_file": str(population_file),
            "controller": args.controller,
            "repeat": args.repeat,
            "step_length": args.step_length,
            "max_steps": args.max_steps,
            "gui": args.gui,
            "driver_profile": args.driver_profile,
            "output_metrics_file": str(output),
            "controller_stats_file": str(controller_stats_output) if controller_stats_output is not None else "",
            "run_summary_file": str(run_summary_output) if run_summary_output is not None else "",
        }
        (run_dir / "run_info.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")
        print(f"Simulazione salvata in: {run_dir}")

    print(f"Log salvato in: {output}")


if __name__ == "__main__":
    main()
