#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


KNOWN_UNSAFE_TLS_PHASES: set[tuple[str, int]] = {
    ("252103298", 2),
    ("258078193", 2),
    ("267313696", 6),
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


def patch_known_unsafe_tls(net_file: Path) -> tuple[int, int]:
    root = ET.parse(net_file).getroot()
    changed_phases = 0
    changed_signals = 0

    for tl in root.findall("tlLogic"):
        tl_id = tl.get("id")
        for phase_index, phase in enumerate(tl.findall("phase")):
            if (tl_id, phase_index) not in KNOWN_UNSAFE_TLS_PHASES:
                continue
            state = phase.get("state", "")
            new_state = state.replace("G", "g")
            if new_state == state:
                continue
            phase.set("state", new_state)
            changed_phases += 1
            changed_signals += state.count("G")

    ET.indent(root, space="    ")
    ET.ElementTree(root).write(net_file, encoding="UTF-8", xml_declaration=True)
    return changed_phases, changed_signals


def write_sumocfg(dst_dir: Path, map_name: str) -> None:
    sumocfg = dst_dir / f"{map_name}.sumocfg"
    sumocfg.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>

<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">

    <input>
        <net-file value="bologna_fixed.net.xml"/>
        <route-files value="bologna_fixed.rou.xml,../vehicletypes.rou.xml"/>
    </input>

    <gui-only>
        <gui-settings-file value="../realworld.view.xml"/>
    </gui-only>

</configuration>
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rigenera una variante stabilizzata della mappa Bologna.")
    parser.add_argument("--src-map", default="bologna", help="Cartella mappa sorgente")
    parser.add_argument("--dst-map", default="bologna_fixed", help="Cartella mappa destinazione")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    maps_root = project_root / "sumo_xml_files"
    src_dir = maps_root / args.src_map
    dst_dir = maps_root / args.dst_map

    src_net = src_dir / f"{args.src_map}.net.xml"
    src_routes = src_dir / f"{args.src_map}.rou.xml"
    if not src_net.exists():
        raise FileNotFoundError(f"Net file non trovato: {src_net}")
    if not src_routes.exists():
        raise FileNotFoundError(f"Route file non trovato: {src_routes}")

    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_net = dst_dir / "bologna_fixed.net.xml"

    with tempfile.TemporaryDirectory(prefix="bologna_plain_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        prefix = tmp_dir / "plain"
        run_cmd(
            [
                "netconvert",
                "--sumo-net-file",
                str(src_net),
                "--plain-output-prefix",
                str(prefix),
            ],
            cwd=project_root,
        )

        run_cmd(
            [
                "netconvert",
                "--node-files",
                str(prefix.with_suffix(".nod.xml")),
                "--edge-files",
                str(prefix.with_suffix(".edg.xml")),
                "--connection-files",
                str(prefix.with_suffix(".con.xml")),
                "--tllogic-files",
                str(prefix.with_suffix(".tll.xml")),
                "--output-file",
                str(dst_net),
                "--geometry.avoid-overlap",
                "--geometry.min-radius.fix",
                "--geometry.max-angle.fix",
                "--no-turnarounds.except-deadend",
                "--junctions.corner-detail",
                "5",
                "--junctions.internal-link-detail",
                "5",
            ],
            cwd=project_root,
        )

    patched_phases, patched_chars = patch_known_unsafe_tls(dst_net)

    shutil.copy2(src_routes, dst_dir / "bologna_fixed.rou.xml")
    write_sumocfg(dst_dir, args.dst_map)

    print(f"Mappa rigenerata: {dst_dir}")
    print(f"- net: {dst_net}")
    print(f"- unsafe phase patch applicati: {patched_phases} fasi ({patched_chars} segnali)")


if __name__ == "__main__":
    main()
