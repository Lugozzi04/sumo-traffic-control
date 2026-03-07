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

Controller MP con anti-spillback hard (toggle ON):

```bash
python3 runner.py \
  -n manhattan3x3_100pc \
  -p data/populations/manhattan3x3_demo.yaml \
  --controller mp \
  --spillback
```

Controller MP con isteresi lost-time-aware:

```bash
python3 runner.py \
  -n manhattan3x3_100pc \
  -p data/populations/manhattan3x3_demo.yaml \
  --controller mp \
  --lost-time-aware \
  --lost-time-sat-flow 0.5 \
  --lost-time-gain 1.0
```

Controller MP con fairness impatience saturata:

```bash
python3 runner.py \
  -n manhattan3x3_100pc \
  -p data/populations/manhattan3x3_demo.yaml \
  --controller mp \
  --fairness \
  --fairness-mu 5.0 \
  --fairness-w-half 30.0
```

Versione con tuning parametri spillback:

```bash
python3 runner.py \
  -n manhattan3x3_100pc \
  -p data/populations/manhattan3x3_demo.yaml \
  --controller mp \
  --spillback \
  --spillback-on 0.90 \
  --spillback-off 0.75 \
  --spillback-min-halts 1 \
  --spillback-alpha 0.5
```

Con GUI:

```bash
python3 runner.py -n manhattan3x3_100pc -p data/populations/manhattan3x3_demo.yaml --controller mp --gui
```

## Dove mettere la tua idea

- Logica decisionale Max-Pressure: `src/controllers/max_pressure.py`
- Nuove metriche: `src/metrics.py`
- Pipeline esperimenti: `runner.py`

## Feature toggles MP

- `--lost-time-aware`: abilita isteresi proporzionale al costo di switch (yellow+all-red)
- `--lost-time-sat-flow`: flusso di saturazione equivalente [veh/s] (default 0.5)
- `--lost-time-gain`: guadagno del margine lost-time-aware (default 1.0)
- `--fairness`: abilita fairness con impatience saturata
- `--fairness-mu`: peso massimo del bonus fairness (default 5.0)
- `--fairness-w-half`: secondi per raggiungere il 50% del bonus fairness (default 30.0)
- `--spillback`: abilita/disabilita il vincolo hard anti-spillback
- `--spillback-on`: soglia ON occupazione downstream [0-1] (default 0.90)
- `--spillback-off`: soglia OFF occupazione downstream [0-1] (default 0.75)
- `--spillback-min-halts`: min veicoli fermi richiesti per attivare blocco (default 1)
- `--spillback-alpha`: fattore EMA [0-1] (default 0.5)


## Utility mappe

- `utils/list_maps.py`: elenca gli scenari disponibili
- `utils/routes_editor.py`: riassegna ID progressivi alle route (`route1`, `route2`, ...)
- `utils/adjust_routes.py`: filtra route con edge iniziale non idoneo (utile su mappe reali)
