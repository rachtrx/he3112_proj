"""
Depreciation / useful-life source extraction for the HE3112 project.

Three extraction paths:
1. get_depreciation_notes(): scans the locally saved 10-K HTML files in data/10k_docs/
   (made by sec_edgar.py) and pulls out sentences about useful lives, depreciation methods
   and estimate changes. HTML source links are recorded; PDF page numbers are not available.
2. get_depreciation_numbers(): pulls the reported figures (D&A, PP&E, capex, net income)
   for each fiscal year from SEC XBRL data, plus an aggregate PP&E/expense ratio.
3. get_server_disclosures(): extracts server gross balances and Meta's server
   depreciation from local HTML notes. These are separate from the aggregate
   company-facts series and are written to the ``server_disclosures`` sheet.

Output: data/depreciation_analysis.xlsx (numbers, notes, notes_estimate_changes,
server_disclosures). Run sec_edgar.py first if the local filing documents are missing.
"""

import re
import warnings
from datetime import date
from pathlib import Path

import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# SEC requires you to identify yourself: "Your Name your.email@example.com"
SEC_USER_AGENT = "Your Name your.email@example.com"

COMPANIES = {"META": 1326801, "AMZN": 1018724}  # ticker -> SEC CIK
START_YEAR, END_YEAR = 2017, 2025
ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "data/10k_docs"
OUTPUT = ROOT / "data/depreciation_analysis.xlsx"

CHATGPT_RELEASE = date(2022, 11, 30)  # FY2022 and earlier = pre-ChatGPT

# --------------------------------------------------------------------------------------
# 1. Notes text from the 10-K HTML filings
# --------------------------------------------------------------------------------------

# A sentence is kept if it matches any of these (case-insensitive). Category = first match.
NOTE_PATTERNS = {
    "estimate_change": r"change in (?:the |an |our )?(?:accounting )?estimate|"
                       r"(?:increas|extend|lengthen|shorten|decreas|reduc|chang)\w* (?:the |our )?"
                       r"(?:estimate of the |estimated )?useful li(?:fe|ves)|"
                       r"useful li(?:fe|ves) (?:will )?chang|"
                       r"useful li(?:fe|ves) of (?:certain |a subset of |our )?(?:servers|network)",
    "useful_life": r"useful li(?:fe|ves)",
    "method": r"straight-line|accelerated (?:method|depreciation)|units[- ]of[- ]production|declining[- ]balance",
    "servers_ai": r"\bservers?\b|network (?:assets|equipment)|data cent(?:er|re)s?|"
                  r"technical infrastructure|technology infrastructure|\bGPUs?\b|artificial intelligence|\bAI\b",
    "depreciation_amount": r"depreciation (?:and amortization )?expense|depreciation (?:and amortization )?was",
}
# servers_ai / depreciation_amount sentences are only kept if they also mention depreciation/useful life
NEEDS_DEPRECIATION_CONTEXT = {"servers_ai", "depreciation_amount"}
DEPRECIATION_CONTEXT = r"depreciat|useful li(?:fe|ves)|amortiz"

YEARS_RE = re.compile(r"\b(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|ten)"
                      r"(?:\s*(?:to|-|–|and)\s*(\d+(?:\.\d+)?))?\s+years?\b", re.I)
MONEY_RE = re.compile(r"\$\s?[\d,]+(?:\.\d+)?\s*(?:billion|million)?", re.I)


def _sentences(page_text: str) -> list[str]:
    text = re.sub(r"\s+", " ", page_text)
    return [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z(])", text) if len(s.strip()) > 30]


