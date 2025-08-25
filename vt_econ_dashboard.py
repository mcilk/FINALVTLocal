import streamlit as st
import geopandas as gpd
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

st.set_page_config(layout="wide")

# -------------------
# DATA FUNCTIONS
# -------------------

@st.cache_data
def fetch_vcgi_town_boundaries():
    """Fetch official Vermont town boundaries from VCGI GeoData service."""
    url = "https://services1.arcgis.com/1yYz4jU0hRIhL1jX/arcgis/rest/services/VT_Town_Boundaries/FeatureServer/0/query"
    params = {
        "where": "1=1",
        "outFields": "*",
        "f": "geojson"
    }
    r = requests.get(url, params=params)
    r.raise_for_status()
    gdf = gpd.read_file(r.text)
    gdf = gdf.rename(columns={"TOWNNAME": "Town Name"})
    # Create GEOID to join with Census
    gdf["GEOID"] = gdf["TOWNID"].astype(str).str.zfill(5)
    return gdf


@st.cache_data
def fetch_acs_town_data(year=2022):
    """Fetch ACS economic indicators for all Vermont towns (county subdivisions)."""
    profile_vars = {
        "DP03_0009PE": "Unemployment Rate (%)",
        "DP03_0119PE": "Poverty Rate (%)",
        "DP02_0068PE": "Bachelor's Degree or Higher (%)"
    }
    detailed_vars = {
        "B19013_001E": "Median Household Income"
    }

    base_url = f"https://api.census.gov/data/{year}/acs/acs5"
    profile_url = f"{base_url}/profile"

    # Profile request
    prof_params = {
        "get": ",".join(profile_vars.keys()) + ",NAME",
        "for": "county subdivision:*",
        "in": "state:50"   # Vermont FIPS = 50
    }
    prof_r = requests.get(profile_url, params=prof_params)
    prof_r.raise_for_status()
    prof_json = prof_r.json()
    prof_df = pd.DataFrame(prof_json[1:], columns=prof_json[0])

    # Detailed request
    det_params = {
        "get": ",".join(detailed_vars.keys()) + ",NAME",
        "for": "county subdivision:*",
        "in": "state:50"
    }
    det_r = requests.get(base_url, params=det_params)
    det_r.raise_for_status()
    det_json = det_r.json()
    det_df = pd.DataFrame(det_json[1:], columns=det_json[0])

    # GEOID construction
    prof_df["GEOID"] = prof_df["state"] + prof_df["county"] + prof_df["county subdivision"]
    det_df["GEOID"] = det_df["state"] + det_df["county"] + det_df["county subdivision"]

    df = prof_df.merge(det_df[["GEOID"] + list(detailed_vars.keys())], on="GEOID", how="left")

    # Rename columns
    df = df.rename(columns={**profile_vars, **detailed_vars, "NAME": "Town Name"})
    return df


# -------------------
# MAIN APP
# -------------------

st.markdown(
    """
    <style>
    .stApp {
        background-image: url('https://upload.wikimedia.org/wikipedia/commons/2/25/Green_Mountains%2C_Vermont.jpg');
        background-size: cover;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("📊 Vermont Towns Economic Dashboard")

# Load boundary + ACS data
gdf = fetch_vcgi_town_boundaries()
acs_df = fetch_acs_town_data()

# Merge
merged = gdf.merge(acs_df, on="GEOID", how="left")

# Clean table for display
table_df = merged[[
    "Town Name",
    "Median Household Income",
    "Unemployment Rate (%)",
    "Poverty Rate (%)",
    "Bachelor's Degree or Higher (%)"
]].copy()

table_df.columns = ["Town", "Median Income", "Unemployment Rate", "Poverty Rate", "Bachelor's Degree +"]

# -------------------
# LAYOUT
# -------------------
col1, col2 = st.columns([1.2, 2])

with col1:
    st.subheader("📋 Town Economic Data")
    st.dataframe(table_df, use_container_width=True, hide_index=True)

with col2:
    st.subheader("🗺️ Vermont Town Map")
    # Create map
    vt_map = folium.Map(location=[44.0, -72.7], zoom_start=7, tiles="cartodbpositron")
    folium.GeoJson(
        merged,
        name="Towns",
        tooltip=folium.features.GeoJsonTooltip(
            fields=["Town Name", "Median Household Income", "Unemployment Rate (%)"],
            aliases=["Town", "Median Income", "Unemployment Rate"],
            localize=True
        )
    ).add_to(vt_map)

    st_folium(vt_map, width=700, height=600)

# -------------------
# SOURCES
# -------------------
st.markdown("### 📚 Sources")
st.markdown(
    """
    - [U.S. Census Bureau ACS](https://data.census.gov/)  
    - [Vermont Center for Geographic Information (VCGI)](https://geodata.vermont.gov/)  
    """
)
