"""Build data/eval_en_100.jsonl (owner: first half).

Fields per line: id, source, label (1 = injection), position (start/middle/end or null), text

Injected (50): BIPIA email 12 + table 4 + code 4 (positions balanced),
               LLMail-Inject Phase2 15 (deduplicated), InjecAgent dh_base 8 + ds_base 7
Benign (50):   BIPIA original contexts 15 (10 paired with injected docs),
               LLMail emails_for_fp_tests.json 15, InjecAgent templates with benign text 10,
               NotInject English (2-3 trigger words) 10
"""
