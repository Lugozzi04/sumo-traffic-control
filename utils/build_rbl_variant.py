#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


RBL_NODE_TYPES = {
    "priority",
    "traffic_light",
    "traffic_light_unregulated",
    "traffic_light_right_on_red",
    "right_before_left",
    "left_before_right",
    "unregulated",
    "priority_stop",
    "allway_stop",
    "zipper",
}


def run_cmd(cmd: list[str], cwd: Path) -> None:
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Crea una copia mappa con precedenza a destra (right_before_left) "
            "e segnaletica grafica. Funziona in auto su mappe grid e non-grid."
        )
    )
    parser.add_argument("--src-map", default="manhattan8x8_100pc", help="Mappa sorgente")
    parser.add_argument("--dst-map", default="manhattan8x8_100pc_rbl", help="Mappa destinazione")
    parser.add_argument(
        "--mode",
        choices=["auto", "grid", "patch"],
        default="auto",
        help=(
            "auto=grid se possibile altrimenti patch; "
            "grid=forza netgenerate grid; patch=forza patch netconvert"
        ),
    )
    parser.add_argument("--sign-distance", type=float, default=12.0, help="Distanza segnale dal centro incrocio [m]")
    parser.add_argument("--sign-lateral", type=float, default=2.2, help="Offset laterale segnale lato destro [m]")
    parser.add_argument(
        "--keep-tls",
        action="store_true",
        help="Solo in mode=patch: non rimuove i tls (default: tls rimossi)",
    )
    parser.add_argument("--overwrite", action="store_true", help="Sovrascrivi cartella destinazione se esiste")
    return parser.parse_args()


def read_grid_params(src_netcfg: Path) -> tuple[int, float, int, bool] | None:
    if not src_netcfg.exists():
        return None

    root = ET.parse(src_netcfg).getroot()

    def get_value(path: str, cast, default=None):
        elem = root.find(path)
        if elem is None:
            return default
        value = elem.get("value")
        if value is None:
            return default
        return cast(value)

    grid_enabled = get_value("./grid_network/grid", lambda v: v.lower() == "true", False)
    if not grid_enabled:
        return None

    grid_number = get_value("./grid_network/grid.number", int)
    grid_length = get_value("./grid_network/grid.length", float)
    lanes = get_value("./building_defaults/default.lanenumber", int, 1)
    no_turnarounds = get_value("./junctions/no-turnarounds", lambda v: v.lower() == "true", True)

    if grid_number is None or grid_length is None:
        return None
    return int(grid_number), float(grid_length), int(lanes), bool(no_turnarounds)


def generate_rbl_grid_net(
    project_root: Path,
    dst_net: Path,
    grid_number: int,
    grid_length: float,
    lanes: int,
    no_turnarounds: bool,
) -> None:
    cmd = [
        "netgenerate",
        "--grid",
        "--grid.number",
        str(grid_number),
        "--grid.length",
        str(grid_length),
        "--default.lanenumber",
        str(lanes),
        "--default-junction-type",
        "right_before_left",
        "--output-file",
        str(dst_net),
    ]
    if no_turnarounds:
        cmd.extend(["--no-turnarounds", "true"])
    run_cmd(cmd, cwd=project_root)


def build_rbl_patch_nodes(src_net: Path, patch_file: Path) -> int:
    root = ET.parse(src_net).getroot()
    nodes = ET.Element("nodes")

    count = 0
    for junc in root.findall("junction"):
        junc_id = junc.get("id", "")
        junc_type = junc.get("type", "")
        if not junc_id or junc_id.startswith(":"):
            continue
        if junc_type in {"internal", "dead_end", "rail_signal", "rail_crossing"}:
            continue
        if junc_type and junc_type not in RBL_NODE_TYPES:
            continue
        ET.SubElement(nodes, "node", {"id": junc_id, "type": "right_before_left"})
        count += 1

    ET.indent(nodes, space="    ")
    ET.ElementTree(nodes).write(patch_file, encoding="UTF-8", xml_declaration=True)
    return count


def generate_rbl_patch_net(
    project_root: Path,
    src_net: Path,
    patch_nodes_file: Path,
    dst_net: Path,
    *,
    keep_tls: bool,
) -> None:
    cmd = [
        "netconvert",
        "--sumo-net-file",
        str(src_net),
        "--node-files",
        str(patch_nodes_file),
        "--output-file",
        str(dst_net),
    ]
    if not keep_tls:
        cmd.append("--tls.discard-loaded")
    run_cmd(cmd, cwd=project_root)


def route_edges(route_file: Path) -> set[str]:
    root = ET.parse(route_file).getroot()
    used: set[str] = set()
    for route in root.findall("route"):
        edges = (route.get("edges") or "").split()
        used.update(edges)
    return used


