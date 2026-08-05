# Proportional verification

Use focused checks first, then expand according to changed contract, risk, and coupling. Do not require absent tools or a whole-project suite for every edit.

| Change | Minimum evidence |
| --- | --- |
| One-line local fix | Relevant focused test or check; inspect the diff |
| Public/API/data contract | Focused behavioural tests plus affected callers, docs, or migrations |
| Framework registration or import wiring | Import/startup or framework-specific check |
| Multi-version library change | Configured type/lint/test checks across the declared support evidence |
| Worker/process containment | Boundary outcome, observability, cleanup, and cancellation/termination behaviour |
| Performance change | Same-workload baseline/after comparison and semantic-equivalence check |

For new or changed tests, control time, randomness, network, and environment. Use bounded polling where eventual consistency is real. Always report checks run, skipped, or failed.
