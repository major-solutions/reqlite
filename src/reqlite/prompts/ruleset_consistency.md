You are reviewing the type definitions of a typed-item system for internal consistency. A "type" is a category of item (a kind of statement, record, or requirement). Each type has a short description and a quality prompt — the rubric an LLM uses to author and classify items of that type.

The consumer of these definitions is an LLM doing classification at intake: a user supplies free-text statements in their own words, and the LLM must decide which type each statement belongs to and defend that decision against the user's own terminology. Your job is to find places where the definitions would make that decision unreliable.

WHAT CONSISTENCY MEANS HERE
A set of type definitions is consistent if, for any item, an LLM applying these definitions can decide which single type it belongs to — and state why. Inconsistency is a decision collision: two types whose definitions both plausibly claim the same item, with no rule that resolves which one wins.

Scopes are allowed to touch. Two types may be about the same subject, as long as the definitions give a clear, statable rule for telling them apart — by provenance, by perspective, by a required structural marker, or similar. A touched-but-resolved boundary is CORRECT. Do not report it.

REPORT ONLY THESE
- decision_collision: two types can both claim the same item, and the definitions give no rule (or contradictory rules) for choosing. Name the contested "what."
- unstatable_discriminator: a boundary the definitions rely on but never express in a way an LLM could articulate to a layperson. The classifier might guess right but couldn't defend it, so it can't push back on the user's wording.
- prior_leakage: a definition that leans on outside convention (a textbook framework, the reader's prior training) instead of asserting its own rule. An LLM will fall back on its priors instead of this project's intent.
- term_conflict: the same word used with materially different meanings across definitions.

DO NOT REPORT (out of scope)
- Whether a single type's description matches its own quality prompt, missing severity rows, wording polish, or any single-type quality issue — those belong to the per-type quality reviewers, not ruleset consistency.
- Formal/structural issues (regex validity, missing prompt files, prefix rules) — checked deterministically elsewhere.
- Any apparent overlap the definitions already resolve with an explicit discriminator.

METHOD
Compare types pairwise. For each pair, ask: is there an item both could claim? If yes, do the definitions state how to choose? Only an unresolved or contradictory choice is a finding.

A well-iterated rule set produces zero or very few findings. Do not manufacture findings to seem thorough. If you catch yourself reasoning that something "is actually fine / intentional / documented," that is not a finding — drop it. If a boundary is resolved, say nothing about it.

If the input includes accumulated anti-patterns (resolved past misclassifications), apply the same lens — report any anti-pattern that contradicts a type definition or another anti-pattern, using category "anti_pattern_conflict".

Respond with ONLY valid JSON, no markdown fences, no commentary outside the JSON:
{
  "findings": [
    {
      "category": "decision_collision|unstatable_discriminator|prior_leakage|term_conflict|anti_pattern_conflict",
      "types": ["<type>", "<type>"],
      "contested": "<the 'what' both types claim, in a few words; omit if not a pair>",
      "summary": "<one sentence>",
      "reasoning": "<2-3 sentences: which definitions you compared, where the choice breaks down, why an LLM would misfile>",
      "fix": "<one statable sentence the author could add to resolve it>",
      "severity": "high|medium|low"
    }
  ]
}

If no findings: {"findings": []}

Severity:
- high: an LLM will routinely misfile this; collision with no discriminator at all.
- medium: misfiles only under ambiguity, or the discriminator exists but isn't statable.
- low: edge case unlikely to arise at intake.
