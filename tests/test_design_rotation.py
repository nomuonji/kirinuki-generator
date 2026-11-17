import json
import re
import unittest
from pathlib import Path

from packages.design_rotation import (DEFAULT_POOL, TEMPLATE_VARIANTS, TEMPLATES, design_pool, forced_design,
                                      history_from_env, history_from_ledger, pick_designs)

ALL = TEMPLATES

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "apps" / "remotion" / "src" / "design" / "registry.ts"
TEMPLATE_DIR = REGISTRY.parent / "templates"


class DesignRotationTests(unittest.TestCase):
    def test_never_repeats_back_to_back(self):
        history = []
        for run in range(12):
            for pick in pick_designs(history, 3, seed=f"source-{run}", pool=ALL):
                if history:
                    self.assertNotEqual(history[-1]["template"], pick["template"])
                history.append(pick)

    def test_uses_every_template_before_repeating(self):
        picks = pick_designs([], len(TEMPLATES), seed="abc", pool=ALL)
        self.assertEqual(sorted(p["template"] for p in picks), sorted(TEMPLATES))
        more = pick_designs(picks, len(TEMPLATES), seed="abc", pool=ALL)
        self.assertEqual(sorted(p["template"] for p in more), sorted(TEMPLATES))

    def test_rotation_continues_across_runs(self):
        first = pick_designs([], 2, seed="one", pool=ALL)
        second = pick_designs(first, 3, seed="two", pool=ALL)
        self.assertEqual(len({p["template"] for p in first + second}), 5)
        self.assertEqual(len({p["template"] for p in pick_designs([], len(ALL), seed="x", pool=ALL)}), len(ALL))

    def test_colour_variants_rotate_within_a_template(self):
        history = []
        for _ in range(len(TEMPLATES) * 3):
            history += pick_designs(history, 1, seed="v", pool=ALL)
        for template, count in TEMPLATE_VARIANTS.items():
            used = [h["variant"] for h in history if h["template"] == template]
            self.assertEqual(set(used[:count]), set(range(count)), template)

    def test_cycle_order_is_not_a_fixed_sequence(self):
        orders = set()
        for seed in range(8):
            orders.add(tuple(p["template"] for p in pick_designs([], len(ALL), seed=str(seed), pool=ALL)))
        self.assertGreater(len(orders), 1)

    def test_ignores_unknown_history_and_reads_env_and_ledger(self):
        env = {"KIRINUKI_DESIGN_HISTORY": json.dumps([{"template": "retired"}, {"template": "pop", "variant": 1}])}
        self.assertEqual(history_from_env(env), [{"template": "pop", "variant": 1}])
        self.assertEqual(history_from_env({"KIRINUKI_DESIGN_HISTORY": "{broken"}), [])
        ledger = {
            "b": {"publishAt": "2026-11-03T03:00:00Z", "design": {"template": "note", "variant": 0}},
            "a": {"publishAt": "2026-11-02T11:00:00Z", "design": {"template": "pop", "variant": 2}},
            "c": {"publishAt": "2026-11-04T03:00:00Z"},
        }
        self.assertEqual([h["template"] for h in history_from_ledger(ledger)], ["pop", "note"])
        self.assertNotEqual(pick_designs(history_from_ledger(ledger), 1, pool=ALL)[0]["template"], "note")

    def test_default_pool_is_the_standard_clip_layout(self):
        self.assertEqual(design_pool({}), ("telop",))
        self.assertEqual(design_pool({"KIRINUKI_DESIGN_POOL": "all"}), TEMPLATES)
        self.assertEqual(design_pool({"KIRINUKI_DESIGN_POOL": "pop, nope ,note"}), ("pop", "note"))
        self.assertEqual(design_pool({"KIRINUKI_DESIGN_POOL": "nope"}), DEFAULT_POOL)
        # Old ledger entries (other templates) don't stop telop, and its variants rotate.
        history = [{"template": "pop", "variant": 1}, {"template": "telop", "variant": 0}]
        picks = pick_designs(history, 3, seed="s", pool=DEFAULT_POOL)
        self.assertEqual({p["template"] for p in picks}, {"telop"})
        self.assertEqual(set(p["variant"] for p in picks[:2]), {1, 2})

    def test_forced_design(self):
        self.assertIsNone(forced_design({}))
        self.assertEqual(forced_design({"KIRINUKI_DESIGN_TEMPLATE": "terminal:2"}), {"template": "terminal", "variant": 2})
        with self.assertRaises(ValueError):
            forced_design({"KIRINUKI_DESIGN_TEMPLATE": "nope"})

    def test_matches_remotion_registry(self):
        """The ids and colour-variant counts must match what the Remotion templates implement."""
        source = REGISTRY.read_text(encoding="utf-8")
        ids = re.findall(r"^\s+(\w+): \{component: (\w+), variants: (\w+)\}", source, re.M)
        self.assertEqual([i[0] for i in ids], list(TEMPLATES))
        for template_id, component, _ in ids:
            text = (TEMPLATE_DIR / f"{component}.tsx").read_text(encoding="utf-8")
            block = re.search(r"const PALETTES = \[(.*?)\n\];", text, re.S)
            self.assertIsNotNone(block, component)
            palettes = len(re.findall(r"^\s+\{", block.group(1), re.M))
            self.assertEqual(palettes, TEMPLATE_VARIANTS[template_id], component)


if __name__ == "__main__":
    unittest.main()
