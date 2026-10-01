"""
LLM-as-judge quality layer (second eval layer, on top of the objective scoreboard).

Two metrics, judged by a local model (mistral) via Ollama:
  - faithfulness    : are the answer's claims supported by the retrieved evidence?
  - answer_relevance: does the answer address the question asked?

The judge is treated with SUSPICION (the GDPR lesson: a local judge can be lenient or
misfire). So:
  - it must output a score AND a reason (auditable),
  - a CONTROL test plants a deliberately-wrong answer and asserts the judge scores it
    lower than the real answer. If the control fails, the judge's scores are not trusted.

Scores are 0.0-1.0. Parsing is strict with a safe fallback to None (unscored, not 0).
"""
from __future__ import annotations

import json
import re

JUDGE_MODEL = "mistral:latest"
OLLAMA_URL = "http://localhost:11434/api/chat"

FAITHFULNESS_SYSTEM = """You are a strict evaluator checking whether an ANSWER is
faithful to the EVIDENCE. Check EVERY specific figure and named cause in the answer
against the evidence, one by one:
- Every NUMBER in the answer (days, counts, dates) must match a number in the evidence.
  If any number differs, the answer is UNFAITHFUL.
- Every named CAUSE in the answer must appear in the evidence. If the answer names a
  cause the evidence does not state, it is UNFAITHFUL.
Synonyms/paraphrases of the SAME fact are fine; different facts are not.

Score 1.0 only if every number and cause matches. Score 0.0 if any number or cause is
wrong or invented. Do not be lenient; a single wrong number means 0.0.

Example - EVIDENCE: "delay 8 days; carrier delay". ANSWER: "arrived 99 days late due to
a mechanical failure" -> {"score": 0.0, "reason": "answer says 99 days but evidence says
8, and names mechanical failure which evidence does not state"}.

Respond with ONLY JSON: {"score": <0.0-1.0>, "reason": "<one sentence>"}"""

RELEVANCE_SYSTEM = """You are a strict evaluator checking whether an ANSWER addresses
the QUESTION asked. Score 1.0 if it directly answers the question, lower if it is
off-topic or evasive. A well-justified refusal to an unanswerable question is relevant
(score it high).

Respond with ONLY JSON: {"score": <0.0-1.0>, "reason": "<one sentence>"}"""


def _ollama_chat(system: str, user: str) -> str:
    import requests
    resp = requests.post(OLLAMA_URL, json={
        "model": JUDGE_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "stream": False, "options": {"temperature": 0.0},
    }, timeout=120)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _parse_score(text: str) -> tuple[float | None, str]:
    """Extract {score, reason}. Returns (None, raw) on parse failure (unscored, not 0)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(0))
            s = float(d.get("score"))
            if 0.0 <= s <= 1.0:
                return s, str(d.get("reason", ""))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    m2 = re.search(r"\b(0(?:\.\d+)?|1(?:\.0+)?)\b", text)
    if m2:
        return float(m2.group(1)), "(parsed from bare number)"
    return None, text.strip()[:120]


def judge_faithfulness(answer: str, evidence_facts: list[str], chat=_ollama_chat):
    user = ("EVIDENCE:\n- " + "\n- ".join(evidence_facts) +
            f"\n\nANSWER:\n{answer}\n\nScore the answer's faithfulness to the evidence.")
    return _parse_score(chat(FAITHFULNESS_SYSTEM, user))


def judge_relevance(answer: str, question: str, chat=_ollama_chat):
    user = f"QUESTION:\n{question}\n\nANSWER:\n{answer}\n\nScore how well the answer addresses the question."
    return _parse_score(chat(RELEVANCE_SYSTEM, user))


def corrupt_answer(answer: str) -> str:
    """Deliberately-wrong version of an answer for the control test."""
    corrupted = re.sub(r"\b\d+(?:\.\d+)?\s+days?\b", "99 days", answer, count=1)
    corrupted = corrupted.replace("customs hold", "a mechanical failure")
    corrupted = corrupted.replace("customs clearance", "a mechanical failure")
    if corrupted == answer:
        corrupted = answer + " The shipment was also lost at sea and never recovered."
    return corrupted
