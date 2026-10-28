# Licensing and publication review

Review date: October 28, 2026. This is an inventory and a list of remaining checks,
not a legal opinion or a certification that every possible distribution complies.
The existing [MIT project license](../LICENSE) is unchanged. No new project license
has been selected. Its scope does not replace third-party software or model terms.

## Source and dependencies

The repository contains original application source, templates, styles, JavaScript,
synthetic fixtures and a fictional seed manifest. No vendored dependency tree,
third-party images/fonts, model weights or installation database was found in the
publication audit. Public resource titles/URLs provide attribution and context;
linked publisher content is not bundled, and the publishers do not endorse this
project. Do not copy their articles or logos into the repository without review.

The following is a direct-dependency inventory based on upstream license files
checked on the review date. Links to mutable upstream branches are evidence, not
pins for every version allowed by requirements.txt:

| Component | Upstream license evidence | Review note |
|---|---|---|
| FastAPI | [MIT](https://github.com/fastapi/fastapi/blob/master/LICENSE) | Preserve applicable copyright/license notices. |
| Uvicorn | [BSD-3-Clause](https://github.com/Kludex/uvicorn/blob/main/LICENSE.md) | Includes dependencies from the `standard` extra. |
| Jinja2 | [BSD-3-Clause](https://github.com/pallets/jinja/blob/main/LICENSE.txt) | Includes its own dependency notices. |
| ItsDangerous | [BSD-3-Clause](https://github.com/pallets/itsdangerous/blob/main/LICENSE.txt) | Project MIT does not replace this license. |
| python-multipart | [Apache-2.0](https://github.com/Kludex/python-multipart/blob/main/LICENSE.txt) | Check the exact installed version and any required notices. |
| HTTPX | [BSD-3-Clause](https://github.com/encode/httpx/blob/master/LICENSE.md) | Review transitive transport/runtime dependencies too. |
| pytest | [MIT](https://github.com/pytest-dev/pytest/blob/main/LICENSE) | Test tooling; currently also installed by the Dockerfile. |

MIT/BSD notices and Apache license/NOTICE requirements need to be handled as
applicable to the material actually redistributed. This table is **not** a bundled
third-party notice file. Before publishing a container image or dependency bundle,
record exact package versions, inspect their distributed license/NOTICE files,
retain the required texts and review modifications. Include Python, Debian/tzdata,
OS packages and all transitive dependencies/extras in that inventory. requirements.txt
uses ranges and `python:3.12-slim` is a mutable tag, so there is no exact reproducible
lockfile or completed image SBOM/notice bundle yet. Do not claim otherwise.

## Optional inference software and model

[Ollama's own license](https://github.com/ollama/ollama/blob/main/LICENSE) is MIT.
That does not determine the license of models served through it or every bundled
runtime component. The default model identifier is `qwen3:8b`. The upstream
[Qwen3-8B model license](https://huggingface.co/Qwen/Qwen3-8B/blob/main/LICENSE) is
Apache-2.0 at the reviewed URL. No model weights are distributed by this repository.

Before using or redistributing a downloaded model, the operator must verify the
actual artifact, version/digest, origin, quantization/conversion and its accompanying
license/NOTICE material. The upstream model page alone does not establish provenance
or all terms for an arbitrary artifact exposed under a local model tag. A model
change requires a fresh terms and request-option review. Rights to training data,
output reuse, suitability and governance for a specific deployment are not resolved
by this inventory. Review generated output before publication; it is not guaranteed
to be accurate, original or representative of community views.

## Intentional contact data and human review

The demonstration host name, phone and email in `.env.example`, application defaults,
Compose examples, README and tests were explicitly requested by the owner for
standby/demo inquiries. They are intentional public-contact defaults, not passwords
or service credentials. No production credentials are needed by the reviewer guide.

Before changing repository visibility, the human owner should reconfirm that these
contact channels should remain publicly searchable in source/history and that all
contributed material may be released under the existing MIT license. If consent
changes, review the historical contact-data copies as well as current files;
editing the latest README alone would not remove them from history. No history
rewrite is authorized or performed by this remediation.

The local `backup/pre-github-email-fix` branch contains older personal commit-email
metadata and must remain unpublished. The audit found only `main` advertised by
origin, with noreply identities on its reachable commits. Do not push backup
branches, tags or mirror refs. No new main-history rewrite was indicated by the
credential scan; it was not a guarantee against every possible unknown secret.

Outstanding human checks before a visibility change are contact/ownership consent,
final secret/provenance review, and confirming that the intended artifact is source
only. Image/model redistribution needs the additional artifact-specific checks
above. Repository publication and public service deployment are distinct decisions;
service security work remains in [operator notes](OPERATIONS.md). Keep the repository
private until visibility is explicitly approved as a separate action.
