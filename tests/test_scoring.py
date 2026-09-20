"""C01 regression tests: relevance must decide, popularity must not.

Before C01 the two highest-scoring documents for "long context attention"
were off-topic (P1), and every arXiv item tied at exactly 5.00 (P5).
"""
import unittest

from support import sample_items  # noqa: E402
import search  # noqa: E402

ON_TOPIC = ("Longformer", "FlashAttention")


def ranked(items):
    terms = search.content_terms("long context attention")
    idf = search.build_idf(items, terms)
    for it in items:
        rel = search.relevance_of(it, terms, idf)
        it["relevance"] = rel
        it["score"] = search.score(it, 2026, rel)
        it["legacy_score"] = search.legacy_score(it, 2026)
    legacy = sorted(items, key=lambda x: -x["legacy_score"])
    new = sorted(items, key=lambda x: -x["score"])
    return legacy, new


class RelevanceDecides(unittest.TestCase):
    def test_offtopic_loses_to_relevant(self):
        """P1: the old score put two off-topic papers at the top."""
        legacy, new = ranked(sample_items())
        self.assertTrue(
            all(not any(o in i["title"] for o in ON_TOPIC)
                for i in legacy[:2]),
            "baseline should reproduce the defect")
        self.assertTrue(
            all(any(o in i["title"] for o in ON_TOPIC) for i in new[:2]),
            "after C01 both top hits must be on-topic, got %s"
            % [i["title"][:40] for i in new[:2]])

    def test_arxiv_items_are_differentiated(self):
        """P5: arXiv carries no citation count, so every recent arXiv item
        scored exactly 5.00 and the order fell back to insertion order."""
        # Three arXiv items as arxiv.py returns them: citations is None.
        items = [
            dict(id="arxiv:2501.00001", source="arxiv", type="paper",
                 title="PolyKV: A Shared Compressed KV Cache Pool",
                 venue="arXiv", citations=None, year=2025,
                 pdf_url="https://arxiv.org/pdf/2501.00001",
                 abstract="KV cache compression for long context serving."),
            dict(id="arxiv:2501.00002", source="arxiv", type="paper",
                 title="ReST-KV: Robust KV Cache Eviction",
                 venue="arXiv", citations=None, year=2025,
                 pdf_url="https://arxiv.org/pdf/2501.00002",
                 abstract="We evict cache entries with layer-wise output "
                          "reconstruction for long context attention."),
            dict(id="arxiv:2501.00003", source="arxiv", type="paper",
                 title="Squeezing the Cache, Preserving the Truth",
                 venue="arXiv", citations=None, year=2025,
                 pdf_url="https://arxiv.org/pdf/2501.00003",
                 abstract="A study of unrelated molecular structures."),
        ]
        terms = search.content_terms("kv cache compression")
        idf = search.build_idf(items, terms)
        old, new = set(), set()
        for it in items:
            rel = search.relevance_of(it, terms, idf)
            old.add(search.legacy_score(it, 2026))
            new.add(search.score(it, 2026, rel))
        self.assertEqual(len(old), 1, "old scoring tied all arXiv items at %s" % old)
        self.assertGreater(len(new), 1, "new scoring must separate arXiv items")

    def test_relevance_is_normalised(self):
        items = sample_items()
        terms = search.content_terms("long context attention")
        idf = search.build_idf(items, terms)
        for it in items:
            rel = search.relevance_of(it, terms, idf)
            self.assertIsNotNone(rel)
            self.assertGreaterEqual(rel, 0.0)
            self.assertLessEqual(rel, 1.0)

    def test_title_hit_beats_abstract_hit(self):
        terms = ["kv"]
        idf = {"kv": 1.0}
        in_title = search.relevance_of({"title": "KV cache", "abstract": "x"},
                                       terms, idf)
        in_abstract = search.relevance_of({"title": "x", "abstract": "kv cache"},
                                          terms, idf)
        self.assertAlmostEqual(in_title, 1.0)
        self.assertAlmostEqual(in_abstract, 0.5)


class IdfWeighting(unittest.TestCase):
    def test_common_term_is_downweighted(self):
        """A term present in every document carries almost no weight."""
        docs = [{"title": "attention model %d" % i, "abstract": ""}
                for i in range(10)]
        idf = search.build_idf(docs, ["attention"])
        self.assertLess(idf["attention"], 0.2)

    def test_rare_term_keeps_weight(self):
        docs = [{"title": "kv cache %d" % i, "abstract": ""} for i in range(10)]
        docs[0]["title"] = "kv cache eviction"
        idf = search.build_idf(docs, ["eviction"])
        self.assertGreater(idf["eviction"], 1.0)


if __name__ == "__main__":
    unittest.main()
