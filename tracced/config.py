"""Defaults for the pump detector and the early engine; config.yaml overrides them (deep merge)."""
import copy
import os

DEFAULTS = {
    "detect": {
        "interval": "5m", "window_hours": 48, "accumulation_hours": 3, "lookback": 24,
        "pump_multiple": 2.0, "breakout_ratio": 1.3, "min_peak_mcap": 1_000_000,
        "merge_gap_min": 60,
    },
}


def _deep_merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    if path and os.path.exists(path):
        try:
            import yaml
            with open(path) as f:
                _deep_merge(cfg, yaml.safe_load(f) or {})
        except ImportError:
            import sys
            print("[warn] pyyaml is not installed — using built-in defaults", file=sys.stderr)
    return cfg
