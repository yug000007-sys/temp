# Company Enrichment Tool

A no-paid-API Streamlit app to enrich company records from Excel and export a completed Excel file.

## Input columns
Your Excel file should contain these columns:

- Company
- City
- State
- Zip
- Country

Some fields can be blank. At minimum, provide Company and Country.

## Output fields
The app exports:

- Company
- Address
- City
- State
- Zip
- Country
- PhoneResearch
- Website
- SIC
- NAICS
- NoOfEmployees(This site only)
- LineOfBusiness
- ParentName
- Confidence
- SourceURL
- Remarks

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## How it works

The app uses public web search through DuckDuckGo search results and extracts likely website, address, phone, and business description from public pages. Because this is a no-API workflow, some websites may block scraping or provide incomplete data. The app marks weak matches as Medium or Low confidence instead of guessing.

## Best practice

For better results, include City, State, Zip, and Country whenever available.

Recommended batch size: 10 to 50 records at a time.

## Deploy on Streamlit Community Cloud

1. Upload this project to GitHub.
2. Go to Streamlit Community Cloud.
3. Choose this repository.
4. Set main file path as `app.py`.
5. Deploy.

