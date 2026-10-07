import re
from django.core.exceptions import ValidationError


def validate_legitimate_reason(value):
    """
    Enforces reason legitimacy validation across the application.
    Rejects purely numeric codes, symbols, or gibberish.
    Requires at least 3 distinct alphabetic words (length >= 2).
    """
    if not value or not str(value).strip():
        raise ValidationError("Reason is required and cannot be empty.")

    text = str(value).strip()
    words = re.findall(r'[a-zA-Z]{2,}', text)
    if len(words) < 3:
        raise ValidationError(
            "Please provide a legitimate justification with at least 3 descriptive words (e.g. 'Income verification completed'). Numeric codes or gibberish are not accepted."
        )
    return text
