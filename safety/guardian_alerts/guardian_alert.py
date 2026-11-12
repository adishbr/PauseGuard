
"""Privacy-safe, localized guardian notification messages."""

from datetime import datetime, timezone


MESSAGES = {
    "en": (
        "PauseGuard needs you to review a safety alert. "
        "Please open the app to view the available details."
    ),
    "hi": (
        "PauseGuard को सुरक्षा अलर्ट की समीक्षा के लिए आपकी "
        "सहायता चाहिए। उपलब्ध जानकारी देखने के लिए कृपया ऐप खोलें।"
    ),
    "kn": (
        "ಸುರಕ್ಷತಾ ಎಚ್ಚರಿಕೆಯನ್ನು ಪರಿಶೀಲಿಸಲು PauseGuard ಗೆ ನಿಮ್ಮ "
        "ಸಹಾಯದ ಅಗತ್ಯವಿದೆ. ಲಭ್ಯವಿರುವ ವಿವರಗಳನ್ನು ನೋಡಲು ದಯವಿಟ್ಟು "
        "ಆ್ಯಪ್ ತೆರೆಯಿರಿ."
    ),
}


def build_guardian_alert(
    case_id: str,
    locale: str = "en",
) -> dict:
    """Build a minimal guardian alert without payment details."""

    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("A valid case_id is required")

    if len(case_id) > 100:
        raise ValueError("case_id is too long")

    if any(char.isspace() for char in case_id):
        raise ValueError("case_id must not contain whitespace")

    if not isinstance(locale, str):
        locale = "en"

    normalized_locale = locale.strip().replace("_", "-")
    language = normalized_locale.split("-")[0].lower()

    if language not in MESSAGES:
        language = "en"

    return {
        "case_id": case_id,
        "message": MESSAGES[language],
        "locale": language,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contains_payment_details": False,
        "approval_requested": False,
    }
