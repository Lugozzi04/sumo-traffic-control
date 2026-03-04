# SUMO Traffic Control - Template

Base template per iniziare un progetto personale di controllo traffico in SUMO.

## Cosa c'e dentro

- `sumo_xml_files/`: scenari e mappe (copiati dal progetto di riferimento)
- `runner.py`: entrypoint principale per eseguire simulazioni
- `generate_population.py`: genera una popolazione YAML compatibile col runner
- `src/controllers/`: controller semaforici (`fixed` e `mp` max-pressure MVP)
- `src/metrics.py`: raccolta metriche base per veicolo
- `data/populations/`: popolazioni di input
- `logs/`: risultati CSV

## Setup rapido

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 1) Genera una popolazione

Esempio su Manhattan 3x3:

```bash
python3 generate_population.py \
  -n manhattan3x3_100pc \
  -o data/populations/manhattan3x3_demo.yaml \
  -N 500 \
  --seed 42
```

## 2) Esegui una simulazione

Controller fisso (baseline):

```bash
python3 runner.py \
  -n manhattan3x3_100pc \
  -p data/populations/manhattan3x3_demo.yaml \
  --controller fixed
```

Controller Max-Pressure MVP:

```bash
python3 runner.py \
  -n manhattan3x3_100pc \
  -p data/populations/manhattan3x3_demo.yaml \
  --controller mp \
  --min-green 10 \
  --max-green 120 \
  --switch-epsilon 0.0
```

Con GUI:

```bash
python3 runner.py -n manhattan3x3_100pc -p data/populations/manhattan3x3_demo.yaml --controller mp --gui
```

## Dove mettere la tua idea

- Logica decisionale Max-Pressure: `src/controllers/max_pressure.py`
- Nuove metriche: `src/metrics.py`
- Pipeline esperimenti: `runner.py`


## Utility mappe

- `utils/list_maps.py`: elenca gli scenari disponibili
- `utils/routes_editor.py`: riassegna ID progressivi alle route (`route1`, `route2`, ...)
- `utils/adjust_routes.py`: filtra route con edge iniziale non idoneo (utile su mappe reali)
