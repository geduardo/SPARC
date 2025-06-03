# src/wedm/__init__.py
from importlib.metadata import version, PackageNotFoundError

from .core import (
    EDMState,
    EnvironmentConfig,
    MaterialDatabase,
    WireMaterial,
    get_material_db,
)

from .envs.wire_edm import WireEDMEnv

from .modules.ignition import IgnitionModule, IgnitionModuleParameters
from .modules.wire import WireModule, WireModuleParameters
from .modules.material import MaterialRemovalModule, MaterialModuleParameters
from .modules.dielectric import DielectricModule, DielectricModuleParameters
from .modules.mechanics import MechanicsModule, MechanicsModuleParameters

__version__ = "0.2.0"

__all__ = [
    # Core classes
    "EDMState",
    "EnvironmentConfig",
    "MaterialDatabase",
    "WireMaterial",
    "get_material_db",
    # Environment
    "WireEDMEnv",
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

try:
    __version__ = version("wedm") if "__package__" in globals() else "0.dev"
except PackageNotFoundError:
    __version__ = "0.dev"
