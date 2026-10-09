# Evaluation

**Current instrument (protocol v1):** `run.py`, `metrics.py`, `inject.py` (catalogue `plfs-injection-catalogue-v2`) and the pre-registered `PROTOCOL.md`.

* Headline metrics on the **CAPI-pass population** (records breaking an approved hard rule and rule-type injections removed); the rule list is scored separately.
* Seeds 1–5 / State fold A for development; seeds 6–20 / fold B for confirmation, run once after the design is frozen.
* Rankings compared: A0 (the superseded V2.0 priority, rebuilt from the same stage outputs), each lane alone, references only, the full value lane, and the operational queue.
* Every run keeps all stage artefacts under `evaluation/runs/protocol_v1/` and records the git commit, input hashes, catalogue version and seed; `python -m evaluation.run --verify <result.json>` recomputes the metrics from them.
* Error catalogue v2: x10, /10, x12 (yearly as monthly), x100, digit transposition, plausible-but-wrong values from another State, casual wage x10, hours +10, occupation miscode, duplicate person, copied household, rule-type injections, FSU fabrication, short interviews and one-day completion (paradata).

**Status: the protocol has not been run for the current method.** `results/2024.json` and `results/2025.json` are the earlier single-seed study of the superseded V2.0 priority (artefacts partly missing; see plan finding N3) and are kept for the record only.

Injected labels are the only known positives; unlabelled records may still hold genuine errors, so precision is a lower bound. Real-world precision and miss rate need the HSD pilot (plan §12.7).
