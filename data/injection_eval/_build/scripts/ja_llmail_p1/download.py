"""Download only data/raw_submissions_phase1.jsonl (plus small metadata) of microsoft/llmail-inject-challenge.

Usage: python -X utf8 -I download.py <out_dir> [list]
"""
import sys
from huggingface_hub import HfApi, hf_hub_download

out = sys.argv[1]
REPO = "microsoft/llmail-inject-challenge"
api = HfApi()
info = api.dataset_info(REPO, files_metadata=True)
print("revision", info.sha)
for s in info.siblings:
    print(s.rfilename, s.size)
if len(sys.argv) > 2 and sys.argv[2] == "list":
    sys.exit()
for f in ["data/raw_submissions_phase1.jsonl", "data/levels_descriptions.json", "data/scenarios.json",
          "data/objectives_descriptions.json", "README.md"]:
    p = hf_hub_download(REPO, f, repo_type="dataset", revision=info.sha, local_dir=out)
    print("saved", p)
