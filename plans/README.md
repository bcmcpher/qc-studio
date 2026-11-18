# Plans

This directory holds planning documents for the evidence bundle and model feedback work
([#13](https://github.com/nipoppy/qc-studio/issues/13),
[#24](https://github.com/nipoppy/qc-studio/issues/24),
[#40](https://github.com/nipoppy/qc-studio/issues/40)). The layout copies
[OpenSpec](https://github.com/Fission-AI/OpenSpec). The OpenSpec CLI is not a project
dependency; the files are plain Markdown.

## Layout

```text
plans/
  specs/<capability>/spec.md     # current behaviour, after a change is archived
  changes/<change>/              # a proposed change
    proposal.md                  # why, what changes, capabilities, impact
    design.md                    # decisions, risks, open questions
    tasks.md                     # numbered task sections with checkboxes
    specs/<capability>/spec.md   # requirement deltas
  changes/archive/YYYY-MM-DD-<change>/
```

A **capability** is one unit of behaviour with its own spec. A **change** adds or modifies one
or more capabilities.

## Spec delta format

- Sections: `## ADDED Requirements`, `## MODIFIED Requirements`, `## REMOVED Requirements`.
- Each requirement is a `### Requirement: <name>` heading with a SHALL statement.
- Each requirement has one or more `#### Scenario: <name>` headings with `**WHEN**` and
  `**THEN**` bullets.

## Changes

Do the changes in this order. Each change has its own branch.

| Change | Capability | Depends on | Branch |
|--------|------------|------------|--------|
| `add-evidence-bundle-export` | `evidence-bundle` | — | `24-evidence-bundle-export` |
| `add-model-feedback` | `model-feedback` | `add-evidence-bundle-export` | `40-model-feedback` |
| `add-feedback-evaluation` | `feedback-evaluation` | `add-model-feedback` | `40-feedback-evaluation` |
| `add-qc-feedback-panel` | `qc-viewer-feedback` | `add-model-feedback` (schema) | `13-qc-feedback-panel` |

`add-feedback-evaluation` and `add-qc-feedback-panel` can run in parallel.

Each change branch starts from the branch of the change it depends on, so the pull requests
stack: `24-evidence-bundle-export` ← `40-model-feedback` ← `40-feedback-evaluation` and
`13-qc-feedback-panel`. After an upstream merge, rebase the next branch onto upstream `main`.

## Work on a change

1. Create the change branch.
2. Do one numbered section of `tasks.md`. Tick its boxes.
3. Commit the code and the ticks together. Stop for review.

## Archive a change

The OpenSpec CLI does this step automatically. Here, do it by hand on the change branch:

1. Merge each delta into `plans/specs/<capability>/spec.md`. Copy `ADDED` requirements, replace
   `MODIFIED` requirements, and delete `REMOVED` requirements.
2. Move the change with `git mv plans/changes/<change> plans/changes/archive/<YYYY-MM-DD>-<change>`.
3. Commit on the change branch. Do not merge it into the fork's `main`: the change reaches
   `main` through a pull request to `nipoppy/qc-studio`. The fork's `main` only mirrors
   upstream `main`.

## Validate

To check the format with the OpenSpec CLI, copy the files into a temporary `openspec/` tree:

```bash
tmp=$(mktemp -d)
mkdir -p "$tmp/openspec"
cp -r plans/changes plans/specs "$tmp/openspec/"
(cd "$tmp" && openspec validate --all --strict)
```
