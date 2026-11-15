# Is the workflow helping?

Use two kinds of evidence. Static checks can detect broken bookkeeping. Real
handoffs establish whether another person or agent can continue the work with
less reconstruction and fewer false completion claims. Do not substitute a
perfect linter score for improved project execution.

## Baseline and first five reviewed attempts

Before adopting the workflow, select the last three comparable handoffs if their
records exist. Record observed values and sample size; mark missing information
unknown. Do not manufacture timing estimates from commit timestamps. Then record
the same measurements for the next five attempts that receive independent review.
Keep this scorecard in the destination project's notes, never in the public skill
with real project details.

| Measure | Definition | Initial target |
|---|---|---|
| Handoff time | Minutes for a fresh reader to identify current artifact, unresolved inputs and next action | Median at most 5 minutes and no worse than the observed baseline |
| False completion corrections | Review findings that a completed claim lacks the specified evidence or scope | Zero after correction; track initial findings rather than hiding them |
| Repeated discovery | Minutes spent reconstructing a fact already settled in the linked evidence | Lower than baseline; explain any necessary revalidation |
| Bookkeeping effort | Minutes maintaining ledger, index, packet and tracker for the attempt | Median at most 10 minutes, revisable if observed cost exceeds benefit |
| Lost dependencies | Open gaps without a usable owner and destination | Zero |
| Review coverage | Accepted latest attempts / all completed prompts | 100% |
| Reconciliation | Errors before publication and stale active records | Zero errors; every stale warning explained |

The helper reports four optional timing/correction measurements and structural
counts. It reports averages, sample counts and missing counts. Compute medians and
baseline comparisons in the scorecard, using the raw observed values. Review
coverage means independently checked artifacts, not merely populated JSON.

After five reviewed attempts, retain, simplify or revise the procedure based on
the measurements. If it takes longer without reducing reconstruction or errors,
remove redundant narrative fields or combine repetitive steps. Keep ordinal
identity, immutable executed instructions, evidence and independent acceptance.
Do not schedule a recurring automation unless the user asks for one.

## Local regression scenarios

The behavioral suite exercises initialization without overwrite, legacy and
pending-PR numbering, duplicate ordinals, path escapes, stale generated views,
invalid closure, missing evidence, changed executed instructions, changed reviewed
packets, supersession chains and gap ownership. These checks run within the
repository's existing `make check`; no additional CI service is required.

## Forward checks with a fresh reader

Use fictional projects and give only the task-local artifacts to a fresh agent:

1. Create the next prompt with a retired ordinal and another reserved in a pending
   PR. Confirm the assigned number and reviewable bounded criteria.
2. Review a packet whose files exist but whose output omits a required case.
   Confirm that semantic review asks for correction despite passing static checks.
3. Resume after a failed attempt and a correction. Confirm it identifies the
   latest attempt, preserves the previous review and does not silently close work.
4. Refresh a tracker after one bounded prompt completes while installation remains
   untested. Confirm only supported stage fields change and rendering stays stable.

Record the prompt, source revision, resulting diff and observed outcome. Report
any unrun scenarios as unrun. A reviewer's identity string or hash alone cannot
prove independence, correct evidence, approval authority or successful delivery.
