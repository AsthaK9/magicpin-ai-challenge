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

    out_file = Path("scratch_inspect.txt")
    with open(out_file, "w", encoding="utf-8") as out:
        for pair in test_pairs:
            t = triggers[pair["trigger_id"]]
            m = merchants[pair["merchant_id"]]
            c = customers.get(pair["customer_id"]) if pair.get("customer_id") else None
            cat = categories.get(m["category_slug"])
            res = compose(cat, m, t, c)
            out.write(f"=== {pair['test_id']}: {t['kind']} ({m['category_slug']}) ===\n")
            out.write(f"Send as: {res['send_as']} | CTA: {res['cta']}\n")
            out.write(f"Body: {res['body']}\n")
            out.write(f"Rationale: {res['rationale']}\n\n")

    print(f"Inspection written to {out_file}")

if __name__ == "__main__":
    main()
