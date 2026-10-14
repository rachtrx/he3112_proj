"""OPTIONAL / NOT USED BY THE FINAL NOTEBOOK.

Pull accounting / financial statement data for a list of companies using yfinance.

Output: one Excel file per company in ./data/, with sheets for the
income statement, balance sheet, cash flow (annual + quarterly) and key info.

The final project uses SEC-derived financials instead. This file is retained
only as an optional Yahoo Finance comparison tool.
"""

from pathlib import Path

import pandas as pd
import yfinance as yf

# add more tickers here, e.g. "AAPL", "MSFT", "GOOGL"
TICKERS = ["META", "AMZN"]
ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "data"

# A few commonly used info fields (market data / valuation)
INFO_FIELDS = [
    "longName", "sector", "industry", "currency", "marketCap", "sharesOutstanding",
    "trailingPE", "forwardPE", "priceToBook", "beta", "dividendYield",
    "returnOnEquity", "returnOnAssets", "profitMargins", "debtToEquity",
]


def get_statements(ticker: str) -> dict[str, pd.DataFrame]:
    t = yf.Ticker(ticker)
    statements = {
        "income_annual": t.income_stmt,
        "income_quarterly": t.quarterly_income_stmt,
        "balance_annual": t.balance_sheet,
        "balance_quarterly": t.quarterly_balance_sheet,
        "cashflow_annual": t.cashflow,
        "cashflow_quarterly": t.quarterly_cashflow,
    }
    # Columns come back as timestamps (one per period) -> make them readable dates
    for name, df in statements.items():
        df.columns = [c.strftime("%Y-%m-%d") for c in df.columns]
        statements[name] = df

    info = t.info
    statements["info"] = pd.DataFrame(
        {"value": [info.get(f) for f in INFO_FIELDS]}, index=INFO_FIELDS
    )
    return statements


def key_ratios(s: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute a few standard ratios from the annual statements."""
    inc, bal, cf = s["income_annual"], s["balance_annual"], s["cashflow_annual"]

    def row(df, name):
        return df.loc[name] if name in df.index else pd.Series(index=df.columns, dtype=float)

    revenue = row(inc, "Total Revenue")
    net_income = row(inc, "Net Income")
    total_assets = row(bal, "Total Assets")
    equity = row(bal, "Stockholders Equity")
    total_debt = row(bal, "Total Debt")

    ratios = pd.DataFrame({
        "Revenue": revenue,
        "Gross Margin": row(inc, "Gross Profit") / revenue,
        "Operating Margin": row(inc, "Operating Income") / revenue,
        "Net Margin": net_income / revenue,
        "ROA": net_income / total_assets,
        "ROE": net_income / equity,
        "Debt / Equity": total_debt / equity,
        "Current Ratio": row(bal, "Current Assets") / row(bal, "Current Liabilities"),
        "Free Cash Flow": row(cf, "Free Cash Flow"),
        "Revenue Growth (YoY)": revenue.sort_index().pct_change(),
    }).T
    # Oldest -> newest, and drop years Yahoo returns with no data
    return ratios.reindex(sorted(ratios.columns), axis=1).dropna(axis=1, how="all")


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    for ticker in TICKERS:
        print(f"Pulling {ticker}...")
        s = get_statements(ticker)
        s["ratios"] = key_ratios(s)

        out = OUTPUT_DIR / f"{ticker}_financials.xlsx"
        with pd.ExcelWriter(out) as writer:
            for sheet, df in s.items():
                df.to_excel(writer, sheet_name=sheet)
        print(f"  saved -> {out}")
        with pd.option_context("display.float_format", "{:,.3f}".format):
            print(s["ratios"].to_string(), "\n")


if __name__ == "__main__":
    main()
