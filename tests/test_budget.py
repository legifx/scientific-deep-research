"""C04 regression tests: the budget must stop the loop, not just complain.

Live evidence (2026-09-20) with --max-mb 0.5: four repositories were cloned
in full and then deleted, about 36.9 MB transferred for a 0.5 MB budget.
"""
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401   # adds scripts/ to sys.path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load_fetch():
    spec = importlib.util.spec_from_file_location("sdr_fetch", SCRIPTS / "fetch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RepoPreeflight(unittest.TestCase):
    def test_oversized_repo_is_never_cloned(self):
        fm = _load_fetch()
        calls = []

        def fake_clone(cmd, **kw):
            calls.append(cmd)
            raise AssertionError("git clone must not run")

        fm.subprocess.run = fake_clone
        dest = Path(tempfile.mkdtemp())
        item = {"title": "org/bigrepo", "clone_url": "https://github.com/org/bigrepo",
                "size_kb": 8 * 1024}          # 8 MB
        path, size, err = fm.fetch_repo(item, dest, budget=1024 * 1024, used=0)
        self.assertEqual(err, "over_budget_preflight")
        self.assertIsNone(path)
        self.assertEqual(calls, [], "no clone may be attempted")
        shutil.rmtree(dest, ignore_errors=True)

    def test_small_repo_is_cloned(self):
        fm = _load_fetch()
        calls = []
        fm.subprocess.run = lambda cmd, **kw: (calls.append(cmd),
                                               type("R", (), {"returncode": 0,
                                                              "stderr": ""})())[1]
        dest = Path(tempfile.mkdtemp())
        item = {"title": "org/small", "clone_url": "https://github.com/org/small",
                "size_kb": 10}
        fm.fetch_repo(item, dest, budget=1024 * 1024, used=0)
        self.assertEqual(len(calls), 1)
        shutil.rmtree(dest, ignore_errors=True)


class LoopStops(unittest.TestCase):
    def _run(self, fm, sizes, budget_mb):
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".sdr").mkdir()
        items = []
        for i, s in enumerate(sizes):
            items.append({"id": "arxiv:%d" % i, "source": "arxiv", "type": "paper",
                          "title": "Paper %d" % i, "year": 2026,
                          "dedupe_key": "arxiv:%d" % i, "size_kb": 0})
        (tmp / ".sdr" / "round.json").write_text(json.dumps({"items": items}))

        attempts = []

        def fake(item, dest, budget=None, used=0):
            attempts.append(item["id"])
            size = sizes[int(item["id"].split(":")[1])]
            p = dest / "papers" / (item["id"].replace(":", "_") + ".pdf")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"%PDF" + b"x" * max(0, size - 4))
            return p, size, None

        fm.fetch_pdf = fake
        sys.argv = ["fetch.py", "--in", str(tmp / ".sdr" / "round.json"),
                    "--dest", str(tmp / "out"), "--all",
                    "--max-mb", str(budget_mb)]
        fm.main()
        out = tmp / "out"
        result = {"attempts": attempts,
                  "state": json.loads((out / ".sdr" / "state.json").read_text())}
        shutil.rmtree(tmp, ignore_errors=True)
        return result

    def test_loop_stops_after_budget_exceeded(self):
        """P3: previously every remaining item was downloaded and deleted."""
        fm = _load_fetch()
        # item 0 fits, item 1 already blows the budget -> loop must stop
        r = self._run(fm, [100_000, 50_000_000, 1000, 1000, 1000], budget_mb=1)
        self.assertEqual(len(r["attempts"]), 2,
                         "loop must stop after the first overrun, attempted %s"
                         % r["attempts"])

    def test_state_stays_within_budget(self):
        fm = _load_fetch()
        r = self._run(fm, [100_000, 50_000_000, 1000, 1000, 1000], budget_mb=1)
        self.assertLessEqual(r["state"]["bytes_used"], 1024 * 1024)


class VolumeAccounting(unittest.TestCase):
    def test_counts_allocated_blocks(self):
        from sources import common
        tmp = Path(tempfile.mkdtemp())
        d = tmp / "many"
        d.mkdir()
        for i in range(50):
            (d / f"f{i}.txt").write_text("x" * 10)   # 500 logical bytes
        measured = common.disk_bytes(d)
        self.assertGreater(measured, 500,
                           "disk accounting must exceed logical size")
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
