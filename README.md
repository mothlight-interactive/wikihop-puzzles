# WikiHop puzzles

Puzzle files for [WikiHop](https://mothlight.dev/games/wikihop), a daily link race through Wikipedia articles.
Everything here is **generated** by `wikihop_gen` (private repo `mothlight-interactive/wikihop`) on the dev machine
and merged through one pull request per run. Do not edit files by hand.

| Path | Contents |
| --- | --- |
| `v1/` | The static API the app loads, served by GitHub Pages (format 1, frozen; schema in `schemas/`) |
| `store/<lang>/pairs-NNNN.jsonl` | Every pair ever made, one per line, never deleted (`daily`, `free` or `retired`) |
| `store/<lang>/state.json` | First daily date and the next pool number |
| `reports/<lang>/<date>.md` | What each run did |
| `tools/validate.py`, `schemas/` | Checks run by the workflows (copied from the generator) |

Rules the checks enforce: published daily puzzles, solutions and pools never change once their date has come
(future daily puzzles of retired pairs may be replaced); daily numbers follow the dates; a pair is never in a random
pool before its daily date. Solutions are public on purpose; the app only loads them after a round ends.

Workflows: `validate.yml` (required check on pull requests), `deploy.yml` (publishes `v1/` to Pages on every push to
`main`), `watcher.yml` (opens an issue when fewer than a year of daily puzzles is left).

Article titles and revision IDs come from Wikipedia; see `LICENSE.md`.
