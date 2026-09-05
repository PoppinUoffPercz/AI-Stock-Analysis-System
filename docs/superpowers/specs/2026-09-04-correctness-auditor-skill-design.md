# Correctness Auditor Skill Design

**Date:** 2026-09-04  
**Status:** Approved in conversation  
**Scope:** Reusable Codex skill for evidence-first, repository-wide correctness auditing

## Goal

Create a Codex skill named `correctness-auditor` that audits an existing codebase
for real behavioral defects with the same high-signal intent as a strong automated
code-review bot. The skill prioritizes correctness, reproducibility, root cause,
and impact over style, refactoring preference, or lint volume.

The skill should find bugs that ordinary green test suites can miss, including
incorrect boundary behavior, broken invariants, mismatched contracts, wrong data
flow, unsafe state transitions, concurrency defects, error-handling failures,
and mathematically or semantically incorrect implementations.

## Non-goals

The skill does not make style, naming, formatting, architecture taste, or general
cleanup findings unless they directly cause incorrect behavior. It does not turn
lint output into audit findings without proving behavioral impact. Security-only
review, performance-only review, and over-engineering review remain separate
workflows unless they expose a correctness defect.

The default audit is read-only. The skill may create temporary probes, fixtures,
or throwaway harnesses needed to prove a finding, but it removes temporary
artifacts before finishing. It does not modify production code unless the user
explicitly asks for fixes after the audit.

## Structural Pattern

Use the methodology pattern. The audit proceeds through sequential evidence gates
so that suspicious code does not become a reported bug until the available
evidence justifies it.

The skill directory will contain:

```text
correctness-auditor/
|-- SKILL.md
|-- README.md
`-- references/
    |-- bug-hunting-checklist.md
    |-- semantic-probes.md
    |-- severity-and-confidence.md
    `-- language-specific-checks.md
```

`SKILL.md` stays focused on workflow, defaults, gates, and output structure.
Detailed bug patterns and probe techniques live in reference files.

## Step 1: Detect the Repository and Verification Surface

Detect the repository language, package/build system, test runner, type checker,
linter, formatter, Git availability, and any richer execution or analysis tools
available in the current runtime.

The skill adapts to what exists. Examples include Python with pytest/Ruff/mypy,
JavaScript or TypeScript with npm/pnpm and test frameworks, Rust with cargo,
Go with `go test`, and compiled projects with their native build systems.

If a preferred tool is unavailable, use the repository's native fallback or
direct source inspection. Missing optional tools must reduce coverage explicitly;
they must not silently abort the audit.

## Step 2: Build a Correctness Map

Inspect repository guidance, architecture documentation, tests, entry points,
public APIs, persistence boundaries, serialization paths, state machines,
numerical code, concurrency, filesystem/network boundaries, and recent changes
when relevant.

Identify areas where incorrect behavior would be material. Rank investigation
targets by blast radius and semantic risk rather than file size or lint count.

The correctness map should capture important invariants and contracts such as:

- valid input and output domains;
- state transition rules;
- ordering, idempotency, and lifecycle expectations;
- units, dimensions, time bases, and numerical assumptions;
- persistence and round-trip guarantees;
- caller/callee contracts and configuration boundaries;
- failure and unavailable-data semantics.

## Step 3: Establish a Baseline

Run the narrowest meaningful native verification commands already provided by
the repository, then broader checks when they are cheap enough to be useful.
Capture exact commands, exit status, failures, skips, and environmental limits.

Existing tests are evidence about current coverage, not proof that the software
is semantically correct. A green baseline allows the auditor to search for bugs
that the existing suite does not encode.

If the baseline fails for unrelated reasons, record that state and continue with
independent correctness investigation where possible.

## Step 4: Generate Candidate Defects

Hunt for candidate defects using source inspection and data-flow tracing. The
reference checklist should cover at least:

- off-by-one and boundary errors;
- empty, null, zero, negative, overflow, precision, and timezone cases;
- stale, partial, duplicate, reordered, or missing data;
- serialization and deserialization mismatches;
- incorrect defaults and ignored configuration;
- state leakage and lifecycle errors;
- inconsistent duplicated implementations;
- exception swallowing and misleading fallback values;
- concurrency, locking, race, retry, and idempotency errors;
- API and schema contract violations;
- incorrect mathematical/statistical units or formulas;
- cache invalidation and freshness errors;
- filesystem/path/platform assumptions;
- tests that assert implementation details while missing actual semantics.

Each candidate starts as a hypothesis, not a finding.

## Step 5: Prove or Reject Candidates with Semantic Probes

For suspicious behavior, create the smallest deterministic probe that exercises
the real contract. Prefer existing tests when they can express the behavior;
otherwise use a focused script, fixture, REPL invocation, differential check,
property test, or minimal harness.

Probe techniques include:

