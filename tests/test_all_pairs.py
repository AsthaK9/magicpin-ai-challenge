import sys
from pathlib import Path
# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import json
from bot import compose

def main():
    cat_dir = Path("expanded/categories")
    categories = {f.stem: json.load(open(f, encoding="utf-8")) for f in cat_dir.glob("*.json")}
    merchants = {f.stem: json.load(open(f, encoding="utf-8")) for f in Path("expanded/merchants").glob("*.json")}
    customers = {f.stem: json.load(open(f, encoding="utf-8")) for f in Path("expanded/customers").glob("*.json")}
    triggers = {f.stem: json.load(open(f, encoding="utf-8")) for f in Path("expanded/triggers").glob("*.json")}
    test_pairs = json.load(open("expanded/test_pairs.json", encoding="utf-8"))["pairs"]

    print(f"Total test pairs: {len(test_pairs)}")
    issues = 0
    results = []

    for pair in test_pairs:
        t = triggers[pair["trigger_id"]]
        m = merchants[pair["merchant_id"]]
        c = customers.get(pair["customer_id"]) if pair.get("customer_id") else None
        cat = categories.get(m["category_slug"])
        res = compose(cat, m, t, c)

        # Check required fields
        required_keys = ["body", "cta", "send_as", "suppression_key", "rationale"]
        for k in required_keys:
            if not res.get(k):
                print(f"FAILED {pair['test_id']}: missing {k}")
                issues += 1

        # Check no URL
        if "http://" in res["body"] or "https://" in res["body"] or "www." in res["body"]:
            print(f"FAILED {pair['test_id']}: URL in body! '{res['body']}'")
            issues += 1

        results.append({
            "test_id": pair["test_id"],
            "kind": t.get("kind"),
            "category": m.get("category_slug"),
            "body": res["body"],
            "cta": res["cta"],
            "send_as": res["send_as"],
            "suppression_key": res["suppression_key"],
            "rationale": res["rationale"],
        })

    print(f"Checked {len(results)} pairs, found {issues} issues.")

    for r in results:
        print(f"\n[{r['test_id']}] kind: {r['kind']} | cat: {r['category']} | send_as: {r['send_as']} | cta: {r['cta']}")
        print(f"Body: {r['body']}")
        print(f"Rationale: {r['rationale']}")

if __name__ == "__main__":
    main()
