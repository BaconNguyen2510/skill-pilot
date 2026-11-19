"""One-shot, two-process blind evaluation of the frozen Skill Pilot candidate.

The ledger must be access-controlled and shared by the release custodians.
It enforces one run per candidate within that ledger, not across copies of it.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import platform
import random
import re
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, TypedDict
from unittest import mock

import contract
from contract import ContractError, validate_labels, validate_queries

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "c042024c8020f3763b710b0783a880cd4ff0c305"
HISTORICAL_CANDIDATES = {
    "2c8daab7ae7a8b06dcfc64863c4043183fd35261": "95c8fe505ba3214788c0ba51e850ee5913bfeb376102f0e9ab8ef89eb8ced3d3",
}
EXPOSED = (
    "eval/queries.jsonl",
    "eval/dev_v2_challenge.jsonl",
)
ARCHIVE_PATHS = (
    "skills/skill-pilot",
    "eval/run_eval.py",
    "eval/corpus_builder.py",
    "eval/metrics.py",
    "eval/validate_eval.py",
    "plugin.json",
    *EXPOSED,
)


class Thresholds(TypedDict):
    mrr_at_5_min: float
    recall_at_5_min: float
    forbidden_rate_at_5_max: float
    abstention_f1_min: float


class EvalConfig(TypedDict):
    protocol: str
    candidate: str
    catalog: str
    catalog_seed: int
    harness: str
    limit: int
    bootstrap_seed: int
    bootstrap_samples: int
    thresholds: Thresholds
    minimum_cases: int
    minimum_intent_families: int
    minimum_per_language: int
    minimum_abstain: int
    minimum_multi_intent: int


CONFIG: EvalConfig = {
    "protocol": "blind-v1",
    "candidate": CANDIDATE,
    "catalog": "frozen-synthetic",
    "catalog_seed": 42,
    "harness": "all",
    "limit": 5,
    "bootstrap_seed": 42,
    "bootstrap_samples": 2000,
    "thresholds": {
        "mrr_at_5_min": 0.65,
        "recall_at_5_min": 0.70,
        "forbidden_rate_at_5_max": 0.10,
        "abstention_f1_min": 0.80,
    },
    "minimum_cases": 200,
    "minimum_intent_families": 100,
    "minimum_per_language": 30,
    "minimum_abstain": 30,
    "minimum_multi_intent": 30,
}
LANGUAGES = ("en", "vi", "vi_no_diacritic", "mixed")
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def write_once(path: Path, data: bytes) -> None:
    # Exclusive creation prevents accidental overwrite; custodians must protect the ledger.
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def read_bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ValueError(f"Artifact too large: {path.name}")
    return data


def json_artifact(path: Path) -> Any:
    return json.loads(read_bounded(path).decode("utf-8"))


def materialize(destination: Path, candidate: str | None = None) -> dict[str, str]:
    """Export only frozen tracked files; never execute checkout bytes."""
    target_candidate = candidate or CANDIDATE
    rev = subprocess.run(
        ["git", "rev-parse", "--verify", target_candidate + "^{commit}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if rev.returncode == 0:
        commit = rev.stdout.strip()
        if commit != target_candidate:
            raise ValueError("Frozen candidate commit mismatch")
        archive_ref = target_candidate
    else:
        archive_ref = "HEAD"
    proc = subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.eol=lf",
            "archive",
            "--format=tar",
            archive_ref,
            "--",
            *ARCHIVE_PATHS,
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    if len(proc.stdout) > 32 * 1024 * 1024:
        raise ValueError("Frozen archive exceeds size limit")
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as archive:
        members = archive.getmembers()
        if any(not (m.isfile() or m.isdir()) for m in members):
            raise ValueError("Frozen archive contains unsupported links or files")
        archive.extractall(destination, members=members, filter="data")
    scout_sha = HISTORICAL_CANDIDATES.get(
        target_candidate,
        "af1c1ee3a93a70c433ccd29426b847b7fd0c7730d82c6e8486ece160ad1550bc",
    )
    pinned = {
        "skills/skill-pilot/scripts/skill_scout.py": scout_sha,
        "eval/run_eval.py": "8d4f26d9aa3647f7cf8db59b8f9b081ceb9e632a1520dd94eb0a95146335c41b",
        "eval/corpus_builder.py": "ec3b214a5a009bdccd3d55f36c6122af3039104ae113ea9b6848f8c843d70684",
        "eval/metrics.py": "ca0de648a5d773a5b0b08e66102b923b7838015d8eb133164a2d7e096c69e411",
        "eval/validate_eval.py": "0b10c322477c1c1f9b107d52faa1743a42ee5876f2d0b9e40077da456f2f797e",
        "eval/queries.jsonl": "19fa39acb0d3cefe6ac825ee340b31fe73b901a1b514b56129603254519d475f",
        "eval/dev_v2_challenge.jsonl": "aa3080e38bf4780799e530df333583956e97626e63ac935b9855c319f371e81f",
    }
    hashes = {}
    for name in (
        "skills/skill-pilot/scripts/skill_scout.py",
        "eval/run_eval.py",
        "eval/corpus_builder.py",
        "eval/metrics.py",
        "eval/validate_eval.py",
        *EXPOSED,
    ):
        hashes[name] = digest((destination / name).read_bytes())
    if hashes["skills/skill-pilot/scripts/skill_scout.py"] != pinned[
        "skills/skill-pilot/scripts/skill_scout.py"
    ] or any(hashes.get(k) != v for k, v in pinned.items() if k in hashes):
        raise ValueError("Frozen scout hash mismatch")
    return hashes


def load_runner(root: Path) -> Any:
    eval_dir = str(root / "eval")
    sys.path.insert(0, eval_dir)
    # Repeated isolated tests must not reuse imports from another checkout.
    for name in ("corpus_builder", "metrics", "validate_eval"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(
        "frozen_eval", root / "eval" / "run_eval.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load frozen evaluation runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prediction_dir(ledger: Path) -> Path:
    if not ledger.is_dir():
        raise ValueError("Ledger must be an existing, protected directory")
    return ledger / f"final-{CANDIDATE}"


def query_readiness(queries: list[dict[str, Any]]) -> list[str]:
    """Check query-visible coverage before consuming the one permitted run."""
    errors = []
    if len(queries) < CONFIG["minimum_cases"]:
        errors.append("too few cases")
    if (
        len({contract._normalized(r["intent_family"]) for r in queries})
        < CONFIG["minimum_intent_families"]
    ):
        errors.append("too few distinct intent families")
    if any(
        sum(r["language"] == lang for r in queries) < CONFIG["minimum_per_language"]
        for lang in LANGUAGES
    ):
        errors.append("too few cases in a language slice")
    if (
        sum(r["category"] == "multi_intent" for r in queries)
        < CONFIG["minimum_multi_intent"]
    ):
        errors.append("too few multi-intent cases")
    return errors


def require_deterministic_runtime() -> None:
    """Require a fixed hash seed set before interpreter startup."""
    if os.environ.get("PYTHONHASHSEED") != "0" or sys.flags.hash_randomization != 0:
        raise ValueError("Start Python with PYTHONHASHSEED=0 before prediction")


def predict_one(
    runner: Any, scout: Any, env: dict[str, Any], query: str
) -> tuple[int, dict[str, Any] | None, str]:
    """Preserve the frozen runner's JSON error payload before it discards nonzero output."""
    captured = io.StringIO()
    completed = False
    original = scout.cmd_search

    def capture(args: Any) -> int:
        nonlocal completed
        with redirect_stdout(captured):
            code = original(args)
        completed = True
        print(captured.getvalue(), end="")
        return code

    with mock.patch.object(scout, "cmd_search", side_effect=capture):
        code, payload = runner._run_scout_search(
            scout, env, query, limit=CONFIG["limit"]
        )
    if code == 0:
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("ranked_matches"), list)
            or not all(isinstance(item, dict) for item in payload["ranked_matches"])
        ):
            return code, None, "invalid_response"
        return code, payload, "ok"
    try:
        error = json.loads(captured.getvalue()) if completed else {}
    except (ValueError, TypeError):
        error = {}
    if (
        code == 1
        and isinstance(error, dict)
        and error.get("error_code") == "INVALID_QUERY"
    ):
        return code, None, "invalid_query_abstention"
    return code, None, "error_or_rejected"


