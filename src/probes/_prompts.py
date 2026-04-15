"""LM-judge prompt templates for evaluation probes."""

CITATION_FAITHFULNESS_PROMPT = """You are a citation faithfulness auditor. Your job is to determine whether a cited source passage actually supports the claim made in a sentence from a research report. You are checking for errors of commission: does the sentence say something the source does not say, or contradict what the source says?

## Source passage being checked
Source: {source_file}, Section: "{source_heading}"

{source_chunk_text}

## Section context (target sentence marked)
The sentence under evaluation is wrapped in <mark> tags below. Read the surrounding sentences to understand what the sentence is claiming.

{marked_section_context}

## Evaluation instructions

**Step 1 — Analyze the source.** Read the source passage and identify the specific claims, facts, and positions it states or clearly implies.

**Step 2 — Identify the claim.** Read the marked sentence in its section context. Determine what factual claim the sentence is making that depends on this citation.

**Step 3 — Compare.** Does the source passage actually state or clearly imply the claim? Consider:
- Does the sentence attribute information to this source that the source does not contain?
- Does the sentence contradict what the source says?
- Does the sentence add specifics (numbers, dates, causal claims) that go beyond what the source states?
- Does the sentence generalize beyond what the source supports?

**Step 4 — Verdict.** Apply the rubric:

### SUPPORTED (score: 1.0)
The source passage directly states or clearly implies the information in the sentence. The claim is accurate and does not go beyond what the source says.

### PARTIALLY_SUPPORTED (score: 0.5)
The source passage contains related information, but the sentence overgeneralizes, adds minor specifics not in the source, or slightly mischaracterizes the source's position. The core idea is present but the details do not fully match.

### NOT_SUPPORTED (score: 0.0)
The source passage does not contain the information claimed by the sentence. The claim is fabricated, contradicts the source, attributes information to the wrong source, or makes claims the source does not make.

Quote the relevant source passage in your rationale if the claim is supported or partially supported.
"""

CITATION_COMPLETENESS_PROMPT = """You are a citation completeness auditor. Your task is to evaluate the Representational Delta between a cited source passage and the text that cites it. You are not checking whether the source supports the claim (that is a separate faithfulness check). You are checking whether the citing text accurately and completely represents what the source actually says — its full message, epistemic weight, and boundaries — without actively misleading the reader.

## Source passage being cited
Source: {source_file}, Section: "{source_heading}"

{source_chunk_text}

## Section context (target sentence marked)
The sentence under evaluation is wrapped in <mark> tags below. Read the surrounding sentences — they are part of the narrative context.

{marked_section_context}

## Evaluation instructions

**Step 1 — Analyze the source.** Carefully read the source passage and identify:
- Its key claims, findings, or positions
- Any epistemic markers: qualifications, hedges, uncertainty language ("may," "suggests," "preliminary," "is correlated with")
- Any scope or applicability conditions (specific contexts, populations, time periods, domains)
- Its overall framing, tone, and argumentative stance
- Any important trade-offs, exceptions, counterexamples, limitations, or absolute baselines mentioned

**Step 2 — Analyze alignment.** Compare the marked citing sentence (and its surrounding context) against the source analysis from Step 1. Check for any material distortion, including but not limited to these common patterns:

- **Epistemic flattening**: Source says "suggests" or "correlates with," report says "proves" or "causes"
- **Scope erasure**: Source limits claim to a specific domain/population/time, report drops those constraints
- **Statistical asymmetry**: Report cherry-picks relative numbers while omitting absolute baselines, or vice versa
- **Trade-off erasure**: Source presents both benefits and costs, report extracts only one side
- **Proportionality skew**: Report elevates a marginal caveat or edge case into the central thesis

These are illustrative exemplars, not an exhaustive checklist. Flag any material distortion of the source's message, even if it does not fit neatly into one of these categories.

**Contextual Adjacency Rule:** Before penalizing for an omission, check whether surrounding sentences in the section already address it. Only flag omissions that are genuinely absent from the local narrative context.

**Step 3 — List omissions.** For each material distortion or omission found, state it as a specific, actionable item (e.g., "Source limits finding to adults over 65; report drops age qualifier"). Empty list if the representation is complete.

**Step 4 — Verdict.** Apply the rubric:

### COMPLETE (score: 1.0)
The citing text (alongside its adjacent context) accurately represents the source's full message. No material nuance, hedge, condition, or context is missing. Framing aligns with the source's intent.

### MINOR_OMISSION (score: 0.7)
The citing text captures the core message but drops minor qualifications or secondary details. These omissions do not materially change the trajectory of the claim or how a reasonable reader would interpret its severity/probability.

### SIGNIFICANT_OMISSION (score: 0.3)
The citing text drops crucial nuance, applicability conditions, trade-offs, or absolute baselines. By flattening epistemic weight or erasing boundaries, the text materially distorts how a reader interprets the source.

### MISREPRESENTATION (score: 0.0)
The citing text actively weaponizes the source through severe cherry-picking, dropping qualifiers that reverse the meaning entirely, or framing a minor footnote as the central thesis.

The boundary between MINOR_OMISSION and SIGNIFICANT_OMISSION is strictly materiality: would a reasonable reader form a different understanding of the claim's severity, probability, or applicability?
"""

