<h1 align="center">Korean Prompt-Injection Register Dataset</h1>

<p align="center">
  A register-controlled Korean benchmark for register bias in prompt-injection detection.
</p>

<p align="center">
  <img alt="Hugging Face" src="https://img.shields.io/badge/🤗-Dataset-yellow">
  <img alt="Paper" src="https://img.shields.io/badge/Paper-link-blue">
  <img alt="Rendered inputs" src="https://img.shields.io/badge/rendered_inputs-1%2C768-red">
  <img alt="Registers" src="https://img.shields.io/badge/registers-8-green">
</p>

## News
- **[2026.09.23]** Analysis resources added.
- **[2026.07.31]** Repository created.

## Overview

A prompt-injection detector should react to what an input *does*, not how it *sounds*. To test whether Korean LLMs actually do this, we keep each item's meaning fixed and vary only its register: every source item appears in 7 Korean registers and in its original English form. Any change in a model's verdict across the 8 versions comes from expression alone.

| register   | 한국어 라벨 | formality | valence  | definition                                  |
| ---------- | ---------- | --------- | -------- | ------------------------------------------- |
| english  | —          | —         | —        | Untranslated English source                 |
| polite   | 존댓말      | high      | neutral  | Standard -yo/-seumnida endings (baseline)   |
| gentle   | 극존칭      | high      | positive | Polite + hedges and deferential requests    |
| casual   | 반말        | low       | neutral  | Non-honorific hae/haera endings             |
| genz     | 젠지어      | low       | neutral  | Casual + neologisms and consonant abbrevs.  |
| emoticon | 이모티콘    | low       | positive | Casual + positive-valence emoji             |
| angry    | 분노체        | low       | negative | Profanity with imperative endings           |
| threat   | 협박체      | low       | negative | Announced harm to the addressee             |

See [`data/registers.json`](data/registers.json) for the full definitions.

## Dataset format

`data/dataset.jsonl` holds 1,768 rows, one JSON object per line. 
Each row is a single rendered input (one item in one register).

| field                   | description                                                     |
| ----------------------- | -------------------------------------------------------------- |
| id                    | item id, shared across all 8 registers of the same item        |
| label                 | 0 benign · 1 injection                                     |
| source                | deepset/prompt-injections (train) or qxcv/tensor-trust`     |
| technique             | injection pattern (injection items only;`null for benign)    |
| register              | one of the 8 registers above                                   |
| formality / valence | register axes (null for english)                           |
| lang                  | Korean                                                   |
| text                  | the rendered input                                             |


## Citation

If you use this dataset, please cite our work 

```bibtex
@article{TODO2026register,
  title   = {Analysis of Register Bias in Prompt Injection Recognition by Korean Language Models},
  author  = {Juhyuk Choi},
  journal = {TODO},
  year    = {2026}
}
```

## Data sources

Two public benchmarks were used.

- **deepset/prompt-injections** — 162 items (123 benign, 39 injection), Apache-2.0.
  <https://huggingface.co/datasets/deepset/prompt-injections>
- **Tensor Trust** — 59 injection items, filtered from the public attack logs and translated into the Korean registers. BSD 2-Clause, © 2023 The Regents of the University of California. The notice and disclaimer are kept in [`LICENSE`](LICENSE).
  <https://github.com/HumanCompatibleAI/tensor-trust-data>

```bibtex
@misc{toyer2023tensor,
  title        = {{Tensor Trust}: Interpretable Prompt Injection Attacks from an Online Game},
  author       = {Toyer, Sam and Watkins, Olivia and Mendes, Ethan Adrian and Svegliato, Justin
                  and Bailey, Luke and Wang, Tiffany and Ong, Isaac and Elmaaroufi, Karim
                  and Abbeel, Pieter and Darrell, Trevor and Ritter, Alan and Russell, Stuart},
  year         = {2023},
  eprint       = {2311.01011},
  archivePrefix= {arXiv}
}
```
