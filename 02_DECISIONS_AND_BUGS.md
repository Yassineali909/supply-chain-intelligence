# DECISIONS & BUGS LOG

The reasoning behind every significant design decision, and every real bug/lesson. This is
the "why it is the way it is" and "don't repeat these mistakes" file. The last session added
the text-to-SQL path, the Qdrant vector store, and semantic search — its decisions and
lessons are D15–D22 and B17–B21.

---

## PART A — MAJOR DESIGN DECISIONS (with reasoning)

### D1. Second project != repeat of the first — chose Supply Chain/Logistics (freight)
Range vs the first project; freight's multi-hop structure genuinely justifies a graph.

### D2–D14 (earlier sessions, still authoritative)
D2 end-to-end != every-technology. D3 correlated synthetic data (events first, docs from
events). D4 hidden causal levers (stripped from agent schema). D5 seven capability-distinct
scenarios. **D6 Option A — "LLM plans, code controls evidence"; text-to-SQL was DEFERRED under
this as the most failure-prone capability.** D7 honest epistemics (COMPARATIVE/TREND not CAUSAL
for observational scenarios; CAUSAL needs a DIRECT doc). D8 the verifier is mutation-tested.
D9 Grafana observability / Streamlit interaction. D10 the control test guards the judge. D11
vertical-slice rule (no feature without a failing case). D12 reuse proven checks by choosing
the honest claim type. D13 refuse rather than default to a planted entity. D14 ranking uses
the DE-CONFOUNDED metric (clean routes).

### D15. Text-to-SQL: let the LLM write SQL, keep Option-A guarantees via LAYERED GUARDRAILS
D6 deferred this as most failure-prone. The whole build: the LLM DRAFTS, deterministic code
VALIDATES and CONTROLS, nothing executes until it passes every guard, the verifier still gates
the final claim, and it REFUSES rather than run SQL it can't validate. The guardrails ARE the
feature (and the interview story). Layers: L1 read-only execution (DB-level), L2 sqlglot parse
→ single SELECT, L3 table allowlist + function denylist, L4 forced LIMIT + timeout, L5 the
verifier. Build order was VERIFY-FIRST: build the guard and ATTACK it with malicious strings
BEFORE any LLM was involved (27/27 adversarial cases blocked/passed correctly).

### D16. Parse, don't regex (guardrail L2)
A parser catches `;`-stacked and comment-hidden payloads a regex can't, AND correctly ALLOWS a
benign `;` inside a string literal. We EXECUTE THE RE-RENDERED AST, so comments and
parser-unsupported clauses (e.g. FOR UPDATE, which sqlglot strips) can't reach the DB.

### D17. AGGREGATE claim type (NEW) instead of reusing NUMERIC — VERIFIED, not assumed
Agreed plan was to "reuse NUMERIC_CLAIM_MATCHES_SQL". VERIFY-FIRST proved it does NOT bind for
counts: the NUMERIC check is DAY-valued only (`_NUM_DAYS_RE`), so a count marked NUMERIC with
correct matching evidence FAILS the check and SILENTLY downgrades SUPPORTED→PARTIALLY_SUPPORTED
(the B15 trap, reproduced empirically). Mislabeling a count as ENTITY_FACT to dodge the check
would be dishonest AND leave threat #6 unguarded. Decision: add a dedicated AGGREGATE claim type
+ check, PURELY ADDITIVELY (new enum member; a check loop that runs only for AGGREGATE claims,
which no existing claim uses) → the 47 original tests untouched, proven byte-identical.

### D18. AGGREGATE check = TRANSCRIPTION guard, NOT semantic correctness (honest limit)
It certifies the claim's number equals the SQL result's number. It does NOT certify the SQL
answers the QUESTION (threat #6 — "confidently-wrong", the hardest). Mitigation: surface the
generated SQL in the answer + evidence locator (auditable), and keep the claim scoped. This is
documented, not hidden. (Seen live: "how many shipments per status" once drafted COUNT(*)
without GROUP BY — correct number, wrong question — fixed via few-shot, but the class remains.)

### D19. Multi-row (grouped) analytical: per-row verification, LABEL IN LOCATOR (chose the
better option, not the simpler). A GROUP BY result (N×2) → ONE AGGREGATE claim PER ROW, each
verified against its SQL value. The group label lives in the evidence LOCATOR, never the
scanned claim text, so a NUMERIC label (e.g. a month number) can't pollute value extraction.
Rejected the simpler "non-numeric labels only" approach because time-series ("per month") is a
central domain question. GROUP BY is detected via the parsed AST to distinguish a real grouping
from a two-metric query. Capped at 25 groups (a table answer must stay human-auditable).

