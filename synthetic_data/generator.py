"""Deterministic, seeded synthetic scenario generator for PauseGuard Policy Lab.

Generates labeled benchmark cases for behavioral baseline evaluation,
mule graph proximity, and policy matrix simulations without using real customer data.
Enforces strict feature/target separation and leakage-safe dataset splitting.
"""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from enum import Enum
import json
import math
from pathlib import Path
import random
from typing import Any


class ScenarioCategory(str, Enum):
    """Benchmark scenario categories per docs/EXPERIMENT_PLAN_AND_METRICS.md."""
    LEGITIMATE_PERSONAL = "legitimate_personal"
    LEGITIMATE_BUSINESS = "legitimate_business"
    APP_COERCION_FRAUD = "app_coercion_fraud"
    BENIGN_ANOMALOUS = "benign_anomalous"
    MULE_PROXIMITY = "mule_proximity"
    VELOCITY_STRUCTURING = "velocity_structuring"


class CustomerProfileType(str, Enum):
    """Supported customer profile categories."""
    PERSONAL = "personal"
    PROFESSIONAL = "professional"
    SMALL_BUSINESS = "small_business"
    ENTERPRISE = "enterprise"


class RegistryCheckStatus(str, Enum):
    """Execution status for high-risk beneficiary registry lookups."""
    PERFORMED = "performed"
    UNAVAILABLE = "unavailable"


