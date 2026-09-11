"""Locations of the runtime files bundled with the compiler."""

from importlib.resources import files
from pathlib import Path


def runtime_directory() -> Path:
    """Return the installed directory containing RLC's KFN and KH files."""
    return Path(str(files("rlc").joinpath("data")))


def default_kfn_path() -> Path:
    """Return the bundled RealLive function-definition database."""
    return runtime_directory() / "reallive.kfn"
