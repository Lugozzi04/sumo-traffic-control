from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

import traci
import yaml

from .paths import route_file_path


DEFAULT_VTYPES = {
    "passenger": {
        "vClass": "passenger",
        "length": "4.8",
        "accel": "2.6",
        "decel": "4.5",
        "emergencyDecel": "9.0",
        "minGap": "2.5",
        "emissionClass": "HBEFA4/PC_petrol_Euro-6ab",
        "color": "#3498DB",
        "guiShape": "passenger/sedan",
    },
    "delivery": {
        "vClass": "delivery",
        "length": "6.0",
        "accel": "2.0",
        "decel": "4.0",
        "emergencyDecel": "8.0",
        "minGap": "2.5",
        "emissionClass": "HBEFA4/LCV_diesel_N1-II_Euro-6ab",
        "color": "#FFFFFF",
        "guiShape": "delivery",
    },
    "truck": {
        "vClass": "truck",
        "length": "12.0",
        "accel": "1.2",
        "decel": "3.5",
        "emergencyDecel": "7.0",
        "minGap": "3.0",
        "emissionClass": "HBEFA4/TT_AT_gt34-40t_Euro-VI_A-C",
        "color": "#C0392B",
        "guiShape": "truck",
    },
    "bus": {
        "vClass": "bus",
        "length": "12.0",
        "accel": "1.3",
        "decel": "3.5",
        "emergencyDecel": "7.0",
        "minGap": "3.0",
        "emissionClass": "HBEFA4/UBus_Std_gt15-18t_Euro-VI_A-C",
        "color": "#28B463",
        "guiShape": "bus",
    },
    "motorcycle": {
        "vClass": "motorcycle",
        "length": "2.5",
        "accel": "4.0",
        "decel": "4.5",
        "emergencyDecel": "8.0",
        "minGap": "1.5",
        "emissionClass": "HBEFA4/MC_4S_gt250cc_Euro-5",
        "color": "#8E44AD",
        "guiShape": "motorcycle",
    },
}


@dataclass
class VehicleInput:
    vehicle_id: str
    route_id: str
    depart: float
    type_id: str


def load_population(filename: Path) -> list[VehicleInput]:
    with filename.open("r", encoding="utf-8") as fd:
        raw = yaml.safe_load(fd)

    if not isinstance(raw, list):
        raise ValueError("Il file popolazione deve contenere una lista YAML")

    population = []
    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"Record non valido in posizione {idx}")

        type_id = str(row.get("type_id", "passenger"))
        if type_id not in DEFAULT_VTYPES:
            raise ValueError(f"type_id non supportato: {type_id}")

        population.append(
            VehicleInput(
                vehicle_id=str(row.get("vehicle_id", f"veh{idx}")),
                route_id=str(row["route_id"]),
                depart=float(row.get("depart", 0.0)),
                type_id=type_id,
            )
        )

    return population


def validate_population_routes(map_name: str, population: list[VehicleInput]) -> None:
    route_tree = ET.parse(route_file_path(map_name))
    route_root = route_tree.getroot()
    valid_route_ids = {route.get("id") for route in route_root.findall("route") if route.get("id")}

    invalid = sorted({vehicle.route_id for vehicle in population if vehicle.route_id not in valid_route_ids})
    if invalid:
        sample = ", ".join(invalid[:5])
        raise ValueError(f"Route non valide nella popolazione: {sample}")


def generate_vehicle_types_file(filename: Path, population: list[VehicleInput]) -> None:
    root = ET.Element("routes")
    for type_id in sorted({vehicle.type_id for vehicle in population}):
        attrs = {"id": type_id}
        attrs.update(DEFAULT_VTYPES[type_id])
        ET.SubElement(root, "vType", attrs)

    tree = ET.ElementTree(root)
    tree.write(filename, encoding="utf-8", xml_declaration=True)


def add_vehicles_to_simulation(population: list[VehicleInput]) -> None:
    for vehicle in population:
        depart = f"{vehicle.depart:.2f}".rstrip("0").rstrip(".")
        traci.vehicle.add(
            vehID=vehicle.vehicle_id,
            routeID=vehicle.route_id,
            typeID=vehicle.type_id,
            depart=depart,
            departLane="best",
            departSpeed="max",
        )
