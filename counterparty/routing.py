from __future__ import annotations

from .models import CandidateScore


def utility(c: CandidateScore, budget: int, mode: str = "safe") -> float:
    if c.price_credits > budget:
        return -1e9
    trust = c.trust_score / 100
    price_efficiency = max(0.0, 1 - c.price_credits / max(budget, 1))
    latency_penalty = min(1.0, c.latency_ms / 300_000)
    uncertainty_penalty = 1 - c.confidence

    # Safe mode penalizes uncertainty aggressively. Explore mode intentionally
    # tolerates sparse evidence to gather information in the Arena's first round.
    uncertainty_weight = 0.28 if mode == "safe" else 0.12
    return (
        0.42 * trust
        + 0.25 * c.task_fit
        + 0.18 * price_efficiency
        + 0.15 * c.confidence
        - 0.10 * latency_penalty
        - uncertainty_weight * uncertainty_penalty
    )


def rank(candidates: list[CandidateScore], budget: int, mode: str = "safe") -> list[tuple[CandidateScore, float]]:
    return sorted(((c, utility(c, budget, mode)) for c in candidates), key=lambda x: (x[1], x[0].service_id), reverse=True)
