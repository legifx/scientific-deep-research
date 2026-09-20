"""C09 regression tests: no library when nothing relevant was found.

Live evidence (2026-09-20): the nonsense query "zzqqxx nonexistent
flapflop" returned 10 items and reported saturated=false, so SDR happily
built a completely off-topic library.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import search  # noqa: E402
from support import install_fixtures, uninstall_fixtures  # noqa: E402


class RelevanceFloor(unittest.TestCase):
    def setUp(self):
        install_fixtures()

    def tearDown(self):
        uninstall_fixtures()

    def test_no_relevant_results_aborts(self):
        """P9: an unanswerable query must abort, not produce a library."""
        tmp = Path(tempfile.mkdtemp())
        sys.argv = ["search.py", "-q", "zzqqxx nonexistent flapflop",
                    "--effort", "low", "--out", str(tmp / "r.json")]
        # The fixture server always returns the same corpus; relevance is
        # measured against the nonsense query, so nothing can match.
        try:
            search.main()
        except SystemExit:
            pass
        data = json.loads((tmp / "r.json").read_text())
        self.assertTrue(data.get("aborted"), "must abort with no relevant hits")
        self.assertEqual(data["items"], [])
        self.assertTrue(data.get("query_suggestions"))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_lenient_floor_keeps_partial_matches(self):
        """The floor drops only total misses — Jev: lenient (conf. 0.91)."""
        items = [{"title": "KV cache compression", "abstract": ""},
                 {"title": "Unrelated paper about frogs", "abstract": "nothing"}]
        terms = search.content_terms("kv cache compression")
        idf = search.build_idf(items, terms)
        hit = search.relevance_of(items[0], terms, idf)
        miss = search.relevance_of(items[1], terms, idf)
        self.assertGreater(hit, 0.0)
        self.assertEqual(miss, 0.0, "a total miss is what the floor removes")

    def test_stopwords_are_never_content_terms(self):
        self.assertEqual(search.content_terms("the and of for with"), [])

    def test_content_terms_keeps_topical_words(self):
        self.assertEqual(sorted(search.content_terms("kv cache compression")),
                         ["cache", "compression", "kv"])


if __name__ == "__main__":
    unittest.main()
