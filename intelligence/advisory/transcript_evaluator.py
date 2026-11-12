"""Transcript Coercion Evaluator for PauseGuard V2.

Deterministic, dependency-free advisory analysis of explicitly
consented call transcripts or messages.

Contextual matching with word boundaries to eliminate false positives
on routine banking vocabulary (e.g. "payment", "bank transfer", "evaluate").

Never executes, obeys, or follows instructions in transcript content.
"""

from dataclasses import dataclass
import re
from time import perf_counter
from typing import Optional

from intelligence.schemas.risk_signals import (
    CalculationMethod,
    DataOrigin,
    SignalProvenance,
    SourceCategory,
    TranscriptCoercionSignal,
)

# Compiled contextual patterns for coercion indicators with strict word boundaries
COERCION_INDICATOR_REGEXES = {
    "urgency": [
        re.compile(r"\b(urgent|urgently|immediately|right now|act now|hurry)\b", re.IGNORECASE),
        re.compile(r"\bwithin \d+ (hours?|minutes?)\b", re.IGNORECASE),
        re.compile(r"\b(deadline|will expire|power will be disconnected|account will be closed)\b", re.IGNORECASE),
        re.compile(r"\b(sim.*deactivated|deactivated within)\b", re.IGNORECASE),
        re.compile(r"\bpay (penalty|deposit|now) (immediately|right now|to avoid)\b", re.IGNORECASE),
    ],
    "authority_impersonation": [
        re.compile(r"\b(police|inspector|cyber cell|crime branch|central police)\b", re.IGNORECASE),
        re.compile(r"\b(customs enforcement|enforcement directorate|airport authority)\b", re.IGNORECASE),
        re.compile(r"\b(bank fraud prevention|bank fraud unit|fraud prevention unit)\b", re.IGNORECASE),
        re.compile(r"\b(trai telecom|telecom verification|telecom regulatory)\b", re.IGNORECASE),
        re.compile(r"\b(court warrant|arrest warrant|cbi officer|income tax officer)\b", re.IGNORECASE),
    ],
    "threat": [
        re.compile(r"\b(arrest warrant|will be arrested|immediate arrest|arrested at)\b", re.IGNORECASE),
        re.compile(r"\b(legal action|police case|fir (will be|has been) (filed|issued|registered))\b", re.IGNORECASE),
        re.compile(r"\b(account (is|will be) (frozen|blocked|suspended|deactivated))\b", re.IGNORECASE),
        re.compile(r"\b(power will be disconnected|service will be disconnected)\b", re.IGNORECASE),
        re.compile(r"\b(prosecute|imprisonment|jail term|implicated in money laundering)\b", re.IGNORECASE),
    ],
    "secrecy": [
        re.compile(r"\b(do not|don't) (tell|inform|share with) (anyone|anybody|your family|branch staff|staff|police)\b", re.IGNORECASE),
        re.compile(r"\b(keep this (secret|strictly confidential|confidential))\b", re.IGNORECASE),
        re.compile(r"\b(share screen|screen sharing|anydesk|teamviewer|remote access)\b", re.IGNORECASE),
        re.compile(r"\b(do not disconnect|stay on the line|stay on call)\b", re.IGNORECASE),
        re.compile(r"\b(share (your )?(otp|pin|password|banking credentials))\b", re.IGNORECASE),
    ],
    "financial_pressure": [
        re.compile(r"\b(verification bond|clearance bond|security deposit|penalty deposit)\b", re.IGNORECASE),
        re.compile(r"\b(safe account|safe reserve|safe reserve account|reserve account)\b", re.IGNORECASE),
        re.compile(r"\b(move your funds|transfer the verification|clearance deposit)\b", re.IGNORECASE),
        re.compile(r"\b(pay penalty deposit|pay to avoid arrest|transfer .* immediately to our officer)\b", re.IGNORECASE),
        re.compile(r"\b(transfer security deposit|deposit now to avoid)\b", re.IGNORECASE),
    ],
}

