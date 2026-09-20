"""C05 regression tests: a failed download must survive as link-only.

Live evidence (2026-09-20): two of eight items returned HTTP 403 and were
then absent from INDEX.md and manifest.json entirely. The workaround
documented in SKILL.md (re-add with --ids) cannot work, because the same
URL fails again.
"""
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LinkOnlyFallback(unittest.TestCase):
    def test_failed_download_becomes_link_only(self):
        fm = _load("sdr_fetch", "fetch.py")
        tmp = Path(tempfile.mkdtemp())
        items = [{"id": "arxiv:1", "source": "arxiv", "type": "paper",
                  "title": "Paywalled Paper", "year": 2015,
                  "dedupe_key": "arxiv:1", "pdf_url": "https://example.org/x.pdf"}]
        (tmp / "round.json").write_text(json.dumps({"items": items}))

        calls = []

        def fake(item, dest, budget=None, used=0):
            calls.append(item["id"])
            return None, 0, "http_403"

        fm.fetch_pdf = fake
        sys.argv = ["fetch.py", "--in", str(tmp / "round.json"),
                    "--dest", str(tmp / "out"), "--all"]
        fm.main()

        fetched = json.loads((tmp / "out" / ".sdr" / "fetched.json").read_text())
        self.assertEqual(len(fetched), 1, "the item must not disappear")
        rec = fetched[0]
        self.assertIsNone(rec["local_path"])
        self.assertEqual(rec["status"], "link_only")
        self.assertEqual(rec["failure_reason"], "http_403")
        shutil.rmtree(tmp, ignore_errors=True)

    def test_no_pdf_url_is_reported(self):
        fm = _load("sdr_fetch", "fetch.py")
        dest = Path(tempfile.mkdtemp())
        _, _, err = fm.fetch_pdf({"id": "arxiv:2", "title": "No PDF"}, dest)
        self.assertEqual(err, "no_pdf_url")
        shutil.rmtree(dest, ignore_errors=True)


class ManifestOutput(unittest.TestCase):
    def _build(self, records):
        mm = _load("sdr_manifest", "manifest.py")
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".sdr").mkdir()
        (tmp / ".sdr" / "fetched.json").write_text(json.dumps(records))
        sys.argv = ["manifest.py", "--dest", str(tmp), "--topic", "t",
                    "--effort", "low"]
        mm.main()
        man = json.loads((tmp / "manifest.json").read_text())
        index = (tmp / "INDEX.md").read_text()
        shutil.rmtree(tmp, ignore_errors=True)
        return man, index

    def test_schema_version_is_present(self):
        man, _ = self._build([{"id": "arxiv:1", "title": "A", "year": 2026,
                               "local_path": "papers/a.pdf", "score": 1.0}])
        self.assertEqual(man["schema_version"], 2)

    def test_link_only_is_marked_in_index(self):
        man, index = self._build([
            {"id": "arxiv:1", "title": "Downloaded Paper", "year": 2026,
             "local_path": "papers/a.pdf", "score": 1.0},
            {"id": "arxiv:2", "title": "Paywalled Paper", "year": 2015,
             "status": "link_only", "failure_reason": "http_403", "score": 1.0},
        ])
        self.assertEqual(man["report"]["link_only"], 1)
        self.assertIn("not downloaded (http_403)", index)

    def test_conflict_is_surfaced_in_index(self):
        man, index = self._build([
            {"id": "arxiv:3", "title": "Conflicting Paper", "year": 2020,
             "local_path": "papers/b.pdf", "score": 1.0,
             "conflict": True, "conflict_fields": ["abstract"],
             "conflict_detail": {"abstract": {"similarity": 0.08,
                                              "used": {"source": "arxiv"},
                                              "rejected": {"source": "openalex"}}}},
        ])
        self.assertEqual(man["report"]["conflicts"], 1)
        self.assertIn("Metadata conflict", index)

    def test_defaults_to_downloaded_when_status_missing(self):
        man, _ = self._build([{"id": "arxiv:1", "title": "A", "year": 2026,
                               "local_path": "papers/a.pdf"}])
        self.assertEqual(man["documents"][0]["status"], "downloaded")


if __name__ == "__main__":
    unittest.main()
