"""Untouched 8-query Vietnamese benchmark comparing raw VI vs. host-LLM structured translation."""

from __future__ import annotations

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "skills" / "skill-pilot" / "scripts"))

import metrics
import skill_scout

CATALOG = [
    {
        "name": "react-ui",
        "category": "ui",
        "tags": ["react"],
        "description": "Build React web applications and UI.",
    },
    {
        "name": "tailwind-css",
        "category": "ui",
        "tags": ["tailwind"],
        "description": "Style web apps with Tailwind CSS.",
    },
    {
        "name": "fastapi-backend",
        "category": "api",
        "tags": ["fastapi", "python"],
        "description": "Build Python FastAPI REST APIs.",
    },
    {
        "name": "docker-ops",
        "category": "ops",
        "tags": ["docker"],
        "description": "Containerize apps with Docker.",
    },
    {
        "name": "postgres-tuning",
        "category": "db",
        "tags": ["postgres", "sql"],
        "description": "Optimize PostgreSQL SQL queries and indexes.",
    },
    {
        "name": "orm-helper",
        "category": "db",
        "tags": ["orm"],
        "description": "Object-relational mapping ORM helper.",
    },
    {
        "name": "chart-dashboard",
        "category": "viz",
        "tags": ["chart", "dashboard"],
        "description": "Create interactive data chart dashboards.",
    },
    {
        "name": "powerpoint-deck",
        "category": "slides",
        "tags": ["powerpoint"],
        "description": "Create PowerPoint presentations.",
    },
    {
        "name": "pytest-testing",
        "category": "test",
        "tags": ["pytest", "python"],
        "description": "Write Python unit tests with pytest.",
    },
    {
        "name": "browser-qa",
        "category": "test",
        "tags": ["browser", "ui"],
        "description": "Test web UI in a real browser.",
    },
    {
        "name": "selenium-runner",
        "category": "test",
        "tags": ["selenium"],
        "description": "Browser automation with Selenium.",
    },
    {
        "name": "react-native-ui",
        "category": "mobile",
        "tags": ["react-native"],
        "description": "Design React Native mobile app UI.",
    },
    {
        "name": "flutter-ui",
        "category": "mobile",
        "tags": ["flutter"],
        "description": "Build Flutter mobile UI.",
    },
    {
        "name": "vercel-deploy",
        "category": "deploy",
        "tags": ["vercel"],
        "description": "Deploy web apps to Vercel.",
    },
    {
        "name": "netlify-deploy",
        "category": "deploy",
        "tags": ["netlify"],
        "description": "Deploy web apps to Netlify.",
    },
]

CASES = [
    {
        "id": "u-1",
        "vi": "làm web react trừ tailwind",
        "pos_en": "build a React web application",
        "neg_en": "exclude Tailwind",
        "gold": {"react-ui"},
        "forb": {"tailwind-css"},
    },
    {
        "id": "u-2",
        "vi": "xây dựng api python bằng fastapi nhưng không dùng docker",
        "pos_en": "build a Python API using FastAPI",
        "neg_en": "do not use Docker",
        "gold": {"fastapi-backend"},
        "forb": {"docker-ops"},
    },
    {
        "id": "u-3",
        "vi": "toi uu truy van sql postgres tranh orm",
        "pos_en": "optimize PostgreSQL SQL queries",
        "neg_en": "avoid ORM",
        "gold": {"postgres-tuning"},
        "forb": {"orm-helper"},
    },
    {
        "id": "u-4",
        "vi": "tao dashboard bieu do du lieu khong dung powerpoint",
        "pos_en": "create a data chart dashboard",
        "neg_en": "do not use PowerPoint",
        "gold": {"chart-dashboard"},
        "forb": {"powerpoint-deck"},
    },
    {
        "id": "u-5",
        "vi": "viết unit test cho backend python bằng pytest",
        "pos_en": "write unit tests for a Python backend using pytest",
        "neg_en": "",
        "gold": {"pytest-testing"},
        "forb": set(),
    },
    {
        "id": "u-6",
        "vi": "kiểm thử giao diện web trên trình duyệt ngoại trừ selenium",
        "pos_en": "test web UI in a browser",
        "neg_en": "exclude Selenium",
        "gold": {"browser-qa"},
        "forb": {"selenium-runner"},
    },
    {
        "id": "u-7",
        "vi": "thiết kế giao diện mobile app react native trừ flutter",
        "pos_en": "design a React Native mobile app UI",
        "neg_en": "exclude Flutter",
        "gold": {"react-native-ui"},
        "forb": {"flutter-ui"},
    },
    {
        "id": "u-8",
        "vi": "triển khai ứng dụng web lên vercel không dùng netlify",
        "pos_en": "deploy a web application to Vercel",
        "neg_en": "do not use Netlify",
        "gold": {"vercel-deploy"},
        "forb": {"netlify-deploy"},
    },
]


def _eval_mode(structured: bool) -> dict:
    mrrs, recalls, forbs, lats = [], [], [], []
    for c in CASES:
        if structured:
            pos_q = c["pos_en"]
            _, neg_q = skill_scout._split_query_negations(c["neg_en"])
        else:
            pos_q, neg_q = skill_scout._split_query_negations(c["vi"])
        direct, alias = skill_scout._query_term_groups(pos_q)
        excl = set(skill_scout.query_terms(neg_q)) if neg_q else set()
        t0 = time.perf_counter()
        scored = []
        for s in CATALOG:
            sc = skill_scout.score_record(
                pos_q,
                direct,
                s["name"],
                s["category"],
                s["tags"],
                s["description"],
                alias_tokens=alias,
                excluded_tokens=excl,
            )
            if sc > 0:
                scored.append((sc, s["name"]))
        scored.sort(key=lambda x: (-x[0], x[1]))
        lats.append((time.perf_counter() - t0) * 1000.0)
        preds = [n for _, n in scored[:5]]
        mrrs.append(metrics.mrr_at_k(preds, c["gold"], 5))
        recalls.append(metrics.recall_at_k(preds, c["gold"], 5))
        forbs.append(1.0 if (set(preds) & c["forb"]) else 0.0)
    n = len(CASES)
    return {
        "mrr@5": round(sum(mrrs) / n, 4),
        "recall@5": round(sum(recalls) / n, 4),
        "forbidden@5": round(sum(forbs) / n, 4),
        "retrieval_only_p95_ms": round(sorted(lats)[int(n * 0.95)], 3),
    }


def main() -> int:
    print(
        json.dumps(
            {
                "cases": len(CASES),
                "raw_vi": _eval_mode(False),
                "host_llm_structured": _eval_mode(True),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
