# data/

Everything the platform reads or writes lives here, apart from the code. `mospi/paths.py` resolves this folder (override with `MOSPI_DATA_DIR`).

| Folder | Contents | Git |
|---|---|---|
| `raw/` | Supplied PLFS deliveries (`2023-June2024/`, `Jan-Dec2024/`, `Post2025/`): input only, never modified. Release contracts in `mospi/pipeline/stages/preprocessing/config.py` name files relative to this folder (pass `--input-root data/raw`). | ignored |
| `<stage>/runs/<run_id>/` | Immutable stored runs of `preprocessing`, `peer_groups`, `statistical`, `contextual`, `ml`, `pattern`, `historical`, `integrity` and `fusion`. Each Fusion run holds its append-only `review_audit.sqlite`. | ignored |
| `pipeline/` | `runs/` (batch timing and quality-gate reports), `jobs/` (records and logs of batches started from the workspace), `logs/`. | ignored |
| `evaluation/` | `runs/` and `logs/` (evaluation work), `results/` (protocol result files: tracked evidence). | `results/` tracked |
| `demo/` | Synthetic bundle for the hosted review-only instance (`scripts/build_demo_data.py`). Holds no PLFS record. | tracked |

The `<stage>/runs/<run_id>/` layout is a contract between the stages, the API, `scripts/export_serving_data.py` and the Docker volume (`/data/<stage>/runs`). Do not rename those folders.
