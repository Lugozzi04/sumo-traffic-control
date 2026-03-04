import argparse
import random
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera popolazione veicoli (YAML)")
    parser.add_argument("-n", "--map-name", dest="map_name", required=True, help="Nome scenario")
    parser.add_argument("-o", "--output", dest="output", required=True, help="File YAML output")
    parser.add_argument("-N", "--vehicle-number", dest="vehicle_number", type=int, required=True, help="Numero veicoli")
    parser.add_argument("--start-time", type=float, default=0.0, help="Inizio finestra partenze (s)")
    parser.add_argument("--end-time", type=float, default=3600.0, help="Fine finestra partenze (s)")
    parser.add_argument("--seed", type=int, default=42, help="Seed random")
    return parser.parse_args()


def load_route_ids(map_name: str) -> list[str]:
    route_file = route_file_path(map_name)
    tree = ET.parse(route_file)
    root = tree.getroot()
    route_ids = [route.get("id") for route in root.findall("route") if route.get("id")]

    if not route_ids:
        raise ValueError(f"Nessuna route trovata in {route_file}")

    return route_ids


def build_population(route_ids: list[str], n_vehicles: int, start_time: float, end_time: float, seed: int):
    rng = random.Random(seed)
    type_ids = list(DEFAULT_TYPE_DISTRIBUTION.keys())
    weights = list(DEFAULT_TYPE_DISTRIBUTION.values())

    population = []
    for idx in range(n_vehicles):
        depart = rng.uniform(start_time, end_time)
        population.append(
            {
                "vehicle_id": f"veh{idx}",
                "route_id": rng.choice(route_ids),
                "depart": round(depart, 2),
                "type_id": rng.choices(type_ids, weights=weights, k=1)[0],
            }
        )

    population.sort(key=lambda item: item["depart"])
    return population


def main() -> None:
    args = parse_args()
    route_ids = load_route_ids(args.map_name)
    population = build_population(route_ids, args.vehicle_number, args.start_time, args.end_time, args.seed)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as fd:
        yaml.safe_dump(population, fd, sort_keys=False)

    print(f"Popolazione creata: {output} ({len(population)} veicoli)")


if __name__ == "__main__":
    main()
