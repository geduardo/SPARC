# src/edm_env/core/module.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Dict, Type

from .state import EDMState


class EDMModule(ABC):
    """
    Abstract base-class for every physical sub-model.    Sub-classes should override :meth:`update`.
    """

    # Optional global registry (useful for reflection / auto-import)
    registry: ClassVar[Dict[str, "EDMModule"]] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        EDMModule.registry[cls.__name__] = cls

    # --------------------------------------------------------------------- #
    # API
    # --------------------------------------------------------------------- #
    def __init__(self, env):
        self.env = env

    @abstractmethod
    def update(self, state: EDMState) -> None: ...
