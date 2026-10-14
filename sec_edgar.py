"""
Pull the 3 main financial statements (income statement, balance sheet, cash flow)
straight from SEC EDGAR 10-K filings using edgartools.

Output: data/<TICKER>_sec_statements.xlsx with one sheet per statement per 10-K,
e.g. income_FY2025, balance_FY2025, cashflow_FY2025, income_FY2024, ...
Data is the full raw statement as filed (all rows, incl. segment/dimension rows).

Also saves each full 10-K document to data/10k_docs/ as .htm. HTML is used
directly by depreciation_notes.py, so a browser/GUI is not required.
"""

from pathlib import Path

import pandas as pd
from edgar import Company, set_identity

# SEC requires you to identify yourself: "Your Name your.email@example.com"
set_identity("Your Name your.email@example.com")

TICKERS = ["META", "AMZN"]
NUM_10KS = 3  # each 10-K has 3 yrs of income/cash flow and 2 yrs of balance sheet
ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "data"
SAVE_10K_DOCS = True  # save full 10-K HTML locally for disclosure extraction
DOCS_FROM_YEAR = 2017  # save 10-K documents for this fiscal year onwards

def save_10k_document(filing, ticker: str, fy: str):
    """Save the SEC 10-K as HTML for local disclosure extraction."""
    docs_dir = OUTPUT_DIR / "10k_docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    html_path = docs_dir / f"{ticker}_10-K_{fy}.htm"
    if html_path.exists():
        print(f"    already have {html_path}")
        return

    # <base> makes relative image links (charts, logos) load from the SEC site
    base_url = filing.document.url.rsplit("/", 1)[0] + "/"
    html = filing.html().replace("<head>", f'<head><base href="{base_url}">', 1)
    html_path.write_text(html, encoding="utf-8")
    print(f"    saved -> {html_path}")


def save_10k_documents(ticker: str):
    for filing in Company(ticker).get_filings(form="10-K"):
        if filing.form != "10-K":  # skip amendments (10-K/A)
            continue
        year = int(filing.period_of_report[:4])
        if year < DOCS_FROM_YEAR:
            break  # filings are newest first
        print(f"  FY{year} 10-K filed {filing.filing_date}")
        save_10k_document(filing, ticker, f"FY{year}")


def pull_statements(ticker: str) -> dict[str, pd.DataFrame]:
    sheets = {}
    for filing in Company(ticker).get_filings(form="10-K").head(NUM_10KS):
        statements = filing.xbrl().statements
        fy = f"FY{filing.period_of_report[:4]}"
        print(f"  {fy} 10-K filed {filing.filing_date}")
        sheets[f"income_{fy}"] = statements.income_statement().to_dataframe()
        sheets[f"balance_{fy}"] = statements.balance_sheet().to_dataframe()
        sheets[f"cashflow_{fy}"] = statements.cash_flow_statement().to_dataframe()
    return sheets


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    for ticker in TICKERS:
        print(f"Pulling {ticker}...")
        if SAVE_10K_DOCS:
            save_10k_documents(ticker)
        sheets = pull_statements(ticker)
        out = OUTPUT_DIR / f"{ticker}_sec_statements.xlsx"
        with pd.ExcelWriter(out) as writer:
            for name, df in sheets.items():
                df.to_excel(writer, sheet_name=name, index=False)
        print(f"  saved -> {out}")


if __name__ == "__main__":
    main()
