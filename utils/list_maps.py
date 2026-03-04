from pathlib import Path


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent / "sumo_xml_files"
    maps = [p.name for p in root.iterdir() if p.is_dir()]
    for name in sorted(maps):
        print(name)
