# Project workflow

A portable project-notes workflow for numbered prompts, execution packets,
independent review and gap tracking. It works alongside the tracker skill and
keeps prompt completion separate from project delivery.

Read [SKILL.md](SKILL.md) for the agent procedure, [the record contract](references/contract.md)
for adoption, and [evaluation](references/evaluation.md) for the next-five-runs
scorecard. The Python helper requires only Python 3.10 or newer and never invokes
agents, touches remote systems or publishes changes.

From the repository root, use `make check` for skill and behavioral validation.
For a project, `workflow.py --help` lists local initialization, allocation,
reconciliation, index regeneration and health-report commands.
