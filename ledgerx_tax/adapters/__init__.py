"""Adapters: one module per tax system. Each exposes send(cfg, inv, ctx), check(cfg, sub, ctx), cancel(cfg, sub, reason, ctx), test(cfg, ctx)."""
from importlib import import_module

MODULES = {"Egypt ETA": "egypt", "Saudi ZATCA": "zatca", "UAE PINT-AE": "uae", "Custom API": "custom"}


def get(system):
	if system not in MODULES:
		raise KeyError(f"Unknown system {system}")
	return import_module("." + MODULES[system], __name__)
