# Company Enrichment Tool - No API

A Streamlit app for semi-automated company enrichment.

## How to deploy on Streamlit Cloud

1. Create a GitHub repository.
2. Upload these files to the repository root:
   - `app.py`
   - `requirements.txt`
   - `README.md`
3. Go to Streamlit Cloud.
4. Create a new app from your GitHub repo.
5. Main file path must be exactly:

```text
app.py
```

## Input columns

Your Excel/CSV should contain these columns:

```text
Company, City, State, Zip, Country
```

Missing columns are created automatically.

## Workflow

1. Upload Excel/CSV.
2. Copy the batch prompt into ChatGPT.
3. Research/enrich records.
4. Paste ChatGPT output back into the app.
5. Download enriched Excel.

## Output fields

```text
Company
Address
City
State
Zip
Country
PhoneResearch
Website
SIC
NAICS
NoOfEmployees(This site only)
LineOfBusiness
ParentName
Confidence
SourceURL
Remarks
```

## Troubleshooting

If Streamlit says "Oh no", open Streamlit Cloud app logs. The most common issues are:

- `app.py` is not in the repo root.
- Main file path is not set to `app.py`.
- Files are still inside a folder after ZIP upload.
- `requirements.txt` is missing.
