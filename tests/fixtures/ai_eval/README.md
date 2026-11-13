# AI completion eval baseline

`baseline.json` is a run of `a2d eval-ai` (via `make eval-ai`) on the 13 Packt workflows in `a2d.advisor.ai_eval.DEFAULT_FIXTURES`, with `databricks-claude-opus-5-5` on 2026-11-13. It holds each step's outcome, check reason, time and tokens, but not the model's code.

Rerun before changing the model or the prompt, and compare:

```
make eval-ai MODEL=databricks-claude-opus-5-5 PROFILE=<your profile>
```

"Completed" means the reply passed the app's checks (valid Python, assigns what later steps read, no forbidden calls). It doesn't prove the code is right, so read a sample of the replies too. When a change is an improvement, replace `baseline.json` with the new report.
