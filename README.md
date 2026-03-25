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

Controller MP con penalita downstream continua:

```bash
python3 runner.py \
  -n manhattan3x3_100pc \
  -p data/populations/manhattan3x3_demo.yaml \
  --controller mp \
  --downstream-penalty \
  --downstream-beta 5.0 \
  --downstream-alpha 0.5
```

Controller MP con platoon extension (headway + guardia downstream):

```bash
python3 runner.py \
  -n manhattan3x3_100pc \
  -p data/populations/manhattan3x3_demo.yaml \
  --controller mp \
  --platoon-extension \
  --platoon-headway-threshold 2.0 \
  --platoon-gap-out-seconds 2.5 \
  --platoon-max-extra-green 8.0 \
  --platoon-guard-occ 0.85
```

Controller MP con Nmin dinamico:

```bash
python3 runner.py \
  -n manhattan3x3_100pc \
  -p data/populations/manhattan3x3_demo.yaml \
  --controller mp \
  --nmin-dynamic \
  --nmin-alpha 1.0 \
  --nmin-floor 2 \
  --nmin-empty-release-seconds 2.0
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

## Ablation batch (seriale + summary automatico)

Script:
- `utils/run_ablation.py`

Cosa fa:
- genera popolazioni `low/medium/high` per ogni mappa e seed;
- esegue scenari MP predefiniti (base, switch-aware, downstream-aware, fairness, platoon-safe, all-on);
- salva risultati run-level e summary aggregati.

Esempio:

```bash
python3 utils/run_ablation.py \
  --maps manhattan6x6_100pc manhattan8x8_100pc \
  --demands low medium high \
  --num-seeds 5 \
  --max-steps 5400
```

Opzionale:
- `--progress-interval <s>`: frequenza aggiornamento `progress.txt/.yaml` (default 15s).

Nota:
- lo script fa preflight automatico (`traci/sumolib/yaml`, comando `sumo`, mappe presenti);
- se tutti i run falliscono, `progress.txt` termina in stato `ERRORE`;
- se una parte fallisce, termina in `COMPLETATO_CON_ERRORI`.
- `--batch-name` e' ignorato: il nome run e' sempre automatico e ordinato.

Output in:
- `logs/ablation/progress.txt` (UNICO file progresso: sempre ultimo run lanciato)
- `logs/ablation/progress.yaml` (stessa info in YAML)
- `logs/ablation/latest_run.txt` (puntatore al run piu recente)
- `logs/ablation/runs/run_XXXX_YYYYMMDD_HHMMSS/` (cartella risultati del singolo run)
  - `config_resolved.yaml`
  - `run_results.csv`
  - `summary_by_group.csv`
  - `summary_vs_base.csv`
  - `summary.md`
  - `populations/`
  - `runs/<map__demand__seed__scenario>/stdout_stderr.log`
  - `runs/<map__demand__seed__scenario>/vehicle_metrics.csv`

## Dove mettere la tua idea

- Logica decisionale Max-Pressure: `src/controllers/max_pressure.py`
- Nuove metriche: `src/metrics.py`
- Pipeline esperimenti: `runner.py`

## Feature toggles MP

- `--lost-time-aware`: abilita isteresi proporzionale al costo di switch (yellow+all-red)
- `--lost-time-sat-flow`: flusso di saturazione equivalente [veh/s], condiviso tra LTA e Nmin dinamico (default 0.5)
- `--lost-time-gain`: guadagno del margine lost-time-aware (default 1.0)
- `--fairness`: abilita fairness con impatience saturata
- `--fairness-mu`: peso massimo del bonus fairness (default 5.0)
- `--fairness-w-half`: secondi per raggiungere il 50% del bonus fairness (default 30.0)
- `--downstream-penalty`: abilita penalita continua downstream (P -= beta * occ_down)
- `--downstream-beta`: peso della penalita downstream (default 5.0)
- `--downstream-alpha`: fattore EMA downstream [0-1] per smoothing corto (default 0.5)
- `--platoon-extension`: abilita estensione verde per arrivi in platoon
- `--platoon-headway-threshold`: soglia headway media [s] per riconoscere platoon (default 2.0)
- `--platoon-gap-out-seconds`: se non passa nessuno per questo tempo, il platoon termina (default 2.5s)
- `--platoon-max-extra-green`: estensione massima extra per attivazione fase (default 8.0s)
- `--platoon-guard-occ`: soglia downstream [0-1] per consentire estensione (default 0.85)
- `--nmin-dynamic`: abilita minimo servizio dinamico dopo ogni switch
- `--nmin-alpha`: guadagno del target Nmin rispetto al costo di switch (default 1.0)
- `--nmin-floor`: minimo veicoli equivalenti per attivazione (default 2)
- `--nmin-empty-release-seconds`: rilascio anticipato se fase vuota (default 2.0s)
- `--spillback`: abilita/disabilita il vincolo hard anti-spillback
- `--spillback-on`: soglia ON occupazione downstream [0-1] (default 0.90)
- `--spillback-off`: soglia OFF occupazione downstream [0-1] (default 0.75)
- `--spillback-min-halts`: min veicoli fermi richiesti per attivare blocco (default 1)
- `--spillback-alpha`: fattore EMA [0-1] (default 0.5)

Nota: `--lost-time-sat-flow` e' condiviso tra `--lost-time-aware` e `--nmin-dynamic`; se attivi una delle due feature, deve essere > 0.


## Utility mappe

- `utils/list_maps.py`: elenca gli scenari disponibili
- `utils/routes_editor.py`: riassegna ID progressivi alle route (`route1`, `route2`, ...)
- `utils/adjust_routes.py`: filtra route con edge iniziale non idoneo (utile su mappe reali)
