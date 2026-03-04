# script che serve per correggere le routes della mappa di bologna,
# trova le routes su cui i veicoli possono spawnare e rimuove dal route file quelle non idonee

import argparse
import xml.etree.ElementTree as ET

def filter_edges(netfile, min_length):
    tree = ET.parse(netfile)
    root = tree.getroot()

    edges = []

    for edge in root.findall("edge"):
        for lane in edge.findall("lane"):
            length = float(lane.get("length", default=0))
            allowed = lane.get("allow", default=None)
            if length >= min_length and allowed is None:
                edges.append(edge.get("id"))

    return edges

def remove_invalid_routes(routefile, valid_edges):
    tree = ET.parse(routefile)
    root = tree.getroot()

    for route in root[:]:
        edges = route.get("edges", default=None)
        if edges is not None:
            edge_list = edges.split(' ')
            if edge_list[0] not in valid_edges:
                root.remove(route)

    tree.write(routefile)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Modulo per estrarre gli edge idonei allo spawn dei veicoli da una mappa")
    parser.add_argument('-n', '--net-file', dest="netfile", required=True, metavar="path/to/net_file.net.xml", help="File .net.xml")
    parser.add_argument('-l', '--min-length', type=int, dest="min_length", required=True, metavar="N", help="Lunghezza minima delle strade")
    parser.add_argument('-r', '--route-file', dest="routefile", required=True, metavar="path/to/route_file.rou.xml", help="File .rou.xml")
    arguments = parser.parse_args()

    edges = filter_edges(arguments.netfile, arguments.min_length)
    remove_invalid_routes(arguments.routefile, edges)
