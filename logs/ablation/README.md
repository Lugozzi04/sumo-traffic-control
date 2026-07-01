# Ablation campaigns

This directory contains the ablation campaigns kept in the repository as compact experiment artifacts.

For each visible campaign, the repository keeps the files that are useful to inspect and reproduce the results:

- `config_resolved.yaml`: resolved experiment configuration;
- `run_results.csv`: one row per completed simulation, when available;
- `summary.md`, `summary_by_group.csv`, `summary_vs_base.csv`: aggregated reports, when available;
- `table.txt`, `winners.txt`: compact textual summaries, when available;
- `populations/`: generated YAML populations used by the scenarios, when available.

The nested raw `runs/` folders are intentionally not tracked because they contain large per-simulation outputs and can be regenerated from the tracked configuration and populations.

Visible campaigns:

- `runs/run_0001_20260325_191427`
- `runs/run_0002_20260327_230042`
- `runs/run_0003_20260327_232504`
- `runs/run_0004_20260327_232509`
- `runs/run_0005_20260327_232855`
- `runs/run_0006_20260327_232909`
- `runs/run_0007_20260327_233816`
- `runs/run_0008_20260328_153614`
- `runs/run_0009_20260430_174205`
- `runs/run_0010_20260430_174356`
- `runs/run_0011_20260430_174438`
- `runs/run_0012_20260430_174548`
- `runs/run_0013_20260502_175736`
- `runs/run_0014_20260502_181739`
- `runs/run_0015_20260504_030124`
- `runs/run_0016_20260507_170054`
- `runs/run_0017_20260509_174007`
- `runs/run_0018_20260517_023911`
- `runs/run_0019_20260517_024322`
- `runs/run_0020_20260517_034036`
- `runs/run_0021_20260526_023859`
- `runs/run_0022_20260526_121656`
- `runs/run_0023_20260526_151234`
- `runs/run_0024_20260527_122000`
- `runs/run_0025_20260614_135131`
- `runs/run_0026_20260614_135635`
- `runs/run_0027_20260614_140642`
- `runs/run_0028_20260612_131724`
- `runs/run_0029_20260614_143342`

Note: `run_0028_20260612_131724` and `run_0029_20260614_143342` were renamed from duplicated `run_0023` and `run_0025` identifiers to keep the campaign list unambiguous.
