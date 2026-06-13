import os
import re
import time
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from rapidfuzz import fuzz

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

US_STATES = {
    "ALABAMA":"AL","ALASKA":"AK","ARIZONA":"AZ","ARKANSAS":"AR","CALIFORNIA":"CA","COLORADO":"CO","CONNECTICUT":"CT","DELAWARE":"DE","FLORIDA":"FL","GEORGIA":"GA","HAWAII":"HI","IDAHO":"ID","ILLINOIS":"IL","INDIANA":"IN","IOWA":"IA","KANSAS":"KS","KENTUCKY":"KY","LOUISIANA":"LA","MAINE":"ME","MARYLAND":"MD","MASSACHUSETTS":"MA","MICHIGAN":"MI","MINNESOTA":"MN","MISSISSIPPI":"MS","MISSOURI":"MO","MONTANA":"MT","NEBRASKA":"NE","NEVADA":"NV","NEW HAMPSHIRE":"NH","NEW JERSEY":"NJ","NEW MEXICO":"NM","NEW YORK":"NY","NORTH CAROLINA":"NC","NORTH DAKOTA":"ND","OHIO":"OH","OKLAHOMA":"OK","OREGON":"OR","PENNSYLVANIA":"PA","RHODE ISLAND":"RI","SOUTH CAROLINA":"SC","SOUTH DAKOTA":"SD","TENNESSEE":"TN","TEXAS":"TX","UTAH":"UT","VERMONT":"VT","VIRGINIA":"VA","WASHINGTON":"WA","WEST VIRGINIA":"WV","WISCONSIN":"WI","WYOMING":"WY","DISTRICT OF COLUMBIA":"DC"
}
CANADA_PROVINCES = {
    "ALBERTA":"AB","BRITISH COLUMBIA":"BC","MANITOBA":"MB","NEW BRUNSWICK":"NB","NEWFOUNDLAND AND LABRADOR":"NL","NORTHWEST TERRITORIES":"NT","NOVA SCOTIA":"NS","NUNAVUT":"NU","ONTARIO":"ON","PRINCE EDWARD ISLAND":"PE","QUEBEC":"QC","SASKATCHEWAN":"SK","YUKON":"YT"
}
ALL_REGION_MAP = {**US_STATES, **CANADA_PROVINCES}
US_STATE_ABBRS = set(US_STATES.values())
CA_PROV_ABBRS = set(CANADA_PROVINCES.values())

OUTPUT_COLUMNS = [
    "Company Name", "Street address", "City", "State", "Postal code", "Country",
    "Phone Number", "Website", "SIC Code", "NAICS Code", "Line of business",
    "Number of employee at this location", "Parent Company", "Trade style",
    "Google Maps Source", "Other Source", "Match Confidence", "QC Notes"
]


def nonempty(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_country(value: str) -> str:
    v = nonempty(value).upper().replace(".", "")
    if v in {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}:
        return "USA"
    if v in {"CA", "CAN", "CANADA"}:
        return "Canada"
    return nonempty(value).title()


def normalize_state(value: str, country: str = "") -> str:
    v = nonempty(value).upper().replace(".", "")
    if not v:
        return ""
    if v in US_STATE_ABBRS or v in CA_PROV_ABBRS:
        return v
    return ALL_REGION_MAP.get(v, v[:2] if country in {"USA", "Canada"} and len(v) > 2 else v)


def normalize_postal(value: str, country: str = "") -> str:
    raw = nonempty(value)
    if not raw:
        return ""
    if "E+" in raw.upper():
        try:
            raw = str(int(float(raw)))
        except Exception:
            pass
    if country == "USA":
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 5:
            return digits[:5]
        return digits.zfill(5) if digits else ""
    if country == "Canada":
        alnum = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
        return alnum[:6]
    return raw


def normalize_phone(value: str, country: str = "") -> str:
    raw = nonempty(value)
    if not raw:
        return ""
    # Remove extensions from main field.
    raw = re.split(r"(?:ext\.?|x)\s*\d+", raw, flags=re.I)[0]
    digits = re.sub(r"\D", "", raw)
    if country in {"USA", "Canada"}:
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return raw


def title_address(value: str) -> str:
    s = nonempty(value)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    return s.title()


def build_query(row: pd.Series, mapping: Dict[str, str]) -> str:
    parts = []
    for key in ["company", "address", "city", "state", "postal", "country"]:
        col = mapping.get(key)
        if col and col != "-- None --":
            parts.append(nonempty(row.get(col, "")))
    return " ".join([p for p in parts if p])


def google_text_search(query: str) -> Optional[Dict]:
    if not GOOGLE_API_KEY or not query:
        return None
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {"query": query, "key": GOOGLE_API_KEY}
    r = requests.get(url, params=params, timeout=20)
    data = r.json()
    if data.get("status") not in {"OK", "ZERO_RESULTS"}:
        return {"error": data.get("status", "UNKNOWN"), "message": data.get("error_message", "")}
    results = data.get("results", [])
    return results[0] if results else None


def google_place_details(place_id: str) -> Optional[Dict]:
    if not GOOGLE_API_KEY or not place_id:
        return None
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    fields = "name,formatted_address,address_component,formatted_phone_number,international_phone_number,website,url,business_status,types"
    params = {"place_id": place_id, "fields": fields, "key": GOOGLE_API_KEY}
    r = requests.get(url, params=params, timeout=20)
    data = r.json()
    if data.get("status") != "OK":
        return None
    return data.get("result", {})


def parse_address_components(components: List[Dict]) -> Dict[str, str]:
    out = {"street_number": "", "route": "", "city": "", "state": "", "postal": "", "country": ""}
    for comp in components or []:
        types = comp.get("types", [])
        long = comp.get("long_name", "")
        short = comp.get("short_name", "")
        if "street_number" in types:
            out["street_number"] = long
        elif "route" in types:
            out["route"] = long
        elif "locality" in types:
            out["city"] = long
        elif "postal_town" in types and not out["city"]:
            out["city"] = long
        elif "administrative_area_level_1" in types:
            out["state"] = short
        elif "postal_code" in types:
            out["postal"] = long
        elif "country" in types:
            out["country"] = "USA" if short == "US" else ("Canada" if short == "CA" else long)
    out["street"] = title_address(" ".join([out["street_number"], out["route"]]).strip())
    return out


def serpapi_company_search(query: str) -> Tuple[str, str]:
    """Returns best URL and snippet from optional SerpAPI fallback."""
    if not SERPAPI_KEY or not query:
        return "", ""
    url = "https://serpapi.com/search.json"
    params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 5}
    try:
        data = requests.get(url, params=params, timeout=25).json()
    except Exception:
        return "", ""
    for item in data.get("organic_results", []):
        link = item.get("link", "")
        snippet = item.get("snippet", "")
        if link:
            return link, snippet
    return "", ""


