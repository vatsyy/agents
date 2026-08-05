# Typing and API boundaries

Use the current [Python typing specification](https://typing.python.org/en/latest/spec/) together with the project's configured type checker and policy.

- Add annotations to new or changed public boundaries and complex internals when they improve checking or understanding.
- Do not impose blanket annotations on dynamic, ORM, framework, or deliberately untyped code.
- Avoid indiscriminate `Any` and `type: ignore`; document genuine boundary cases and keep suppressions narrow.
- Use PEP 585 and PEP 604 syntax only when the resolved Python target supports it.
- Preserve public API and data contracts unless the task changes them in scope. When changing them, update callers, tests, documentation, and migrations as relevant.
- Avoid incidental wildcard imports. Controlled package re-exports with `__all__` are acceptable when they are part of the public contract.
