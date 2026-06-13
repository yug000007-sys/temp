import io
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

try:
    from duckduckgo_search import DDGS
    DDG_AVAILABLE = True
except Exception:
    DDGS = None
    DDG_AVAILABLE = False

OUTPUT_COLUMNS = [
    "Company", "Address", "City", "State", "Zip", "Country", "PhoneResearch", "Website",
    "SIC", "NAICS", "NoOfEmployees(This site only)", "LineOfBusiness", "ParentName",
    "Confidence", "SourceURL", "ResearchURL", "Remarks"
]
INPUT_COLUMNS = ["Company", "City", "State", "Zip", "Country"]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}(?:[\s.-]?\d{3,4})?")
BAD_DOMAINS = ["facebook.com", "linkedin.com", "instagram.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org"]

@dataclass
class SearchResult:
    title: str
    href: str
    body: str

def clean(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()

def normalize_input_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in df.columns:
        c = str(col).strip().lower().replace(" ", "").replace("_", "")
        if c in ["company", "companyname", "name"]:
            rename_map[col] = "Company"
        elif c in ["city", "town"]:
            rename_map[col] = "City"
        elif c in ["state", "province", "region"]:
            rename_map[col] = "State"
        elif c in ["zip", "zipcode", "postalcode", "postcode"]:
            rename_map[col] = "Zip"
        elif c == "country":
            rename_map[col] = "Country"
    df = df.rename(columns=rename_map)
    for col in INPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[INPUT_COLUMNS]

def build_query(row: pd.Series) -> str:
    parts = [clean(row.get(c)) for c in INPUT_COLUMNS]
    parts += ["official website address phone"]
    return " ".join([p for p in parts if p])

def research_url(query: str) -> str:
    return "https://duckduckgo.com/?q=" + quote_plus(query)

def search_web(query: str, max_results: int = 8) -> List[SearchResult]:
    results = []
    if not DDG_AVAILABLE:
        return results
    try:
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=max_results):
                href = item.get("href") or item.get("url") or ""
                if href:
                    results.append(SearchResult(item.get("title", ""), href, item.get("body", "")))
    except Exception as exc:
        st.warning(f"Search failed. I added a manual ResearchURL instead. Error: {exc}")
    return results

def choose_result(company: str, country: str, results: List[SearchResult]) -> Optional[SearchResult]:
    if not results:
        return None
    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", company) if len(t) > 1]
    scored = []
    for r in results:
        url = r.href.lower()
        if any(bad in url for bad in BAD_DOMAINS):
            continue
        text = f"{r.title} {r.body} {r.href}".lower()
        score = 0
        for token in tokens:
            if token in url: score += 4
            if token in text: score += 2
        if country and country.lower() in text: score += 1
        if any(w in text for w in ["official", "contact", "about", "company"]): score += 1
        scored.append((score, r))
    if not scored:
        return results[0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]

def fetch_page(url: str) -> Tuple[str, str]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        text = soup.get_text("\n", strip=True)
        return title, re.sub(r"\n{2,}", "\n", text)[:25000]
    except Exception:
        return "", ""

def extract_phone(text: str) -> str:
    for m in PHONE_RE.findall(text):
        candidate = re.sub(r"\s+", " ", m).strip(" .,-")
        digits = re.sub(r"\D", "", candidate)
        if 7 <= len(digits) <= 15:
            return candidate
    return "Not Publicly Available"