CITATION_SUFFICIENCY_PROMPT = """You are a citation sufficiency auditor. Your task is to evaluate the Evidentiary Delta between a cited source passage and the claim it is asked to support. You are not checking whether the source says what the text claims (that is a separate faithfulness check) or whether the text captures the source's full message (that is a separate completeness check). You are checking whether the source possesses the evidentiary weight to fully carry the burden of proof required by the claim.

A sentence can be perfectly faithful (no lies) and perfectly complete (no dropped caveats), yet still insufficient — using a narrow, localized observation to assert a sweeping, universal, or hyper-causal conclusion.

## Source passage being cited (Evaluating Marker [^{citation_id}])
Source: {source_file}, Section: "{source_heading}"

{source_chunk_text}

## Target citing sentence
{citing_sentence}

## Section context (target sentence marked)
The sentence above is wrapped in <mark> tags below within its surrounding section. Read the surrounding sentences — they are part of the narrative context.

{marked_section_context}

## Evaluation instructions

**Step 1 — Claim burden analysis.** Read the target citing sentence above in its section context. Identify:
- The exact scope of the claim (universal vs. limited, absolute vs. qualified)
- The magnitude and certainty of the language used (definitive vs. tentative)
- All distinct sub-assertions the sentence makes
- The overall rhetorical weight placed on this citation

**Step 2 — Evidence capacity analysis.** Read the source passage and identify:
- The actual scope of its findings (sample size, population, domain, time period)
- The strength of its conclusions (correlation vs. causation, preliminary vs. established)
- The specific facts and positions it can defensibly support
- Any explicit limitations or qualifications

**Step 3 — Evidentiary gap analysis.** Compare the claim burden (Step 1) against the evidence capacity (Step 2). Check for these specific failure modes:

- **Scope/Sample Extrapolation (Hasty Generalization):** The source details a localized or narrow finding. The claim projects this universally or to a broader population/domain than the source covers.
- **Magnitude & Rhetorical Inflation:** The source provides modest quantitative or qualitative evidence. The citing text uses heavily inflated rhetorical weight ("explosive," "unprecedented," "revolutionary") that the evidence does not warrant. The evidence points in the right direction but is insufficient to justify the extreme language.
- **Causal Escalation:** The source establishes a correlation, coexistence, hypothesis, or simulation ("may suggest," "is associated with"). The claim elevates this to a definitive causal law ("proves," "causes," "guarantees").
- **Compound Claim Partiality (Orphaned Sub-assertions):** The citing sentence makes multiple distinct factual assertions (A, B, and C). The appended citation only provides evidence for A, leaving B and C "orphaned" without evidentiary backing from this specific source.

These are the primary archetypes, but flag any evidentiary overreach even if it does not fit neatly into one of these categories.

**Contextual Adjacency Rule:** You are evaluating citation marker [^{citation_id}] only. If the sentence makes a compound claim (A and B) and contains multiple citation markers (e.g., [^1][^2]), do NOT penalize this source for only supporting one part if sibling citations are presumably there to cover the rest. Assume the sibling citations successfully cover the other parts of the compound claim unless it is blatantly obvious they do not. Evaluate your assigned source strictly on whether it supports its portion of the claim.

**Step 4 — List unsupported elements.** For each evidentiary gap found, state it as a specific, actionable item (e.g., "The word 'universally' is unsupported; the source only studied European markets" or "Source establishes correlation; claim uses 'causes'"). Empty list if the evidence fully carries the burden of proof.

**Step 5 — Verdict.** Apply the rubric:

### FULLY_SUFFICIENT (score: 1.0)
The scope, magnitude, and universality of the claim match the provided evidence. The citation completely shoulders the burden of proof required by all sub-assertions in the citing sentence. No evidentiary gap exists.

### MINOR_OVERREACH (score: 0.7)
The core of the claim is supported, but the citing text slightly stretches the evidence — using a marginally stronger adjective than warranted, or generalizing slightly beyond the strict bounds of the source. A reasonable reader would accept it, but an academic reviewer would ask for minor softening of the language.

### SIGNIFICANT_OVERREACH (score: 0.3)
The claim makes a major conceptual leap. It wildly extrapolates a local finding to a global trend, escalates correlation to causation, or leaves major parts of a compound claim completely unsupported by the cited source.

### UNSUPPORTED_FIG_LEAF (score: 0.0)
The citation is used as a technicality to bypass the requirement for evidence. The source might share keywords with the claim, but it is entirely anecdotal, tangentially related, or fails entirely to support the primary argumentative thrust of the sentence.

The boundary between MINOR_OVERREACH and SIGNIFICANT_OVERREACH is the magnitude of the conceptual leap: could the claim be fixed with minor language softening, or does it require fundamentally different evidence?
"""
