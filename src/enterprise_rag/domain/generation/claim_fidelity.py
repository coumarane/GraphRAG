"""Claim-strength fidelity: do not upgrade tested/demo values to recommendations.

General rule for cosmetics/spec RAG: challenge-test concentrations, MIC values,
and slide demos are not the same as recommended / specified / approved use levels
unless the evidence literally says so.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# Questions that ask for a normative / prescribed value.
_ASKS_NORMATIVE = re.compile(
    r"(?i)\b("
    r"recommended(?:\s+\w+){0,3}\s+(?:use\s+)?(?:level|rate|dosage|dose|amount|concentration)|"
    r"recommended\s+use|"
    r"(?:official|specified|approved|labelled|labeled)\s+(?:use\s+)?(?:level|dosage|dose|rate)|"
    r"use\s+level|"
    r"dosage\s+recommendation|"
    r"how\s+much\s+(?:should|to)\s+(?:I\s+)?(?:use|add)|"
    r"what\s+(?:is|are)\s+the\s+recommended\b"
    r")\b"
)

# Evidence language that actually supports a normative claim.
_EVIDENCE_NORMATIVE = re.compile(
    r"(?i)\b("
    r"recommended(?:\s+\w+){0,4}\s+(?:use\s+)?(?:level|rate|dosage|dose|amount)|"
    r"recommended\s+use|"
    r"(?:suggested|advised)\s+(?:use\s+)?(?:level|dosage)|"
    r"use\s+level\s*[:=]|"
    r"dosage\s*[:=]|"
    r"incorporation\s+level|"
    r"add(?:ed)?\s+at\s+\d|"
    r"specification(?:s)?\b.{0,40}\b(?:use|level|dosage)|"
    r"typical\s+use\s+level|"
    r"guidelines?\s+for\s+use"
    r")\b"
)

# Evidence that is merely experimental / demonstrated — must not be upgraded.
_EVIDENCE_DEMO = re.compile(
    r"(?i)\b("
    r"challenge\s+test|"
    r"tested\s+(?:at|with|in)|"
    r"showing\s+(?:antimicrobial|activity)|"
    r"minimum\s+inhibitory|"
    r"\bMIC\b|"
    r"demonstrated|"
    r"in\s+(?:the\s+)?(?:toner|cream|lotion|formula|formulation)\b|"
    r"\d+(?:\.\d+)?\s*%\s*(?:SY-)?KNP|"
    r"with\s+\d+(?:\.\d+)?\s*%\s*"
    r")\b"
)

# Answer language that asserts a recommendation.
_ANSWER_NORMATIVE = re.compile(
    r"(?i)\b("
    r"recommended\s+use\s+level|"
    r"recommended\s+(?:dosage|dose|concentration|amount)|"
    r"the\s+recommended\s+\w+\s+is|"
    r"should\s+be\s+used\s+at|"
    r"official\s+use\s+level|"
    r"specified\s+use\s+level"
    r")\b"
)

# Denial / clarification that mentions recommendation without asserting one.
_ANSWER_DENIES_NORMATIVE = re.compile(
    r"(?i)\b("
    r"no(?:t)?\s+(?:an?\s+)?explicit\s+recommended|"
    r"not\s+(?:an?\s+)?explicit(?:ly)?\s+recommended|"
    r"no\s+recommended(?:/specified)?(?:\s+use\s+level)?\s+was\s+found|"
    r"does\s+not\s+(?:state|specify|provide)\s+a\s+recommended|"
    r"not\s+explicitly\s+recommended\s+in\s+the\s+evidence|"
    r"no\s+explicit\s+recommended/specified\s+use\s+level"
    r")\b"
)

CLAIM_STRENGTH_OVERREACH = "claim_strength_overreach"


def question_asks_normative_value(question: str) -> bool:
    return bool(_ASKS_NORMATIVE.search(question or ""))


def evidence_states_normative_value(texts: Sequence[str]) -> bool:
    blob = "\n".join(texts)
    return bool(_EVIDENCE_NORMATIVE.search(blob))


def evidence_shows_demo_or_test_level(texts: Sequence[str]) -> bool:
    blob = "\n".join(texts)
    return bool(_EVIDENCE_DEMO.search(blob))


def answer_asserts_normative_value(answer: str) -> bool:
    text = answer or ""
    if _ANSWER_DENIES_NORMATIVE.search(text):
        return False
    return bool(_ANSWER_NORMATIVE.search(text))


def build_claim_fidelity_hint(question: str, evidence_texts: Sequence[str]) -> str | None:
    """User-message hint when the question is normative but evidence is only demo/test."""
    if not question_asks_normative_value(question):
        return None
    if evidence_states_normative_value(evidence_texts):
        return None
    if evidence_shows_demo_or_test_level(evidence_texts):
        return (
            "CLAIM FIDELITY (required):\n"
            "- The question asks for a recommended/specified/official value "
            "(e.g. use level).\n"
            "- Evidence only shows tested, challenge-test, demo, or MIC "
            "concentrations — not an explicit recommendation.\n"
            "- Do NOT say \"recommended use level\" (or similar). Say the value "
            "was used/tested in the cited experiment and that no explicit "
            "recommended/specified use level was found in the evidence.\n"
            "- Cite only the test slides; add a short warning that recommendation "
            "language is absent."
        )
    return (
        "CLAIM FIDELITY (required):\n"
        "- The question asks for a recommended/specified value, but the evidence "
        "does not state one.\n"
        "- Say so briefly. Do not invent a recommendation from unrelated numbers. "
        "Return citation_ids as [] if nothing supports the ask."
    )


def detect_claim_strength_overreach(question: str, answer: str, evidence_texts: Sequence[str]) -> bool:
    """True when the answer upgrades demo/test evidence into a recommendation."""
    if not question_asks_normative_value(question):
        return False
    if evidence_states_normative_value(evidence_texts):
        return False
    return answer_asserts_normative_value(answer)


def soften_normative_overreach(answer: str) -> str:
    """Deterministic rewrite when the model upgrades tested levels to recommendations."""
    softened = re.sub(
        r"(?i)\bthe recommended use level(?:\s+in\s+(?:a\s+)?finished\s+formula)?\b",
        "the concentration used in the cited challenge/demo tests "
        "(not an explicit recommended use level)",
        answer,
    )
    softened = re.sub(
        r"(?i)\brecommended use level\b",
        "tested concentration (not explicitly recommended in the evidence)",
        softened,
    )
    note = (
        "No explicit recommended/specified use level was found in the evidence; "
        "values above reflect tested challenge-formula concentrations only."
    )
    if note.casefold() not in softened.casefold():
        softened = f"{softened.rstrip()}\n\n{note}"
    return softened
