# Data

This directory contains datasets, logs, and processed data for the Hybrid AI Traffic Management System.

> **Note**: Most data files are gitignored due to size. See [Regenerating Data](#regenerating-data) to recreate them.

## Directory Structure

```
data/
├── raw/                    # Runtime telemetry logs (gitignored)
│   ├── run_001/
│   │   ├── rsu_features_1hz.csv
│   │   ├── edge_flow_1hz.csv
│   │   └── logger_manifest.json
│   ├── run_002/
│   └── ...
│
├── splits/                 # Train/val/test splits (gitignored)
│   ├── run_001/
│   │   ├── train.csv
│   │   ├── val.csv
│   │   └── test.csv
│   └── ...
│
├── processed/              # Phase 2 sweep results (gitignored)
│   └── phase2sweep_*/
│
└── exports/                # Bundled datasets
    └── phase1_bundle_*/
        ├── manifest.json
        └── *.tar.gz
```

## Data Files

### RSU Features (`rsu_features_1hz.csv`)

Per-RSU telemetry at 1 Hz:

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | float | Simulation time (s) |
| `rsu_id` | string | RSU identifier |
| `vehicle_count` | int | Vehicles in RSU range |
| `avg_speed` | float | Mean vehicle speed (m/s) |
| `max_speed` | float | Max vehicle speed (m/s) |
| `min_speed` | float | Min vehicle speed (m/s) |
| `occupancy` | float | Lane occupancy ratio |
| `congestion_flag` | bool | Current congestion status |

### Edge Flow (`edge_flow_1hz.csv`)

Per-edge traffic flow at 1 Hz:

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | float | Simulation time (s) |
| `edge_id` | string | SUMO edge identifier |
| `flow` | int | Vehicles/hour |
| `density` | float | Vehicles/km |
| `mean_speed` | float | Mean speed on edge (m/s) |

### Logger Manifest (`logger_manifest.json`)

Metadata for each run:

```json
{
  "run_id": "run_001",
  "scenario": "demo",
  "start_time": "2026-04-01T10:00:00Z",
  "end_time": "2026-04-01T10:30:00Z",
  "steps": 1800,
  "seed": 42,
  "traffic_scale": 1.0
}
```

## Regenerating Data

### Step 1: Run SUMO Simulation with Logging

```bash
python3 sumo/run_sumo_pipeline.py \
  --scenario demo \
  --max-steps 1800 \
  --traffic-scale 1.0 \
  --enable-logging \
  --log-dir data/raw/run_XXX
```

### Step 2: Process and Label

```bash
# Label congestion horizons
python3 pipelines/processing/horizon_labeler.py \
  --input data/raw/run_XXX/rsu_features_1hz.csv \
  --output data/raw/run_XXX/labeled.csv

# Split into train/val/test
python3 pipelines/processing/temporal_split.py \
  --input data/raw/run_XXX/labeled.csv \
  --output-dir data/splits/run_XXX
```

### Step 3: Validate (No Leakage)

```bash
python3 pipelines/processing/leakage_validator.py \
  --train data/splits/run_XXX/train.csv \
  --val data/splits/run_XXX/val.csv \
  --test data/splits/run_XXX/test.csv
```

## Phase 1 Pipeline

For full Phase 1 data pipeline:

```bash
bash pipelines/processing/run_phase1_closure.sh
```

This script:
1. Runs multiple SUMO simulations
2. Labels all outputs
3. Splits temporally
4. Validates no leakage
5. Exports bundle to `data/exports/`

## Data Size Estimates

| Directory | Typical Size | Notes |
|-----------|--------------|-------|
| `raw/` (1 run) | ~10-20 MB | 30 min simulation |
| `raw/` (full) | ~1-2 GB | 100+ runs |
| `splits/` | ~1.5 GB | Derived from raw |
| `exports/` | ~50-100 MB | Compressed bundles |

## Gitignore Policy

Large/regenerable data is gitignored:

```gitignore
data/raw/
data/splits/
data/exports/*.tar.gz
data/processed/phase2sweep_*/
```

## Export Bundles

Bundled datasets for sharing:

```bash
# Create export bundle
python3 pipelines/processing/export_dataset_bundle.py \
  --runs run_001 run_002 run_003 \
  --output data/exports/phase1_bundle_v1

# Bundle contents:
# - manifest.json (run metadata)
# - splits.tar.gz (train/val/test CSVs)
```
