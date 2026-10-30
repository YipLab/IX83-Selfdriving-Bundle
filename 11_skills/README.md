# 11_skills

Repo-local agent skills. Each skill is a directory holding a `SKILL.md` with YAML frontmatter (`name`, `description`) and, when the detail would crowd the body, a `references/` folder of supporting notes.

A skill is guidance for how to approach a class of task. It is not a recipe, a run record, or an authorization: per [AGENTS.md](../AGENTS.md), recipe (versioned executable workflow), skill (discovery/guidance) and run (resolved execution record) stay distinct, and named hardware work still needs the authorization its own record names.

| Skill | Use when |
| --- | --- |
| [headless-pipeline-rehearsal](headless-pipeline-rehearsal/SKILL.md) | Continuing the canonical Q01–Q12 implementation backlog, recorded-data/software work or authorized headless stationary-sample rehearsal, with manuscript outputs mapped to code owners and evidence gates. |

## Adding a skill

- Name the directory for the task class in kebab case, and match `name` in the frontmatter to it.
- Keep `description` to one sentence that states the trigger and the outcome; it is what the catalog shows.
- Put durable procedure in `SKILL.md`, and stage-specific or method-specific detail in `references/`.
- Link paths relatively, keep documentation claims separate from runtime and physical evidence, and do not let a skill assert an acceptance state that a record has not established.
