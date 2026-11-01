# DEVELOPMENT MANIFEST

> **SatQuery AI**
>
> **Version:** 1.0
>
> **Purpose:** Defines the engineering philosophy, development principles, and long-term practices used while building SatQuery. This document governs *how* the project evolves, how technical decisions are made, and how quality is preserved over time.

---

# 1. Philosophy

SatQuery is not built to win a hackathon.

It is not built to become a viral AI demo.

It is built to become an engineering-grade Earth Intelligence Platform.

Every line of code should move the platform closer to that objective.

Development should optimize for longevity rather than speed.

Temporary solutions are acceptable during experimentation, but permanent architecture should always favor clarity, modularity, and reliability.

---

# 2. The First Rule

> **Never confuse a working demo with a finished system.**

A prototype proves an idea.

An engineering system proves reliability.

SatQuery aims for the second.

---

# 3. The Builder's Mindset

While developing SatQuery, think like:

- a software architect before a programmer,
- a scientist before an AI enthusiast,
- a systems engineer before a framework user.

Technology choices are tools.

The architecture is the product.

---

# 4. Build Systems, Not Features

Features eventually become obsolete.

Systems continue to grow.

When solving a problem, ask:

> "Can this become a reusable capability instead of a one-time feature?"

Whenever possible:

Don't build:

- Flood Detector

Build:

- Change Detection Engine

Don't build:

- Forest Counter

Build:

- Vegetation Analysis Engine

Don't build:

- Rain Predictor

Build:

- Climate Analysis Framework

Systems create future features naturally.

---

# 5. Build Once, Reuse Everywhere

Every capability should be reusable.

Every module should have one purpose.

If code is copied twice,

it probably belongs somewhere else.

Duplication is technical debt.

---

# 6. Prefer Integration Over Reinvention

SatQuery should not attempt to outperform decades of open-source research.

Instead:

Study.

Understand.

Integrate.

Improve where necessary.

If a mature, well-tested solution already exists,

prefer building around it instead of replacing it.

Only reinvent when:

- integration is impossible,
- licensing prevents usage,
- scientific limitations require it,
- architecture demands it.

---

# 7. Modular Thinking

Every module should answer one question.

"What is my responsibility?"

If the answer contains the word "and",

the module is probably doing too much.

---

# 8. Every Abstraction Must Earn Its Place

Do not create abstractions for hypothetical future needs.

Create them only when:

- multiple implementations exist,
- clear separation improves maintainability,
- replacement is expected.

Abstraction should remove complexity,

not introduce it.

---

# 9. Data Before AI

Never ask an AI model to infer something that can be measured directly.

Use:

GIS

Satellite imagery

Weather

Spatial analysis

Databases

Statistics

before asking an LLM.

Language models interpret.

They should not replace observation.

---

# 10. Evidence Before Language

The reasoning pipeline should always follow:

Observation

↓

Evidence

↓

Reasoning

↓

Explanation

Never reverse this order.

---

# 11. Every Answer Must Be Traceable

Every analytical result should eventually answer:

Where did this come from?

Which datasets?

Which tools?

Which models?

Which reasoning?

Which confidence?

If the answer cannot be traced,

it should not be trusted.

---

# 12. Incremental Development

Large goals should be divided into stable milestones.

Each milestone should:

work,

be testable,

remain usable,

be independently valuable.

Never leave the project in a permanently broken state.

---

# 13. Testing Philosophy

Every important capability deserves evidence.

Testing should prove:

correctness,

stability,

reproducibility,

interface behavior,

failure handling.

Tests are part of the architecture,

not an afterthought.

---

# 14. Refactoring Philosophy

Refactor only when it increases clarity.

Never refactor simply because code looks old.

If refactoring introduces uncertainty,

delay it.

Correctness always outweighs elegance.

---

# 15. Repository Organization

The repository should reflect the architecture.

Folders should represent responsibilities,

not implementation details.

Someone opening the repository for the first time should understand the system within minutes.

Structure is communication.

---

# 16. Documentation Philosophy

If a future version of yourself cannot understand a module after six months,

the documentation has failed.

Document:

why,

not just what.

Code already explains "how."

Documentation should explain:

purpose,

responsibility,

trade-offs,

assumptions.

---

# 17. Performance Philosophy

Optimize only after measurement.

Never sacrifice readability for hypothetical speed.

Premature optimization creates permanent complexity.

When optimization becomes necessary,

measure,

profile,

improve,

verify.

---

# 18. AI Model Philosophy

Models are replaceable.

Capabilities are permanent.

Never tightly couple architecture to one model.

Every model should be viewed as an interchangeable implementation of a capability.

Today's best model will eventually be replaced.

The architecture should survive that replacement.

---

# 19. External Dependencies

Every dependency increases maintenance.

Before introducing one,

ask:

Does it solve a real problem?

Is it actively maintained?

Is it well understood?

Can it be replaced?

What happens if it disappears?

Dependencies are architectural decisions,

not conveniences.

---

# 20. Technical Debt

Technical debt is acceptable only when:

- explicitly acknowledged,
- documented,
- temporary.

Invisible technical debt becomes permanent debt.

---

# 21. Decision Framework

Before implementing anything,

answer these questions:

Why does this exist?

Does it align with the Constitution?

Does it strengthen the architecture?

Can it be reused?

Can it be tested?

Can it be explained?

Can it be replaced?

Will it still make sense one year from now?

If multiple answers are "No,"

reconsider the implementation.

---

# 22. Failure Philosophy

Expect failure.

Design for recovery.

A failed subsystem should degrade gracefully rather than collapse the entire platform.

Errors should teach.

Logs should explain.

Failures should be observable.

---

# 23. Continuous Learning

Every completed milestone should leave the project stronger than before.

Capture:

mistakes,

successful patterns,

architectural lessons,

performance discoveries,

unexpected behaviors.

Institutional knowledge is an asset.

Do not let it disappear.

---

# 24. Evolution Strategy

SatQuery should evolve by:

adding capabilities,

improving reasoning,

expanding datasets,

strengthening evidence,

increasing trust.

It should not evolve by accumulating unrelated features.

Depth is preferred over breadth.

---

# 25. Definition of Done

A feature is **not done** when it runs.

A feature is done when it is:

implemented,

tested,

documented,

understood,

integrated,

maintainable,

consistent with the Constitution,

consistent with the Architecture,

consistent with this Manifest.

---

# 26. The Final Rule

Every major engineering decision should pass one final test.

Ask:

> **If this project grows to one million lines of code, will this decision still make sense?**

If the answer is no,

it is probably the wrong decision.

Think beyond today's implementation.

Build for the platform SatQuery is becoming, not just the prototype it is today.

---

# Closing Statement

SatQuery is not a collection of models, APIs, or algorithms.

It is a long-term engineering effort to build a trustworthy system that helps people understand the Earth.

Code will change.

Models will improve.

Technologies will be replaced.

But disciplined engineering is what allows the platform to survive those changes.

Every commit should leave SatQuery more understandable, more reliable, and more aligned with its mission than it was before.

That is the standard by which development should be measured.