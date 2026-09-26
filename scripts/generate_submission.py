import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from bot import compose

def main():
    cat_dir = Path("expanded/categories")
    categories = {f.stem: json.load(open(f, encoding="utf-8")) for f in cat_dir.glob("*.json")}
    merchants = {f.stem: json.load(open(f, encoding="utf-8")) for f in Path("expanded/merchants").glob("*.json")}
    customers = {f.stem: json.load(open(f, encoding="utf-8")) for f in Path("expanded/customers").glob("*.json")}
    triggers = {f.stem: json.load(open(f, encoding="utf-8")) for f in Path("expanded/triggers").glob("*.json")}
    test_pairs = json.load(open("expanded/test_pairs.json", encoding="utf-8"))["pairs"]

    sub_file = Path("submission.jsonl")
    lines = []

    for pair in test_pairs:
        t = triggers[pair["trigger_id"]]
        m = merchants[pair["merchant_id"]]
        c = customers.get(pair["customer_id"]) if pair.get("customer_id") else None
        cat = categories.get(m["category_slug"])
        res = compose(cat, m, t, c)

        item = {
            "test_id": pair["test_id"],
            "body": res["body"],
            "cta": res["cta"],
            "send_as": res["send_as"],
            "suppression_key": res["suppression_key"],
            "rationale": res["rationale"],
        }
        lines.append(json.dumps(item, ensure_ascii=False))

    with open(sub_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Generated {len(lines)} lines in {sub_file}")

if __name__ == "__main__":
    main()
