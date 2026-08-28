"""Enterprise Privacy Policy & PII Scrubbing Engine.

Enforces strict column-level and value-level data protection rules to ensure
that sensitive data, Personally Identifiable Information (PII), credentials,
financial/medical details, and free-form personal text NEVER enter LLM prompts
or schema discovery contexts.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Set
from loguru import logger

from app.core.config.settings import settings

# 1. Comprehensive list of sensitive column name patterns
DENIED_EXACT_OR_TOKEN_PATTERNS: tuple[str, ...] = (
    "pin", "pwd", "ssn", "ein", "tin", "otp", "totp", "cvv", "cvc", "ccv",
    "apt", "zip", "raw", "log", "logs", "bio", "id", "uid", "guid", "usr", "name",
)

DENIED_SUBSTRING_PATTERNS: tuple[str, ...] = (
    # Credentials & Security
    "password", "passwd", "secret", "token", "auth", "credential", "private_key", "privatekey",
    "api_key", "apikey", "access_token", "accesstoken", "auth_token", "authtoken", "session_id", "sessionid",
    "jwt", "bearer", "signature", "salt", "hash",
    # Government & Identification
    "social_security", "socialsecurity", "national_id", "nationalid", "passport", "tax_id", "taxid",
    "driver_license", "drivers_license", "license_num", "civil_id", "iqama",
    # Contact Details
    "email", "mail", "phone", "mobile", "telephone", "cell", "fax",
    "address", "street", "postal", "building",
    # Personal & Demographics
    "first_name", "firstname", "last_name", "lastname", "full_name", "fullname", "sur_name", "surname",
    "customer_name", "patient_name", "client_name", "employee_name", "user_name", "username",
    "dob", "date_of_birth", "birthdate", "birth_date", "race", "ethnicity", "religion",
    # Financial & Banking
    "credit_card", "creditcard", "card_number", "cardnumber", "exp_date",
    "bank_account", "bankaccount", "iban", "swift", "routing_number", "routingnumber",
    "salary", "wage", "compensation", "credit_limit", "credit_score", "balance_due",
    # Medical & Healthcare (HIPAA)
    "diagnosis", "prescription", "medical", "patient", "mrn", "health_record", "clinical",
    # Unstructured / Free-Text / Blobs (high risk of containing unvetted PII)
    "note", "notes", "comment", "comments", "body", "description", "content", "payload",
    "blob", "json", "xml", "html", "stacktrace", "remark", "remarks",
    # Technical Identity
    "ip_address", "ipaddress", "mac_address", "macaddress", "device_id", "cookie",
)

# 2. Strict, whitelist of allowed categorical/low-cardinality semantic columns
ALLOWED_SAMPLE_CATEGORICAL_PATTERNS: tuple[str, ...] = (
    "status", "type", "kind", "category", "gender", "tier",
    "country", "state", "city", "region", "currency", "code",
    "priority", "segment", "department", "role", "plan", "flag",
    "mode", "source", "medium", "channel", "brand", "level",
    "frequency", "iso_code", "payment_method", "shipping_method",
)

# 3. Regex matchers for sniffing value-level PII
_EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")
_CREDIT_CARD_REGEX = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")
_SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE_REGEX = re.compile(r"(?:\+?\d{1,4}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}\b")
_IPV4_REGEX = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_JWT_REGEX = re.compile(r"\beyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*\b")
_UUID_REGEX = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def is_safe_semantic_sample_column(col_name: str, strict_mode: Optional[bool] = None) -> bool:
    """
    Checks if a column is strictly safe for value profiling and LLM prompt inclusion.
    Enforces a strict categorical allowlist AND a comprehensive sensitive denylist.
    Eliminates the legacy len(name) <= 15 loophole.
    """
    is_strict = strict_mode if strict_mode is not None else getattr(settings, "strict_privacy_mode", False)
    if is_strict:
        return False

    name = col_name.lower().strip().replace(" ", "_")
    tokens = set(name.split("_"))

    # 1. Deny if matched against exact or token patterns
    if any(t in tokens for t in DENIED_EXACT_OR_TOKEN_PATTERNS):
        return False

    # 2. Deny if matched against sensitive substring patterns
    if any(k in name for k in DENIED_SUBSTRING_PATTERNS):
        return False

    # 3. Must match an explicitly allowed categorical concept
    return any(k in name for k in ALLOWED_SAMPLE_CATEGORICAL_PATTERNS)


class PIIValueSanitizer:
    """Sniffs and sanitizes individual sample values for hidden PII."""

    @classmethod
    def contains_pii(cls, val: Any) -> bool:
        """Returns True if the string representation of val matches known PII patterns."""
        if val is None:
            return False
        s_val = str(val).strip()
        if not s_val or len(s_val) < 4:
            return False

        if _EMAIL_REGEX.search(s_val):
            return True
        if _CREDIT_CARD_REGEX.search(s_val):
            return True
        if _SSN_REGEX.search(s_val):
            return True
        if _PHONE_REGEX.search(s_val):
            return True
        if _IPV4_REGEX.search(s_val):
            return True
        if _JWT_REGEX.search(s_val):
            return True
        if _UUID_REGEX.search(s_val):
            return True

        return False

    @classmethod
    def sanitize_sample(cls, val: Any, max_len: int = 25) -> Optional[str]:
        """
        Sanitizes a single sample value:
        - Drops None/empty
        - Drops values containing PII
        - Truncates to max_len
        - Returns clean string or None if unsafe.
        """
        if val is None:
            return None
        s_val = str(val).strip()
        if not s_val:
            return None

        if cls.contains_pii(s_val):
            logger.debug("Scrubbed PII value from sample candidate: %s", s_val[:10] + "...")
            return None

        if len(s_val) > max_len:
            s_val = s_val[:max_len]

        return s_val

    @classmethod
    def sanitize_samples(
        cls,
        samples: List[Any],
        max_samples: int = 3,
        max_len: int = 25,
    ) -> List[str]:
        """Filters and sanitizes a list of sample values, dropping any unsafe values."""
        clean_samples: List[str] = []
        seen = set()
        for s in samples:
            clean = cls.sanitize_sample(s, max_len=max_len)
            if clean and clean not in seen:
                seen.add(clean)
                clean_samples.append(clean)
                if len(clean_samples) >= max_samples:
                    break
        return clean_samples
