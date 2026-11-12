"""Mule Graph Proximity Scorer for PauseGuard V2.

Computes shortest-path network proximity to synthetic mule accounts and
detects rapid fan-in (in-degree) anomalies using pure standard-library BFS traversal.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from intelligence.schemas.risk_signals import (
    CalculationMethod,
    DataOrigin,
    MuleGraphSignal,
    SignalProvenance,
    SourceCategory,
)


@dataclass
class SyntheticTransactionGraph:
    """In-memory synthetic directed graph of transaction flows."""
    incoming_edges: dict[str, set[str]] = field(default_factory=lambda: {})
    counterparties: dict[str, set[str]] = field(default_factory=lambda: {})
    flagged_mule_nodes: set[str] = field(default_factory=set)

    def add_transaction(self, payer_id: str, beneficiary_id: str) -> None:
        """Record a directed payment edge between payer and beneficiary."""
        if beneficiary_id not in self.incoming_edges:
            self.incoming_edges[beneficiary_id] = set()
        self.incoming_edges[beneficiary_id].add(payer_id)

        # Record bidirectional counterparty connectivity for community traversal
        if payer_id not in self.counterparties:
            self.counterparties[payer_id] = set()
        if beneficiary_id not in self.counterparties:
            self.counterparties[beneficiary_id] = set()

        self.counterparties[payer_id].add(beneficiary_id)
        self.counterparties[beneficiary_id].add(payer_id)

    def is_empty(self) -> bool:
        """Return True if graph contains zero recorded edges."""
        return len(self.counterparties) == 0


class MuleGraphProximityScorer:
    """Evaluates mule proximity and fan-in risk across synthetic graph topology."""

    def __init__(self, graph: SyntheticTransactionGraph | None = None) -> None:
        self.graph = graph

    def evaluate_proximity(self, beneficiary_id: str) -> MuleGraphSignal:
        """Calculate network hop distance to flagged mules and in-degree fan-in."""
        # Unperformed / missing graph state: return explicit nulls per contract
        if self.graph is None or self.graph.is_empty():
            return MuleGraphSignal(
                status="unperformed",
                in_degree_incoming_unique_payers=None,
                hop_distance_to_flagged_mule=None,
                cluster_risk_score=None,
                provenance=SignalProvenance(
                    source_category=SourceCategory.MODEL_INFERENCE,
                    data_origin=DataOrigin.UNAVAILABLE,
                    calculation_method=CalculationMethod.UNPERFORMED,
                    is_synthetic=True,
                ),
            )

        # Compute incoming unique payer count (in-degree)
        in_degree = len(self.graph.incoming_edges.get(beneficiary_id, set()))

        # Shortest-path BFS traversal to any confirmed mule node (max 4 hops)
        hop_distance = self._bfs_shortest_path_to_mule(beneficiary_id, max_depth=4)

        # Compute composite cluster risk index (0 - 100)
        cluster_score = self._compute_cluster_risk(hop_distance, in_degree)

        return MuleGraphSignal(
            status="evaluated",
            in_degree_incoming_unique_payers=in_degree,
            hop_distance_to_flagged_mule=hop_distance,
            cluster_risk_score=cluster_score,
            provenance=SignalProvenance(
                source_category=SourceCategory.MODEL_INFERENCE,
                data_origin=DataOrigin.SYNTHETIC_FIXTURE,
                calculation_method=CalculationMethod.GRAPH_TRAVERSAL,
                is_synthetic=True,
            ),
        )

    def _bfs_shortest_path_to_mule(self, target_id: str, max_depth: int = 4) -> int | None:
        """Breadth-first search for shortest distance to any flagged mule node."""
        if target_id in self.graph.flagged_mule_nodes:
            return 0

        queue: deque[tuple[str, int]] = deque([(target_id, 0)])
        visited: set[str] = {target_id}

        while queue:
            current_node, depth = queue.popleft()

            if depth >= max_depth:
                continue

            for neighbor in self.graph.counterparties.get(current_node, set()):
                if neighbor in self.graph.flagged_mule_nodes:
                    return depth + 1

                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))

        return None

    @staticmethod
    def _compute_cluster_risk(hop_distance: int | None, in_degree: int) -> int:
        """Derive normalized 0-100 cluster risk score based on proximity and fan-in."""
        if hop_distance == 0:
            return 100
        elif hop_distance == 1:
            # Immediate 1-hop counterparty to confirmed mule
            base = 75
            bonus = min(20, in_degree * 2)
            return min(95, base + bonus)
        elif hop_distance == 2:
            base = 40
            bonus = min(25, in_degree * 2)
            return min(65, base + bonus)
        elif hop_distance == 3:
            base = 15
            bonus = min(15, in_degree * 2)
            return min(30, base + bonus)
        else:
            # No path to mule within max depth: score based purely on unusual fan-in velocity
            if in_degree >= 15:
                return 50  # Rapid fan-in anomaly into personal account
            elif in_degree >= 8:
                return 25
            else:
                return min(10, in_degree * 2)


def evaluate_mule_proximity(
    graph: SyntheticTransactionGraph | None,
    beneficiary_id: str,
) -> MuleGraphSignal:
    """Functional convenience wrapper for MuleGraphProximityScorer."""
    scorer = MuleGraphProximityScorer(graph)
    return scorer.evaluate_proximity(beneficiary_id)
