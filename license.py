"""
SimHeut96 — Système de codes d'activation
===========================================
Logique de génération / vérification des codes de licence.
SECRET_KEY est lue depuis une variable d'environnement : ne jamais la
mettre en clair dans le code une fois déployée.
"""

import hmac
import hashlib
import os
import secrets
from datetime import date, timedelta
from dataclasses import dataclass
from typing import Optional

# =============================================================================
# CONFIGURATION
# =============================================================================

SECRET_KEY = os.environ.get("SIMHEUT96_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "La variable d'environnement SIMHEUT96_SECRET_KEY doit être définie "
        "(clé longue et aléatoire, à générer une seule fois et à garder secrète)."
    )

PLANS = {
    "ESSAI": {"label": "Essai gratuit", "max_membres": 20, "duree_jours": 30},
    "STD":   {"label": "Standard",      "max_membres": 60, "duree_jours": 365},
    "PRO":   {"label": "Pro (illimité)", "max_membres": 999, "duree_jours": 365},
}

PLAN_CODES = {"ESSAI": 1, "STD": 2, "PRO": 3}
PLAN_NAMES = {v: k for k, v in PLAN_CODES.items()}
EPOCH = date(2026, 1, 1)


# =============================================================================
# ENCODAGE
# =============================================================================

def _b32(raw: bytes) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    n = int.from_bytes(raw, "big")
    out = []
    while n > 0:
        n, rem = divmod(n, 32)
        out.append(alphabet[rem])
    return "".join(reversed(out)) or alphabet[0]


def _from_b32(s: str) -> int:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    n = 0
    for ch in s:
        if ch not in alphabet:
            raise ValueError(f"Caractère invalide dans le code : {ch}")
        n = n * 32 + alphabet.index(ch)
    return n


def _chunk(s: str, size: int = 4) -> str:
    return "-".join(s[i:i + size] for i in range(0, len(s), size))


# =============================================================================
# GÉNÉRATION
# =============================================================================

def generate_license_code(plan: str, date_expiration: Optional[date] = None) -> str:
    if plan not in PLANS:
        raise ValueError(f"Plan inconnu : {plan}")
    if date_expiration is None:
        date_expiration = date.today() + timedelta(days=PLANS[plan]["duree_jours"])

    jours_expiration = (date_expiration - EPOCH).days
    if not (0 <= jours_expiration < 65536):
        raise ValueError("Date d'expiration hors plage encodable.")

    nonce = secrets.randbits(24)

    payload = (
        PLAN_CODES[plan].to_bytes(1, "big")
        + jours_expiration.to_bytes(2, "big")
        + nonce.to_bytes(3, "big")
    )

    signature = hmac.new(SECRET_KEY.encode(), payload, hashlib.sha256).digest()[:3]
    code_bytes = payload + signature

    return "SIMH-" + _chunk(_b32(code_bytes).rjust(15, "A"))


# =============================================================================
# VÉRIFICATION
# =============================================================================

@dataclass
class LicenseCheckResult:
    valide: bool
    raison: str = ""
    plan: Optional[str] = None
    max_membres: Optional[int] = None
    date_expiration: Optional[str] = None


def verify_license_code(code: str) -> LicenseCheckResult:
    raw = code.strip().upper().replace(" ", "")
    if not raw.startswith("SIMH-"):
        return LicenseCheckResult(False, "Format de code invalide (préfixe manquant).")
    body = raw[5:].replace("-", "")
    if len(body) != 15:
        return LicenseCheckResult(False, "Format de code invalide (longueur incorrecte).")

    try:
        value = _from_b32(body)
        code_bytes = value.to_bytes(9, "big")
    except (ValueError, OverflowError):
        return LicenseCheckResult(False, "Code illisible ou corrompu.")

    payload, signature = code_bytes[:6], code_bytes[6:]
    expected_signature = hmac.new(SECRET_KEY.encode(), payload, hashlib.sha256).digest()[:3]

    if not hmac.compare_digest(signature, expected_signature):
        return LicenseCheckResult(False, "Signature invalide — code falsifié ou corrompu.")

    plan_id = payload[0]
    jours_expiration = int.from_bytes(payload[1:3], "big")
    plan = PLAN_NAMES.get(plan_id)
    if plan is None:
        return LicenseCheckResult(False, "Plan inconnu dans ce code.")

    exp = EPOCH + timedelta(days=jours_expiration)
    if date.today() > exp:
        return LicenseCheckResult(False, f"Code expiré depuis le {exp.isoformat()}.",
                                   plan=plan, date_expiration=exp.isoformat())

    return LicenseCheckResult(
        True, "Code valide.", plan=plan,
        max_membres=PLANS[plan]["max_membres"], date_expiration=exp.isoformat())
