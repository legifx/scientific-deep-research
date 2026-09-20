"""C02 regression tests: conflicting sources must be flagged, not mixed.

Live evidence: OpenAlex serves the wrong abstract for
W4298289240 ("Generative Adversarial Networks") — the abstract belongs to a
KV-cache paper. arXiv has the correct one. SDR queries both (P2).
"""
import json
import unittest
from pathlib import Path

import support  # noqa: F401,E402   # adds scripts/ to sys.path
import search  # noqa: E402
from support import FIXTURES  # noqa: E402
from sources import openalex  # noqa: E402

CORRUPT = json.loads(
    (FIXTURES / "openalex_work_corrupt_abstract.json").read_text())


def _abstract_of(work):
    inv = work.get("abstract_inverted_index") or {}
    pos = {}
    for w, idx in inv.items():
        for i in idx:
            pos[i] = w
    return " ".join(pos[i] for i in sorted(pos))


class ConflictDetection(unittest.TestCase):
    def test_abstract_conflict_is_flagged(self):
        bad = openalex._to_item(CORRUPT)
        good = dict(bad)
        good["source"] = "arxiv"
        good["abstract"] = ("We propose a new framework for estimating "
                            "generative models via an adversarial process, in "
                            "which we simultaneously train two models.")
        merged = search.merge(good, bad)
        self.assertIsNotNone(merged, "same title must merge")
        self.assertTrue(merged.get("conflict"))
        self.assertEqual(merged["conflict_fields"], ["abstract"])
        det = merged["conflict_detail"]["abstract"]
        self.assertLess(det["similarity"], search.CONFLICT_THRESHOLD)
        # the authoritative source wins
        self.assertEqual(det["used"]["source"], "arxiv")
        self.assertEqual(det["rejected"]["source"], "openalex")
        # but nothing is lost: both variants stay in the record
        self.assertIn("adversarial", merged["abstract"])
        self.assertIn("Key-Value", det["rejected"]["value"])

    def test_live_corrupt_abstract_really_differs(self):
        """Guards the fixture: upstream must still be wrong, else this test
        stops being a regression test for P2."""
        bad_abstract = _abstract_of(CORRUPT)
        self.assertIn("KV cache", bad_abstract)
        good = ("We propose a new framework for estimating generative models "
                "via an adversarial process")
        self.assertLess(search.common.jaccard(bad_abstract, good),
                        search.CONFLICT_THRESHOLD)

    def test_agreeing_sources_do_not_flag(self):
        a = {"title": "Longformer: The Long-Document Transformer",
             "abstract": "Transformers cannot process long sequences because "
                         "of self attention cost.",
             "source": "arxiv", "citations": 10}
        b = dict(a)
        b["source"] = "openalex"
        merged = search.merge(a, b)
        self.assertFalse(merged.get("conflict"))

    def test_diverging_titles_are_not_merged(self):
        a = {"title": "Generative Adversarial Networks", "abstract": "x y z",
             "source": "arxiv"}
        b = {"title": "Attention-deficit hyperactivity disorder",
             "abstract": "a b c", "source": "openalex"}
        self.assertIsNone(search.merge(a, b),
                          "different works must not be merged")


if __name__ == "__main__":
    unittest.main()