- adversarial and boundary-value inputs;
- direct invariant checks;
- round-trip tests;
- differential execution between equivalent paths;
- reference-formula comparison;
- old-versus-new behavior where history is relevant;
- metamorphic properties;
- deterministic concurrency/retry scenarios where feasible.

Discard candidates when the probe or source evidence contradicts the hypothesis.
Do not preserve weak suspicions simply to increase finding count.

## Step 6: Trace Confirmed Defects to Root Cause

For each surviving candidate, trace the incorrect value, state, or decision back
to the earliest code or contract error that explains the observed behavior.

Report the root cause rather than a downstream symptom. If the exact root cause
cannot be proven, downgrade confidence and state what remains unverified.

Before suggesting a fix, identify the smallest repair boundary that would correct
the behavior without unrelated refactoring.

## Step 7: Grade Severity and Confidence

Severity:

| Grade | Meaning |
|---|---|
| P0 | Catastrophic correctness failure, data loss/corruption, or similarly severe system impact |
| P1 | Materially wrong behavior under realistic use |
| P2 | Real bug under a narrower or edge-case condition |
| P3 | Low-impact correctness defect worth fixing |

Confidence:

| State | Requirement |
|---|---|
| Confirmed | Reproduced or directly proven with deterministic evidence |
| High confidence | Strong code-path or invariant proof where direct reproduction is impractical |
| Suspected | Plausible lead with unresolved evidence gap; report separately from confirmed findings |

Severity measures impact. Confidence measures strength of evidence. Do not use one
as a substitute for the other.

## Step 8: Report the Audit

Order confirmed findings by severity, then confidence and blast radius. Each
finding must include:

1. **Title and severity** — one concrete behavioral statement.
2. **Confidence** — confirmed or high confidence.
3. **Location** — exact file and narrow line/function reference.
4. **Observed behavior** — what the software actually does.
5. **Expected behavior** — the contract or invariant it violates.
6. **Evidence** — exact command, probe, trace, or source proof.
7. **Impact** — realistic consequence and affected scope.
8. **Root cause** — earliest proven cause.
9. **Suggested repair boundary** — minimal fix direction without implementing it.

Example shape:

```text
[P1] Drawdown calculation ignores the initial equity peak
Confidence: Confirmed
Location: path/to/file.py:123
Observed: returns [-0.5, 0.1] report a smaller drawdown than the equity path implies
Expected: initial wealth participates in peak-to-trough drawdown
Evidence: <exact deterministic probe>
Impact: understates risk for strategies that lose immediately
Root cause: cumulative equity begins after applying the first return
Suggested repair boundary: include initial wealth in the drawdown path
```

After confirmed findings, include a short `Suspected / needs more evidence`
section only when useful. Include the baseline commands and material coverage
limits so the user can judge the audit's reach.

If no confirmed defects survive verification, report that no confirmed
correctness findings were found and state what was actually tested. Never claim
the codebase is bug-free.

## Defaults

| Parameter | Default | Rationale |
|---|---|---|
| Scope | Entire current repository | Matches repo-audit intent |
| Mode | Read-only audit | Keeps audit separate from remediation |
| Finding threshold | High-confidence behavioral defect | Controls false positives |
| Baseline depth | Native focused checks, then broader checks when practical | Balances evidence and cost |
| Probe policy | Deterministic smallest useful reproduction | Maximizes signal |
| Severity ordering | P0 to P3 | Prioritizes impact |
| Suspected findings | Separate section | Prevents speculation from mixing with proven bugs |
| Temporary artifacts | Remove before completion | Leaves workspace clean |
| Fixes | Do not apply unless explicitly requested | Preserves audit boundary |

## Error Handling and Coverage Limits

When a command cannot run because of missing dependencies, credentials, platform
constraints, unavailable services, or broken unrelated setup, record the exact
limit and continue using independent evidence paths where possible.

Do not turn inability to reproduce into confirmation. Use `High confidence` only
when source/invariant evidence is strong enough to establish the defect without
execution. Otherwise leave the item in the suspected section or discard it.

## Quality Requirements

The completed skill should score at least 80/100 on the `skill-creator` quality
rubric before delivery. In particular it must have:

- exhaustive correctness-audit triggers;
- explicit defaults for every user-omittable parameter;
- runtime detection and fallback paths;
- numbered methodology steps with evidence gates;
- a lean SKILL.md with detailed references;
- deterministic output structure;
- graceful handling of partial verification;
- strong separation between confirmed findings and speculation.

## Validation Strategy

Validate the skill itself against representative repositories or fixtures with
known defects. At minimum, evaluation should demonstrate that it can:

- find a semantic bug missed by a green unit suite;
- reject at least one plausible false positive after probing;
- distinguish severity from confidence;
- avoid reporting pure style/lint issues as correctness defects;
- produce reproducible evidence for a confirmed finding;
- finish cleanly when no confirmed defects are found.

The evaluation does not need to prove exhaustive bug detection. It should prove
that the workflow produces fewer, stronger, more actionable findings than a
static suspicion-only review.
