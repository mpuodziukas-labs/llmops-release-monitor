import contextlib, io, pathlib, subprocess, sys, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import evaluate, releasemon as rm


def run_main():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = evaluate.main()
    return code, buf.getvalue()


class Mutant:
    """Break one detector inside the block, restore on exit."""
    def __init__(self, name, value):
        self.name, self.value = name, value

    def __enter__(self):
        self.orig = getattr(rm, self.name)
        setattr(rm, self.name, self.value)

    def __exit__(self, *a):
        setattr(rm, self.name, self.orig)


class Units(unittest.TestCase):
    def test_kappa_by_hand(self):
        # po=0.8, pa=pb=0.6 -> pe=0.52 -> kappa=(0.8-0.52)/0.48
        a = [1] * 6 + [0] * 4
        b = [1] * 5 + [0, 1] + [0] * 3
        self.assertAlmostEqual(rm.cohen_kappa(a, b), (0.8 - 0.52) / 0.48, places=9)
        self.assertEqual(rm.cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]), 1.0)

    def test_psi_identical_is_zero(self):
        x = rm.score_window(8, 2, 2000, 1)
        self.assertAlmostEqual(rm.psi(x, x), 0.0, places=6)

    def test_gate_tolerance_boundary(self):
        self.assertTrue(rm.gate({"quality": 0.90}, {"quality": 0.895}))
        self.assertFalse(rm.gate({"quality": 0.90}, {"quality": 0.88}))

    def test_chain_detects_edit_and_delete(self):
        a = evaluate.fresh().state["audit"]
        self.assertEqual(rm.verify_chain(a), (True, None))
        self.assertFalse(rm.verify_chain(a[:1] + a[2:])[0])
        a[1]["data"]["model"] = "other"
        self.assertEqual(rm.verify_chain(a), (False, 1))

    def test_deterministic(self):
        self.assertEqual(run_main(), run_main())

    def test_subprocess_under_60s(self):
        r = subprocess.run([sys.executable, "evaluate.py"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.strip().endswith("6/6 planted failures caught, 4/4 controls passed"))

    def test_readme_matches_output(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn(run_main()[1].rstrip("\n"), readme)


class Mutants(unittest.TestCase):
    def missed(self, name, value):
        with Mutant(name, value):
            code, out = run_main()
        self.assertEqual(code, 1, out)
        self.assertEqual(run_main()[0], 0)  # restored, GREEN again
        return [l for l in out.splitlines() if l.endswith("MISS")]

    def test_gate_always_promotes(self):
        self.assertTrue(any("regressed" in r for r in self.missed("gate", lambda *a, **k: True)))

    def test_slo_never_breaches(self):
        rows = self.missed("slo_breaches", lambda *a: [])
        self.assertTrue(any("latency" in r for r in rows) and any("cost" in r for r in rows))

    def test_psi_blind(self):
        self.assertTrue(any("drift window" in r for r in self.missed("psi", lambda *a, **k: 0.0)))

    def test_kappa_blind(self):
        self.assertTrue(any("judge drifts" in r for r in self.missed("judge_drifted", lambda *a: False)))

    def test_chain_blind(self):
        self.assertTrue(any("tampered" in r for r in self.missed("verify_chain", lambda e: (True, None))))

    def test_false_alarm_fails_control(self):
        self.assertTrue(any("stable production" in r for r in self.missed("psi", lambda *a, **k: 9.9)))

    def test_exit_code_one_in_subprocess(self):
        code = "import sys, evaluate, releasemon as rm; rm.psi = lambda *a, **k: 0.0; sys.exit(evaluate.main())"
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
