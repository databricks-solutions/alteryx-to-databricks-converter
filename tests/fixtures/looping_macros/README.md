# Batch and iterative macro fixtures

Real Alteryx workflows that call batch and iterative macros, with the macros next to them in the folder layout the workflows reference, so macro expansion finds them. They come from the same MIT-licensed Packt repositories as `tests/fixtures/packt` (see the LICENSE there):

| Folder | Source | What it shows |
|---|---|---|
| `advanced_ch1` | Advanced Alteryx, Chapter 1 | A batch macro with a group-by (each run gets the input rows for one control value), and an iterative macro that uses `[Engine.IterationNumber]` and a numeric question set on the call |
| `cookbook_ch1_r3` | Alteryx Designer Cookbook, ch1 recipe 3 | A batch macro whose control parameter is the file each run reads (an UpdateInput Action) |
| `cookbook_ch11_r3` | Alteryx Designer Cookbook, ch11 recipe 3 | An iterative macro that pages through an API, with a question value used as `[#1]` in a Formula |
| `engineering_ch10` | Data Engineering with Alteryx, Chapter 10 | A batch macro whose control value is written into a Filter expression |