def extract_address(text: str, city: str, state: str, zip_code: str, country: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    best = (0, "")
    for i, line in enumerate(lines):
        block = ", ".join(lines[max(0, i-2): min(len(lines), i+3)])
        b = block.lower()
        score = 0
        if city and city.lower() in b: score += 3
        if state and state.lower() in b: score += 2
        if zip_code and zip_code.lower() in b: score += 4
        if country and country.lower() in b: score += 1
        if any(k in b for k in ["address", "headquarters", "office", "contact", "street", "road", "drive", "avenue", "〒"]): score += 1
        if score > best[0] and len(block) < 500:
            best = (score, block)
    return best[1] if best[0] >= 3 else "Not Publicly Available"

def extract_description(text: str, fallback: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    lower = t.lower()
    for marker in ["about us", "about", "company profile", "business"]:
        idx = lower.find(marker)
        if idx >= 0:
            return t[idx:idx+350]
    return re.sub(r"\s+", " ", fallback).strip()[:300] or "Not Publicly Available"

def infer_codes(desc: str) -> Tuple[str, str]:
    d = desc.lower()
    rules = [
        (["aerospace", "aircraft", "aviation", "defense"], "3721 Aircraft", "336411 Aircraft Manufacturing"),
        (["software", "saas", "technology", "it services"], "7372 Prepackaged Software", "541511 Custom Computer Programming Services"),
        (["consulting", "advisory", "management"], "8742 Management Consulting Services", "541611 Administrative Management Consulting Services"),
        (["logistics", "freight", "shipping"], "4731 Freight Transportation Arrangement", "488510 Freight Transportation Arrangement"),
        (["manufacturing", "manufacturer", "factory"], "3999 Manufacturing Industries, NEC", "339999 All Other Miscellaneous Manufacturing"),
        (["construction", "contractor"], "1542 General Contractors", "236220 Commercial and Institutional Building Construction"),
        (["chemical", "chemicals"], "2899 Chemicals and Chemical Preparations", "325998 Other Miscellaneous Chemical Product Manufacturing"),
        (["electronics", "semiconductor", "electrical"], "3679 Electronic Components", "334419 Other Electronic Component Manufacturing"),
    ]
    for words, sic, naics in rules:
        if any(w in d for w in words):
            return sic, naics
    return "Not Publicly Available", "Not Publicly Available"

def confidence(row: pd.Series, selected: Optional[SearchResult], address: str, website: str) -> str:
    score = 0
    company = clean(row.get("Company")).lower()
    city = clean(row.get("City")).lower()
    zip_code = clean(row.get("Zip")).lower()
    text = " ".join([selected.title, selected.body, selected.href, address]).lower() if selected else address.lower()
    if company and any(t in text for t in re.findall(r"[a-z0-9]+", company)): score += 2
    if city and city in text: score += 2
    if zip_code and zip_code in text: score += 3
    if website != "Not Publicly Available": score += 1
    if address != "Not Publicly Available": score += 2
    if score >= 7: return "High"
    if score >= 4: return "Medium"
    return "Low"

def enrich_one(row: pd.Series, delay: float) -> Dict[str, str]:
    company, city, state, zip_code, country = [clean(row.get(c)) for c in INPUT_COLUMNS]
    query = build_query(row)
    url_for_research = research_url(query)
    results = search_web(query)
    if not results:
        results = search_web(f"{company} {country} headquarters address website")
    selected = choose_result(company, country, results)
    page_title, page_text = fetch_page(selected.href) if selected else ("", "")
    time.sleep(delay)
    combined = "\n".join([selected.title if selected else "", selected.body if selected else "", page_title, page_text])
    website = selected.href if selected else "Not Publicly Available"
    phone = extract_phone(combined)
    address = extract_address(combined, city, state, zip_code, country)
    lob = extract_description(combined, selected.body if selected else "")
    sic, naics = infer_codes(lob)
    conf = confidence(row, selected, address, website)
    remarks = "Likely match based on public source." if conf == "High" else ("Review recommended before final use." if conf == "Medium" else "Needs manual verification; use ResearchURL.")
    return {
        "Company": company,
        "Address": address,
        "City": city or "Not Publicly Available",
        "State": state or "Not Publicly Available",
        "Zip": zip_code or "Not Publicly Available",
        "Country": country,
        "PhoneResearch": phone,
        "Website": website,
        "SIC": sic,
        "NAICS": naics,
        "NoOfEmployees(This site only)": "Not Publicly Available",
        "LineOfBusiness": lob,
        "ParentName": "Not Publicly Available",
        "Confidence": conf,
        "SourceURL": selected.href if selected else "Not Publicly Available",
        "ResearchURL": url_for_research,
        "Remarks": remarks,
    }

def to_excel_bytes(df: pd.DataFrame) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Enriched Companies")
    return bio.getvalue()

st.set_page_config(page_title="Company Enrichment Tool", layout="wide")
st.title("Company Enrichment Tool")
st.caption("No paid API. Upload Excel -> enrich from public web -> download Excel.")

if not DDG_AVAILABLE:
    st.warning("DuckDuckGo search package is not available. The app will still run, but records will show manual ResearchURL links. Check requirements.txt deployment.")

with st.expander("Required input columns"):
    st.write(", ".join(INPUT_COLUMNS))
    sample = pd.DataFrame([
        {"Company": "Boeing", "City": "Tanner", "State": "AL", "Zip": "35671", "Country": "USA"},
        {"Company": "BOEL", "City": "Osaka-Shi", "State": "", "Zip": "", "Country": "Japan"},
    ])
    st.download_button("Download sample input Excel", data=to_excel_bytes(sample), file_name="sample_input.xlsx")

uploaded = st.file_uploader("Upload Excel file", type=["xlsx", "xls"])
max_rows = st.number_input("Maximum rows to process", min_value=1, max_value=500, value=25)
delay = st.slider("Delay between page requests", 0.0, 3.0, 0.5, 0.1)

if uploaded:
    try:
        df = pd.read_excel(uploaded)
        df = normalize_input_columns(df).head(int(max_rows))
        st.subheader("Input preview")
        st.dataframe(df, use_container_width=True)
        if st.button("Start enrichment"):
            out = []
            prog = st.progress(0)
            for i, row in df.iterrows():
                try:
                    out.append(enrich_one(row, delay))
                except Exception as exc:
                    q = build_query(row)
                    out.append({
                        "Company": clean(row.get("Company")), "Address": "Not Publicly Available",
                        "City": clean(row.get("City")) or "Not Publicly Available", "State": clean(row.get("State")) or "Not Publicly Available",
                        "Zip": clean(row.get("Zip")) or "Not Publicly Available", "Country": clean(row.get("Country")),
                        "PhoneResearch": "Not Publicly Available", "Website": "Not Publicly Available", "SIC": "Not Publicly Available", "NAICS": "Not Publicly Available",
                        "NoOfEmployees(This site only)": "Not Publicly Available", "LineOfBusiness": "Not Publicly Available", "ParentName": "Not Publicly Available",
                        "Confidence": "Low", "SourceURL": "Not Publicly Available", "ResearchURL": research_url(q), "Remarks": f"Error: {exc}",
                    })
                prog.progress((len(out)) / len(df))
            result = pd.DataFrame(out, columns=OUTPUT_COLUMNS)
            st.subheader("Output")
            st.dataframe(result, use_container_width=True)
            st.download_button("Download enriched Excel", to_excel_bytes(result), "enriched_companies.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as exc:
        st.error(f"Could not read/process the uploaded file: {exc}")
else:
    st.info("Upload Excel to begin.")