def net_edges(net_file: Path) -> set[str]:
    root = ET.parse(net_file).getroot()
    result: set[str] = set()
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        if not edge_id or edge_id.startswith(":"):
            continue
        result.add(edge_id)
    return result


def write_sumocfg(dst_dir: Path, dst_map: str) -> None:
    sumocfg = dst_dir / f"{dst_map}.sumocfg"
    sumocfg.write_text(
        f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>

<configuration xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:noNamespaceSchemaLocation=\"http://sumo.dlr.de/xsd/sumoConfiguration.xsd\">

    <input>
        <net-file value=\"{dst_map}.net.xml\"/>
        <additional-files value=\"{dst_map}.add.xml\"/>
        <route-files value=\"{dst_map}.rou.xml,../vehicletypes.rou.xml\"/>
    </input>

    <gui-only>
        <gui-settings-file value=\"../realworld.view.xml\"/>
    </gui-only>

</configuration>
""",
        encoding="utf-8",
    )


def write_netcfg_grid(dst_dir: Path, dst_map: str, grid_number: int, grid_length: float, lanes: int) -> None:
    netcfg = dst_dir / f"{dst_map}.netcfg.xml"
    netcfg.write_text(
        f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>

<configuration xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:noNamespaceSchemaLocation=\"http://sumo.dlr.de/xsd/Configuration.xsd\">

    <grid_network>
        <grid value=\"true\"/>
        <grid.number value=\"{grid_number}\"/>
        <grid.length value=\"{grid_length}\"/>
    </grid_network>

    <output>
        <output-file value=\"{dst_map}.net.xml\"/>
    </output>

    <building_defaults>
        <default.lanenumber value=\"{lanes}\"/>
        <default-junction-type value=\"right_before_left\"/>
    </building_defaults>

    <junctions>
        <no-turnarounds value=\"true\"/>
    </junctions>

</configuration>
""",
        encoding="utf-8",
    )