# -----------------------------------------------------------------------------
# Disaggregated Feature, Target, and Metadata Interfaces (Anti-Leakage)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class ScenarioFeatures:
    """Inference-time model features.

    CRITICAL: Excludes ground truth, expected policy tier, scenario category,
    and direct deterministic registry labels to prevent predictive leakage.
    """
    amount_paise: int
    profile_type: str
    payer_baseline_median_paise: int | None
    is_new_beneficiary: bool
    prior_transfers_count: int
    recent_attempts_in_window: int
    recent_amount_paise_in_window: int
    transcript_text: str | None
    transcript_consented: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScenarioTargets:
    """Evaluation targets reserved for ground-truth simulation and scoring."""
    ground_truth_label: str  # "legitimate" or "fraud"
    expected_policy_tier: int  # 0: allow, 1: warn, 2: step-up, 3: restrict/guardian

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScenarioMetadata:
    """Synthetic provenance, identifiers, and scenario taxonomy."""
    scenario_id: str
    category: str
    payer_id: str
    beneficiary_id: str
    registry_check_status: str  # "performed" or "unavailable"
    is_listed_in_registry: bool | None
    is_synthetic: bool = True

    def __post_init__(self):
        if self.registry_check_status not in ("performed", "unavailable"):
            raise ValueError(
                f"registry_check_status must be 'performed' or 'unavailable', got {self.registry_check_status!r}"
            )
        if self.registry_check_status == "performed":
            if self.is_listed_in_registry not in (True, False):
                raise ValueError(
                    "When registry_check_status is 'performed', is_listed_in_registry must be True or False (not None)"
                )
        elif self.registry_check_status == "unavailable":
            if self.is_listed_in_registry is not None:
                raise ValueError(
                    "When registry_check_status is 'unavailable', is_listed_in_registry must be None"
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScenarioMetadata":
        d = dict(data)
        if "registry_check_status" not in d:
            if d.get("is_listed_in_registry") is None:
                d["registry_check_status"] = "unavailable"
            else:
                d["registry_check_status"] = "performed"
        return cls(**d)


@dataclass(frozen=True)
class SyntheticPaymentScenario:
    """A fully specified synthetic payment scenario for evaluation."""
    scenario_id: str
    category: ScenarioCategory
    payer_id: str
    profile_type: str  # "personal", "professional", "small_business", "enterprise"
    beneficiary_id: str
    amount_paise: int
    purpose: str
    payer_baseline_median_paise: int | None
    is_new_beneficiary: bool
    prior_transfers_count: int
    recent_attempts_in_window: int
    recent_amount_paise_in_window: int
    transcript_text: str | None
    transcript_consented: bool
    registry_check_status: str  # "performed" or "unavailable"
    is_listed_in_registry: bool | None
    expected_policy_tier: int  # 0: allow, 1: warn, 2: step-up, 3: restrict/guardian
    ground_truth_label: str  # "legitimate" or "fraud"
    is_synthetic: bool = True

    def __post_init__(self):
        if self.registry_check_status not in ("performed", "unavailable"):
            raise ValueError(
                f"registry_check_status must be 'performed' or 'unavailable', got {self.registry_check_status!r}"
            )
        if self.registry_check_status == "performed":
            if self.is_listed_in_registry not in (True, False):
                raise ValueError(
                    "When registry_check_status is 'performed', is_listed_in_registry must be True or False (not None)"
                )
        elif self.registry_check_status == "unavailable":
            if self.is_listed_in_registry is not None:
                raise ValueError(
                    "When registry_check_status is 'unavailable', is_listed_in_registry must be None"
                )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["category"] = self.category.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SyntheticPaymentScenario":
        """Reconstruct a scenario object from a serialized dictionary."""
        d = dict(data)
        if isinstance(d["category"], str):
            d["category"] = ScenarioCategory(d["category"])
        if "registry_check_status" not in d:
            if d.get("is_listed_in_registry") is None:
                d["registry_check_status"] = "unavailable"
            else:
                d["registry_check_status"] = "performed"
        return cls(**d)

    def to_features(self) -> ScenarioFeatures:
        """Extract only legitimate inference-time features, stripping labels and IDs."""
        return ScenarioFeatures(
            amount_paise=self.amount_paise,
            profile_type=self.profile_type,
            payer_baseline_median_paise=self.payer_baseline_median_paise,
            is_new_beneficiary=self.is_new_beneficiary,
            prior_transfers_count=self.prior_transfers_count,
            recent_attempts_in_window=self.recent_attempts_in_window,
            recent_amount_paise_in_window=self.recent_amount_paise_in_window,
            transcript_text=self.transcript_text if self.transcript_consented else None,
            transcript_consented=self.transcript_consented,
        )

    def to_targets(self) -> ScenarioTargets:
        """Extract ground-truth labels and expected policy tiers."""
        return ScenarioTargets(
            ground_truth_label=self.ground_truth_label,
            expected_policy_tier=self.expected_policy_tier,
        )

    def to_metadata(self) -> ScenarioMetadata:
        """Extract tracking metadata and synthetic declaration."""
        return ScenarioMetadata(
            scenario_id=self.scenario_id,
            category=self.category.value,
            payer_id=self.payer_id,
            beneficiary_id=self.beneficiary_id,
            registry_check_status=self.registry_check_status,
            is_listed_in_registry=self.is_listed_in_registry,
            is_synthetic=self.is_synthetic,
        )


@dataclass(frozen=True)
class DatasetSplits:
    """Container for leakage-safe train/validation/test splits."""
    train: list[SyntheticPaymentScenario]
    val: list[SyntheticPaymentScenario]
    test: list[SyntheticPaymentScenario]
    report: dict[str, Any]


# -----------------------------------------------------------------------------
# Synthetic Text Corpus & Templates (Explicitly Fictional)
# -----------------------------------------------------------------------------

COERCION_TRANSCRIPTS = [
    "URGENT: This is Inspector Sharma from Central Police Cyber Cell. Your account is implicated in money laundering. Transfer the verification bond immediately or warrant will be issued. Do not disconnect or tell anyone.",
    "Customs Enforcement Office notice: A package containing illegal narcotics addressed to your Aadhaar has been intercepted at Delhi Airport. Pay penalty deposit now to avoid immediate arrest.",
    "Electricity department urgent notice: Your power will be disconnected at 8:00 PM tonight due to pending KYC update. Click link and pay Rs. 48,000 security deposit right now. Share screen via AnyDesk.",
    "Bank Fraud Prevention Unit: We detected unauthorized login. Move your funds to Safe Reserve Account immediately to protect them. Do not share this call with branch staff.",
    "TRAI Telecom Verification: Your SIM card will be deactivated within 2 hours due to unauthorized commercial calls. Transfer Rs. 35,000 clearance deposit immediately to our officer.",
]

BENIGN_HIGH_VALUE_PURPOSES = [
    "Advance token for family wedding banquet venue booking",
    "Quarterly university semester tuition fee payment",
    "Annual maintenance contract and server hardware renewal",
    "Advance deposit for residential rental agreement renewal",
    "Payment for new work laptop and external display workstation",
    "Hospital admission emergency deposit for specialized surgery",
    "Corporate legal retainer and patent filing fee installment",
]

PROFESSIONAL_PURPOSES = [
    "Annual professional indemnity insurance premium",
    "Specialized CAD architectural software annual license",
    "Subcontractor freelance graphic design milestone 2",
    "Chartered accountant audit assistance retainer",
    "Office coworking conference space quarterly booking",
]

SMALL_BUSINESS_PURPOSES = [
    "Invoice settlement raw materials batch 401",
    "Wholesale textile shipment transport clearance",
    "Quarterly warehouse refrigeration maintenance fee",
    "Packaging supplies corrugated carton bulk order",
    "Local commercial logistics advance delivery fee",
]

ENTERPRISE_PURPOSES = [
    "Bulk raw material procurement contract vendor payout",
    "Enterprise cloud infrastructure quarterly dedicated hosting",
    "National fleet logistics transport settlement invoice",
    "Corporate facility management facilities retainer",
    "Quarterly hardware workstation lease renewal",
]


# -----------------------------------------------------------------------------
# Mock Registry Loader (Strict Fictional Boundaries)
# -----------------------------------------------------------------------------

def load_mock_registry_with_status(
    registry_path: Path | str | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Inspect and load mock high-risk registry with explicit execution status.

    Returns:
        (flagged_dict, "performed") if file exists and parses valid JSON.
        (None, "unavailable") if file does not exist.

    Raises:
        ValueError if the file exists but contains invalid JSON or schema violations.
    """
    if registry_path is None:
        path = Path(__file__).parent / "registry_mock.json"
    else:
        path = Path(registry_path)

    if not path.exists():
        return None, "unavailable"

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        raise ValueError(f"Malformed registry file at {path}: {exc}") from exc

    if not isinstance(data, dict) or "flagged_beneficiaries" not in data:
        raise ValueError(f"Malformed registry file: missing 'flagged_beneficiaries' key in {path}")

    flagged = data["flagged_beneficiaries"]
    if not isinstance(flagged, dict):
        raise ValueError(f"Malformed registry file: 'flagged_beneficiaries' must be a dict in {path}")

    return flagged, "performed"


def load_mock_registry(registry_path: Path | str | None = None) -> dict[str, Any]:
    """Load mock high-risk registry from repository fixture.

    Preserves backward-compatible public interface returning dict of flagged beneficiaries.
    Returns empty dict if file is missing. Raises ValueError on malformed structure.
    """
    flagged, status = load_mock_registry_with_status(registry_path)
    if status == "unavailable" or flagged is None:
        return {}
    return flagged


# -----------------------------------------------------------------------------
# Core Generator with Full 4-Profile Coverage
# -----------------------------------------------------------------------------

def generate_scenario_dataset(
    seed: int = 42,
    count_per_category: int = 25,
    registry_path: Path | str | None = None,
) -> list[SyntheticPaymentScenario]:
    """Generate a reproducible, balanced dataset of synthetic payment scenarios.

    Guarantees deterministic output given the same seed.
    Covers all four customer profiles (personal, professional, small_business, enterprise).
    Distinguishes performed registry lookups from unavailable lookup status.
    """
    if count_per_category < 1:
        raise ValueError("count_per_category must be at least 1")

    rng = random.Random(seed)
    registry_entries, registry_check_status = load_mock_registry_with_status(registry_path)

    if registry_check_status == "performed":
        registry_beneficiary_ids = list(registry_entries.keys()) if registry_entries else []
    else:
        registry_beneficiary_ids = []

    def get_registry_flag(ben_id: str) -> tuple[str, bool | None]:
        if registry_check_status == "unavailable":
            return "unavailable", None
        return "performed", (ben_id in registry_entries) if registry_entries else False

    scenarios: list[SyntheticPaymentScenario] = []

    # 1. Legitimate Personal (T0 / T1, legitimate)
    for i in range(count_per_category):
        amount = rng.randint(5000, 250000)  # Rs. 50 - Rs. 2,500
        baseline = rng.randint(40000, 150000)  # median Rs. 400 - Rs. 1,500
        is_new = rng.random() < 0.25
        priors = 0 if is_new else rng.randint(3, 30)
        payer_id = f"usr_synth_pers_{i:03d}"
        ben_id = f"ben_synth_pers_{i:03d}"
        reg_status, is_listed = get_registry_flag(ben_id)
        scenarios.append(
            SyntheticPaymentScenario(
                scenario_id=f"scn_pers_legit_{i:03d}",
                category=ScenarioCategory.LEGITIMATE_PERSONAL,
                payer_id=payer_id,
                profile_type=CustomerProfileType.PERSONAL.value,
                beneficiary_id=ben_id,
                amount_paise=amount,
                purpose="groceries and daily expenses",
                payer_baseline_median_paise=baseline,
                is_new_beneficiary=is_new,
                prior_transfers_count=priors,
                recent_attempts_in_window=1,
                recent_amount_paise_in_window=amount,
                transcript_text=None,
                transcript_consented=False,
                registry_check_status=reg_status,
                is_listed_in_registry=is_listed,
                expected_policy_tier=0 if not is_new else 1,
                ground_truth_label="legitimate",
            )
        )

    # 2. Legitimate Business (T0 / T1, legitimate; distributed across professional, small_business, enterprise)
    for i in range(count_per_category):
        tier_choice = i % 3
        if tier_choice == 0:
            # Professional: Rs. 5,000 - Rs. 1,00,000 (median Rs. 15k - Rs. 80k)
            profile = CustomerProfileType.PROFESSIONAL.value
            amount = rng.randint(500000, 10000000)
            baseline = rng.randint(1500000, 8000000)
            purpose = rng.choice(PROFESSIONAL_PURPOSES)
            payer_id = f"usr_synth_prof_{i:03d}"
        elif tier_choice == 1:
            # Small Business: Rs. 25,000 - Rs. 5,00,000 (median Rs. 50k - Rs. 4L)
            profile = CustomerProfileType.SMALL_BUSINESS.value
            amount = rng.randint(2500000, 50000000)
            baseline = rng.randint(5000000, 40000000)
            purpose = rng.choice(SMALL_BUSINESS_PURPOSES)
            payer_id = f"usr_synth_smb_{i:03d}"
        else:
            # Enterprise: Rs. 1,00,000 - Rs. 50,00,000 (median Rs. 10L - Rs. 1Cr)
            profile = CustomerProfileType.ENTERPRISE.value
            amount = rng.randint(10000000, 500000000)
            baseline = rng.randint(100000000, 1000000000)
            purpose = rng.choice(ENTERPRISE_PURPOSES)
            payer_id = f"usr_synth_ent_{i:03d}"

        is_new = rng.random() < 0.40  # Businesses routinely pay new suppliers
        priors = 0 if is_new else rng.randint(1, 25)
        ben_id = f"ben_synth_vendor_{i:03d}"
        reg_status, is_listed = get_registry_flag(ben_id)
        scenarios.append(
            SyntheticPaymentScenario(
                scenario_id=f"scn_biz_legit_{i:03d}",
                category=ScenarioCategory.LEGITIMATE_BUSINESS,
                payer_id=payer_id,
                profile_type=profile,
                beneficiary_id=ben_id,
                amount_paise=amount,
                purpose=purpose,
                payer_baseline_median_paise=baseline,
                is_new_beneficiary=is_new,
                prior_transfers_count=priors,
                recent_attempts_in_window=rng.randint(1, 4),
                recent_amount_paise_in_window=amount + rng.randint(0, 5000000),
                transcript_text=None,
                transcript_consented=False,
                registry_check_status=reg_status,
                is_listed_in_registry=is_listed,
                expected_policy_tier=0 if not is_new else 1,
                ground_truth_label="legitimate",
            )
        )

    # 3. APP Coercion Fraud (T3, fraud)
    for i in range(count_per_category):
        amount = rng.randint(3500000, 15000000)  # Rs. 35,000 - Rs. 1,50,000
        baseline = rng.randint(30000, 100000)  # Personal median Rs. 300 - Rs. 1,000 (35x - 150x deviation!)
        transcript = rng.choice(COERCION_TRANSCRIPTS)
        payer_id = f"usr_synth_victim_{i:03d}"
        ben_id = f"ben_synth_scammer_{i:03d}"
        reg_status, is_listed = get_registry_flag(ben_id)
        scenarios.append(
            SyntheticPaymentScenario(
                scenario_id=f"scn_app_fraud_{i:03d}",
                category=ScenarioCategory.APP_COERCION_FRAUD,
                payer_id=payer_id,
                profile_type=CustomerProfileType.PERSONAL.value,
                beneficiary_id=ben_id,
                amount_paise=amount,
                purpose="kyc security deposit clearance",
                payer_baseline_median_paise=baseline,
                is_new_beneficiary=True,
                prior_transfers_count=0,
                recent_attempts_in_window=1,
                recent_amount_paise_in_window=amount,
                transcript_text=transcript,
                transcript_consented=True,
                registry_check_status=reg_status,
                is_listed_in_registry=is_listed,
                expected_policy_tier=3,
                ground_truth_label="fraud",
            )
        )

    # 4. Benign Anomalous (T1 / T2, legitimate high deviation without fraud)
    for i in range(count_per_category):
        profile_choice = rng.choice([
            CustomerProfileType.PERSONAL.value,
            CustomerProfileType.PROFESSIONAL.value,
            CustomerProfileType.SMALL_BUSINESS.value,
        ])
        if profile_choice == CustomerProfileType.PERSONAL.value:
            amount = rng.randint(8000000, 25000000)  # Rs. 80,000 - Rs. 2,50,000
            baseline = rng.randint(80000, 200000)  # Personal median Rs. 800 - Rs. 2,000
        elif profile_choice == CustomerProfileType.PROFESSIONAL.value:
            amount = rng.randint(20000000, 50000000)  # Rs. 2L - Rs. 5L (annual equipment)
            baseline = rng.randint(3000000, 8000000)
        else:
            amount = rng.randint(60000000, 150000000)  # Rs. 6L - Rs. 15L (annual plant upgrade)
            baseline = rng.randint(10000000, 30000000)

        purpose = rng.choice(BENIGN_HIGH_VALUE_PURPOSES)
        payer_id = f"usr_synth_anom_{i:03d}"
        ben_id = f"ben_synth_merchant_valid_{i:03d}"
        reg_status, is_listed = get_registry_flag(ben_id)
        scenarios.append(
            SyntheticPaymentScenario(
                scenario_id=f"scn_benign_anom_{i:03d}",
                category=ScenarioCategory.BENIGN_ANOMALOUS,
                payer_id=payer_id,
                profile_type=profile_choice,
                beneficiary_id=ben_id,
                amount_paise=amount,
                purpose=purpose,
                payer_baseline_median_paise=baseline,
                is_new_beneficiary=rng.random() < 0.5,
                prior_transfers_count=rng.randint(0, 5),
                recent_attempts_in_window=1,
                recent_amount_paise_in_window=amount,
                transcript_text=None,
                transcript_consented=False,
                registry_check_status=reg_status,
                is_listed_in_registry=is_listed,
                expected_policy_tier=2,
                ground_truth_label="legitimate",
            )
        )

    # 5. Mule Proximity Cluster (T3 / Hard Reject, fraud)
    for i in range(count_per_category):
        amount = rng.randint(1500000, 8000000)  # Rs. 15,000 - Rs. 80,000
        baseline = rng.randint(50000, 150000)
        if registry_check_status == "performed" and registry_beneficiary_ids:
            is_direct_hit = (i % 2 == 0)
            ben_id = rng.choice(registry_beneficiary_ids) if is_direct_hit else f"ben_synth_mule_adjacent_{i:03d}"
        elif registry_check_status == "performed":
            ben_id = f"ben_synth_mule_adjacent_{i:03d}"
        else:
            ben_id = f"ben_synth_mule_unconfirmed_{i:03d}"

        reg_status, is_listed = get_registry_flag(ben_id)
        payer_id = f"usr_synth_mule_victim_{i:03d}"
        scenarios.append(
            SyntheticPaymentScenario(
                scenario_id=f"scn_mule_cluster_{i:03d}",
                category=ScenarioCategory.MULE_PROXIMITY,
                payer_id=payer_id,
                profile_type=CustomerProfileType.PERSONAL.value,
                beneficiary_id=ben_id,
                amount_paise=amount,
                purpose="investment return activation",
                payer_baseline_median_paise=baseline,
                is_new_beneficiary=True,
                prior_transfers_count=0,
                recent_attempts_in_window=1,
                recent_amount_paise_in_window=amount,
                transcript_text=None,
                transcript_consented=False,
                registry_check_status=reg_status,
                is_listed_in_registry=is_listed,
                expected_policy_tier=3,
                ground_truth_label="fraud",
            )
        )

    # 6. Velocity Structuring / Smurfing (T2 / T3, fraud / attempted bypass)
    for i in range(count_per_category):
        single_amount = rng.randint(900000, 990000)  # Rs. 9,000 - Rs. 9,900
        attempts = rng.randint(4, 7)
        total_in_window = single_amount * attempts
        payer_id = f"usr_synth_smurf_{i:03d}"
        ben_id = f"ben_synth_smurf_dest_{i:03d}"
        reg_status, is_listed = get_registry_flag(ben_id)
        scenarios.append(
            SyntheticPaymentScenario(
                scenario_id=f"scn_structuring_{i:03d}",
                category=ScenarioCategory.VELOCITY_STRUCTURING,
                payer_id=payer_id,
                profile_type=CustomerProfileType.PERSONAL.value,
                beneficiary_id=ben_id,
                amount_paise=single_amount,
                purpose="quick assistance",
                payer_baseline_median_paise=100000,  # Rs. 1,000 median
                is_new_beneficiary=True,
                prior_transfers_count=0,
                recent_attempts_in_window=attempts,
                recent_amount_paise_in_window=total_in_window,
                transcript_text=None,
                transcript_consented=False,
                registry_check_status=reg_status,
                is_listed_in_registry=is_listed,
                expected_policy_tier=3,
                ground_truth_label="fraud",
            )
        )

    return scenarios


# -----------------------------------------------------------------------------
# Leakage-Safe Dataset Splitting (Payer-Grouped Stratification)
# -----------------------------------------------------------------------------

def split_dataset(
    scenarios: list[SyntheticPaymentScenario],
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    seed: int = 42,
) -> DatasetSplits:
    """Split scenarios into train, validation, and test datasets.

    Guarantees:
    1. Determinism via configurable seed.
    2. Zero payer leakage: all records from a given payer_id are confined to a single split.
    3. Category representation across splits where sample sizes permit.
    4. Exact validation of split ratios and inputs.
    """
    if not scenarios:
        raise ValueError("Cannot split an empty dataset")

    # Ratio validation
    if any(r < 0 for r in (train_ratio, val_ratio, test_ratio)):
        raise ValueError("Split ratios must be non-negative")
    if train_ratio <= 0:
        raise ValueError("train_ratio must be strictly positive")
    if not math.isclose(train_ratio + val_ratio + test_ratio, 1.0, rel_tol=1e-5):
        raise ValueError(
            f"Split ratios must sum to 1.0 (got {train_ratio + val_ratio + test_ratio:.4f})"
        )

    rng = random.Random(seed)

    # Group scenarios by payer_id to guarantee zero payer leakage
    payer_to_scenarios: dict[str, list[SyntheticPaymentScenario]] = defaultdict(list)
    for scn in scenarios:
        payer_to_scenarios[scn.payer_id].append(scn)

    unique_payers = list(payer_to_scenarios.keys())
    if len(unique_payers) < 3:
        raise ValueError(
            f"Dataset must contain at least 3 distinct payers to perform a 3-way split (found {len(unique_payers)})"
        )

    # Group payers by primary scenario category to approximate category stratification
    category_to_payers: dict[ScenarioCategory, list[str]] = defaultdict(list)
    for payer, scn_list in payer_to_scenarios.items():
        primary_cat = scn_list[0].category
        category_to_payers[primary_cat].append(payer)

    train_payers: set[str] = set()
    val_payers: set[str] = set()
    test_payers: set[str] = set()

    # Stratify by allocating payers per category
    for cat, payers in category_to_payers.items():
        shuffled_payers = list(payers)
        rng.shuffle(shuffled_payers)
        n = len(shuffled_payers)

        if n == 1:
            # Single-payer categories cannot be split across sets; allocate to training
            train_payers.add(shuffled_payers[0])
            continue
        elif n == 2:
            train_payers.add(shuffled_payers[0])
            test_payers.add(shuffled_payers[1])
            continue

        n_val = max(1, round(n * val_ratio))
        n_test = max(1, round(n * test_ratio))
        n_train = n - n_val - n_test

        # Ensure train gets at least one if possible
        if n_train < 1:
            n_train = 1
            if n_val > n_test:
                n_val -= 1
            else:
                n_test -= 1

        train_payers.update(shuffled_payers[:n_train])
        val_payers.update(shuffled_payers[n_train : n_train + n_val])
        test_payers.update(shuffled_payers[n_train + n_val :])

    # Reconstruct scenario splits from payer groups
    train_scenarios = [s for p in train_payers for s in payer_to_scenarios[p]]
    val_scenarios = [s for p in val_payers for s in payer_to_scenarios[p]]
    test_scenarios = [s for p in test_payers for s in payer_to_scenarios[p]]

    # Zero leakage assertion
    assert len(train_payers & val_payers) == 0, "Payer leakage detected between train and val!"
    assert len(train_payers & test_payers) == 0, "Payer leakage detected between train and test!"
    assert len(val_payers & test_payers) == 0, "Payer leakage detected between val and test!"

    # Compile split distribution report
    report = {
        "seed": seed,
        "total_scenarios": len(scenarios),
        "total_unique_payers": len(unique_payers),
        "splits": {
            "train": {
                "count": len(train_scenarios),
                "proportion": round(len(train_scenarios) / len(scenarios), 4),
                "unique_payers": len(train_payers),
                "categories": dict(Counter(s.category.value for s in train_scenarios)),
                "labels": dict(Counter(s.ground_truth_label for s in train_scenarios)),
            },
            "val": {
                "count": len(val_scenarios),
                "proportion": round(len(val_scenarios) / len(scenarios), 4),
                "unique_payers": len(val_payers),
                "categories": dict(Counter(s.category.value for s in val_scenarios)),
                "labels": dict(Counter(s.ground_truth_label for s in val_scenarios)),
            },
            "test": {
                "count": len(test_scenarios),
                "proportion": round(len(test_scenarios) / len(scenarios), 4),
                "unique_payers": len(test_payers),
                "categories": dict(Counter(s.category.value for s in test_scenarios)),
                "labels": dict(Counter(s.ground_truth_label for s in test_scenarios)),
            },
        },
        "leakage_verified": True,
        "is_synthetic": True,
    }

    return DatasetSplits(
        train=train_scenarios,
        val=val_scenarios,
        test=test_scenarios,
        report=report,
    )


# -----------------------------------------------------------------------------
# Feature & Target Separation (Anti-Leakage Extraction)
# -----------------------------------------------------------------------------

def separate_features_and_targets(
    scenarios: list[SyntheticPaymentScenario],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate a scenario dataset into features, targets, and metadata.

    Guarantees no evaluation targets or raw identifiers exist in the feature set.
    """
    features = [s.to_features().to_dict() for s in scenarios]
    targets = [s.to_targets().to_dict() for s in scenarios]
    metadata = [s.to_metadata().to_dict() for s in scenarios]
    return features, targets, metadata


# -----------------------------------------------------------------------------
# Distribution Summary & Export Utilities
# -----------------------------------------------------------------------------

def summarize_dataset(scenarios: list[SyntheticPaymentScenario]) -> dict[str, Any]:
    """Produce a comprehensive statistical breakdown of a scenario dataset."""
    if not scenarios:
        return {"total_records": 0, "is_synthetic": True}

    amounts = [s.amount_paise for s in scenarios]
    categories = Counter(s.category.value for s in scenarios)
    profiles = Counter(s.profile_type for s in scenarios)
    labels = Counter(s.ground_truth_label for s in scenarios)
    tiers = Counter(s.expected_policy_tier for s in scenarios)
    unique_payers = len({s.payer_id for s in scenarios})
    unique_beneficiaries = len({s.beneficiary_id for s in scenarios})
    registry_statuses = Counter(s.registry_check_status for s in scenarios)
    registry_matches = Counter(
        "listed" if s.is_listed_in_registry is True
        else "not_listed" if s.is_listed_in_registry is False
        else "unknown_unavailable"
        for s in scenarios
    )

    return {
        "total_records": len(scenarios),
        "unique_payers": unique_payers,
        "unique_beneficiaries": unique_beneficiaries,
        "categories": dict(categories),
        "profiles": dict(profiles),
        "labels": dict(labels),
        "expected_policy_tiers": dict(tiers),
        "registry_check_statuses": dict(registry_statuses),
        "registry_matches": dict(registry_matches),
        "amount_paise_stats": {
            "min": min(amounts),
            "max": max(amounts),
            "median": sorted(amounts)[len(amounts) // 2],
            "total": sum(amounts),
        },
        "is_synthetic": True,
        "declaration": "Synthetic lab dataset for PauseGuard Policy Lab evaluation only.",
    }


def generate_dataset_manifest(
    scenarios: list[SyntheticPaymentScenario],
    seed: int = 42,
) -> dict[str, Any]:
    """Generate reproducible dataset manifest metadata."""
    summary = summarize_dataset(scenarios)
    return {
        "manifest_version": "2.0.0",
        "random_seed": seed,
        "generator": "PauseGuard Synthetic Data Engine V2",
        "summary": summary,
        "is_synthetic": True,
        "license": "Internal Project Evaluation Only",
    }


def export_dataset_to_json(
    scenarios: list[SyntheticPaymentScenario],
    filepath: Path | str,
    seed: int | None = None,
) -> Path:
    """Export scenarios to a formatted JSON file with metadata."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "is_synthetic": True,
        "declaration": "Fictional mock dataset for PauseGuard Policy Lab evaluation only.",
        "seed": seed,
        "count": len(scenarios),
        "scenarios": [s.to_dict() for s in scenarios],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def export_dataset_to_jsonl(
    scenarios: list[SyntheticPaymentScenario],
    filepath: Path | str,
) -> Path:
    """Export scenarios to line-delimited JSON (JSONL) format."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for s in scenarios:
            f.write(json.dumps(s.to_dict()) + "\n")
    return path


def load_dataset_from_json(filepath: Path | str) -> list[SyntheticPaymentScenario]:
    """Load and parse scenarios from a JSON export file."""
    path = Path(filepath)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    raw_list = data["scenarios"] if isinstance(data, dict) and "scenarios" in data else data
    return [SyntheticPaymentScenario.from_dict(item) for item in raw_list]


def load_dataset_from_jsonl(filepath: Path | str) -> list[SyntheticPaymentScenario]:
    """Load and parse scenarios from a line-delimited JSON (JSONL) export file."""
    path = Path(filepath)
    scenarios: list[SyntheticPaymentScenario] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                scenarios.append(SyntheticPaymentScenario.from_dict(json.loads(line)))
    return scenarios
