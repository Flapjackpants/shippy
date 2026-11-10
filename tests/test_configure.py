import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "shippy-t3"
    / "scripts"
    / "configure.py"
)


def load_configure_module():
    spec = importlib.util.spec_from_file_location("configure", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {SCRIPT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestConfigureBlackBox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.configure = load_configure_module()

    def setUp(self):
        self.catalog = self.configure.load_catalog()

    def test_01_default_routes_order(self):
        cfg = self.configure.default_config(self.catalog)
        routes = self.configure.build_routes(self.catalog, cfg)

        expected_hr = [
            "opencode/deepseek-v4.1-flash-free",
            "gemini-3.8-flash",
            "opencode/inkling-2-small-free",
            "opencode/mimo-v2.6-flash-free",
        ]
        self.assertEqual(
            [m["id"] for m in routes["high-risk"]["free"]], expected_hr
        )

        expected_ord = [
            "gemini-3.8-flash",
            "opencode/deepseek-v4.1-flash-free",
            "opencode/inkling-2-small-free",
            "opencode/mimo-v2.6-flash-free",
        ]
        self.assertEqual(
            [m["id"] for m in routes["ordinary"]["free"]], expected_ord
        )

        expected_mech = [
            "opencode/glm-5.3-flash-free",
            "opencode/mimo-v2.6-flash-free",
            "opencode/longcat-2.5-free",
            "opencode/inkling-2-small-free",
        ]
        self.assertEqual(
            [m["id"] for m in routes["mechanical"]["free"]], expected_mech
        )

        expected_ver = [
            "kilo/kilo-auto/free",
            "opencode/glm-5.3-flash-free",
            "opencode/mimo-v2.6-flash-free",
            "opencode/longcat-2.5-free",
        ]
        self.assertEqual(
            [m["id"] for m in routes["verification"]["free"]], expected_ver
        )

        self.assertEqual(
            [m["id"] for m in routes["high-risk"]["fallback"]],
            ["gpt-6-sol", "claude-sonnet-5-5"],
        )
        self.assertEqual(
            [m["id"] for m in routes["verification"]["fallback"]],
            ["gpt-6-luna", "claude-haiku-5-5"],
        )

    def test_02_removing_opencode_removes_from_rendered(self):
        cfg = self.configure.default_config(self.catalog)
        cfg["routes"] = [p for p in cfg["routes"] if p != "opencode"]
        routes = self.configure.build_routes(self.catalog, cfg)
        rendered = self.configure.render_routes(self.catalog, routes)
        self.assertNotIn("opencode:", rendered)

    def test_03_per_category_limit(self):
        cfg = self.configure.default_config(self.catalog)
        cfg["perCategory"] = 2
        routes = self.configure.build_routes(self.catalog, cfg)
        for cat_name in self.configure.CATEGORIES:
            self.assertEqual(len(routes[cat_name]["free"]), 2)

    def test_04_fallback_order(self):
        cfg = self.configure.default_config(self.catalog)
        cfg["fallbacks"] = ["claudeAgent", "codex"]
        routes = self.configure.build_routes(self.catalog, cfg)
        for cat_name in self.configure.CATEGORIES:
            fb = routes[cat_name]["fallback"]
            self.assertGreater(len(fb), 0)
            self.assertEqual(fb[0]["provider"], "claudeAgent")

    def test_05_tags_in_rendered_output(self):
        cfg = {
            "routes": ["antigravity", "acpRegistry_kimi_code"],
            "fallbacks": [],
            "perCategory": 4,
        }
        routes = self.configure.build_routes(self.catalog, cfg)
        rendered = self.configure.render_routes(self.catalog, routes)
        self.assertIn(
            'antigravity:gemini-3.8-flash {"thinking_level":"medium"} [pool antigravity/gemini]',
            rendered,
        )
        self.assertIn(
            'acpRegistry_kimi_code:kimi-code/k3.1-pro {"thinking":"high"} [pool acpRegistry_kimi_code] [limited]',
            rendered,
        )

    def test_06_save_and_load_config_env(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            orig = os.environ.get("SHIPPY_CONFIG_DIR")
            try:
                os.environ["SHIPPY_CONFIG_DIR"] = tmp_dir
                cfg = self.configure.default_config(self.catalog)
                json_path, md_path = self.configure.save(self.catalog, cfg)
                self.assertTrue(json_path.is_file())
                self.assertTrue(md_path.is_file())
                loaded = self.configure.load_config(self.catalog)
                self.assertEqual(loaded["routes"], cfg["routes"])
                self.assertEqual(loaded["fallbacks"], cfg["fallbacks"])
                self.assertEqual(loaded["perCategory"], cfg["perCategory"])
            finally:
                if orig is not None:
                    os.environ["SHIPPY_CONFIG_DIR"] = orig
                else:
                    os.environ.pop("SHIPPY_CONFIG_DIR", None)

    def test_07_non_tty_returns_2(self):
        with patch("sys.stdin.isatty", return_value=False):
            res = self.configure.main([])
            self.assertEqual(res, 2)

    def test_08_subprocess_defaults_print(self):
        res = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--defaults", "--print"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        dash_lines = [
            line for line in res.stdout.splitlines() if line.startswith("- ")
        ]
        self.assertEqual(len(dash_lines), 4)

    def test_13_paid_provider_not_in_free_routes(self):
        cfg = {"routes": ["codex", "opencode"], "fallbacks": [], "perCategory": 4}
        routes = self.configure.build_routes(self.catalog, cfg)
        for cat in self.configure.CATEGORIES:
            providers = [m["provider"] for m in routes[cat]["free"]]
            self.assertNotIn("codex", providers)

    def test_14_load_config_moves_paid_provider_from_routes_to_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            orig = os.environ.get("SHIPPY_CONFIG_DIR")
            try:
                os.environ["SHIPPY_CONFIG_DIR"] = tmp_dir
                cfg_file = Path(tmp_dir) / "t3.json"
                raw = {
                    "routes": ["opencode", "codex"],
                    "fallbacks": [],
                    "perCategory": 4,
                }
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(raw, f)
                loaded = self.configure.load_config(self.catalog)
                self.assertEqual(loaded["routes"], ["opencode"])
                self.assertEqual(loaded["fallbacks"], ["codex"])
            finally:
                if orig is not None:
                    os.environ["SHIPPY_CONFIG_DIR"] = orig
                else:
                    os.environ.pop("SHIPPY_CONFIG_DIR", None)

    def test_15_interactive_loop_paid_provider_cycles_fallback_off_fallback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            orig = os.environ.get("SHIPPY_CONFIG_DIR")
            try:
                os.environ["SHIPPY_CONFIG_DIR"] = tmp_dir
                inputs = iter(["12", "12", "s"])
                with patch("builtins.input", side_effect=inputs), \
                     patch("sys.stdin.isatty", return_value=True), \
                     patch("sys.stdout", new_callable=io.StringIO):
                    ret = self.configure.main([])
                self.assertEqual(ret, 0)
                cfg_file = Path(tmp_dir) / "t3.json"
                self.assertTrue(cfg_file.is_file())
                with open(cfg_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertIn("codex", saved["fallbacks"])
                self.assertNotIn("codex", saved["routes"])
            finally:
                if orig is not None:
                    os.environ["SHIPPY_CONFIG_DIR"] = orig
                else:
                    os.environ.pop("SHIPPY_CONFIG_DIR", None)


class TestConfigureWhiteBox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.configure = load_configure_module()

    def setUp(self):
        self.catalog = self.configure.load_catalog()

    def test_09_normalization(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_file = Path(tmp_dir) / "t3.json"

            # Case A: unknown provider, both routes & fallbacks, clamp 99 -> 8
            raw_a = {
                "routes": ["antigravity", "unknown_provider_1", "opencode", "antigravity"],
                "fallbacks": ["opencode", "unknown_provider_2", "claudeAgent", "claudeAgent"],
                "perCategory": 99,
            }
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(raw_a, f)

            stderr_buf = io.StringIO()
            with patch("sys.stderr", stderr_buf):
                loaded_a = self.configure.load_config(self.catalog, path=cfg_file)

            self.assertEqual(loaded_a["routes"], ["antigravity", "opencode"])
            # opencode is in routes, so it must not stay in fallbacks
            self.assertEqual(loaded_a["fallbacks"], ["claudeAgent"])
            self.assertEqual(loaded_a["perCategory"], 8)
            self.assertIn("unknown_provider_1", stderr_buf.getvalue())
            self.assertIn("unknown_provider_2", stderr_buf.getvalue())

            # Case B: perCategory non-int "x" -> 4
            raw_b = {
                "routes": ["antigravity"],
                "fallbacks": ["codex"],
                "perCategory": "x",
            }
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(raw_b, f)

            loaded_b = self.configure.load_config(self.catalog, path=cfg_file)
            self.assertEqual(loaded_b["perCategory"], 4)

            # Case C: perCategory clamped below 1 -> 1
            raw_c = {
                "routes": ["antigravity"],
                "fallbacks": [],
                "perCategory": 0,
            }
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(raw_c, f)

            loaded_c = self.configure.load_config(self.catalog, path=cfg_file)
            self.assertEqual(loaded_c["perCategory"], 1)

    def test_10_catalog_integrity(self):
        providers = self.catalog["providers"]
        models = self.catalog["models"]
        categories = set(self.configure.CATEGORIES)

        self.assertEqual(set(self.catalog["categories"]), categories)

        for model in models:
            self.assertIn(
                model["provider"],
                providers,
                f"Model {model['id']} provider {model['provider']} not in providers",
            )
            for rank_cat in model.get("ranks", {}).keys():
                self.assertIn(
                    rank_cat,
                    categories,
                    f"Model {model['id']} has invalid category {rank_cat}",
                )

        # Pool members check
        provider_model_ids = {}
        for model in models:
            provider_model_ids.setdefault(model["provider"], set()).add(model["id"])

        for pid, pinfo in providers.items():
            pools = pinfo.get("pools", {})
            for pool_name, model_ids in pools.items():
                for mid in model_ids:
                    self.assertIn(
                        mid,
                        provider_model_ids.get(pid, set()),
                        f"Pool {pool_name} member {mid} is not a model ID of {pid}",
                    )

    def test_11_render_empty_routes(self):
        cfg = {"routes": [], "fallbacks": [], "perCategory": 4}
        routes = self.configure.build_routes(self.catalog, cfg)
        rendered = self.configure.render_routes(self.catalog, routes)
        for cat in self.configure.CATEGORIES:
            self.assertIn(f"- {cat}: none | fallback: none", rendered)

    def test_12_interactive_loop_commands(self):
        # Test interactive loop cycling, u <n>, k <n>, p, and q
        inputs = iter([
            "1",      # cycle provider 1 (antigravity: route -> fallback)
            "1",      # cycle provider 1 (fallback -> off)
            "1",      # cycle provider 1 (off -> route)
            "u 12",   # move fallback earlier
            "k 3",    # change perCategory to 3
            "p",      # preview
            "invalid_cmd", # trigger ?
            "q",      # quit
        ])
        config = self.configure.default_config(self.catalog)
        with patch("builtins.input", side_effect=inputs), \
             patch("sys.stdout", new_callable=io.StringIO) as stdout_mock:
            ret = self.configure._interactive_loop(self.catalog, config)
            self.assertEqual(ret, 0)
            self.assertEqual(config["perCategory"], 3)
            self.assertIn("?", stdout_mock.getvalue())


if __name__ == "__main__":
    unittest.main()
