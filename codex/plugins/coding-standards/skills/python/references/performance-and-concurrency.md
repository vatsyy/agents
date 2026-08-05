# Performance, concurrency, and resilience

Use this reference when the task changes a measured hotspot, concurrency, caching, retries, timeouts, or worker isolation.

## Performance

Choose algorithms and data structures before micro-optimising. Check for accidental O(n²) work, repeated parsing or I/O, needless copies, and avoidable allocations.

For performance work, establish a baseline and compare before/after on the same representative workload. Verify semantic equivalence and report the environment, metric, and measurement uncertainty. Routine changes need only avoid evident regressions.

Do not add a cache, JIT, alternative interpreter, or concurrency solely for speculative speed.

## Boundaries and cancellation

Retries, timeouts, degradation, and worker isolation are domain behaviour. Add them only when the project or explicit in-scope task contract requires them, with bounded limits and observable failure.

Catch `Exception` broadly only at a documented containment boundary, such as a process, job, request, worker, plugin callback, or batch-item boundary. Preserve cancellation and process-termination semantics; never catch `BaseException` except in explicit termination machinery.
