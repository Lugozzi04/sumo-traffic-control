from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUMO_XML_DIR = PROJECT_ROOT / "sumo_xml_files"


def scenario_dir(map_name: str) -> Path:
    path = SUMO_XML_DIR / map_name
    if not path.exists():
        raise FileNotFoundError(f"Scenario non trovato: {path}")
    return path


def sumocfg_path(map_name: str) -> Path:
    path = scenario_dir(map_name) / f"{map_name}.sumocfg"
    if not path.exists():
        raise FileNotFoundError(f"Config SUMO non trovata: {path}")
    return path


def route_file_path(map_name: str) -> Path:
    path = scenario_dir(map_name) / f"{map_name}.rou.xml"
    if not path.exists():
        raise FileNotFoundError(f"Route file non trovato: {path}")
    return path


def vehicletypes_path() -> Path:
    return SUMO_XML_DIR / "vehicletypes.rou.xml"


def logs_dir() -> Path:
    return PROJECT_ROOT / "logs"
