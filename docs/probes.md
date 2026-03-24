# Measurement Probes Reference

Detailed reference for the probe system in `probes/`. Read this when implementing or modifying probes.

## Overview

Measurement probes are LM-judge evaluators that run after each section is written, scoring the section's quality along a specific dimension. Probe results are stored on `SectionResult.probe_results` (keyed by probe name) and serialized to `context_state.json` as part of the audit trail.

**Integration point:** `research/pipeline.py` calls `run_probes()` after each section writer finishes. The dispatcher in `probes/__init__.py` iterates the probe registry and calls each registered probe.

## Probe Registry (`probes/__init__.py`)

- `ProbeFunc` -- Type alias for the standard probe signature: `async (SectionResult, list[Finding], ResearchContext) -> ProbeResult`.
- `_PROBE_REGISTRY: list[ProbeFunc]` -- List of registered probe functions, populated at import time.
- `register_probe(func)` -- Decorator that appends a probe function to the registry. Apply to the public `run_<name>_probe` function in each probe module.
- `run_probes(section_result, section_evidence, context)` -- Dispatcher that iterates the registry and calls each probe, storing results on `section_result.probe_results`.
- Probe modules are imported at the bottom of `__init__.py` (after `register_probe` is defined) to trigger registration. Adding a new probe requires one import line here.

## Shared Judge Utility (`probes/_judge.py`)

- `call_judge(client, model, prompt, response_schema, temperature) -> T` -- Generic async helper that calls `beta.chat.completions.parse()` with any Pydantic response schema. Raises on failure; callers handle exceptions and produce error verdicts.

## Implemented Probes

The three implemented per-citation probes form a mutually exclusive, collectively exhaustive evaluation of how a citation is used. Each measures a distinct direction of evaluation:

| Probe | Direction | Question |
|---|---|---|
| Faithfulness | Anti-hallucination | Does the source say what the text claims? |
| Completeness | Anti-cherry-picking | Did the text capture the source's full message? |
| Sufficiency | Anti-overreaching | Does the source carry the burden of proof the claim requires? |

- **Citation Faithfulness** (`probes/faithfulness.py`) -- For each `[^N]` citation in a section, extracts the citing sentence (with all `[^N]` markers stripped to avoid confusing the judge), resolves the cited source chunk from evidence, and asks an LM judge: "does the source passage actually support the claim in this sentence?" Scores each citation as SUPPORTED (1.0), PARTIALLY_SUPPORTED (0.5), or NOT_SUPPORTED (0.0). This measures *precision/faithfulness* -- errors of commission (claiming something the source doesn't say), not errors of omission.

- **Citation Completeness** (`probes/completeness.py`) -- Evaluates the Representational Delta between a cited source passage and the text that cites it. Checks whether the citing text accurately and completely represents what the source actually says -- its full message, epistemic weight, and boundaries -- without actively misleading the reader. Catches missing hedges, scope erasure, statistical asymmetry, trade-off erasure, and proportionality skew. Scores each citation as COMPLETE (1.0), MINOR_OMISSION (0.7), SIGNIFICANT_OMISSION (0.3), or MISREPRESENTATION (0.0).

- **Citation Sufficiency** (`probes/sufficiency.py`) -- Evaluates the Evidentiary Delta between a cited source passage and the claim it is asked to support. A sentence can be perfectly faithful (no lies) and perfectly complete (no dropped caveats), yet still insufficient if the author uses a narrow, localized observation to assert a sweeping, universal, or hyper-causal conclusion. The judge evaluates against four specific failure mode archetypes:
  1. **Scope/Sample Extrapolation** -- Source details a narrow finding; claim projects universally.
  2. **Magnitude & Rhetorical Inflation** -- Source provides modest evidence; claim uses extreme adjectives.
  3. **Causal Escalation** -- Source establishes correlation/hypothesis; claim elevates to definitive causation.
  4. **Compound Claim Partiality** -- Sentence asserts A, B, and C; citation only supports A.

  The prompt injects the specific `[^N]` citation ID being evaluated so the judge knows its role in multi-citation sentences. The target citing sentence is isolated in its own block before the full section context to reduce cognitive load. The Contextual Adjacency Rule instructs the judge to assume sibling citations cover other parts of a compound claim unless it is blatantly obvious they do not -- the judge evaluates only whether its assigned source supports its portion of the claim. Uses a chain-of-thought judge schema (`claim_burden_analysis` -> `evidence_capacity_analysis` -> `evidentiary_gap_analysis` -> `unsupported_elements` -> `verdict`). Scores each citation as FULLY_SUFFICIENT (1.0), MINOR_OVERREACH (0.7), SIGNIFICANT_OVERREACH (0.3), or UNSUPPORTED_FIG_LEAF (0.0).

## Design Patterns for New Probes

New probes should follow these conventions:

- **Module location:** `probes/<probe_name>.py` with a public async function `run_<probe_name>_probe(section_result, section_evidence, context) -> ProbeResult`.
- **Registration:** Decorate the public function with `@register_probe` (imported from `probes`), then add `from probes import <module>` to `probes/__init__.py` to trigger registration at import time.
- **Judge response schema:** Each probe defines its own `_JudgeResponse(BaseModel)` with `Literal` verdict types and probe-specific fields. This model is passed to `call_judge()` as the `response_schema` for structured output parsing.
- **Verdict models:** Use `CitationVerdict` for per-citation probes, `SectionVerdict` for per-section probes. Add new `BaseVerdict` subclasses in `models.py` if neither fits.
- **Score derivation:** Define a `_VERDICT_SCORES` dict mapping verdict strings to floats. Derive `score` from the verdict on the caller side -- do not ask the LM to return a score.
- **Prompt templates:** Live in `probes/_prompts.py`. Strip any metadata (citation markers, section numbering) that could bias the judge.
- **Concurrency:** Run all judge calls for a section concurrently via `asyncio.gather()`.
- **Graceful degradation:** Never crash the pipeline. If a judge call fails, record verdict as `PARSE_ERROR` with score 0.0 and the exception message as rationale.
- **Aggregation:** Populate `ProbeResult.summary` with probe-specific metrics (e.g., `num_supported`, `num_citations_checked`). Use `ProbeResult.mean_score` for the overall section score.
- **Uses shared infra:** Call `call_judge()` from `probes/_judge.py` with `context.infra.openai_client`. Do not use the Agents SDK Runner.
