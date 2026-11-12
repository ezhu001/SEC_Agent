"""Freeze identities from previously reviewed raw primary rows, independently of the app parser."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning


def local(tag):
    return tag.name.split(":")[-1].lower() if tag.name else ""


def reviewed_identities(raw, spec, reference):
    # SEC XHTML is examined as browser HTML to preserve the reviewed table positions.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(raw, "lxml")
    contexts, units = {}, {}
    def text(node, name):
        found = node.find(lambda tag: local(tag) == name)
        return found.get_text(strip=True) if found else None
    for node in soup.find_all(lambda tag: local(tag) == "context"):
        identifier = node.find(lambda tag: local(tag) == "identifier")
        contexts[node["id"]] = {"start": text(node, "startdate"), "end": text(node, "enddate") or text(node, "instant"),
            "instant": text(node, "instant") is not None,
            "entity_identifier": identifier.get_text(strip=True) if identifier else None,
            "entity_scheme": identifier.get("scheme") if identifier else None,
            "dimensions": {tag.get("dimension", "unknown"): tag.get_text(strip=True)
                for tag in node.find_all(lambda tag: local(tag) in {"explicitmember", "typedmember"})}}
    for unit in soup.find_all(lambda tag: local(tag) == "unit"):
        measures = unit.find_all(lambda tag: local(tag) == "measure")
        units[unit["id"]] = measures[0].get_text(strip=True).split(":")[-1] if len(measures) == 1 else None
    result = {}
    tables = soup.find_all("table")
    for component, (table_index, row_index) in reference["primary_rows"].items():
        table = tables[table_index]
        rows = [row for row in table.find_all("tr") if row.find_parent("table") is table]
        row = rows[row_index]
        found = {}
        for node in row.find_all(lambda tag: local(tag) == "nonfraction"):
            context = contexts[node["contextref"]]
            if context["end"] not in reference["ends"]:
                continue
            index = reference["ends"].index(context["end"])
            period = ["FY2025", "FY2024"][index]
            value = Decimal(node.get_text("", strip=True).replace(",", "").replace("$", ""))
            if node.get("sign") == "-":
                value = -abs(value)
            scale = int(node.get("scale", "0"))
            value *= Decimal(10) ** scale
            currency = units[node["unitref"]]
            if period in found or value != Decimal(str(reference[component][index])) * 1_000_000:
                raise ValueError(f"Primary reviewed amount missing or ambiguous: {spec['ticker']}/{component}/{period}")
            if currency != "USD" or context["dimensions"] or not context["entity_identifier"] or context["entity_identifier"].lstrip("0") != str(spec["cik"]).lstrip("0"):
                raise ValueError("Primary reviewed unit/entity/scope mismatch")
            found[period] = {**context, "period": period, "concept": node["name"], "context_id": node["contextref"],
                             "value": float(value), "scale": scale, "unit": "currency", "currency": currency}
        if set(found) != {"FY2025", "FY2024"}:
            raise ValueError("Both reviewed fiscal years are required")
        result[component] = found
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="artifacts/multi-company/corpus/manifest.json")
    parser.add_argument("--references", default="evaluation/cases/pilot_references.json")
    parser.add_argument("--output", default="evaluation/cases/scope_references_v2.json")
    args = parser.parse_args()
    corpus = json.loads(Path(args.corpus).read_text())
    references = json.loads(Path(args.references).read_text())
    for spec in corpus["filings"]:
        raw = Path(spec["local_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
            raise ValueError("Source hash changed")
        ref = references["references"][spec["ticker"]]
        ref["fact_identities"] = reviewed_identities(raw, spec, ref)
        ref["identity_source_sha256"] = spec["sha256"]
    references["scoring_version"] = "2"
    references["identity_review"] = "Raw inline facts at the previously SEC-reviewed primary table/row positions; amounts, fiscal ends, issuer, currency and dimensions checked independently of the runtime parser."
    with Path(args.output).open("x") as output:
        json.dump(references, output, indent=2)
    print("Frozen 48 reviewed fact identities; previous references unchanged:", args.output)


if __name__ == "__main__":
    main()
