# Kammat CLI: Work In Progress.
This is still a work in progress.

In this WIP, Kammat uses one shared pipeline for CLI and GUI execution:


## How CLI and GUI share execution

```text
CLI input ─┐
           ├─→ RunConfig → build_plan() → ExecutionPlan → run_plan()
GUI input ─┘                                           ↓
                                         RunEvent stream + RunResult
                                             ├─→ CLI text/JSON
                                             └─→ GUI console/progress
```

Both paths use the same configuration schema, stage registry, planner,
execution adapters, process runner, output verification, and per-stage logs.
The CLI and GUI differ only in input collection and result presentation.

## Typical CLI workflow

```bash
# Create and validate configuration
kammat config init --output ./study.json --profile full --workspace ./workspace
kammat config validate --config ./study.json

# Inspect and preview the pipeline
kammat stage list --config ./study.json
kammat plan --config ./study.json --json

# Execute the plan
kammat run --config ./study.json

# Use the shared pipeline
kammat gui
```

Stage selection is available on `plan` and `run` through `--stage`, `--from`,
`--until`, and `--no-deps`. Use `--set SECTION.FIELD=VALUE` for temporary
in-memory overrides. `plan` and `--dry-run` do not execute stages.
