import io
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS


OUTPUT_COLUMNS = [
    "Company",
    "Address",
    "City",
    "State",
    "Zip",
    "Country",
    "PhoneResearch",
    "Website",
    "SIC",
    "NAICS",
    "NoOfEmployees(This site only)",
    "LineOfBusiness",
    "ParentName",
    "Confidence",
    "SourceURL",
    "Remarks",
]

REQUIRED_INPUT_COLUMNS = ["Company", "City", "State", "Zip", "Country"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}

PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}(?:[\s.-]?\d{3,4})?"
)

ADDRESS_KEYWORDS = [
    "address",
    "head office",
    "headquarters",
    "location",
    "office",
    "contact",
    "〒",
    "street",
    "road",
    "avenue",
    "drive",
    "suite",
    "floor",
    "building",
]

BAD_DOMAINS = [
    "facebook.com",
    "linkedin.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "wikipedia.org",
]


@dataclass
class SearchResult:
    title: str
    href: str
    body: str


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def build_query(row: pd.Series) -> str:
    parts = [
        clean_text(row.get("Company")),
        clean_text(row.get("City")),
        clean_text(row.get("State")),
        clean_text(row.get("Zip")),
        clean_text(row.get("Country")),
        "official website address phone",
    ]
    return " ".join([p for p in parts if p])


def fallback_query(row: pd.Series) -> str:
    parts = [
        clean_text(row.get("Company")),
        clean_text(row.get("Country")),
        "company headquarters address website",
    ]
    return " ".join([p for p in parts if p])


def search_web(query: str, max_results: int = 8) -> List[SearchResult]:
    results: List[SearchResult] = []
    try:
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=max_results):
                href = item.get("href") or item.get("url") or ""
                if not href:
                    continue
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        href=href,
                        body=item.get("body", ""),
                    )
                )
    except Exception as exc:
        st.warning(f"Search failed for query: {query}. Error: {exc}")
    return results


def likely_official_url(company: str, country: str, results: List[SearchResult]) -> Optional[SearchResult]:
    company_tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", company) if len(t) > 1]
    scored: List[Tuple[int, SearchResult]] = []

    for result in results:
        url_lower = result.href.lower()
        title_lower = result.title.lower()
        body_lower = result.body.lower()
        if any(domain in url_lower for domain in BAD_DOMAINS):
            continue

        score = 0
        for token in company_tokens:
            if token in url_lower:
                score += 4
            if token in title_lower:
                score += 3
            if token in body_lower:
                score += 1
        if country and country.lower() in body_lower:
            score += 1
        if any(word in title_lower for word in ["official", "home", "contact", "about"]):
            score += 1
        scored.append((score, result))

    if not scored:
        return results[0] if results else None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def fetch_page(url: str, timeout: int = 12) -> Tuple[str, str]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        text = soup.get_text("\n", strip=True)
        text = re.sub(r"\n{2,}", "\n", text)
        return title, text[:25000]
    except Exception:
        return "", ""


def extract_phone(text: str) -> str:
    matches = PHONE_RE.findall(text)
    cleaned = []
    for m in matches:
        candidate = re.sub(r"\s+", " ", m).strip(" .,-")
        digits = re.sub(r"\D", "", candidate)
        if 7 <= len(digits) <= 15:
            cleaned.append(candidate)
    return cleaned[0] if cleaned else "Not Publicly Available"