def row_to_output(row: pd.Series, mapping: Dict[str, str], delay: float = 0.15) -> Dict[str, str]:
    raw_company = nonempty(row.get(mapping.get("company", ""), "")) if mapping.get("company") != "-- None --" else ""
    raw_address = nonempty(row.get(mapping.get("address", ""), "")) if mapping.get("address") != "-- None --" else ""
    raw_city = nonempty(row.get(mapping.get("city", ""), "")) if mapping.get("city") != "-- None --" else ""
    raw_state = nonempty(row.get(mapping.get("state", ""), "")) if mapping.get("state") != "-- None --" else ""
    raw_postal = nonempty(row.get(mapping.get("postal", ""), "")) if mapping.get("postal") != "-- None --" else ""
    raw_country = nonempty(row.get(mapping.get("country", ""), "")) if mapping.get("country") != "-- None --" else ""

    country = normalize_country(raw_country)
    postal = normalize_postal(raw_postal, country)
    state = normalize_state(raw_state, country)
    output = {
        "Company Name": raw_company.title(),
        "Street address": title_address(raw_address),
        "City": raw_city.title(),
        "State": state,
        "Postal code": postal,
        "Country": country,
        "Phone Number": "", "Website": "", "SIC Code": "", "NAICS Code": "",
        "Line of business": "", "Number of employee at this location": "",
        "Parent Company": "", "Trade style": "", "Google Maps Source": "",
        "Other Source": "", "Match Confidence": "", "QC Notes": ""
    }

    notes = []
    query = build_query(row, mapping)
    place = google_text_search(query)
    if isinstance(place, dict) and place.get("error"):
        notes.append(f"Google Places error: {place['error']} {place.get('message','')}")
        place = None

    details = None
    if place and place.get("place_id"):
        details = google_place_details(place["place_id"])
        time.sleep(delay)

    if details:
        comp = parse_address_components(details.get("address_components", []))
        g_country = normalize_country(comp.get("country", "")) or country
        # Preserve user postal except formatting. Use Google postal only if raw postal is blank.
        g_postal = normalize_postal(comp.get("postal", ""), g_country)
        output["Country"] = g_country or output["Country"]
        output["Postal code"] = output["Postal code"] or g_postal
        output["State"] = normalize_state(comp.get("state", ""), output["Country"]) or output["State"]
        output["City"] = comp.get("city", "").title() or output["City"]
        output["Street address"] = comp.get("street", "") or title_address(details.get("formatted_address", "")) or output["Street address"]
        output["Company Name"] = nonempty(details.get("name", "")).title() or output["Company Name"]
        output["Phone Number"] = normalize_phone(details.get("formatted_phone_number") or details.get("international_phone_number", ""), output["Country"])
        output["Website"] = nonempty(details.get("website", ""))
        output["Google Maps Source"] = nonempty(details.get("url", ""))
        confidence = fuzz.token_set_ratio(raw_company, output["Company Name"]) if raw_company and output["Company Name"] else 0
        output["Match Confidence"] = str(confidence)
        if postal and g_postal and postal != g_postal:
            notes.append(f"Postal preserved from input ({postal}); Google Maps showed {g_postal}.")
        if confidence < 70 and raw_company:
            notes.append("Low company-name match confidence; review manually.")
        if not output["Website"]:
            src, snippet = serpapi_company_search(f"{output['Company Name']} {output['City']} website")
            output["Other Source"] = src
            if src:
                notes.append("Website/source found via fallback search; verify manually.")
    else:
        src, snippet = serpapi_company_search(query)
        output["Other Source"] = src
        if src:
            notes.append("Not found on Google Maps; fallback source returned.")
        else:
            notes.append("No confident Google Maps match found.")

    # Google does not provide SIC/NAICS/employees/parent/trade style reliably.
    notes.append("SIC, NAICS, employees, parent company, and trade style require a separate enrichment source/API if not obvious from public pages.")
    output["QC Notes"] = " ".join(notes)
    return output


