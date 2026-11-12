"""Regression tests for confirmed high-risk registry priority."""

import unittest
from pydantic import ValidationError

from intelligence.schemas.risk_signals import (
    RiskSignals,
    make_degraded_advisory,
)


class TestRegistryPriority(unittest.TestCase):

    def make_payload(self, caution_level):
        payload = make_degraded_advisory(
            payment_id="pg_synth_registry_test",
            payer_id="usr_synth_test",
            beneficiary_id="ben_synth_confirmed_mule",
            amount_paise=100000,
            degraded_reasons=("test_fixture",),
        ).model_dump()

        # Convert the fallback into a complete synthetic evaluation.
        payload["evaluation_status"] = "complete"
        payload["degraded_reasons"] = ()
        payload["advisory_score"] = 25
        payload["suggested_caution_level"] = caution_level

        # Simulate a successfully performed positive registry lookup.
        payload["registry"] = {
            "check_status": "performed",
            "is_listed_high_risk": True,
            "registry_category": "confirmed_mule",
            "provenance": {
                "source_category": "trusted_source",
                "data_origin": "mock_registry_table",
                "calculation_method": "deterministic_lookup",
                "is_synthetic": True,
            },
        }

        return payload

    def test_confirmed_registry_hit_rejects_low_and_medium_caution(self):
        """A confirmed registry hit must not receive LOW or MEDIUM caution."""
        for caution_level in ("low", "medium"):
            with self.subTest(caution_level=caution_level):
                payload = self.make_payload(caution_level)

                with self.assertRaises(ValidationError):
                    RiskSignals.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