def get_depreciation_notes(ticker: str, fiscal_year: int) -> pd.DataFrame:
    """Return depreciation-related sentences from a local HTML filing.

    SEC HTML filings have no stable printed-page pagination. The page column is
    retained for workbook compatibility but left blank; source_file/source_url
    identify the evidence instead.
    """
    html_path = DOCS_DIR / f"{ticker}_10-K_FY{fiscal_year}.htm"
    if not html_path.exists():
        print(f"  missing {html_path} (run sec_edgar.py)")
        return pd.DataFrame()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "lxml")
    base = soup.find("base", href=True)
    source_url = (base["href"].rstrip("/") + "/" + html_path.name) if base else ""
    text = (soup.body or soup).get_text(" ", strip=True)

    rows, seen = [], set()
    for sentence in _sentences(text):
        category = next((c for c, p in NOTE_PATTERNS.items() if re.search(p, sentence, re.I)), None)
        if category is None:
            continue
        if category in NEEDS_DEPRECIATION_CONTEXT and not re.search(DEPRECIATION_CONTEXT, sentence, re.I):
            continue
        if sentence in seen:  # 10-Ks repeat sentences (MD&A + notes)
            continue
        seen.add(sentence)
        rows.append({
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "page": pd.NA,
            "category": category,
            "years_mentioned": "; ".join(m.group(0) for m in YEARS_RE.finditer(sentence)),
            "amounts_mentioned": "; ".join(m.group(0).strip() for m in MONEY_RE.finditer(sentence)),
            "sentence": sentence,
            "source_file": html_path.name,
            "source_url": source_url,
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# 2. Numbers from SEC XBRL "company facts"
# --------------------------------------------------------------------------------------

# metric -> XBRL tags to try, in order (companies switch tags over the years)
METRICS = {
    "depreciation": ["Depreciation"],
    "dep_and_amortization": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"],
    "ppe_gross": ["PropertyPlantAndEquipmentGross",
                  "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetBeforeAccumulatedDepreciationAndAmortization"],
    "accumulated_depreciation": ["AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
                                 "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAccumulatedDepreciationAndAmortization"],
    "ppe_net": ["PropertyPlantAndEquipmentNet",
                "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
}


def _annual_values(facts: dict, tag: str) -> dict[int, float]:
    """Fiscal year -> value for one tag, using 10-K full-year (or year-end) figures, latest filing wins."""
    if tag not in facts:
        return {}
    out = {}
    for f in sorted(facts[tag]["units"].get("USD", []), key=lambda f: f["filed"]):
        if f.get("form") != "10-K":
            continue
        end = date.fromisoformat(f["end"])
        if "start" in f and not 350 <= (end - date.fromisoformat(f["start"])).days <= 380:
            continue  # skip quarterly durations
        out[end.year] = f["val"]
    return out


def get_depreciation_numbers(ticker: str, cik: int) -> pd.DataFrame:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    resp = requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=60)
    resp.raise_for_status()
    facts = resp.json()["facts"]["us-gaap"]

    df = pd.DataFrame(index=range(START_YEAR, END_YEAR + 1))
    df.index.name = "fiscal_year"
    for metric, tags in METRICS.items():
        series = pd.Series(dtype=float)
        for tag in tags:  # earlier tags take priority, later ones fill gaps
            series = series.combine_first(pd.Series(_annual_values(facts, tag), dtype=float))
        df[metric] = series

    # Derived measures
    # Aggregate proxy only: gross PP&E includes multiple asset classes, CIP and land.
    # It is not management's stated useful life for servers.
    df["gross_ppe_to_depreciation_ratio_yrs"] = df["ppe_gross"] / df["depreciation"]
    df["depreciation_pct_of_gross_ppe"] = df["depreciation"] / df["ppe_gross"]
    df["depreciation_pct_of_revenue"] = df["depreciation"] / df["revenue"]
    df["capex_to_depreciation"] = df["capex"] / df["depreciation"]
    df["period"] = ["pre-ChatGPT" if y <= CHATGPT_RELEASE.year else "post-ChatGPT" for y in df.index]
    df.insert(0, "ticker", ticker)
    return df.reset_index()


# --------------------------------------------------------------------------------------

def main():
    required_docs = [DOCS_DIR / f'{ticker}_10-K_FY{year}.htm'
                     for ticker in COMPANIES for year in range(START_YEAR, END_YEAR + 1)]
    missing = [path for path in required_docs if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f'Missing {len(missing)} local 10-K HTML filings. Run sec_edgar.py first; '
            f'first missing file: {missing[0]}')
    numbers, notes = [], []
    for ticker, cik in COMPANIES.items():
        print(f"{ticker}: numbers from SEC XBRL...")
        numbers.append(get_depreciation_numbers(ticker, cik))
        for year in range(START_YEAR, END_YEAR + 1):
            print(f"{ticker}: scanning FY{year} 10-K...")
            notes.append(get_depreciation_notes(ticker, year))

    numbers = pd.concat(numbers, ignore_index=True)
    notes = pd.concat(notes, ignore_index=True)
    with pd.ExcelWriter(OUTPUT) as writer:
        numbers.to_excel(writer, sheet_name="numbers", index=False)
        notes.to_excel(writer, sheet_name="notes", index=False)
        notes[notes["category"] == "estimate_change"].to_excel(
            writer, sheet_name="notes_estimate_changes", index=False)
        get_server_disclosures().to_excel(writer, sheet_name="server_disclosures", index=False)
    print(f"\nsaved -> {OUTPUT}  ({len(notes)} note sentences)")

    cols = ["ticker", "fiscal_year", "depreciation", "ppe_gross", "gross_ppe_to_depreciation_ratio_yrs", "period"]
    with pd.option_context("display.float_format", "{:,.2f}".format, "display.width", 200):
        print(numbers[cols].to_string(index=False))


def get_server_disclosures():
    """Build structured server-note data from local 10-K HTML files.

    This is a data-building step. The final notebook reads the resulting
    ``server_disclosures`` sheet and never parses HTML or calls the SEC.
    Category rows are gross historical cost, not net PP&E or server capex.
    """
    urls = {
        'META_2021': 'https://www.sec.gov/Archives/edgar/data/1326801/000132680122000018/fb-20211231.htm',
        'META_2022': 'https://www.sec.gov/Archives/edgar/data/1326801/000132680123000013/meta-20221231.htm',
        'META_2023': 'https://www.sec.gov/Archives/edgar/data/1326801/000132680124000012/meta-20231231.htm',
        'META_2024': 'https://www.sec.gov/Archives/edgar/data/1326801/000132680125000017/meta-20241231.htm',
        'META_2025': 'https://www.sec.gov/Archives/edgar/data/1326801/000162828026003942/meta-20251231.htm',
        'AMZN_2024': 'https://www.sec.gov/Archives/edgar/data/1018724/000101872425000004/amzn-20241231.htm',
        'AMZN_2025': 'https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm',
    }

    def compact(text):
        return re.sub(r'\s+', ' ', text).strip()

    def soup_for(ticker, year):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', XMLParsedAsHTMLWarning)
            return BeautifulSoup((DOCS_DIR / f'{ticker}_10-K_FY{year}.htm').read_text(), 'lxml')

    records = []
    for ticker in ['META', 'AMZN']:
        for fy in range(2021, 2026):
            soup = soup_for(ticker, fy)
            for table in soup.find_all('table'):
                text = compact(table.get_text(' ', strip=True))
                if not ('Servers and network' in text and 'Construction in progress' in text
                        and 'accumulated depreciation' in text.lower()):
                    continue
                years = list(dict.fromkeys(map(int, re.findall(r'\b20\d{2}\b', text))))[:2]
                assert len(years) == 2, (ticker, fy, text[:100])
                fields = {}
                for row in table.find_all('tr'):
                    cells = [compact(c.get_text(' ', strip=True))
                             for c in row.find_all(['td', 'th'], recursive=False)]
                    if not cells:
                        continue
                    label = cells[0]
                    values = [float(v.replace(',', '').replace('(', '').replace(')', '').strip()) / 1000
                              for v in cells[1:]
                              if re.fullmatch(r'\(?\s*\d[\d,]*(?:\.\d+)?\s*\)?', v)]
                    if len(values) != 2:
                        continue
                    if label.startswith('Servers and network'):
                        key = 'server_gross_bn'
                    elif label in ['Property and equipment, gross', 'Gross property and equipment']:
                        key = 'ppe_gross_bn'
                    elif label in ['Property and equipment, net', 'Total property and equipment, net']:
                        key = 'ppe_net_bn'
                    elif 'accumulated depreciation' in label.lower():
                        key = 'accumulated_dep_bn'
                    elif label == 'Construction in progress':
                        key = 'cip_bn'
                    else:
                        continue
                    fields[key] = dict(zip(years, values))
                for year in years:
                    rec = {'ticker': ticker, 'fiscal_year': year, 'filing_year': fy,
                           'balance_basis': 'gross historical cost',
                           'source_file': f'{ticker}_10-K_FY{fy}.htm',
                           'source_url': urls.get(f'{ticker}_{fy}', ''),
                           'source_section': 'Property and equipment note; category table'}
                    rec.update({k: v[year] for k, v in fields.items()})
                    assert np.isclose(rec['ppe_gross_bn'] - rec['accumulated_dep_bn'], rec['ppe_net_bn'])
                    records.append(rec)

    assets = (pd.DataFrame(records).sort_values('filing_year')
              .drop_duplicates(['ticker', 'fiscal_year'], keep='last'))
    expenses = []
    for fy in range(2021, 2026):
        text = compact(soup_for('META', fy).get_text(' ', strip=True))
        match = re.search(r'servers and network assets depreciation (?:expenses were|of) (.*?)respectively', text)
        assert match, fy
        amounts = re.findall(r'\$\s*([\d.]+)\s*billion', match.group(1))
        years = re.findall(r'\b20\d{2}\b', match.group(1))
        assert len(amounts) == len(years) == 3, (fy, match.group())
        for year, amount in zip(years, amounts):
            expenses.append({'ticker': 'META', 'fiscal_year': int(year),
                             'server_dep_bn': float(amount),
                             'dep_source_file': f'META_10-K_FY{fy}.htm',
                             'dep_filing_year': fy})
    expenses = (pd.DataFrame(expenses).sort_values('dep_filing_year')
                .drop_duplicates(['ticker', 'fiscal_year'], keep='last'))
    result = assets.merge(expenses, on=['ticker', 'fiscal_year'], how='left')
    result['server_share_gross_pct'] = result.server_gross_bn / result.ppe_gross_bn * 100
    return result.sort_values(['ticker', 'fiscal_year']).reset_index(drop=True)


if __name__ == "__main__":
    main()