def process_file(df: pd.DataFrame, mapping: Dict[str, str], delay: float) -> pd.DataFrame:
    rows = []
    progress = st.progress(0)
    status = st.empty()
    total = len(df)
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        status.write(f"Processing row {i} of {total}")
        rows.append(row_to_output(row, mapping, delay=delay))
        progress.progress(i / total)
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    return pd.concat([df.reset_index(drop=True), result], axis=1)


st.set_page_config(page_title="Company Lead Cleaner", layout="wide")
st.title("Company Lead Cleaner")
st.caption("Google Maps first, fallback search second, then export a cleaned Excel file.")

with st.sidebar:
    st.header("API keys")
    st.write("Set keys in `.env` or your deployment secrets.")
    st.write("Google Places API:", "✅ found" if GOOGLE_API_KEY else "❌ missing")
    st.write("SerpAPI fallback:", "✅ found" if SERPAPI_KEY else "Optional / missing")
    delay = st.number_input("Delay between Google requests", min_value=0.0, max_value=2.0, value=0.15, step=0.05)

uploaded = st.file_uploader("Drop Excel or CSV file", type=["xlsx", "xls", "csv"])

if uploaded:
    if uploaded.name.lower().endswith(".csv"):
        df = pd.read_csv(uploaded, dtype=str)
    else:
        df = pd.read_excel(uploaded, dtype=str)
    st.subheader("Input preview")
    st.dataframe(df.head(20), use_container_width=True)

    cols = ["-- None --"] + list(df.columns)
    def guess(options, targets):
        lower = {c.lower(): c for c in df.columns}
        for t in targets:
            for k, v in lower.items():
                if t in k:
                    return v
        return "-- None --"

    st.subheader("Map your columns")
    c1, c2, c3 = st.columns(3)
    with c1:
        company = st.selectbox("Company column", cols, index=cols.index(guess(cols, ["company", "name"])) if guess(cols, ["company", "name"]) in cols else 0)
        address = st.selectbox("Address column", cols, index=cols.index(guess(cols, ["address", "street"])) if guess(cols, ["address", "street"]) in cols else 0)
    with c2:
        city = st.selectbox("City column", cols, index=cols.index(guess(cols, ["city"])) if guess(cols, ["city"]) in cols else 0)
        state = st.selectbox("State column", cols, index=cols.index(guess(cols, ["state", "province"])) if guess(cols, ["state", "province"]) in cols else 0)
    with c3:
        postal = st.selectbox("ZIP / Postal column", cols, index=cols.index(guess(cols, ["zip", "postal"])) if guess(cols, ["zip", "postal"]) in cols else 0)
        country = st.selectbox("Country column", cols, index=cols.index(guess(cols, ["country"])) if guess(cols, ["country"]) in cols else 0)

    mapping = {"company": company, "address": address, "city": city, "state": state, "postal": postal, "country": country}

    if st.button("Process full batch", type="primary"):
        if not GOOGLE_API_KEY:
            st.error("Add GOOGLE_PLACES_API_KEY first. Google Maps is the required first source.")
        else:
            cleaned = process_file(df, mapping, delay)
            st.success("Processing complete")
            st.dataframe(cleaned.head(50), use_container_width=True)
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                cleaned.to_excel(writer, index=False, sheet_name="Cleaned_Data")
                rules = pd.DataFrame({"Rule": [
                    "Google Maps is the first source.",
                    "If not found on Google Maps, fallback search is used when SERPAPI_KEY is available.",
                    "USA/US/United States is normalized to USA.",
                    "USA ZIP is preserved and formatted to 5 digits.",
                    "USA/Canada states/provinces are abbreviated.",
                    "USA/Canada phone numbers are formatted xxx-xxx-xxxx.",
                    "Input postal code is not overwritten by Google postal code; conflict is noted in QC Notes.",
                    "SIC/NAICS/employees/parent/trade style need a separate enrichment source/API if not available from public sources."
                ]})
                rules.to_excel(writer, index=False, sheet_name="Rules_Applied")
            st.download_button(
                "Download cleaned Excel",
                output.getvalue(),
                file_name="cleaned_company_leads.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