def predict(queries_path: Path, label_sha256: str, ledger: Path) -> Path:
    """Receive unlabeled queries and a label-file hash, never a label file."""
    require_deterministic_runtime()
    if not re.fullmatch(r"[0-9a-f]{64}", label_sha256):
        raise ValueError(
            "A lowercase SHA-256 commitment to finalized labels is required"
        )
    out = prediction_dir(ledger)
    with tempfile.TemporaryDirectory(prefix="skill-pilot-blind-") as tmp:
        root = Path(tmp) / "candidate"
        root.mkdir()
        hashes = materialize(root)
        query_bytes = read_bounded(queries_path)
        query_snapshot = Path(tmp) / "queries.jsonl"
        write_once(query_snapshot, query_bytes)
        queries = validate_queries(query_snapshot, [root / p for p in EXPOSED])
        if issues := query_readiness(queries):
            raise ValueError("Query coverage insufficient: " + "; ".join(issues))
        query_sha = digest(query_bytes)
        runner = load_runner(root)
        scout = runner.load_scout_module()
        env = runner.build_eval_environment(
            Path(tmp) / "corpus", seed=CONFIG["catalog_seed"]
        )
        catalog = sorted(env["catalog_ids"])
        runtime = {
            "python": platform.python_version(),
            "python_build": sys.version,
            "hash_seed": "0",
            "platform": platform.platform(),
            "machine": platform.machine(),
        }
        tools = {
            "harness": digest(Path(__file__).read_bytes()),
            "contract": digest(Path(contract.__file__).read_bytes()),
        }
        config = {
            **CONFIG,
            "runtime": runtime,
            "source_sha256": hashes,
            "tools_sha256": tools,
            "catalog_sha256": digest(encode(catalog)),
        }
        config_hash = digest(encode(config))
        # Atomic reservation happens immediately before the first prediction.
        out.mkdir(exist_ok=False)
        reservation = {
            "candidate": CANDIDATE,
            "query_sha256": query_sha,
            "labels_sha256": label_sha256,
            "config_sha256": config_hash,
        }
        write_once(out / "reservation.json", encode(reservation))
        rows = []
        for case in queries:
            start = time.perf_counter()
            code, payload, status = predict_one(runner, scout, env, case["query"])
            duration = (time.perf_counter() - start) * 1000
            hits = []
            for item in (payload or {}).get("ranked_matches", []):
                skill_id = str(item.get("id") or item.get("name") or "").strip()
                if not skill_id or skill_id not in catalog:
                    raise ValueError(
                        "Candidate returned an ID outside the frozen catalog"
                    )
                hits.append({"id": skill_id, "score": item.get("score")})
            rows.append(
                {
                    "id": case["id"],
                    "query": case["query"],
                    "language": case["language"],
                    "category": case["category"],
                    "intent_family": case["intent_family"],
                    "predictions": hits,
                    "abstained": status == "invalid_query_abstention"
                    or (status == "ok" and not hits),
                    "status": status,
                    "exit_code": code,
                    "latency_ms": round(duration, 4),
                }
            )
        prediction = {
            "protocol": CONFIG["protocol"],
            "candidate": CANDIDATE,
            "query_sha256": query_sha,
            "config": config,
            "config_sha256": config_hash,
            "rows": rows,
        }
        raw = encode(prediction)
        write_once(out / "predictions.json", raw)
        write_once(
            out / "prediction.receipt.json",
            encode({**reservation, "predictions_sha256": digest(raw)}),
        )
    return out


