import io
import re
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Company Enrichment Tool", layout="wide")

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

INPUT_COLUMNS = ["Company", "City", "State", "Zip", "Country"]


def clean_value(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def build_query(row):
    parts = [
        clean_value(row.get("Company", "")),
        clean_value(row.get("City", "")),
        clean_value(row.get("State", "")),
        clean_value(row.get("Zip", "")),
        clean_value(row.get("Country", "")),
        "official address phone website",
    ]
    return " ".join([p for p in parts if p])


def google_search_url(query):
    return "https://www.google.com/search?q=" + quote_plus(query)


def make_prompt(row):
    company = clean_value(row.get("Company", ""))
    city = clean_value(row.get("City", ""))
    state = clean_value(row.get("State", ""))
    zip_code = clean_value(row.get("Zip", ""))
    country = clean_value(row.get("Country", ""))
    return f"""Research this company and return ONLY this format. Use official/company sources when possible. If not verified, write Not verified. Never invent values.\n\nInput:\nCompany: {company}\nCity: {city}\nState: {state}\nZip: {zip_code}\nCountry: {country}\n\nRequired output:\nCompany=\nAddress=\nCity=\nState=\nZip=\nCountry=\nPhoneResearch=\nWebsite=\nSIC=\nNAICS=\nNoOfEmployees(This site only)=\nLineOfBusiness=\nParentName=\nConfidence= High/Medium/Low\nSourceURL=\nRemarks=\n"""


def parse_output_text(text):
    result = {col: "" for col in OUTPUT_COLUMNS}
    key_map = {c.lower(): c for c in OUTPUT_COLUMNS}
    aliases = {
        "phone": "PhoneResearch",
        "phone research": "PhoneResearch",
        "employees": "NoOfEmployees(This site only)",
        "noofemployees": "NoOfEmployees(This site only)",
        "lineofbusiness": "LineOfBusiness",
        "line of business": "LineOfBusiness",
        "parent": "ParentName",
        "parent name": "ParentName",
        "source": "SourceURL",
        "source url": "SourceURL",
    }
    for line in str(text).splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized = re.sub(r"\s+", " ", key.strip().lower())
        normalized_compact = re.sub(r"[^a-z0-9]", "", normalized)
        target = key_map.get(normalized) or aliases.get(normalized) or aliases.get(normalized_compact)
        if target:
            result[target] = value.strip()
    return result


st.title("Company Enrichment Tool - No API")
st.write("Upload Excel/CSV, generate research prompts/search links, paste ChatGPT results, then download Excel.")

with st.expander("Required input columns", expanded=False):
    st.write(", ".join(INPUT_COLUMNS))

uploaded_file = st.file_uploader("Upload Excel or CSV", type=["xlsx", "xls", "csv"])

if uploaded_file is not None:
    try:
        name = uploaded_file.name.lower()
        if name.endswith(".csv"):
            df = pd.read_csv(uploaded_file, dtype=str).fillna("")
        else:
            df = pd.read_excel(uploaded_file, dtype=str).fillna("")

        for col in INPUT_COLUMNS:
            if col not in df.columns:
                df[col] = ""

        st.success(f"Loaded {len(df)} records")
        st.dataframe(df[INPUT_COLUMNS].head(50), use_container_width=True)

        batch_size = st.number_input("Batch size", min_value=1, max_value=100, value=25, step=1)
        start_row = st.number_input("Start row", min_value=1, max_value=max(1, len(df)), value=1, step=1)
        start_idx = int(start_row) - 1
        end_idx = min(start_idx + int(batch_size), len(df))
        batch = df.iloc[start_idx:end_idx]

        st.subheader("Batch prompt")
        batch_prompt = "You are a B2B company researcher. For each record, research and return the exact requested fields. Mark uncertain fields as Not verified.\n\n"
        for i, (_, row) in enumerate(batch.iterrows(), start=start_idx + 1):
            batch_prompt += f"Record {i}:\n{make_prompt(row)}\n"
        st.text_area("Copy this into ChatGPT", batch_prompt, height=350)

        st.subheader("Search links")
        link_rows = []
        for i, (_, row) in enumerate(batch.iterrows(), start=start_idx + 1):
            q = build_query(row)
            link_rows.append({"Row": i, "Company": clean_value(row.get("Company", "")), "SearchQuery": q, "GoogleURL": google_search_url(q)})
        st.dataframe(pd.DataFrame(link_rows), use_container_width=True)

        st.subheader("Paste ChatGPT enriched results")
        pasted = st.text_area("Paste results here. Separate records with a blank line, or paste one after another.", height=300)

        if st.button("Parse pasted results and download Excel"):
            blocks = re.split(r"\n\s*\n(?=Company=|Company\s*=)", pasted.strip()) if pasted.strip() else []
            parsed = [parse_output_text(block) for block in blocks if block.strip()]
            if not parsed:
                st.warning("No parsable records found. Make sure lines use Field=Value format.")
            else:
                out_df = pd.DataFrame(parsed, columns=OUTPUT_COLUMNS)
                st.dataframe(out_df, use_container_width=True)
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    out_df.to_excel(writer, index=False, sheet_name="Enriched")
                st.download_button(
                    "Download enriched Excel",
                    data=buffer.getvalue(),
                    file_name="enriched_companies.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

    except Exception as e:
        st.error("The app hit an error while reading or processing the file.")
        st.exception(e)
else:
    sample = pd.DataFrame([
        {"Company": "Boeing", "City": "Tanner", "State": "AL", "Zip": "35671", "Country": "USA"},
        {"Company": "Boel", "City": "Osaka-Shi", "State": "", "Zip": "", "Country": "Japan"},
    ])
    st.subheader("Sample input")
    st.dataframe(sample, use_container_width=True)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        sample.to_excel(writer, index=False, sheet_name="Input")
    st.download_button(
        "Download sample Excel",
        data=buffer.getvalue(),
        file_name="sample_input.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
