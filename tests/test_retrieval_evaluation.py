from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase, main

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.retrieval.evaluation import DEFAULT_DATASET, EvalOptions, run_retrieval_eval

FIXTURE_DIR = Path(__file__).resolve().parent / "evals" / "retrieval"


class RetrievalEvaluationTests(TestCase):
    def test_default_local_docs_fixture_eval_passes(self) -> None:
        report = run_retrieval_eval(EvalOptions(dataset_path=DEFAULT_DATASET))

        self.assertEqual(report["summary"]["cases"], 6)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertGreater(report["summary"]["mrr"], 0)

    def test_legacy_inline_neon_fixture_eval_passes(self) -> None:
        report = run_retrieval_eval(EvalOptions(dataset_path=FIXTURE_DIR / "neon_fixture.json"))

        self.assertEqual(report["summary"]["cases"], 3)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertGreater(report["summary"]["mrr"], 0)


if __name__ == "__main__":
    main()
