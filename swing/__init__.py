"""Swing Trade Finder for NSE stocks."""
import os
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path=None):
    path = path or os.path.join(ROOT, "config.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
