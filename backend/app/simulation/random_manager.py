"""Deterministic Random Number Management.

Guarantees bit-exact reproducibility across simulation runs using explicit random seeds.
"""

import random
from typing import Any


class SeededRandomManager:
    """Deterministic pseudo-random number generator manager."""

    def __init__(self, seed: int = 42) -> None:
        self._seed: int = seed
        self._rng = random.Random(seed)

    @property
    def seed(self) -> int:
        """Return the current seed."""
        return self._seed

    def reseed(self, seed: int) -> None:
        """Reseed the random generator."""
        self._seed = seed
        self._rng.seed(seed)

    def random(self) -> float:
        """Return a random float in [0.0, 1.0)."""
        return self._rng.random()

    def uniform(self, a: float, b: float) -> float:
        """Return a random float N such that a <= N <= b."""
        return self._rng.uniform(a, b)

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        """Return Gaussian/normal distribution random float."""
        return self._rng.gauss(mu, sigma)

    def get_state(self) -> dict[str, Any]:
        """Return full internal state of the RNG for snapshot serialization."""
        return {
            "seed": self._seed,
            "rng_state": self._rng.getstate(),
        }

    def set_state(self, state: dict[str, Any]) -> None:
        """Restore internal RNG state from snapshot state dictionary."""
        self._seed = state.get("seed", 42)
        if "rng_state" in state:
            # Reconstruct tuple structure for random.getstate()
            rng_tuple = tuple(state["rng_state"])
            # Ensure internal tuple types match random.getstate() signature
            version, state_data, gauss_next = rng_tuple
            state_data_tuple = tuple(state_data) if isinstance(state_data, list) else state_data
            self._rng.setstate((version, state_data_tuple, gauss_next))
