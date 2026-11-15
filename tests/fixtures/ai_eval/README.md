# AI completion eval baseline

`baseline.json` is a run of `a2d eval-ai` (via `make eval-ai`) on the 13 Packt workflows in `a2d.advisor.ai_eval.DEFAULT_FIXTURES`, with `databricks-claude-opus-5-5` on 2026-11-14. It holds each step's outcome, check reason, how many model calls it took (2 when the first reply failed the checks and was retried), the shared helper it calls if any, time and tokens, and each shared helper's outcome, but not the model's code. Its median and 90th-percentile step times are also `TYPICAL_STEP_SECONDS` in `a2d.advisor.completion`, which the AI screen uses for its time estimate: update both together.

Rerun before changing the model or the prompt, and compare:

```
make eval-ai MODEL=databricks-claude-opus-5-5 PROFILE=<your profile>
```

"Completed" means the reply passed the app's checks (valid Python, assigns what later steps read, no forbidden calls). It doesn't prove the code is right, so read a sample of the replies too. When a change is an improvement, replace `baseline.json` with the new report.