### D20. Qdrant exact lookup via PAYLOAD FILTER, not vector similarity — to PRESERVE RC-06
The JSON store's `search_documents` is an EXACT shipment-code lookup, and RC-06's honest refusal
DEPENDS on it returning [] when no doc exists. A naive "swap to vector search" would return the
nearest doc even when none is relevant → silently breaks RC-06. So the Qdrant migration uses an
EXACT payload filter (whole SH- codes), preserving []-on-absent. Proven on the real corpus: all
5 RC-06 shipments empty in both backends; exact lookup matches JSON 15/15. Semantic search is
ADDED alongside as a NEW capability, never used for the exact lookup. (It also FIXES a latent
JSON substring over-match: `"SH-1" in text` matched "SH-10"; Qdrant matches whole codes.)

### D21. Backend switch is OPT-IN (USE_QDRANT=1), JSON default — deterministic tests, reversible
`document_retrieval.py` routes to Qdrant only when USE_QDRANT=1 AND an index exists, else JSON,
with a safe fallback. Default = JSON so the eval/tests stay deterministic and the migration is
reversible and demoable both ways. Parity PROVEN live through the real RC-07 + RC-06
investigations (identical outcome + evidence on both backends) before trusting it.

### D22. Semantic doc_search = Option-A RAG (retrieve + REPORT, no LLM synthesis)
"What do our docs say about X?" invites RAG hallucination (the model asserting beyond the docs).
So the model does NOT write the answer: vectors retrieve, deterministic code reports exactly what
was retrieved (doc ids + snippets + scores), the claim is a RELATIONSHIP claim (verifier gates by
binding, no over-assertion), evidence is CONTEXTUAL (semantic ≠ causal, cf. D7). A grounded-LLM
SUMMARY was DEFERRED because it needs its OWN hallucination verifier — do NOT ship the summary
version without that check. Similarity floor = 0.55, MEASURED (see B21), with a below-floor
refusal (the semantic analogue of RC-06).

---

## PART B — REAL BUGS HIT & HOW THEY WERE FIXED

### B1–B16 (earlier sessions — still the standard)
B1 cross-scenario collision (invariant checks). B2 schema-rebuild idempotency (test the
REBUILD). B3 evidence-phrasing vs verifier regex mismatch. B4 comparative derived-gap check.
B5 missing negative PARTIAL test (mutation testing found it). B6 small-model routing loop (fix
STRUCTURALLY — remove the tool). B7 agent hardcoded a cause contradicting its doc (judge caught
it). B8 judge too lenient (control test caught it). B9 run-logging key collision ("ran without
error" != "worked"). B10 fragile multi-anchor patch half-applied → small independent edits. B11
weak LLM overrode a clear signal (`_has_strong_pattern`). B12 non-unique anchor in a scripted
patch (assert count==1, apply in memory, write only if all pass). B13 the `code <file>`
shorthand created a junk file (prefer heredocs; watch `git status`). B14 "right outcome, right
reason?" (inspect claims/checks, not just the badge). **B15 evidence number formatting defeated
the verifier's extractor ("Nd" vs "N days") → silent downgrade (verifier is phrasing-sensitive
BY DESIGN).** B16 anchored-append guard duplicated content on re-run (assert replacement NOT
already present).

### B17. VERIFY-FIRST paid off: count-as-NUMERIC silently downgrades (text-to-SQL)
Reproduced empirically BEFORE building: a count claim marked NUMERIC with correct matching SQL
evidence → NUMERIC check FAILS ("could not extract one delay value") → SUPPORTED silently
downgraded to PARTIALLY_SUPPORTED. Perfect prose, correct number, wrong outcome — the B15 class.
Fix: the AGGREGATE type (D17). Lesson: the "reuse an existing check" plan MUST be verified to
bind before building on it; don't assume.

