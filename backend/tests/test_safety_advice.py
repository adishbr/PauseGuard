import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.safety_advice import purpose_advice


@pytest.mark.parametrize("value", [False, True, None, 0, 1, "false"])
def test_helper_values_never_authorize_and_invalid_values_degrade(value):
    advice = purpose_advice("synthetic purpose", assessor=lambda _: SimpleNamespace(
        suspicious=value, reasons=("unreviewed_raw_helper_reason",)))
    assert advice.can_authorize_payment is False
    assert advice.available is (type(value) is bool)
    assert advice.suspicious is (value if type(value) is bool else True)
    assert "unreviewed_raw_helper_reason" not in repr(advice)


def test_unavailable_helper_is_explicitly_cautious():
    def unavailable(_):
        raise RuntimeError("synthetic-private")
    advice = purpose_advice("synthetic purpose", assessor=unavailable)
    assert advice.suspicious and not advice.available and not advice.can_authorize_payment
    assert "synthetic-private" not in repr(advice)


def test_cancellation_is_not_swallowed_as_advice():
    def cancelled(_):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        purpose_advice("synthetic purpose", assessor=cancelled)


def test_actual_member4_purpose_helper_injects_without_reason_code_promotion(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "safety/purpose_challenge/purpose_challenge.py"
    spec = importlib.util.spec_from_file_location("fixture_member4_purpose", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    ordinary = purpose_advice("supplier invoice", assessor=module.assess_purpose)
    coercion = purpose_advice("police arrest immediately", assessor=module.assess_purpose)
    assert ordinary.available and not ordinary.suspicious
    assert coercion.available and coercion.suspicious
    assert ordinary.can_authorize_payment is coercion.can_authorize_payment is False
