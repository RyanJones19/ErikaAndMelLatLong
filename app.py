"""Streamlit app: upload a CSV or Excel file of addresses, get back the same file with lat/lon columns."""

import io
import re
import time

import pandas as pd
import streamlit as st
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import OpenCage

st.set_page_config(page_title="CSV / Excel Geocoder", page_icon="📍")
st.title("📍 CSV / Excel Geocoder")
st.caption("Upload a CSV or Excel file with address columns. Returns the same data with `lat` and `lon` added.")


def strip_suite(street: str) -> str:
    return re.sub(r"\s*(#|Ste\.?|Suite|Unit|Apt\.?)\s*\S+\s*$", "", street, flags=re.IGNORECASE).strip()


def build_query(row: pd.Series, cols: list[str]) -> str:
    parts = [str(row[c]).strip() for c in cols if pd.notna(row[c]) and str(row[c]).strip()]
    return ", ".join(parts) + ", USA"


@st.cache_resource
def get_geocoder(api_key: str):
    return OpenCage(api_key=api_key)


def geocode_with_backoff(geocoder, query: str, max_attempts: int = 4) -> object | None:
    """Call the geocoder with exponential backoff on transient errors (timeout, 429, 5xx)."""
    delay = 2.0
    for attempt in range(1, max_attempts + 1):
        try:
            return geocoder.geocode(query, timeout=10)
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            if attempt == max_attempts:
                st.warning(f"Gave up on {query!r} after {max_attempts} attempts: {e}")
                return None
            time.sleep(delay)
            delay *= 2  # 2s, 4s, 8s
    return None


def geocode_one(geocoder, query: str, retry_query: str | None) -> tuple[float | None, float | None, str]:
    for q in [query] + ([retry_query] if retry_query and retry_query != query else []):
        loc = geocode_with_backoff(geocoder, q)
        if loc:
            return loc.latitude, loc.longitude, loc.address
    return None, None, ""


uploaded = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"])

if uploaded:
    if uploaded.name.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(uploaded)
    else:
        df = pd.read_csv(uploaded)
    st.write(f"**{len(df)} rows loaded.** Preview:")
    st.dataframe(df.head(), use_container_width=True)

    st.subheader("Pick the address column(s)")
    st.caption("Select in the order they should appear in the address (e.g. street, city, state, zip).")
    address_cols = st.multiselect(
        "Address columns",
        options=list(df.columns),
        default=[c for c in ["street", "city", "state", "zip"] if c in df.columns],
    )

    try:
        api_key = st.secrets["OPENCAGE_API_KEY"]
    except (KeyError, FileNotFoundError):
        st.error(
            "Missing OPENCAGE_API_KEY. Add it to `.streamlit/secrets.toml` locally "
            "or to the Secrets section in the Streamlit Cloud app settings."
        )
        st.stop()

    if st.button("Geocode", type="primary", disabled=not address_cols):
        geocoder = get_geocoder(api_key)
        progress = st.progress(0.0, text="Starting...")
        results = []
        failed_names = []

        for i, (_, row) in enumerate(df.iterrows(), 1):
            query = build_query(row, address_cols)
            retry = None
            for col in address_cols:
                if "street" in col.lower() or "address" in col.lower():
                    stripped = strip_suite(str(row[col]))
                    if stripped != str(row[col]):
                        retry_row = row.copy()
                        retry_row[col] = stripped
                        retry = build_query(retry_row, address_cols)
                    break

            lat, lon, matched = geocode_one(geocoder, query, retry)
            results.append({"lat": lat, "lon": lon, "matched_address": matched})
            if lat is None:
                failed_names.append(query)
            progress.progress(i / len(df), text=f"[{i}/{len(df)}] {query[:60]}")
            time.sleep(1.1)  # Nominatim 1 req/sec policy

        progress.empty()
        out = pd.concat([df.reset_index(drop=True), pd.DataFrame(results)], axis=1)

        success = out["lat"].notna().sum()
        st.success(f"Geocoded {success}/{len(out)} rows.")
        if failed_names:
            with st.expander(f"{len(failed_names)} failures"):
                for q in failed_names:
                    st.text(q)

        st.dataframe(out, use_container_width=True)

        if success > 0:
            mappable = out.dropna(subset=["lat", "lon"]).rename(columns={"lon": "longitude", "lat": "latitude"})
            st.map(mappable[["latitude", "longitude"]])

        csv_buf = io.StringIO()
        out.to_csv(csv_buf, index=False)
        xlsx_buf = io.BytesIO()
        with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
            out.to_excel(writer, index=False, sheet_name="geocoded")

        col1, col2 = st.columns(2)
        col1.download_button(
            "⬇️ Download CSV",
            data=csv_buf.getvalue(),
            file_name="addresses_geocoded.csv",
            mime="text/csv",
        )
        col2.download_button(
            "⬇️ Download Excel",
            data=xlsx_buf.getvalue(),
            file_name="addresses_geocoded.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
