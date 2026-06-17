# PLAN.md (commit this BEFORE reading CLARIFICATIONS.md or writing solution code)

> Delete the prompts below and replace with your own. Keep it tight.

## Architecture

A streaming, dependency-light pipeline using Python's native `csv` and `json` modules. We read `companies.csv` row by row, resolve each company against the mocked provider sources, merge what we find into a single record, score it, and stream the result into the output CSV — no need to hold the whole dataset in memory, and no external libraries to vet for a take-home slice.

For each row:
1. Look up the company across available mock sources using a multi-tier match: (1) exact name match, (2) normalized match (lowercased, legal suffixes like LLC/Inc/Co stripped), (3) substring/loose match as a last resort. This guards against the matching step silently failing just because of cosmetic name differences, which would otherwise produce false "not found" results.
2. Aggregate every field we find across sources into one candidate record, rather than picking a single "winning" source — different providers tend to be strong on different fields (e.g. one has a verified role, another has a verified email), so combining is more complete than choosing.
3. Score the record for confidence (see Quality below).
4. Emit one output row: `contact_name`, `contact_role`, `contact_email_or_phone`, `confidence_score`, `source`, `needs_human_review` — matching the schema in PROBLEM.md.

**Provenance below the `source` column:** a single `source` string isn't enough to make every value traceable, so internally each field on the merged record carries the provider(s) it came from (e.g. `registry[name,role]`, `enrichment[email]`). The output `source` column is a flattened, comma-separated rendering of that map. If the grading format expects something else, this internal structure can be re-rendered without touching the matching or scoring logic.

## Sources & strategy

We treat each mock provider as an independent, imperfect witness rather than a single source of truth. The strategy is corroboration over reliance on any one source: a single provider can be stale, wrong, or simply missing a field, but if two unrelated providers agree on the same name or contact detail, that agreement is a much stronger signal than either alone. This shapes both the merge step (combine fields across sources) and the confidence score (reward independent agreement).

We don't assume all providers are equally trustworthy for every field — e.g. a registry-style source is likely more authoritative for legal role/ownership, while a contact-enrichment source is likely more authoritative for live email/phone. The plan defaults to combining rather than ranking, but the matching matrix is the natural place to encode source-trust ordering if conflicts turn out to be common in the real mocks.

## Quality

**Confidence score (0–100), deterministic:**
- **Base score — source consensus:** 40 if the company resolves against only one provider; 75 if two or more independent providers agree on the company (regardless of whether they agree on every field). The jump is a heuristic, not a measured statistic: independent providers are unlikely to make the *same* mistake or go stale in the *same* way at the *same* time, so agreement across them is meaningfully stronger evidence than any single source on its own.
- **Completeness boost:** +15 if the merged record has both a usable email and a usable phone (multi-channel reachability is itself a signal of an active, real business); +5 if it has only one of the two.
- **Cap:** hard-capped at 100.
- **Review gate:** flagged `needs_human_review: true` if the final score is below 70, or if both email and phone are missing/null — in the latter case there's nothing to act on regardless of score, so it always goes to a human.

**Dedupe:** if multiple sources return the same field value, it's recorded once with multiple provenance tags rather than duplicated; if sources disagree on a field (e.g. two different names), the conflict itself is preserved in provenance rather than silently overwritten, so a human reviewer can see the discrepancy rather than trusting whichever value happened to be merged last.

**Cannot-verify:** a company that resolves against zero providers (even after fallback matching) is emitted with empty contact fields, `confidence_score: 0`, `source: none`, and `needs_human_review: true` — rather than omitted from the output. A logistics team chasing 1,000 unpaid accounts needs to know which accounts produced nothing, not just see them disappear from the report.

**False-positive risk:** the main risk is the fallback/substring matching step confusing two different companies with similar names (e.g. same name, different state). The matching tier order is exact → normalized → substring specifically so the loosest tier is a last resort, and any substring-tier match is itself a candidate for a lower confidence ceiling or a review flag — to be tuned once we see how aggressive the real mock data's near-duplicates are.

## Privacy / compliance

- No real scraping — operate only against the provided mocks (per PROBLEM.md), so the slice never touches a live person or company.
- Strict B2B boundary: do not collect or infer personal/non-professional social profiles for the decision-maker; only business-context identity and contact fields are in scope.
- Minimum viable data: store only the attributes needed for the payment-collection workflow (name, role, business email/phone) — no incidental personal data even if a mock source happened to expose it.
- If a contact channel appears to be a personal/residential one rather than a corporate one (e.g. a personal Gmail with no business association, a home address pattern), treat it as unverified for B2B outreach purposes and flag `needs_human_review` rather than including it confidently.

## Clarifying questions

1. **Question:** PROBLEM.md says the goal is to "drive payment" — should the target persona be the Finance/AP Manager (who actually moves money) or the Owner/Founder (who holds ultimate decision authority), when both are available for the same company?
   - Why it matters: this directly drives the priority/selection weighting when a company has multiple plausible contacts across sources.
   - Default assumption: prefer Owner/Founder for small businesses (likely the only real decision-maker in a small shop), but prefer an explicit AP/Finance contact when one is present, since they're closer to the actual payment action.
   - What changes if answered: the selection weighting inside the merge step — e.g. if AP/Finance should always win when present regardless of company size, that's a simpler, harder rule to encode than the size-dependent default above.

2. **Question:** When two sources disagree on a field for the same company (e.g. different contact names, or different phone numbers), should the pipeline pick a single winner automatically, or always surface the conflict for human review?
   - Why it matters: determines whether "confidence" needs to account for field-level disagreement specifically, separate from the source-count consensus score, and whether disagreement alone should be enough to force a review flag even at otherwise-high confidence.
   - Default assumption: surface the conflict in provenance and let the existing score/threshold logic decide review status, rather than adding a separate disagreement penalty — keeps the scoring model simpler for this slice.
   - What changes if answered: if disagreement should always force review, that becomes an explicit additional gate alongside the <70 and missing-channel rules.

3. **Question:** How loose should fallback name matching be allowed to get — is a substring/partial match across a single token acceptable, or should fallback matching require agreement on most/all significant tokens in the company name?
   - Why it matters: too loose risks merging two unrelated companies (false positive, the more dangerous failure mode per the brief); too strict risks missing real matches due to formatting differences and producing unnecessary "cannot-verify" results.
   - Default assumption: require agreement on all significant tokens after stripping legal suffixes (so "Cedar Ridge Plumbing LLC" matches "Cedar Ridge Plumbing" but not just "Cedar Ridge"), treating single-token substring matches as too risky to trust automatically.
   - What changes if answered: if looser single-token matching turns out to be acceptable, that loosens the tier-3 fallback and likely needs an extra confidence penalty to compensate for the higher false-positive risk.
