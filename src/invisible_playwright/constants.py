"""Backward-compat shim — spostato in invisible_core.constants (alias completo)."""
import sys as _sys
from invisible_core import constants as _mod
_sys.modules[__name__] = _mod
