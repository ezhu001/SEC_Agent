import re
import time
from urllib.parse import urlparse
import requests


class SECClient:
    def __init__(self, settings):
        self.settings = settings
        self.session = requests.Session()
        self.last_request = 0.0

    def get(self, url, as_json=False):
        if not self.settings.sec_user_agent or "@" not in self.settings.sec_user_agent:
            raise ValueError("Configure FFA_SEC_USER_AGENT with an identifiable contact email")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {"www.sec.gov", "data.sec.gov"}:
            raise ValueError("Only HTTPS SEC sources are supported")
        for attempt in range(self.settings.transport_retries + 1):
            time.sleep(max(0, 0.2 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                response = self.session.get(url, headers={"User-Agent": self.settings.sec_user_agent}, timeout=60, allow_redirects=False)
                response.raise_for_status()
                if response.is_redirect:
                    raise ValueError("Unexpected SEC redirect")
                return response.json() if as_json else response.content
            except requests.RequestException:
                if attempt == self.settings.transport_retries:
                    raise
                time.sleep(0.5 * (attempt + 1))

    def resolve(self, identifier):
        accession = None
        parts = identifier.split("/")
        entity = parts[0]
        if len(parts) == 2:
            accession = parts[1]
        elif re.fullmatch(r"\d{10}-\d{2}-\d{6}", entity):
            accession, entity = entity, entity[:10]
        if entity.isdigit():
            cik = int(entity)
        else:
            tickers = self.get("https://www.sec.gov/files/company_tickers.json", True)
            matches = [v for v in tickers.values() if v["ticker"].lower() == entity.lower()]
            if len(matches) != 1:
                raise ValueError("Ticker not found uniquely")
            cik = matches[0]["cik_str"]
        submissions = self.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", True)
        recent = submissions["filings"]["recent"]
        blocks = [recent]
        if accession and accession not in recent["accessionNumber"]:
            blocks.extend(self.get("https://data.sec.gov/submissions/" + f["name"], True)
                          for f in submissions["filings"].get("files", []))
        for block in blocks:
            for i, acc in enumerate(block["accessionNumber"]):
                if (accession and acc == accession) or (not accession and block["form"][i] == "10-K"):
                    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{block['primaryDocument'][i]}"
                    return url, {"cik": cik, "entity": submissions["name"], "accession": acc,
                                 "form": block["form"][i], "selection": "explicit accession" if accession else "latest available 10-K"}
        raise ValueError("Requested filing not found")
