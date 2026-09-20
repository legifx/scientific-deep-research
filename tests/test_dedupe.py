"""C07 regression tests: duplicates that the old dedupe could not catch.

Live evidence (2026-09-20): "Alpha-Park/genpark-..." and
"alphaparkinc/genpark-..." were both cloned; arXiv-DOIs
(10.48550/arxiv.X) differ from publisher DOIs, so the same paper appeared
twice.
"""
import unittest

import search  # noqa: E402


class DedupeKeys(unittest.TestCase):
    def test_arxiv_doi_maps_to_arxiv_key(self):
        a = {"id": "arxiv:1406.2661", "doi": "10.48550/arxiv.1406.2661",
             "title": "Generative Adversarial Networks", "source": "arxiv"}
        self.assertEqual(search.dedupe_key(a), "arxiv:1406.2661")

    def test_same_paper_two_doi_spellings(self):
        """The classic cross-source duplicate."""
        arxiv_rec = {"id": "arxiv:1406.2661", "doi": "10.48550/arxiv.1406.2661",
                     "title": "Generative Adversarial Networks",
                     "source": "arxiv"}
        oa_rec = {"id": "openalex:W4298289240", "openalex_id": "W4298289240",
                  "doi": "10.48550/arxiv.1406.2661",
                  "title": "Generative Adversarial Networks",
                  "source": "openalex"}
        self.assertEqual(search.dedupe_key(arxiv_rec),
                         search.dedupe_key(oa_rec))

    def test_repo_owner_is_ignored(self):
        a = {"id": "github:Alpha-Park/genpark", "title": "Alpha-Park/genpark",
             "clone_url": "https://github.com/Alpha-Park/genpark.git",
             "source": "github"}
        b = {"id": "github:alphaparkinc/genpark",
             "title": "alphaparkinc/genpark",
             "clone_url": "https://github.com/alphaparkinc/genpark.git",
             "source": "github"}
        self.assertEqual(search.dedupe_key(a), search.dedupe_key(b))

    def test_different_repos_stay_apart(self):
        a = {"id": "github:a/kvzip", "title": "a/kvzip",
             "clone_url": "https://github.com/a/kvzip.git", "source": "github"}
        b = {"id": "github:b/defensivekv", "title": "b/defensivekv",
             "clone_url": "https://github.com/b/defensivekv.git",
             "source": "github"}
        self.assertNotEqual(search.dedupe_key(a), search.dedupe_key(b))

    def test_distinct_papers_stay_apart(self):
        a = {"id": "openalex:W1", "title": "Longformer", "year": 2020,
             "source": "openalex"}
        b = {"id": "openalex:W2", "title": "FlashAttention", "year": 2022,
             "source": "openalex"}
        self.assertNotEqual(search.dedupe_key(a), search.dedupe_key(b))

    def test_priority_order(self):
        """DOI before arXiv id before OpenAlex id before title."""
        self.assertTrue(search.dedupe_key(
            {"id": "arxiv:1", "doi": "10.1000/x", "title": "t"}).startswith("doi:"))
        self.assertTrue(search.dedupe_key(
            {"id": "arxiv:1234.5678", "title": "t"}).startswith("arxiv:"))
        self.assertTrue(search.dedupe_key(
            {"id": "openalex:W1", "openalex_id": "W1", "title": "t"}
        ).startswith("openalex:"))
        self.assertTrue(search.dedupe_key(
            {"id": "x", "title": "Some Paper", "year": 2020}).startswith("title:"))


if __name__ == "__main__":
    unittest.main()
