from ..config.financial_concepts import CONCEPTS
from ..tools.numeric_parser import normalize


def lexical_signals(row, component):
    _, aliases, concepts = CONCEPTS[component]
    label = normalize(row.label)
    exact = label in {normalize(a) for a in aliases}
    tokens = set(label.split())
    overlap = max((len(tokens & set(normalize(a).split())) / max(len(tokens | set(normalize(a).split())), 1) for a in aliases), default=0)
    xbrl = any(f.concept and f.concept.split(":")[-1] in concepts for f in row.facts)
    if component == "gross_profit" and (not row.facts or any(f.unit != "currency" for f in row.facts)):
        # "Gross margin" can name either an amount or a rate. Its dimension
        # must agree before it counts as concept support anywhere in the app.
        exact, xbrl = False, False
    return float(overlap), exact, xbrl
