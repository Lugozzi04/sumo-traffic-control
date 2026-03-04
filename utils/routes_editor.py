import argparse
import xml.etree.ElementTree as et

parser = argparse.ArgumentParser("Correttore per le routes")
parser.add_argument('-f', '--filename', required=True, dest="file")
arguments = parser.parse_args()

# Carica il file XML
tree = et.parse(arguments.file)
root = tree.getroot()

# Modifica gli attributi per ogni riga
for i, elem in enumerate(root):
    elem.set("id", "route" + str(i+1))

# Salva il file XML modificato
tree.write(arguments.file)