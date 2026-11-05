from ..config.prompts import CORRECTOR
from ..schemas.results import Correction
from ..models.local_decoder import DecoderError
import re


def correct(decoder, payload):
    result = decoder.complete("corrector", CORRECTOR, payload, Correction)
    allowed = {row["evidence_id"] for row in payload["available_candidates"]}
    if result.decision == "REPLACE" and result.evidence_id not in allowed:
        raise DecoderError("Corrector selected an evidence ID outside the supplied candidate set")
    if result.decision == "EXPAND_SEARCH" and not payload.get("expansion_allowed", False):
        raise DecoderError("Corrector requested an expansion forbidden by the explicit remaining budget")
    if result.decision != "REPLACE" and re.search(r"accounting[ _-]*identity|certificate|reconcil", result.reason, re.I):
        raise DecoderError("Recovery cannot require an optional Python accounting certificate or expand search to obtain one")
    return result