# Compiled contextual patterns for prompt-injection detection with word boundaries
PROMPT_INJECTION_REGEXES = [
    re.compile(r"\b(ignore|disregard|forget) (all )?(previous|prior|system) (instructions|prompts?|rules?)\b", re.IGNORECASE),
    re.compile(r"\b(system prompt|new instructions)\b", re.IGNORECASE),
    re.compile(r"\b(you are now in (admin|developer|jailbreak|god) mode)\b", re.IGNORECASE),
    re.compile(r"\b(act as|pretend you are|roleplay as) (an? )?(unrestricted|evil|dan|jailbroken)\b", re.IGNORECASE),
    re.compile(r"\b(override|bypass) (the )?(safety|security|rules?|checks?|filters?)\b", re.IGNORECASE),
    re.compile(r"\b(ignore safety|disable safety|disable checks?)\b", re.IGNORECASE),
    re.compile(r"\b(eval\s*\(|exec\s*\(|subprocess\.|os\.system|__import__)\b", re.IGNORECASE),
]


def _detect_coercion_indicators(text: str) -> tuple[str, ...]:
    """Detect coercion indicator categories in transcript text using contextual regexes.

    Returns tuple of detected category names. Contextual regex matching with word boundaries
    prevents false positives on routine banking terms like 'payment' or 'transfer'.
    """
    detected = []
    for category, patterns in COERCION_INDICATOR_REGEXES.items():
        if any(p.search(text) for p in patterns):
            detected.append(category)
    return tuple(detected)


def _detect_prompt_injection(text: str) -> bool:
    """Detect possible prompt injection patterns in transcript text.

    Conservative detection using contextual word-bounded regexes.
    Does NOT flag standalone benign words like 'execute' or 'evaluate'.
    """
    return any(p.search(text) for p in PROMPT_INJECTION_REGEXES)


@dataclass(frozen=True)
class TranscriptEvaluationResult:
    """Result of transcript evaluation with timing."""
    signal: TranscriptCoercionSignal
    elapsed_ms: float


def evaluate_transcript(
    transcript_text: Optional[str],
    transcript_consented: bool,
) -> TranscriptEvaluationResult:
    """Evaluate consented transcript for coercion and prompt injection signals.

    Args:
        transcript_text: Transcript content if available.
        transcript_consented: Explicit consent flag from payer/guardian.

    Returns:
        TranscriptEvaluationResult with validated TranscriptCoercionSignal and timing.
    """
    start = perf_counter()

    if transcript_text is None or not transcript_text.strip():
        signal = TranscriptCoercionSignal(
            status="absent",
            coercion_detected=None,
            coercion_indicators=(),
            suspected_prompt_injection=None,
            provenance=SignalProvenance(
                source_category=SourceCategory.MODEL_INFERENCE,
                data_origin=DataOrigin.UNAVAILABLE,
                calculation_method=CalculationMethod.UNPERFORMED,
                is_synthetic=True,
            ),
        )
        return TranscriptEvaluationResult(signal=signal, elapsed_ms=(perf_counter() - start) * 1000)

    if not transcript_consented:
        signal = TranscriptCoercionSignal(
            status="unconsented",
            coercion_detected=None,
            coercion_indicators=(),
            suspected_prompt_injection=None,
            provenance=SignalProvenance(
                source_category=SourceCategory.MODEL_INFERENCE,
                data_origin=DataOrigin.UNAVAILABLE,
                calculation_method=CalculationMethod.UNPERFORMED,
                is_synthetic=True,
            ),
        )
        return TranscriptEvaluationResult(signal=signal, elapsed_ms=(perf_counter() - start) * 1000)

    coercion_indicators = _detect_coercion_indicators(transcript_text)
    coercion_detected = len(coercion_indicators) > 0
    suspected_prompt_injection = _detect_prompt_injection(transcript_text)

    signal = TranscriptCoercionSignal(
        status="evaluated",
        coercion_detected=coercion_detected,
        coercion_indicators=coercion_indicators,
        suspected_prompt_injection=suspected_prompt_injection,
        provenance=SignalProvenance(
            source_category=SourceCategory.MODEL_INFERENCE,
            data_origin=DataOrigin.CONSENTED_AUDIO_TRANSCRIPT,
            calculation_method=CalculationMethod.NLP_REGEX_COERCION,
            is_synthetic=True,
        ),
    )

    elapsed = (perf_counter() - start) * 1000
    return TranscriptEvaluationResult(signal=signal, elapsed_ms=elapsed)
