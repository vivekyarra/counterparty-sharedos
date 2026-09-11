from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class BayesianReputation:
    successes: int
    failures: int
    alpha_prior: float = 2.0
    beta_prior: float = 2.0

    @property
    def observations(self) -> int:
        return self.successes + self.failures

    @property
    def mean(self) -> float:
        a = self.alpha_prior + self.successes
        b = self.beta_prior + self.failures
        return a / (a + b)

    @property
    def variance(self) -> float:
        a = self.alpha_prior + self.successes
        b = self.beta_prior + self.failures
        total = a + b
        return (a * b) / (total * total * (total + 1))

    @property
    def confidence(self) -> float:
        # Evidence-volume confidence. It deliberately never reaches 1.0.
        n = self.observations
        return min(0.99, n / (n + 8.0))

    def score_100(self) -> float:
        # Shrink sparse evidence toward neutral rather than rewarding one lucky pass.
        adjusted = 0.5 * (1 - self.confidence) + self.mean * self.confidence
        return round(adjusted * 100, 2)

    def conservative_score_100(self, z: float = 1.645) -> float:
        # Approximate lower confidence bound; useful for safe routing.
        lower = max(0.0, self.mean - z * sqrt(self.variance))
        adjusted = 0.5 * (1 - self.confidence) + lower * self.confidence
        return round(adjusted * 100, 2)
