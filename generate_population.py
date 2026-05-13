import argparse
import random
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

import yaml

from src.paths import route_file_path


DEFAULT_TYPE_DISTRIBUTION = {
    "passenger": 0.75,
    "delivery": 0.10,
    "motorcycle": 0.10,
    "truck": 0.03,
    "bus": 0.02,
}


@dataclass(frozen=True)
class RouteInfo:
    route_id: str
    edge_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera popolazione veicoli (YAML)")
    parser.add_argument("-n", "--map-name", dest="map_name", required=True, help="Nome scenario")
    parser.add_argument("-o", "--output", dest="output", required=True, help="File YAML output")
    parser.add_argument("-N", "--vehicle-number", dest="vehicle_number", type=int, required=True, help="Numero veicoli")
    parser.add_argument("--start-time", type=float, default=0.0, help="Inizio finestra partenze (s)")
    parser.add_argument("--end-time", type=float, default=3600.0, help="Fine finestra partenze (s)")
    parser.add_argument("--seed", type=int, default=42, help="Seed random")
    parser.add_argument(
        "--route-sampling",
        choices=["uniform", "edge_weighted"],
        default="uniform",
        help="Metodo campionamento route",
    )
    parser.add_argument(
        "--route-weight-exponent",
        type=float,
        default=1.0,
        help="Esponente peso route per edge_weighted",
    )
    parser.add_argument(
        "--depart-profile",
        choices=["uniform", "peaked"],
        default="uniform",
        help="Profilo temporale partenze",
    )
    parser.add_argument(
        "--peak-factor",
        type=float,
        default=0.75,
        help="Intensita picchi partenze [0-1] se depart-profile=peaked",
    )
    args = parser.parse_args()
    if args.route_weight_exponent < 0:
        parser.error("--route-weight-exponent deve essere >= 0")
    if not 0.0 <= args.peak_factor <= 1.0:
        parser.error("--peak-factor deve essere nel range [0, 1]")
    return args


def load_route_infos(map_name: str) -> list[RouteInfo]:
    route_file = route_file_path(map_name)
    tree = ET.parse(route_file)
    root = tree.getroot()
    route_infos: list[RouteInfo] = []
    for route in root.findall("route"):
        route_id = route.get("id")
        if not route_id:
            continue
        edges_attr = route.get("edges", "").strip()
        edge_count = len(edges_attr.split()) if edges_attr else 1
        route_infos.append(RouteInfo(route_id=route_id, edge_count=max(1, edge_count)))

    if not route_infos:
        raise ValueError(f"Nessuna route trovata in {route_file}")

    return route_infos


def _draw_departure_fraction(rng: random.Random, depart_profile: str, peak_factor: float) -> float:
    if depart_profile == "uniform":
        return rng.random()

    # Two broad peaks (commute-like) blended with uniform to control aggressiveness.
    if rng.random() < 0.55:
        peaked = rng.betavariate(3.0, 5.0)
    else:
        peaked = rng.betavariate(5.0, 3.0)
    base = rng.random()
    return peak_factor * peaked + (1.0 - peak_factor) * base


def build_population(
    route_infos: list[RouteInfo],
    n_vehicles: int,
    start_time: float,
    end_time: float,
    seed: int,
    route_sampling: str,
    route_weight_exponent: float,
    depart_profile: str,
    peak_factor: float,
):
    rng = random.Random(seed)
    type_ids = list(DEFAULT_TYPE_DISTRIBUTION.keys())
    weights = list(DEFAULT_TYPE_DISTRIBUTION.values())
    route_ids = [route.route_id for route in route_infos]
    if route_sampling == "edge_weighted":
        route_weights = [float(route.edge_count) ** route_weight_exponent for route in route_infos]
    else:
        route_weights = None
    span = max(0.0, end_time - start_time)

    population = []
    for idx in range(n_vehicles):
        if span == 0.0:
            depart = start_time
        else:
            depart = start_time + _draw_departure_fraction(rng, depart_profile, peak_factor) * span
        if route_weights is None:
            route_id = rng.choice(route_ids)
        else:
            route_id = rng.choices(route_ids, weights=route_weights, k=1)[0]
        population.append(
            {
                "vehicle_id": f"veh{idx}",
                "route_id": route_id,
                "depart": round(depart, 2),
                "type_id": rng.choices(type_ids, weights=weights, k=1)[0],
            }
        )

    population.sort(key=lambda item: item["depart"])
    return population


def main() -> None:
    args = parse_args()
    route_infos = load_route_infos(args.map_name)
    population = build_population(
        route_infos,
        args.vehicle_number,
        args.start_time,
        args.end_time,
        args.seed,
        args.route_sampling,
        args.route_weight_exponent,
        args.depart_profile,
        args.peak_factor,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as fd:
        yaml.safe_dump(population, fd, sort_keys=False)

    print(f"Popolazione creata: {output} ({len(population)} veicoli)")


if __name__ == "__main__":
    main()
