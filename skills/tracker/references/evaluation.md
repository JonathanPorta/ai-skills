# Evaluate tracker updates

For each of the next five real updates, record the following in that update's
run packet or tracker README. Use the project's workflow report for prompt counts
and missing handoffs; do not maintain a second prompt-status ledger.

| Check | Measurement |
|---|---|
| Evidence coverage | Number of changed status claims with dated, inspectable evidence / total changed status claims |
| Unsupported completion | Count of stages or gates advanced without corresponding evidence; target zero |
| Preserved independent stages | Changes limited to stages actually supported by evidence; list any regression |
| View consistency | Renderer check result plus review of narrative/state agreement |
| Handoff usefulness | Independent reader can identify current state, gaps and next action; pass/fail with reason |
| Review corrections | Count and nature of corrections required after executor submission |
| Repeated discovery | Count of questions already answered in accessible prior evidence |

Capture the first update as the baseline. After five, compare correction and
repeated-discovery counts, inspect any false completions and change the process
where it caused friction. Do not call the workflow effective merely because its
validator passes, or invent a time-saved estimate without timed observations.

Regression cases in `tests/test_tracker.py` cover configured locations and hub
sources, stale output detection, ownership, path containment and independent
stages. These are synthetic checks, not evidence that live project tracking is
accurate. Any visual review not performed must remain explicitly unverified.
