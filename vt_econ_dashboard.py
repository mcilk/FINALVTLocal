import streamlit as st
import geopandas as gpd
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

# ----------------------
# Page Setup
# ----------------------
st.set_page_config(layout="wide", page_title="Vermont Economic Dashboard")
st.markdown(
    """
    <style>
    body {
        background-image: url('https://upload.wikimedia.org/wikipedia/commons/thumb/7/7d/Green_Mountains_in_Vermont.JPG/1920px-Green_Mountains_in_Vermont.JPG');
        background-size: cover;
    }
    .block-container {
        background-color: rgba(255, 255, 255, 0.85);
        border-radius: 15px;
        padding: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🌄 Vermont Town Economic Dashboard")

# ----------------------
# Fetch Town Boundaries
# ----------------------
@st.cache_data
def fetch_town_boundaries():
    url = (
        "https://services.arcgis.com/pwNwIGBE7M7VOXjQ/"
        "arcgis/rest/services/VT_Town_Boundaries__VCGI_/FeatureServer/0/query"
    )
    params = {"where": "1=1", "outFields": "*", "f": "geojson"}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    gdf = gpd.read_file(r.text)
    gdf.rename(columns={"TOWNNAME": "Town"}, inplace=True)
    if "FIPS6" in gdf.columns:
        gdf.rename(columns={"FIPS6": "GEOID"}, inplace=True)
    return gdf

gdf = fetch_town_boundaries()

# ----------------------
# Fetch ACS Data
# ----------------------
@st.cache_data
def fetch_acs_data(year=2023):
    vars_profile = {
        "DP03_0009PE": "Unemployment (%)",
        "DP03_0119PE": "Poverty (%)",
    }
    vars_detail = {
        "B19013_001E": "Median Income ($)",
    }

    base = f"https://api.census.gov/data/{year}/acs/acs5"
    prof = f"{base}/profile"

    prof_params = {
        "get": "NAME," + ",".join(vars_profile.keys()),
        "for": "county subdivision:*",
        "in": "state:50",
    }
    prof_resp = requests.get(prof, params=prof_params).json()
    prof_df = pd.DataFrame(prof_resp[1:], columns=prof_resp[0])

    detail_params = {
        "get": ",".join(vars_detail.keys()),
        "for": "county subdivision:*",
        "in": "state:50",
    }
    det_resp = requests.get(base, params=detail_params).json()
    det_df = pd.DataFrame(det_resp[1:], columns=det_resp[0])

    prof_df["GEOID"] = prof_df["state"] + prof_df["county"] + prof_df["county subdivision"]
    det_df["GEOID"] = det_df["state"] + det_df["county"] + det_df["county subdivision"]

    df = prof_df.merge(det_df[["GEOID"] + list(vars_detail.keys())], on="GEOID")
    df.rename(columns={**vars_profile, **vars_detail, "NAME": "TownFull"}, inplace=True)

    # Clean town names to match boundaries
    df["Town"] = df["TownFull"].str.replace(" town, Vermont", "", regex=False)
    df["Town"] = df["Town"].str.replace(" gore, Vermont", "", regex=False)
    df["Town"] = df["Town"].str.replace(" grant, Vermont", "", regex=False)

    return df[["GEOID", "Town"] + list(vars_profile.values()) + list(vars_detail.values())]

acs = fetch_acs_data()

# ----------------------
# Merge boundaries + ACS
# ----------------------
merged = gdf.merge(acs, on="Town", how="left")

# Add example policy initiatives
policy_links = {
    "Burlington": "https://www.burlingtonvt.gov/CEDO/Economic-Development",
    "Montpelier": "https://www.montpelier-vt.org/31/Economic-Development",
    "Brattleboro": "https://brattleboro.org/business/",
}
merged["Policy Link"] = merged["Town"].map(policy_links).fillna("https://accd.vermont.gov/economic-development")

# ----------------------
# Layout: Table + Map
# ----------------------
col1, col2 = st.columns([1.2, 2.5])

with col1:
    st.subheader("📋 Economic Metrics by Town")
    table = merged[["Town", "Median Income ($)", "Unemployment (%)", "Poverty (%)", "Policy Link"]].copy()
    table.rename(columns={
        "Town": "Town",
        "Median Income ($)": "Median Income ($)",
        "Unemployment (%)": "Unemployment (%)",
        "Poverty (%)": "Poverty (%)",
        "Policy Link": "Policy Initiatives"
    }, inplace=True)

    # Convert policy links to clickable HTML
    table["Policy Initiatives"] = table["Policy Initiatives"].apply(lambda x: f'<a href="{x}" target="_blank">Link</a>')

    st.write(
        table.to_html(escape=False, index=False),
        unsafe_allow_html=True
    )

with col2:
    st.subheader("🗺️ Map of Vermont Towns (Median Income)")
    m = folium.Map(location=[44.0, -72.7], zoom_start=7, tiles="cartodbpositron")

    folium.Choropleth(
        geo_data=merged.__geo_interface__,
        data=merged,
        columns=["Town", "Median Income ($)"],
        key_on="feature.properties.Town",
        fill_color="YlGnBu",
        fill_opacity=0.8,
        line_opacity=0.3,
        legend_name="Median Income ($)",
    ).add_to(m)

    folium.LayerControl().add_to(m)
    st_folium(m, width=750, height=650)

# ----------------------
# Footer
# ----------------------
st.markdown("---")
st.markdown(
    """
    **Sources:**  
    - [U.S. Census Bureau - ACS 5-year Data](https://data.census.gov/)  
    - [Vermont Center for Geographic Information (VCGI)](https://vcgi.vermont.gov/)  
    """
)