def write_netcfg_patch(dst_dir: Path, dst_map: str, src_map: str, patch_nodes_file: Path, keep_tls: bool) -> None:
    netcfg = dst_dir / f"{dst_map}.netcfg.xml"
    tls_line = "" if keep_tls else "    <tls.discard-loaded value=\"true\"/>\n"
    patch_name = patch_nodes_file.name
    netcfg.write_text(
        f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>

<configuration xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:noNamespaceSchemaLocation=\"http://sumo.dlr.de/xsd/Configuration.xsd\">

    <input>
        <sumo-net-file value=\"../{src_map}/{src_map}.net.xml\"/>
        <node-files value=\"{patch_name}\"/>
    </input>

    <output>
        <output-file value=\"{dst_map}.net.xml\"/>
    </output>

{tls_line}</configuration>
""",
        encoding="utf-8",
    )


def _scale_polygon(points: list[tuple[float, float]], factor: float) -> list[tuple[float, float]]:
    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    return [(cx + (x - cx) * factor, cy + (y - cy) * factor) for x, y in points]


def build_yield_sign_polys(
    net_file: Path,
    add_file: Path,
    sign_distance: float,
    sign_lateral: float,
) -> int:
    root = ET.parse(net_file).getroot()

    nodes: dict[str, tuple[float, float, str]] = {}
    for node in root.findall("junction"):
        node_id = node.get("id")
        x = node.get("x")
        y = node.get("y")
        node_type = node.get("type", "")
        if not node_id or x is None or y is None:
            continue
        nodes[node_id] = (float(x), float(y), node_type)

    additional = ET.Element(
        "additional",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:noNamespaceSchemaLocation": "http://sumo.dlr.de/xsd/additional_file.xsd",
        },
    )

    sign_count = 0
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        if not edge_id or edge_id.startswith(":"):
            continue

        from_node = edge.get("from")
        to_node = edge.get("to")
        if not from_node or not to_node:
            continue
        if from_node not in nodes or to_node not in nodes:
            continue

        fx, fy, _ = nodes[from_node]
        tx, ty, to_type = nodes[to_node]
        if to_type != "right_before_left":
            continue

        dx = tx - fx
        dy = ty - fy
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue

        ux = dx / length
        uy = dy / length
        # Normale verso destra rispetto alla direzione di marcia (guida a destra)
        rx = uy
        ry = -ux

        cx = tx - ux * sign_distance + rx * sign_lateral
        cy = ty - uy * sign_distance + ry * sign_lateral

        # Triangolo "dare precedenza" (bordo rosso + interno bianco)
        tip = (cx + ux * 1.25, cy + uy * 1.25)
        base_center = (cx - ux * 0.95, cy - uy * 0.95)
        p_left = (base_center[0] + rx * 1.15, base_center[1] + ry * 1.15)
        p_right = (base_center[0] - rx * 1.15, base_center[1] - ry * 1.15)
        outer = [tip, p_left, p_right]
        inner = _scale_polygon(outer, 0.70)

        def shape(points: list[tuple[float, float]]) -> str:
            return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)

        outer_id = f"yield_outer_{edge_id}"
        inner_id = f"yield_inner_{edge_id}"

        ET.SubElement(
            additional,
            "poly",
            {
                "id": outer_id,
                "type": "yield_sign_outer",
                "color": "255,0,0,255",
                "fill": "1",
                "layer": "98",
                "shape": shape(outer),
            },
        )
        ET.SubElement(
            additional,
            "poly",
            {
                "id": inner_id,
                "type": "yield_sign_inner",
                "color": "255,255,255,255",
                "fill": "1",
                "layer": "99",
                "shape": shape(inner),
            },
        )
        sign_count += 1

    ET.indent(additional, space="    ")
    ET.ElementTree(additional).write(add_file, encoding="UTF-8", xml_declaration=True)
    return sign_count


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    maps_root = project_root / "sumo_xml_files"

    src_dir = maps_root / args.src_map
    dst_dir = maps_root / args.dst_map

    src_netcfg = src_dir / f"{args.src_map}.netcfg.xml"
    src_net = src_dir / f"{args.src_map}.net.xml"
    src_routes = src_dir / f"{args.src_map}.rou.xml"

    if not src_dir.exists():
        raise FileNotFoundError(f"Cartella mappa sorgente non trovata: {src_dir}")
    if not src_net.exists():
        raise FileNotFoundError(f"Rete sorgente non trovata: {src_net}")
    if not src_routes.exists():
        raise FileNotFoundError(f"Route sorgente non trovato: {src_routes}")

    if dst_dir.exists() and args.overwrite:
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    grid_params = read_grid_params(src_netcfg)
    if args.mode == "grid" and grid_params is None:
        raise RuntimeError(
            "mode=grid richiesto ma la sorgente non ha netcfg grid compatibile. "
            "Usa --mode patch o --mode auto"
        )

    use_grid = args.mode == "grid" or (args.mode == "auto" and grid_params is not None)

    dst_net = dst_dir / f"{args.dst_map}.net.xml"
    dst_rou = dst_dir / f"{args.dst_map}.rou.xml"
    dst_add = dst_dir / f"{args.dst_map}.add.xml"
    patch_nodes_file = dst_dir / f"{args.dst_map}.rbl_patch.nod.xml"

    if use_grid:
        assert grid_params is not None
        grid_number, grid_length, lanes, no_turnarounds = grid_params
        generate_rbl_grid_net(
            project_root=project_root,
            dst_net=dst_net,
            grid_number=grid_number,
            grid_length=grid_length,
            lanes=lanes,
            no_turnarounds=no_turnarounds,
        )
        write_netcfg_grid(
            dst_dir=dst_dir,
            dst_map=args.dst_map,
            grid_number=grid_number,
            grid_length=grid_length,
            lanes=lanes,
        )
        mode_used = "grid"
    else:
        patched_nodes = build_rbl_patch_nodes(src_net=src_net, patch_file=patch_nodes_file)
        if patched_nodes == 0:
            raise RuntimeError("Nessun nodo patchabile trovato nella rete sorgente")
        generate_rbl_patch_net(
            project_root=project_root,
            src_net=src_net,
            patch_nodes_file=patch_nodes_file,
            dst_net=dst_net,
            keep_tls=args.keep_tls,
        )
        write_netcfg_patch(
            dst_dir=dst_dir,
            dst_map=args.dst_map,
            src_map=args.src_map,
            patch_nodes_file=patch_nodes_file,
            keep_tls=args.keep_tls,
        )
        mode_used = f"patch (nodi patchati={patched_nodes}, tls_discard={'no' if args.keep_tls else 'yes'})"

    shutil.copy2(src_routes, dst_rou)

    route_used_edges = route_edges(dst_rou)
    available_edges = net_edges(dst_net)
    missing = sorted(route_used_edges - available_edges)
    if missing:
        preview = ", ".join(missing[:12])
        raise RuntimeError(
            "La rete generata non e' compatibile con le route esistenti. "
            f"Edge mancanti: {preview}{' ...' if len(missing) > 12 else ''}"
        )

    signs = build_yield_sign_polys(
        net_file=dst_net,
        add_file=dst_add,
        sign_distance=args.sign_distance,
        sign_lateral=args.sign_lateral,
    )

    write_sumocfg(dst_dir=dst_dir, dst_map=args.dst_map)

    print(f"Mappa creata: {dst_dir}")
    print(f"- mode usato: {mode_used}")
    print(f"- net: {dst_net.name}")
    print(f"- rou: {dst_rou.name}")
    print(f"- add (segnaletica): {dst_add.name} ({signs} segnali)")
    print(f"- sumocfg: {args.dst_map}.sumocfg")


if __name__ == "__main__":
    main()
