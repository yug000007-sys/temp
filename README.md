# Company Lead Cleaner Web App

A drag-and-drop Streamlit web app for cleaning company lead Excel/CSV files using your rules.

## What it does

- Upload an Excel/CSV file.
- Map raw columns such as company, address, city, state, ZIP/postal, country.
- Search Google Maps / Google Places first.
- Use optional SerpAPI Google Search fallback when Google Maps has no match.
- Export a cleaned Excel file with:
  - Company Name
  - Street address
  - City
  - State
  - Postal code
  - Country
  - Phone Number
  - Website
  - SIC Code
  - NAICS Code
  - Line of business
  - Number of employee at this location
  - Parent Company
  - Trade style
  - Google Maps Source
  - Other Source
  - Match Confidence
  - QC Notes

## Important limits

Google Places does not reliably provide SIC, NAICS, employee count, parent company, or trade style. The app leaves these blank and flags them unless you connect a separate enrichment provider/API later.

## Rules included

- Google Maps is the first source.
- Fallback search is used only if Google Maps does not return a confident match.
- `United States`, `US`, `U.S.` are normalized to `USA`.
- USA ZIP codes are formatted as exactly 5 digits.
- Input ZIP/postal code is preserved; Google postal conflicts are written to QC Notes instead of overwriting.
- USA and Canada states/provinces are abbreviated.
- USA and Canada phone numbers are formatted as `xxx-xxx-xxxx`.
- Addresses are title-cased and normalized.

## Setup

1. Install Python 3.10+.
2. Open this folder in Terminal / Command Prompt.
3. Create a virtual environment:

```bash
python -m venv .venv
```

4. Activate it:

Windows:
```bash
.venv\Scripts\activate
```

Mac/Linux:
```bash
source .venv/bin/activate
```

5. Install dependencies:

```bash
pip install -r requirements.txt
```

6. Copy `.env.example` to `.env` and add your keys:

```bash
GOOGLE_PLACES_API_KEY=your_google_places_api_key_here
SERPAPI_KEY=optional_serpapi_key_here
```

7. Run the app:

```bash
streamlit run streamlit_app.py
```

## Deployment

You can deploy this on Streamlit Community Cloud, Render, Railway, or an internal server. Add the same API keys as environment variables/secrets.

## Suggested next upgrade

For better completion of SIC, NAICS, employees, parent company, and trade style, connect a business-enrichment API such as Data Axle, People Data Labs, Clearbit-like company enrichment, or another licensed business database.