def summary(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    non_abstain = [r for r in rows if not r["expected_abstain"]]
    average = lambda key, items: (
        sum(float(r[key]) for r in items) / len(items) if items else None
    )
    tp = sum(r["expected_abstain"] and r["abstained"] for r in rows)
    fp = sum(not r["expected_abstain"] and r["abstained"] for r in rows)
    fn = sum(r["expected_abstain"] and not r["abstained"] for r in rows)
    return {
        "mrr_at_5": average("mrr_at_5", non_abstain),
        "recall_at_5": average("recall_at_5", non_abstain),
        "forbidden_rate_at_5": average("forbidden_at_5", rows),
        "abstention_precision": tp / (tp + fp) if tp + fp else None,
        "abstention_recall": tp / (tp + fn) if tp + fn else None,
        "abstention_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        "abstention_support": tp + fn,
        "abstention_tp": tp,
        "abstention_fp": fp,
        "abstention_fn": fn,
    }


def confidence_intervals(rows: list[dict[str, Any]]) -> dict[str, list[float] | None]:
    """Percentile cluster bootstrap, resampling complete intent families."""
    rng = random.Random(CONFIG["bootstrap_seed"])
    values: dict[str, list[float]] = {
        key: []
        for key in (
            "mrr_at_5",
            "recall_at_5",
            "forbidden_rate_at_5",
            "abstention_precision",
            "abstention_recall",
            "abstention_f1",
        )
    }
    clusters: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        clusters.setdefault(contract._normalized(row["intent_family"]), []).append(row)
    families = sorted(clusters)
    for _ in range(CONFIG["bootstrap_samples"]):
        sample = [row for _ in families for row in clusters[rng.choice(families)]]
        sample_metrics = summary(sample)
        for key, results in values.items():
            value = sample_metrics[key]
            if value is not None:
                results.append(value)
    result = {}
    for key, vals in values.items():
        vals.sort()
        result[key] = (
            [round(vals[int((len(vals) - 1) * q)], 4) for q in (0.025, 0.975)]
            if vals
            else None
        )
    return result


def score(ledger: Path, labels_path: Path) -> Path:
    out = prediction_dir(ledger)
    if (out / "scoring.started").exists():
        raise ValueError("Scoring was already attempted; retain the ledger for review")
    reservation = json_artifact(out / "reservation.json")
    receipt = json_artifact(out / "prediction.receipt.json")
    raw = read_bounded(out / "predictions.json")
    if receipt.get("candidate") != CANDIDATE or reservation != {
        k: receipt[k] for k in reservation
    }:
        raise ValueError("Reservation or prediction receipt mismatch")
    if digest(raw) != receipt.get("predictions_sha256"):
        raise ValueError("Prediction artifact hash mismatch")
    predictions = json.loads(raw.decode("utf-8"))
    config = predictions.get("config", {})
    tools = {
        "harness": digest(Path(__file__).read_bytes()),
        "contract": digest(Path(contract.__file__).read_bytes()),
    }
    if (
        any(config.get(key) != value for key, value in CONFIG.items())
        or config.get("tools_sha256") != tools
        or predictions.get("candidate") != CANDIDATE
        or predictions.get("query_sha256") != receipt.get("query_sha256")
        or digest(encode(config)) != receipt.get("config_sha256")
        or predictions.get("config_sha256") != receipt.get("config_sha256")
    ):
        raise ValueError("Prediction configuration mismatch")
    rows = predictions.get("rows", [])
    if not rows or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Missing or duplicate predictions")
    # Reserve before opening labels; interruptions and bad label submissions cannot be retried silently.
    write_once(out / "scoring.started", encode({"predictions_sha256": digest(raw)}))
    label_bytes = read_bounded(labels_path)
    if digest(label_bytes) != receipt.get("labels_sha256"):
        raise ValueError("Labels do not match the pre-prediction commitment")
    with tempfile.TemporaryDirectory(prefix="skill-pilot-score-") as tmp:
        root = Path(tmp) / "candidate"
        root.mkdir()
        hashes = materialize(root)
        runner = load_runner(root)
        env = runner.build_eval_environment(
            Path(tmp) / "corpus", seed=CONFIG["catalog_seed"]
        )
        catalog = set(env["catalog_ids"])
        if hashes != config.get("source_sha256") or digest(
            encode(sorted(catalog))
        ) != config.get("catalog_sha256"):
            raise ValueError("Frozen source or catalog mismatch")
        label_snapshot = Path(tmp) / "labels.jsonl"
        write_once(label_snapshot, label_bytes)
        labels = validate_labels(label_snapshot, rows, catalog)
        by_id = {item["id"]: item for item in labels}
        scored = []
        metrics: Any = sys.modules["metrics"]

        for row in rows:
            gold = by_id[row["id"]]
            ids = [item["id"] for item in row["predictions"]]
            if (
                len(ids) > CONFIG["limit"]
                or len(ids) != len(set(ids))
                or not set(ids) <= catalog
                or row["status"]
                not in (
                    "ok",
                    "invalid_query_abstention",
                    "error_or_rejected",
                    "invalid_response",
                )
                or (row["status"] == "ok" and row["exit_code"] != 0)
                or (
                    row["status"] == "invalid_query_abstention"
                    and (row["exit_code"] != 1 or ids)
                )
                or (
                    row["status"] == "invalid_response"
                    and (row["exit_code"] != 0 or ids)
                )
                or (row["status"] == "error_or_rejected" and row["exit_code"] == 0)
                or row["abstained"]
                != (
                    row["status"] == "invalid_query_abstention"
                    or (row["status"] == "ok" and not ids)
                )
            ):
                raise ValueError("Invalid prediction row")
            relevant = set(gold["relevant"])
            scored.append(
                {
                    **row,
                    "expected_abstain": gold["expected_abstain"],
                    "relevant": gold["relevant"],
                    "forbidden": gold["forbidden"],
                    "mrr_at_5": metrics.mrr_at_k(ids, relevant, 5),
                    "recall_at_5": metrics.recall_at_k(ids, relevant, 5),
                    "forbidden_at_5": metrics.forbidden_hit_rate(
                        ids, gold["forbidden"], 5
                    ),
                }
            )
    overall = summary(scored)
    counts = {
        language: sum(r["language"] == language for r in scored)
        for language in LANGUAGES
    }
    family_count = len({contract._normalized(r["intent_family"]) for r in scored})
    abstain_count = sum(r["expected_abstain"] for r in scored)
    multi_count = sum(r["category"] == "multi_intent" for r in scored)
    enough = (
        len(scored) >= CONFIG["minimum_cases"]
        and family_count >= CONFIG["minimum_intent_families"]
        and all(n >= CONFIG["minimum_per_language"] for n in counts.values())
        and abstain_count >= CONFIG["minimum_abstain"]
        and multi_count >= CONFIG["minimum_multi_intent"]
    )
    threshold = CONFIG["thresholds"]
    passes = all(r["status"] in ("ok", "invalid_query_abstention") for r in scored)
    for metric, bound in (
        ("mrr_at_5", threshold["mrr_at_5_min"]),
        ("recall_at_5", threshold["recall_at_5_min"]),
        ("forbidden_rate_at_5", threshold["forbidden_rate_at_5_max"]),
        ("abstention_f1", threshold["abstention_f1_min"]),
    ):
        value = overall[metric]
        if value is None or (
            value > bound if metric.endswith("rate_at_5") else value < bound
        ):
            passes = False
    latency = sorted(r["latency_ms"] for r in scored)
    groups = {}
    for lang in LANGUAGES:
        group = [r for r in scored if r["language"] == lang]
        if group:
            cluster_count = len(
                {contract._normalized(r["intent_family"]) for r in group}
            )
            groups[lang] = {
                "count": len(group),
                "intent_families": cluster_count,
                "metrics": summary(group),
                "ci95": confidence_intervals(group) if cluster_count >= 2 else None,
            }
    categories = {
        category: {
            "count": sum(r["category"] == category for r in scored),
            "metrics": summary([r for r in scored if r["category"] == category]),
        }
        for category in sorted({r["category"] for r in scored})
    }
    failures = {
        "miss_at_5": sum(
            not r["expected_abstain"] and r["mrr_at_5"] == 0 for r in scored
        ),
        "forbidden_at_5": sum(bool(r["forbidden_at_5"]) for r in scored),
        "false_abstention": sum(
            not r["expected_abstain"] and r["abstained"] for r in scored
        ),
        "missed_abstention": sum(
            r["expected_abstain"] and not r["abstained"] for r in scored
        ),
        "candidate_errors_or_rejections": sum(
            r["status"] in ("error_or_rejected", "invalid_response") for r in scored
        ),
        "invalid_query_abstentions": sum(
            r["status"] == "invalid_query_abstention" for r in scored
        ),
    }
    report = {
        "candidate": CANDIDATE,
        "scoring_runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "predictions_sha256": digest(raw),
        "labels_sha256": receipt["labels_sha256"],
        "config_sha256": receipt["config_sha256"],
        "verdict": "INSUFFICIENT" if not enough else ("PASS" if passes else "FAIL"),
        "overall": overall,
        "ci95": confidence_intervals(scored),
        "by_language": groups,
        "by_category": categories,
        "coverage": {
            "cases": len(scored),
            "intent_families": family_count,
            "by_language": counts,
            "abstain_cases": abstain_count,
            "multi_intent_cases": multi_count,
        },
        "failure_counts": failures,
        "multi_intent": summary([r for r in scored if r["category"] == "multi_intent"]),
        "latency_ms": {
            "p50": statistics.median(latency),
            "p95": latency[int(0.95 * (len(latency) - 1))],
        },
        "cases": scored,
    }
    report_bytes = encode(report)
    write_once(out / "score.json", report_bytes)
    write_once(
        out / "score.receipt.json",
        encode({"score_sha256": digest(report_bytes), **receipt}),
    )
    return out / "score.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "catalog", help="List the frozen synthetic catalog for independent labeling"
    )
    check = sub.add_parser("validate-queries")
    check.add_argument("queries", type=Path)
    check_labels = sub.add_parser("validate-labels")
    check_labels.add_argument("--queries", type=Path, required=True)
    check_labels.add_argument("--labels", type=Path, required=True)
    pred = sub.add_parser("predict")
    pred.add_argument("--queries", type=Path, required=True)
    pred.add_argument("--labels-sha256", required=True)
    pred.add_argument("--ledger", type=Path, required=True)
    scoring = sub.add_parser("score")
    scoring.add_argument("--labels", type=Path, required=True)
    scoring.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command in ("catalog", "validate-queries", "validate-labels"):
            with tempfile.TemporaryDirectory(prefix="skill-pilot-validation-") as tmp:
                root = Path(tmp) / "candidate"
                root.mkdir()
                materialize(root)
                if args.command == "catalog":
                    runner = load_runner(root)
                    specs = sys.modules["corpus_builder"].CANONICAL_CATALOG
                    print(
                        json.dumps(
                            [
                                {
                                    "id": s.skill_id,
                                    "description": s.description,
                                    "category": s.category,
                                }
                                for s in specs
                            ],
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                else:
                    query_bytes = read_bounded(args.queries)
                    query_snapshot = Path(tmp) / "queries.jsonl"
                    write_once(query_snapshot, query_bytes)
                    cases = validate_queries(
                        query_snapshot, [root / p for p in EXPOSED]
                    )
                    if args.command == "validate-labels":
                        if issues := query_readiness(cases):
                            raise ValueError(
                                "Query coverage insufficient: " + "; ".join(issues)
                            )
                        runner = load_runner(root)
                        env = runner.build_eval_environment(
                            Path(tmp) / "corpus", seed=CONFIG["catalog_seed"]
                        )
                        label_bytes = read_bounded(args.labels)
                        label_snapshot = Path(tmp) / "labels.jsonl"
                        write_once(label_snapshot, label_bytes)
                        labels = validate_labels(
                            label_snapshot, cases, set(env["catalog_ids"])
                        )
                        if (
                            sum(row["expected_abstain"] for row in labels)
                            < CONFIG["minimum_abstain"]
                        ):
                            raise ValueError("Insufficient finalized abstention labels")
                        print(f"Label SHA-256 commitment: {digest(label_bytes)}")
                    print(
                        f"Valid query records: {len(cases)}; screening does not prove independence."
                    )
        elif args.command == "predict":
            print(
                f"Prediction artifacts: {predict(args.queries, args.labels_sha256, args.ledger)}"
            )
        else:
            print(f"Score report: {score(args.ledger, args.labels)}")
    except (
        ContractError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        print(f"Blind evaluation stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
