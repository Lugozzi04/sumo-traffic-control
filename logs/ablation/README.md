# Ablation campaigns

Tracked campaigns:

- `runs/run_0023_20260612_131724`: Manhattan 8x8 campaign used for the general Max-Pressure comparison.
- `runs/run_0025_20260614_143342`: Bologna campaign used for the final comparison with `mp_program0` and `mp_super`.

For each campaign, the repository keeps:

- `config_resolved.yaml`: resolved experiment configuration;
- `run_results.csv`: one row per completed simulation;
- `summary.md`, `summary_by_group.csv`, `summary_vs_base.csv`: aggregated reports;
- `populations/`: generated YAML populations used by the scenarios.

The nested raw `runs/` folders are not tracked to keep the repository lightweight.
