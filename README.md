# product-actions

Scheduled product reports for the Lascade product team: catchup, ad spend, install → paid, marketing
net, digests, chat summaries and others. The repository is public and every job's output and artifact
is sealed; see `CLAUDE.md` for the rules and `CONTEXT.md` for the vocabulary.

Shared pieces (the sealing toolkit and the Claude client in `scripts/ai/`) come from
[Lascade-Co/actions](https://github.com/Lascade-Co/actions). Run `scripts/fetch-ai.sh` before local
tests, then `pip install -r requirements.txt -r scripts/ai/requirements.txt pytest` and `python -m pytest -q`.