### B18. Regex lookahead defeated by a trailing sentence period (caught by testing)
The AGGREGATE value extractor `(?![\w.])` rejected "142." (number at a sentence end, period
follows). Fixed to `(?!\d)`. Lesson: test the extractor against real phrasings (numbers at
sentence ends, decimals, entity-code digits) — this is exactly the B3/B15 family.

### B19. The missing commit — a GREEN BOARD hid a broken repo (IMPORTANT)
After the text-to-SQL work, 132 tests passed LOCALLY — but the commit adding the AGGREGATE enum
+ verifier check + router route NEVER RAN (its `git commit` got separated from `git add` in a
paste). `analytical.py` (committed) referenced an AGGREGATE type/check that WEREN'T committed →
a fresh clone would NOT build. Caught by reading `git status` + `git log`, NOT by tests.
Fix: committed the missing files; then VERIFIED by cloning fresh to /tmp and running the suite
there (138 passed from the clone). Lesson (now standard): "done" = green FROM A CLEAN CLONE and a
confirmed test count, never a local green alone. `git log`/`git status` are part of the test.

### B20. A whole test file silently never joined the suite (semantic route)
`test_semantic.py` never got copied into `tests/`; the suite reported `141 passed` which LOOKED
fine but was the pre-semantic count — the entire new feature was UNTESTED in the suite. Caught by
checking the EXPECTED count (should have jumped to 155), not by any failure. Fix: wrote the file
into `tests/` via heredoc, re-ran, 156. Lesson: after adding tests, verify the COUNT moved by the
expected amount; a flat count is a silent "file not collected."

### B21. A GUESSED threshold served noise — measured it instead (semantic floor)
Initial SCORE_FLOOR=0.4 was set from intuition. A deliberately off-topic query ("quantum
computing") returned 5 unrelated docs at ~0.44 as "relevant" — the semantic version of
returning nearest-but-irrelevant. Caught by RUNNING THE OFF-TOPIC CASE ON PURPOSE (testing the
failure, not just the happy path). Fix: measured the score distribution on the real corpus
(on-topic ≥0.72, off-topic ≤0.40 — a wide clean gap), set floor=0.55 in the gap, regression-
locked it with a test. Lesson: thresholds are MEASURED from the real distribution, not guessed,
then locked with a test. (D22, B21 together are a strong interview story.)

### Environment lessons this session
- WSL + snap Docker is broken (no daemon, no `docker.service`, no `docker` group). For Docker
  Compose next: `apt remove` the snap, install `docker.io` or Docker Desktop with WSL
  integration. Qdrant did NOT need Docker — local on-disk mode (`QdrantClient(path=...)`).
- qdrant-client local mode prints a harmless `ImportError: ... Python is likely shutting down`
  traceback from its destructor at interpreter teardown. Cosmetic; fires AFTER results; ignore.
- Browser downloads land in Windows Downloads (`/mnt/c/Users/yassi/Downloads`), NOT the WSL
  repo, and duplicate names get a ` (1)` suffix. Copy across with `cp` and VERIFY by content
  (grep for a distinctive symbol), not by filename. Strip CRLF with `sed -i 's/\r$//'`.
- `ollama pull nomic-embed-text` (~274MB, 768-dim) is required for the Qdrant embedder.

---

## PART C — GITHUB / WORKFLOW LESSONS
- GitHub rejects passwords — use a PAT (repo scope); never paste the token in chat.
- Commit PER FEATURE/UNIT with descriptive messages — clean history is an interview point.
- Watch `git status` for strays before every `git add` (B13); remove `.orig`/`.bak` backups.
- venv must be re-activated each new terminal; WSL services (postgres, neo4j, grafana, AND the
  need to re-activate) do NOT persist across restarts; Python is 3.14.
- Generated indexes/artifacts are git-ignored: `rc07_vertical_slice/qdrant_data/`, `artifacts/`.
- The handoff docs (00–03) live IN the repo — they are the cross-session memory. Keep them current.
