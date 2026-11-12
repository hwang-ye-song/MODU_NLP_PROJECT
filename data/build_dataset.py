"""Build data/eval_en.jsonl, about 600 English samples (plan: docs/PROJECT.md).

Fields per line: id, source, label (1 = injection), position (start/middle/end or null), text

Injected (300): BIPIA email/table/code contexts x text/code attacks x 3 positions (synthesized) 150,
                LLMail-Inject data/raw_submissions_phase2.jsonl (deduplicated) 75,
                InjecAgent dh_base + ds_base Tool Responses 75
Benign (300):   BIPIA original contexts 100 (some paired with injected docs),
                LLMail emails_for_fp_tests.json 100,
                InjecAgent templates with benign text in the attack slot 50,
                NotInject English (2-3 trigger words, reported separately) 50
"""
