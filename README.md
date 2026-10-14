# AI infrastructure depreciation — HE3112

This project studies how depreciation assumptions affect Meta and Amazon reported earnings. The final deliverable is [ai_server_depreciation.ipynb](ai_server_depreciation.ipynb).

The notebook has two parts:

1. A historical counterfactual applying standard accelerated depreciation schedules to estimated additions to Meta's server/network pool from 2021 to 2025. It compares changes in expense, earnings, margins and PP&E with actual annual revenue. Results depend on explicit assumptions; this is not a fitted economic depreciation curve or a restatement of Meta's accounts.
2. An analysis of actual useful-life revisions disclosed by Meta and Amazon, their reported earnings effects, and share-price movements around the announcements. The market study cannot isolate the depreciation news from the other news released at the same time.

## First-time setup and run

Complete every step below, in order. This is the required first-time workflow: the SEC filings, SEC financial data, depreciation workbook, and market prices must all be downloaded/prepared before the notebook is opened. Do not skip steps 3–5 or try to run the notebook first; it expects those local files to exist and does not download them.

### 1. Create the Python virtual environment

Use Python 3.11 if possible.

macOS/Linux:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Keep the virtual environment activated for the remaining steps.

### 2. Add your SEC contact details

The SEC asks automated clients to identify themselves. Before downloading anything from the SEC:

- In `sec_edgar.py`, replace the example identity in `set_identity("Your Name your.email@example.com")` with your own name and email.
- In `depreciation_notes.py`, replace the example `SEC_USER_AGENT` with the same identifying name and email.

### 3. Download the SEC source filings and statement exports

Run:

```bash
python sec_edgar.py
```

This required download creates Meta and Amazon 10-K HTML files in `data/10k_docs/` and the statement exports `data/META_sec_statements.xlsx` and `data/AMZN_sec_statements.xlsx`. The notebook's main financial input is built in the next step; the statement exports are retained for verification. This works on a headless server and does not need Chrome, a GUI, or PDF printing.

### 4. Download SEC company facts and build the depreciation data workbook

Run:

```bash
python depreciation_notes.py
```

This required step downloads SEC company-facts data and combines it with the filing files from step 3 to create `data/depreciation_analysis.xlsx`. The workbook contains:

- `numbers`: annual company financial measures;
- `notes`: depreciation-related filing sentences with local HTML filenames and SEC source links (HTML has no PDF page numbers);
- `notes_estimate_changes`: a filtered subset of those sentences;
- `server_disclosures`: server and PP&E details extracted from the local filing HTML.

### 5. Download the market-price source data

Run:

```bash
python market_data.py
```

This required download retrieves adjusted daily prices for META, AMZN and SPY into `data/final_analysis/adjusted_daily_prices.csv` and records the download details in `price_provenance.csv`.

### 6. Open and run the notebook

With the virtual environment still activated, run:

```bash
python -m jupyter lab ai_server_depreciation.ipynb
```

Because Jupyter was started from the activated virtual environment, use that environment for the notebook. If Jupyter shows a kernel selector, choose the kernel associated with `.venv`. Then choose **Run All**. Only do this after steps 3–5 have completed successfully. The notebook reads those local files and does not download source data while running.

## Data files: where they come from and how they are used

| File or script                               | Creates / contains                                                                             | Role                                                                     |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `sec_edgar.py`                             | Downloads SEC filings and creates raw `*_sec_statements.xlsx` files                          | Supplies local filings; statement exports can verify the cleaned figures |
| `depreciation_notes.py`                    | Creates `data/depreciation_analysis.xlsx` using SEC company facts and local filing documents | Main financial and disclosure data used by the notebook                  |
| `market_data.py`                           | Downloads Yahoo adjusted prices and writes the local price CSV and provenance CSV              | Market data used by the event study                                      |
| `analysis_support.py`                      | Calculates depreciation scenarios, earnings bridges and event-study results                    | Analysis functions imported by the notebook                              |
| `data/final_analysis/analysis_tables.xlsx` | Notebook-generated tables                                                                      | Calculated results and model inputs/outputs                              |
| `data/final_analysis/figures/`             | Notebook-generated PNG and SVG charts                                                          | Figures for the report or presentation                                   |

The overall path is:

```text
sec_edgar.py ──> local 10-K files ──┐
                                    ├──> depreciation_notes.py ──> depreciation_analysis.xlsx ──┐
SEC company-facts API ──────────────┘                                                            │
market_data.py ──> adjusted_daily_prices.csv ────────────────────────────────────────────────────┴──> notebook
```

The `*_sec_statements.xlsx` files are not used as the notebook's direct numeric input, but they are useful verification sources. SEC statement exports and company-facts values may differ because of XBRL tags, units, filing versions, periods or dimensional details. Check that you are comparing the same reported measure and period.

## Important interpretation notes

- Meta's $98.040bn 2025 server/network balance is **gross cost**. It is about 41.9% of Meta's $233.726bn gross PP&E, not a net PP&E percentage.
- Meta reports server-specific depreciation. The supplied Amazon filings do not provide the same server-specific depreciation series, so the notebook does not invent one by allocating total depreciation across asset categories.
- Gross PP&E divided by depreciation is not a disclosed server useful life.
- The earnings bridges reverse management's disclosed effects; they do not independently prove management's estimates are correct.
- The counterfactual curves are standard accounting schedules applied under stated assumptions. They are not estimated from GPU resale values or claims about the true economic decay curve.
- The market study has only three announcement events and cannot separate depreciation-related share-price changes from earnings, guidance, growth or AI-spending news.

The assignment permits a four-page report (excluding references and workings) and up to ten slides. Use the charts that make distinct points rather than including every notebook output.