def extract_address(text: str, city: str, state: str, zip_code: str, country: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidate_lines = []
    city_l = city.lower()
    state_l = state.lower()
    zip_l = zip_code.lower()
    country_l = country.lower()

    for i, line in enumerate(lines):
        line_l = line.lower()
        score = 0
        if city_l and city_l in line_l:
            score += 3
        if state_l and state_l in line_l:
            score += 2
        if zip_l and zip_l in line_l:
            score += 4
        if country_l and country_l in line_l:
            score += 1
        if any(k in line_l for k in ADDRESS_KEYWORDS):
            score += 1
        if score >= 3:
            start = max(0, i - 2)
            end = min(len(lines), i + 3)
            block = ", ".join(lines[start:end])
            if len(block) <= 400:
                candidate_lines.append((score, block))

    if candidate_lines:
        candidate_lines.sort(key=lambda x: x[0], reverse=True)
        return candidate_lines[0][1]
    return "Not Publicly Available"


def extract_description(text: str, search_body: str) -> str:
    lower = text.lower()
    for marker in ["about us", "about", "company", "profile", "business"]:
        idx = lower.find(marker)
        if idx != -1:
            snippet = text[idx : idx + 700]
            snippet = re.sub(r"\s+", " ", snippet).strip()
            if len(snippet) > 80:
                return snippet[:350]
    body = re.sub(r"\s+", " ", search_body).strip()
    return body[:300] if body else "Not Publicly Available"


def infer_codes(description: str) -> Tuple[str, str]:
    d = description.lower()
    rules = [
        (("aerospace", "aircraft", "aviation", "defense"), "3721 Aircraft", "336411 Aircraft Manufacturing"),
        (("software", "saas", "technology", "it services"), "7372 Prepackaged Software", "541511 Custom Computer Programming Services"),
        (("consulting", "advisory", "management"), "8742 Management Consulting Services", "541611 Administrative Management Consulting Services"),
        (("logistics", "freight", "transport", "shipping"), "4731 Freight Transportation Arrangement", "488510 Freight Transportation Arrangement"),
        (("manufacturing", "manufacturer", "factory"), "3999 Manufacturing Industries, NEC", "339999 All Other Miscellaneous Manufacturing"),
        (("construction", "contractor", "building"), "1542 General Contractors", "236220 Commercial and Institutional Building Construction"),
        (("chemical", "chemicals"), "2899 Chemicals and Chemical Preparations", "325998 Other Miscellaneous Chemical Product Manufacturing"),
        (("electronics", "semiconductor", "electrical"), "3679 Electronic Components", "334419 Other Electronic Component Manufacturing"),
    ]
    for keywords, sic, naics in rules:
        if any(k in d for k in keywords):
            return sic, naics
    return "Not Publicly Available", "Not Publicly Available"


def confidence_score(row: pd.Series, selected: Optional[SearchResult], address: str, website: str) -> str:
    if not selected:
        return "Low"
    company = clean_text(row.get("Company")).lower()
    city = clean_text(row.get("City")).lower()
    zip_code = clean_text(row.get("Zip")).lower()
    text = " ".join([selected.title, selected.body, selected.href, address]).lower()
    score = 0
    if company and any(token in text for token in re.findall(r"[a-z0-9]+", company)):
        score += 2
    if city and city in text:
        score += 2
    if zip_code and zip_code in text:
        score += 3
    if website != "Not Publicly Available":
        score += 1
    if address != "Not Publicly Available":
        score += 2
    if score >= 7:
        return "High"
    if score >= 4:
        return "Medium"
    return "Low"


def enrich_one(row: pd.Series, sleep_seconds: float = 0.5) -> Dict[str, str]:
    company = clean_text(row.get("Company"))
    city = clean_text(row.get("City"))
    state = clean_text(row.get("State"))
    zip_code = clean_text(row.get("Zip"))
    country = clean_text(row.get("Country"))

    query = build_query(row)
    results = search_web(query)
    if not results:
        results = search_web(fallback_query(row))
    selected = likely_official_url(company, country, results)

    title = ""
    page_text = ""
    if selected:
        title, page_text = fetch_page(selected.href)
        time.sleep(sleep_seconds)

    combined_text = "\n".join([
        selected.title if selected else "",
        selected.body if selected else "",
        title,
        page_text,
    ])

    website = selected.href if selected else "Not Publicly Available"
    phone = extract_phone(combined_text)
    address = extract_address(combined_text, city, state, zip_code, country)
    line_of_business = extract_description(combined_text, selected.body if selected else "")
    sic, naics = infer_codes(line_of_business)
    confidence = confidence_score(row, selected, address, website)

    remarks = ""
    if confidence == "Low":
        remarks = "Needs manual verification; weak public match."
    elif confidence == "Medium":
        remarks = "Review recommended before final use."
    else:
        remarks = "Likely match based on public source."

    return {
        "Company": company,
        "Address": address,
        "City": city if city else "Not Publicly Available",
        "State": state if state else "Not Publicly Available",
        "Zip": zip_code if zip_code else "Not Publicly Available",
        "Country": country,
        "PhoneResearch": phone,
        "Website": website,
        "SIC": sic,
        "NAICS": naics,
        "NoOfEmployees(This site only)": "Not Publicly Available",
        "LineOfBusiness": line_of_business,
        "ParentName": "Not Publicly Available",
        "Confidence": confidence,
        "SourceURL": selected.href if selected else "Not Publicly Available",
        "Remarks": remarks,
    }


def normalize_input_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in df.columns:
        normalized = str(col).strip().lower().replace(" ", "")
        if normalized in ["company", "companyname", "name"]:
            rename_map[col] = "Company"
        elif normalized in ["city", "town"]:
            rename_map[col] = "City"
        elif normalized in ["state", "province", "region"]:
            rename_map[col] = "State"
        elif normalized in ["zip", "zipcode", "postalcode", "postcode"]:
            rename_map[col] = "Zip"
        elif normalized in ["country"]:
            rename_map[col] = "Country"
    df = df.rename(columns=rename_map)
    for col in REQUIRED_INPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[REQUIRED_INPUT_COLUMNS]


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Enriched Companies")
    return output.getvalue()


def make_sample_file() -> bytes:
    sample = pd.DataFrame(
        [
            {"Company": "Boeing", "City": "Tanner", "State": "AL", "Zip": "35671", "Country": "USA"},
            {"Company": "BOEL", "City": "Osaka-Shi", "State": "", "Zip": "", "Country": "Japan"},
        ]
    )
    return dataframe_to_excel_bytes(sample)


st.set_page_config(page_title="Company Enrichment Tool", layout="wide")
st.title("Company Enrichment Tool")
st.write("Upload Excel, enrich company records from public web sources, and download the output Excel.")

with st.expander("Required input format", expanded=False):
    st.write("Columns: Company, City, State, Zip, Country")
    st.download_button(
        "Download sample input Excel",
        data=make_sample_file(),
        file_name="sample_input.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

uploaded = st.file_uploader("Upload Excel file", type=["xlsx", "xls"])
max_rows = st.number_input("Maximum rows to process", min_value=1, max_value=500, value=25, step=1)
sleep_seconds = st.slider("Delay between page requests", min_value=0.0, max_value=3.0, value=0.5, step=0.1)

if uploaded:
    input_df = pd.read_excel(uploaded)
    input_df = normalize_input_columns(input_df).head(int(max_rows))
    st.subheader("Input preview")
    st.dataframe(input_df, use_container_width=True)

    if st.button("Start enrichment"):
        rows = []
        progress = st.progress(0)
        status = st.empty()
        for idx, row in input_df.iterrows():
            status.write(f"Processing {idx + 1}/{len(input_df)}: {clean_text(row.get('Company'))}")
            try:
                rows.append(enrich_one(row, sleep_seconds=sleep_seconds))
            except Exception as exc:
                rows.append({
                    "Company": clean_text(row.get("Company")),
                    "Address": "Not Publicly Available",
                    "City": clean_text(row.get("City")) or "Not Publicly Available",
                    "State": clean_text(row.get("State")) or "Not Publicly Available",
                    "Zip": clean_text(row.get("Zip")) or "Not Publicly Available",
                    "Country": clean_text(row.get("Country")),
                    "PhoneResearch": "Not Publicly Available",
                    "Website": "Not Publicly Available",
                    "SIC": "Not Publicly Available",
                    "NAICS": "Not Publicly Available",
                    "NoOfEmployees(This site only)": "Not Publicly Available",
                    "LineOfBusiness": "Not Publicly Available",
                    "ParentName": "Not Publicly Available",
                    "Confidence": "Low",
                    "SourceURL": "Not Publicly Available",
                    "Remarks": f"Error: {exc}",
                })
            progress.progress((idx + 1) / len(input_df))

        output_df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
        st.subheader("Enriched output")
        st.dataframe(output_df, use_container_width=True)
        excel_bytes = dataframe_to_excel_bytes(output_df)
        st.download_button(
            "Download enriched Excel",
            data=excel_bytes,
            file_name="enriched_companies.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
else:
    st.info("Upload an Excel file to begin.")
