"""Frozen runtime concept definitions, independent of development gold labels."""
REVENUE_LABELS = {
    "reported_total": ["revenue", "revenues", "total revenue", "total revenues"],
    "net_sales": ["net sales", "total net sales"],
}


CONCEPTS = {
    "revenue": ("operations", [*REVENUE_LABELS["reported_total"], *REVENUE_LABELS["net_sales"]], ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]),
    "operating_income": ("operations", ["operating income", "income from operations"], ["OperatingIncomeLoss"]),
    "current_assets": ("balance", ["current assets", "total current assets"], ["AssetsCurrent"]),
    "current_liabilities": ("balance", ["current liabilities", "total current liabilities"], ["LiabilitiesCurrent"]),
    "gross_profit": ("operations", ["gross profit", "gross margin"], ["GrossProfit"]),
    "cost_of_sales": ("operations", ["total cost of sales", "cost of sales", "cost of revenue", "cost of goods sold"], ["CostOfRevenue", "CostOfGoodsAndServicesSold"]),
    "research_and_development": ("operations", ["research and development", "research and development expense"], ["ResearchAndDevelopmentExpense"]),
    "inventory": ("balance", ["inventories", "inventory"], ["InventoryNet"]),
    "accounts_receivable": ("balance", ["accounts receivable net", "accounts receivable", "receivables net"], ["AccountsReceivableNetCurrent"]),
}


def definition(component):
    statement, aliases, xbrl = CONCEPTS[component]
    result = {"canonical_concept": component, "allowed_reported_labels": aliases,
              "expected_statement": statement, "expected_value_dimension": "monetary amount, not percent or ratio",
              "supported_xbrl_concepts": xbrl}
    if component == "revenue":
        result["reported_label_bases"] = REVENUE_LABELS
        result["interpretation"] = (
            "Use the reported consolidated revenue total for registered revenue metrics. "
            "Net sales may represent the revenue line when no separate reported revenue total exists. "
            "When both are reported, Net sales is a different basis and must not replace the revenue total. "
            "Do not sum rows, select the largest amount, or mix revenue bases across years.")
    elif component == "gross_profit":
        result["interpretation"] = ("Gross profit is the monetary subtotal revenue minus cost of sales. "
            "Some financial statements label that AMOUNT 'Gross margin'. A monetary Gross margin row "
            "is an allowed source for gross_profit; a percentage Gross margin row is not. "
            "The gross margin RATE is calculated separately as gross_profit / revenue * 100 by Python.")
    else:
        result["interpretation"] = component.replace("_", " ") + " as a reported monetary amount"
    return result
