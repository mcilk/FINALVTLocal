import streamlit as st
import geopandas as gpd
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

# -------------------------
# Streamlit Page Setup
# -------------------------
st.set_page_config(layout="wide", page_title="Vermont Town Economic Dashboard")

# -------------------------
# Fetch Vermont Town Boundaries (VCGI ArcGIS)
# -------------------------
@st.cache_data
def fetch_town_boundaries():
    url = "https://services.arcgis.com/pwNwIGBE7M7VOXjQ/arcgis/rest/services/VT_Town_Boundaries__VCGI_/FeatureServer/0/query"
    params = {"where": "1=1", "outFields": "*", "f": "geojson"}
    r = requests.get(url, params=params)
    r.raise_for_status()
    return gpd.read_file(r.text)

# -------------------------
# Fetch ACS Economic Data (2023 5-year)
# -------------------------
@st.cache_data
def fetch_acs_data(year=2023):
    profile_vars = {
        "DP03_0009PE": "Unemployment Rate (%)",
        "DP03_0119PE": "Poverty Rate (%)",
        "DP02_0068PE": "Bachelor's Degree + (%)"
    }
    detail_vars = {"B19013_001E": "Median Income"}

    base = f"https://api.census.gov/data/{year}/acs/acs5"
    prof_url = f"{base}/profile"

    # Profile call
    prof_params = {
        "get": ",".join(profile_vars.keys()) + ",NAME",
        "for": "county subdivision:*",
        "in": "state:50"
    }
    prof = requests.get(prof_url, params=prof_params).json()
    prof_df = pd.DataFrame(prof[1:], columns=prof[0])

    # Detailed call
    det_params = {
        "get": ",".join(detail_vars.keys()) + ",NAME",
        "for": "county subdivision:*",
        "in": "state:50"
    }
    det = requests.get(base, params=det_params).json()
    det_df = pd.DataFrame(det[1:], columns=det[0])

    # Build GEOID
    prof_df["GEOID"] = prof_df["state"] + prof_df["county"] + prof_df["county subdivision"]
    det_df["GEOID"] = det_df["state"] + det_df["county"] + det_df["county subdivision"]

    # Merge
    df = prof_df.merge(det_df[["GEOID"] + list(detail_vars.keys())], on="GEOID", how="left")
    df = df.rename(columns={**profile_vars, **detail_vars, "NAME": "Town"})

    return df[["GEOID", "Town"] + list(profile_vars.values()) + list(detail_vars.values())]

# -------------------------
# Load & Merge
# -------------------------
gdf = fetch_town_boundaries()
acs = fetch_acs_data()
merged = gdf.merge(acs, left_on="GEOID", right_on="GEOID", how="left")

# -------------------------
# Build Table
# -------------------------
table = merged[["Town", "Median Income", "Unemployment Rate (%)",
                "Poverty Rate (%)", "Bachelor's Degree + (%)"]].copy()

# -------------------------
# Streamlit Layout
# -------------------------
st.title("🌄 Vermont Town Economic Dashboard")

col1, col2 = st.columns([1, 2])

# --- Left Column: Table ---
with col1:
    st.subheader("Town Economic Metrics")
    st.dataframe(table, use_container_width=True, hide_index=True)

# --- Right Column: Map ---
with col2:
    st.subheader("Map View (Median Income)")
    m = folium.Map(location=[44.0, -72.7], zoom_start=7, tiles="cartodbpositron")
    folium.Choropleth(
        geo_data=merged,
        data=merged,
        columns=["GEOID", "Median Income"],
        key_on="feature.properties.GEOID",
        fill_color="YlGnBu",
        fill_opacity=0.7,
        line_opacity=0.2,
        legend_name="Median Income (USD)"
    ).add_to(m)
    st_folium(m, width=700, height=600)

# -------------------------
# Sources
# -------------------------
st.markdown("""
---
**Sources:**  
- [U.S. Census Bureau, American Community Survey (ACS) 2023 5-year](https://data.census.gov/)  
- [Vermont Center for Geographic Information (VCGI)](https://vcgi.vermont.gov/)  
""")
