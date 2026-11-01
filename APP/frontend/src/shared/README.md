# `src/shared`

**Purpose.** Frontend-wide types and utilities.

**Belongs here**
- `types.ts` single import point for wire types
- `generated/` (machine-written from `contracts/`; never edit)
- `registry.ts`, `constants.ts`, `utils.ts`

**Never here**
- React
- Hand-written duplicates of generated types

**Depends on.** none.

**Public interface.** Types re-exported from `types.ts`.
