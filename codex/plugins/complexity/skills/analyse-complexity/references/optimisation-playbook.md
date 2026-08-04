# Optimisation Playbook

Use these patterns after validating behaviour and data shape. Complexity estimates are review claims, not facts from the scanner alone.

## Nested Lookup Loops

When each item in one collection scans another collection, consider building a dictionary, map, set, grouped index, or sorted representation once.

Check duplicate keys, first-match versus last-match behaviour, observable ordering, missing-record behaviour, key normalisation, and object identity.

## Membership Checks In Loops

When a loop repeatedly checks membership against a list or computed sequence, consider materialising a set before the loop.

Check hashability, equality semantics, normalisation, mutation after set creation, and whether list ordering was part of the behaviour.

## Sorting In Loops

When a loop repeatedly sorts the same or growing collection, consider sorting once, using a heap, binary insertion, or changing the algorithm to avoid repeated global ordering work.

Check whether intermediate sorted states are externally observed and whether the comparator depends on loop-local state.

## Pairwise Comparisons

For all-pairs checks, consider sort plus two pointers, sweep-line processing, interval trees, bucketing, or union-find depending on the domain.

Check boundary inclusivity, stable tie-breaking, duplicate intervals, and whether approximate bucketing is acceptable.

## N+1 I/O

For database, API, or filesystem calls in loops, consider bulk fetches, joins, preloading, batching, caching, or moving I/O outside the loop.

Preserve tenancy, permissions, filtering, sorting, pagination, retry behaviour, missing-record handling, and rate limits.

## Render-Path Work

For UI components, avoid repeated filter/map/sort/reduce work during render when collections are large or renders are frequent.

Prefer selectors, memoisation with complete dependencies, server-side derivation, stable props where measured, and virtualisation for long lists.

## Do Not Optimise Blindly

Do not add caches without invalidation, change public ordering casually, collapse distinct records with the same display label, replace clear cold-path code with obscure structures, or trade maintainability for unmeasured gains.
