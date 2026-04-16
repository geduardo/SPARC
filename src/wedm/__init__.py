# src/wedm/__init__.py
from importlib.metadata import PackageNotFoundError, version

from .core import (
    EDMState,
    EnvironmentConfig,
    HotStateBundle,
    MaterialDatabase,
    WireMaterial,
    get_material_db,
)

from .envs.wire_edm import WireEDMEnv, WireEDMSimulator

from .modules.ignition import IgnitionModule, IgnitionModuleParameters
from .modules.wire import WireModule, WireModuleParameters
from .modules.material import MaterialRemovalModule, MaterialModuleParameters
from .modules.dielectric import DielectricModule, DielectricModuleParameters
from .modules.mechanics import MechanicsModule, MechanicsModuleParameters

_FALLBACK_VERSION = "0.2.0"
__version__ = _FALLBACK_VERSION

__all__ = [
    # Core classes
    "EDMState",
    "EnvironmentConfig",
    "HotStateBundle",
    "MaterialDatabase",
    "WireMaterial",
    "get_material_db",
    # Environment
    "WireEDMEnv",
    "WireEDMSimulator",
    # Modules and their parameters
    "IgnitionModule",
    "IgnitionModuleParameters",
    "WireModule",
    "WireModuleParameters",
    "MaterialRemovalModule",
    "MaterialModuleParameters",
    "DielectricModule",
    "DielectricModuleParameters",
    "MechanicsModule",
    "MechanicsModuleParameters",
]

for dist_name in ("wedm-learning-environment", "wedm"):
    try:
        __version__ = version(dist_name)
        break
    except PackageNotFoundError:
        continue
else:
    __version__ = _FALLBACK_VERSION
