# SUMO Traffic Control - Template

Base template per iniziare un progetto personale di controllo traffico in SUMO.

## Cosa c'e dentro

- `sumo_xml_files/`: scenari e mappe (copiati dal progetto di riferimento)
- `runner.py`: entrypoint principale per eseguire simulazioni
- `generate_population.py`: genera una popolazione YAML compatibile col runner
- `src/controllers/`: controller semaforici (`fixed` e `mp` max-pressure MVP)
- `src/metrics.py`: raccolta metriche base per veicolo
- `data/populations/`: popolazioni di input
- `logs/simulations/`: output delle simulazioni singole (`runner.py`)
- `logs/ablation/`: output batch/ablation (`utils/run_ablation.py`)

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

Profilo guidatori "human light" (globale su tutto il run):

```bash
python3 runner.py \
  -n manhattan3x3_100pc \
  -p data/populations/manhattan3x3_demo.yaml \
  --controller mp \
  --driver-profile human_light
```

Output (default runner):
- viene creata una cartella nuova per ogni run in `logs/simulations/`
- formato: `sim_XXXX_YYYYMMDD_HHMMSS/`
- dentro trovi:
  - `vehicle_metrics.csv`
  - `run_info.json` (parametri e metadata del run)

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
- usa preset scenario conservativi (tuning v1) per ridurre over-switch/over-penalty rispetto ai default grezzi;
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
- `--jobs <N>`: parallelismo semplice tra scenari per ogni seed (default 1, es. 2/3/4).
- `--scenario-pack <name>`: set scenari da usare (`tuned_v1` default, `tuning_matrix_v1` per tuning).
- `--scenarios <nome1 nome2 ...>`: subset scenari del pack (utile per mini-run veloci).
- `--list-scenarios`: stampa gli scenari disponibili nel pack selezionato ed esce.
- `--driver-profile {default,human_light}`: profilo guidatori globale (vale per tutti gli scenari nel batch).
- `--human-light`: scorciatoia per `--driver-profile human_light`.
- `--include-fixed-baseline`: aggiunge scenario `fixed_base` legacy (semafori statici default della mappa).
- `--include-fixed-program0`: aggiunge scenario `fixed_program0` (semafori statici con `programID=0`).
- `--include-fixed-tuned`: aggiunge scenario `fixed_tuned` (semafori statici `programID=0` con verde principale fissato).
- `--include-rbl-baseline`: aggiunge scenario `rbl_base` su mappa `<map>_rbl` (precedenza a destra), se presente.
- `--delta-baseline-scenario <nome>`: scenario usato come baseline per `DeltaWait/DeltaTravel` (default: `fixed_program0` se presente, poi `fixed_tuned`, poi `fixed_base`, altrimenti `mp_base`).

Nota:
- lo script fa preflight automatico (`traci/sumolib/yaml`, comando `sumo`, mappe presenti);
- se tutti i run falliscono, `progress.txt` termina in stato `ERRORE`;
- se una parte fallisce, termina in `COMPLETATO_CON_ERRORI`.
- `--batch-name` e' ignorato: il nome run e' sempre automatico e ordinato.

Esempio tuning mirato (mini-matrix):

```bash
.venv/bin/python utils/run_ablation.py \
  --maps manhattan6x6_100pc \
  --demands low medium high \
  --num-seeds 3 \
  --jobs 3 \
  --max-steps 5400 \
  --scenario-pack tuning_matrix_v1 \
  --scenarios mp_base mp_lta_g020 mp_lta_g030 mp_lta_g040 mp_nmin_only mp_lta_plus_nmin mp_downstream_b08 mp_downstream_b12 mp_downstream_b16 mp_platoon_x2 mp_platoon_x3 mp_platoon_x4 mp_fair_mu2 mp_fair_mu3 mp_fair_mu4
```

Esempio completo (MP + semaforo classico + precedenza a destra, stessa batch):

```bash
.venv/bin/python utils/run_ablation.py \
  --maps manhattan8x8_100pc \
  --demands low medium high \
  --num-seeds 4 \
  --jobs 3 \
  --max-steps 5400 \
  --scenario-pack tuning_matrix_v1 \
  --include-fixed-program0 \
  --include-fixed-tuned \
  --include-rbl-baseline \
  --delta-baseline-scenario fixed_program0
```

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
- `utils/build_bologna_fixed.py`: rigenera una variante stabilizzata della mappa `bologna`
- `utils/build_rbl_variant.py`: crea una variante `*_rbl` con precedenza a destra (`right_before_left`) e segnaletica grafica (supporta mappe grid e non-grid)

## Variante right-before-left (RBL)

Per creare una copia di una mappa con precedenza a destra:

```bash
.venv/bin/python utils/build_rbl_variant.py \
  --src-map manhattan8x8_100pc \
  --dst-map manhattan8x8_100pc_rbl \
  --overwrite
```


Modalita:
- `--mode auto` (default): usa `grid` quando possibile, altrimenti `patch` via `netconvert`
- `--mode grid`: forza rigenerazione grid
- `--mode patch`: forza patch nodi a `right_before_left`

Questo crea `sumo_xml_files/<dst_map>/` con:
- `<dst_map>.net.xml` (rete right-before-left)
- `<dst_map>.rou.xml` (route copiate dalla mappa originale)
- `<dst_map>.add.xml` (triangoli grafici \"dare precedenza\")
- `<dst_map>.sumocfg` (config pronta all'uso)

## Bologna fixed

Per rigenerare la mappa corretta:

```bash
.venv/bin/python utils/build_bologna_fixed.py
```

Questo crea `sumo_xml_files/bologna_fixed/` con:
- `bologna_fixed.net.xml` (net rigenerata + patch semafori unsafe)
- `bologna_fixed.rou.xml` (route base copiata)
- `bologna_fixed.sumocfg`

GUI con veicoli (debug visuale):

```bash
.venv/bin/python generate_population.py -n bologna_fixed -o data/populations/gui_bologna_fixed.yaml -N 3000 --start-time 0 --end-time 2400 --seed 42
.venv/bin/python runner.py -n bologna_fixed -p data/populations/gui_bologna_fixed.yaml --controller mp --gui --step-length 0.2
```
