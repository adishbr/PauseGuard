"""Unit tests for PauseGuard Mule Graph Proximity Scorer.

Verifies shortest path BFS traversal, fan-in anomaly detection,
honest unperformed null states, and RiskSignals contract compliance.
"""

import unittest

from intelligence.mule_graph.graph_proximity import (
    MuleGraphProximityScorer,
    SyntheticTransactionGraph,
    evaluate_mule_proximity,
)
from intelligence.schemas.risk_signals import (
    CalculationMethod,
    DataOrigin,
    SourceCategory,
)


class TestMuleGraphProximity(unittest.TestCase):

    def setUp(self):
        self.graph = SyntheticTransactionGraph(
            flagged_mule_nodes={"ben_synth_mule_master_01"}
        )
        # Create a cluster:
        # PayerA -> ben_synth_mule_master_01
        # PayerB -> MuleAdjacent01 -> ben_synth_mule_master_01
        # PayerC -> TwoHopsAway02 -> MuleAdjacent01
        # PayerClean -> CleanBeneficiary
        self.graph.add_transaction("usr_payer_a", "ben_synth_mule_master_01")
        self.graph.add_transaction("usr_payer_b", "ben_synth_mule_adj_01")
        self.graph.add_transaction("ben_synth_mule_adj_01", "ben_synth_mule_master_01")
        self.graph.add_transaction("usr_payer_c", "ben_synth_two_hops_02")
        self.graph.add_transaction("ben_synth_two_hops_02", "ben_synth_mule_adj_01")
        self.graph.add_transaction("usr_payer_clean", "ben_clean_merchant")

    def test_direct_mule_hit(self):
        """Verify beneficiary listed directly in flagged set has hop_distance=0 and score=100."""
        signal = evaluate_mule_proximity(self.graph, "ben_synth_mule_master_01")

        self.assertEqual(signal.status, "evaluated")
        self.assertEqual(signal.hop_distance_to_flagged_mule, 0)
        self.assertEqual(signal.cluster_risk_score, 100)
        self.assertGreaterEqual(signal.in_degree_incoming_unique_payers, 1)

    def test_one_hop_adjacent_node(self):
        """Verify immediate counterparty to a flagged mule has hop_distance=1 and elevated score."""
        signal = evaluate_mule_proximity(self.graph, "ben_synth_mule_adj_01")

        self.assertEqual(signal.status, "evaluated")
        self.assertEqual(signal.hop_distance_to_flagged_mule, 1)
        self.assertGreaterEqual(signal.cluster_risk_score, 75)
        self.assertLessEqual(signal.cluster_risk_score, 95)

    def test_two_hop_adjacent_node(self):
        """Verify node 2 hops away from confirmed mule has hop_distance=2 and moderate risk."""
        signal = evaluate_mule_proximity(self.graph, "ben_synth_two_hops_02")

        self.assertEqual(signal.status, "evaluated")
        self.assertEqual(signal.hop_distance_to_flagged_mule, 2)
        self.assertGreaterEqual(signal.cluster_risk_score, 40)
        self.assertLessEqual(signal.cluster_risk_score, 65)

    def test_clean_isolated_node(self):
        """Verify clean beneficiary with no mule connection has hop_distance=None and low score."""
        signal = evaluate_mule_proximity(self.graph, "ben_clean_merchant")

        self.assertEqual(signal.status, "evaluated")
        self.assertIsNone(signal.hop_distance_to_flagged_mule)
        self.assertLessEqual(signal.cluster_risk_score, 10)
        self.assertEqual(signal.in_degree_incoming_unique_payers, 1)

    def test_high_fan_in_anomaly_detection(self):
        """Verify rapid in-degree fan-in (e.g. 16 distinct payers) triggers anomaly scoring."""
        fan_graph = SyntheticTransactionGraph(flagged_mule_nodes=set())
        for i in range(16):
            fan_graph.add_transaction(f"usr_victim_{i:02d}", "ben_rapid_fan_in")

        signal = evaluate_mule_proximity(fan_graph, "ben_rapid_fan_in")

        self.assertEqual(signal.status, "evaluated")
        self.assertEqual(signal.in_degree_incoming_unique_payers, 16)
        self.assertIsNone(signal.hop_distance_to_flagged_mule)
        # 16 distinct payers triggers high fan-in alert (score=50)
        self.assertEqual(signal.cluster_risk_score, 50)

    def test_unperformed_empty_graph(self):
        """Verify unperformed or empty graph returns status='unperformed' with all nulls."""
        empty_graph = SyntheticTransactionGraph()
        signal = evaluate_mule_proximity(empty_graph, "ben_any")

        self.assertEqual(signal.status, "unperformed")
        self.assertIsNone(signal.in_degree_incoming_unique_payers)
        self.assertIsNone(signal.hop_distance_to_flagged_mule)
        self.assertIsNone(signal.cluster_risk_score)
        self.assertEqual(signal.provenance.data_origin, DataOrigin.UNAVAILABLE)
        self.assertEqual(signal.provenance.calculation_method, CalculationMethod.UNPERFORMED)

    def test_none_graph_handling(self):
        """Verify None graph object returns unperformed status safely."""
        signal = evaluate_mule_proximity(None, "ben_any")

        self.assertEqual(signal.status, "unperformed")
        self.assertIsNone(signal.in_degree_incoming_unique_payers)
        self.assertIsNone(signal.cluster_risk_score)


if __name__ == "__main__":
    unittest.main()
