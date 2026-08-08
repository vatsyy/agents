# Project and runtime resolution

Use this reference when Python support, Ruff discovery, monorepos, packaging, deployment, or framework wiring is relevant.

## Effective configuration

Resolve configuration for each changed subtree using the repository's actual command, working directory, explicit `--config` arguments, nested configuration files, and `extend` relationships. Ruff configuration is not implicitly merged across directories; the nearest applicable file and command invocation determine the effective settings.

Do not change configuration merely to make a change pass. If an existing rule conflicts with a real project contract, make the smallest documented, scoped configuration change and report it.

## Python support

- Libraries: `requires-python` is the packaging contract. CI demonstrates tested versions; classifiers and documentation corroborate it.
- Applications: deployment/runtime definitions and CI environments are credible consumers.
- Preserve every credible active consumer unless the task explicitly changes support.
- If credible sources materially conflict and cannot be satisfied safely, report the conflict and request direction.
- Ruff `target-version` describes parser/lint intent; it is not by itself the compatibility contract.

Required compatibility code for a declared support matrix is legitimate. Speculative shims for versions outside that matrix are not.

## Framework wiring

Avoid accidental import-time work, but preserve deliberate registration and wiring used by frameworks such as Django, Frappe, Celery, and plugin systems. Treat documented registration as part of the module contract.

## Framework discovery for audits

For a repository scan, identify a framework only from local evidence: package metadata, dependencies, imports, directory layout, entry points, registration modules, or project documentation. Read the framework-specific material only after that evidence exists.

Apply framework conventions only where the identified framework and repository make them relevant. Record the evidence alongside any framework-specific finding. If the project does not establish a framework, retain general Python guidance and state the uncertainty rather than guessing.
