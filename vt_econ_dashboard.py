import streamlit as st
import geopandas as gpd
import pandas as pd
import requests
import folium
from io import StringIO
from streamlit_folium import st_folium

# -----------------------------
# Streamlit Page Configuration
# -----------------------------
st.set_page_config(layout="wide", page_title="Vermont Town Economic Dashboard")

# Custom CSS for background image
st.markdown(
    """
    <style>
    .stApp {
        background-image: url('https://upload.wikimedia.org/wikipedia/commons/6/6e/Green_Mountains_in_Vermont.jpg');
        background-size: cover;
        background-attachment: fixed;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🏔 Vermont Town Economic Dashboard")

# -----------------------------
# 1. Fetch VCGI Town Boundaries
# -----------------------------
@st.cache_data
def fetch_town_boundaries():
    service_url = (
        "https://services.arcgis.com/pwNwIGBE7M7VOXjQ/"
        "arcgis/rest/services/VT_Town_Boundaries__VCGI_/FeatureServer/0/query"
    )
    params = {"where": "1=1", "outFields": "*", "f": "geojson"}
    resp = requests.get(service_url, params=params)
    resp.raise_for_status()
    gdf = gpd.read_file(resp.text)
    return gdf

gdf = fetch_town_boundaries()

# Identify correct GEOID field
possible_geoid_fields = ["GEOID", "GEOID10", "TOWN_GEOID", "TOWNID", "FIPS"]
geoid_field = next((f for f in possible_geoid_fields if f in gdf.columns), None)
if not geoid_field:
    st.error(f"No GEOID-like column found in boundaries data. Columns: {list(gdf.columns)}")
    st.stop()

gdf = gdf.rename(columns={geoid_field: "GEOID"})

# -----------------------------
# 2. Fetch ACS Data
# -----------------------------
@st.cache_data
def fetch_acs_data(year=2023):
    profile_vars = {
        "DP03_0009PE": "Unemployment Rate (%)",
        "DP03_0119PE": "Poverty Rate (%)",
        "DP02_0068PE": "Bachelor's Degree + (%)"
    }
    detail_vars = {
        "B19013_001E": "Median Income"
    }

    profile_url = f"https://api.census.gov/data/{year}/acs/acs5/profile"
    base_url = f"https://api.census.gov/data/{year}/acs/acs5"

    prof_params = {
        "get": ",".join(profile_vars.keys()) + ",NAME",
        "for": "county subdivision:*",
        "in": "state:50"
    }
    prof = requests.get(profile_url, params=prof_params).json()
    prof_df = pd.DataFrame(prof[1:], columns=prof[0])

    det_params = {
        "get": ",".join(detail_vars.keys()) + ",NAME",
        "for": "county subdivision:*",
        "in": "state:50"
    }
    det = requests.get(base_url, params=det_params).json()
    det_df = pd.DataFrame(det[1:], columns=det[0])

    prof_df["GEOID"] = prof_df["state"] + prof_df["county"] + prof_df["county subdivision"]
    det_df["GEOID"] = det_df["state"] + det_df["county"] + det_df["county subdivision"]

    df = prof_df.merge(
        det_df[["GEOID"] + list(detail_vars.keys())],
        on="GEOID",
        how="left"
    )
    df = df.rename(columns={**profile_vars, **detail_vars, "NAME": "Town"})
    return df[["GEOID", "Town"] + list(profile_vars.values()) + list(detail_vars.values())]

acs = fetch_acs_data()

# -----------------------------
# 3. Merge Boundary + ACS Data
# -----------------------------
merged = gdf.merge(acs, on="GEOID", how="left")

# Policy initiative placeholder links
policy_links = {
    "Burlington": "https://www.burlingtonvt.gov/",
    "Montpelier": "https://www.montpelier-vt.org/",
    "Rutland": "https://www.rutlandcity.org/",
    "Brattleboro": "https://www.brattleboro.org/",
}
merged["Policy Initiative"] = merged["Town"].map(policy_links).fillna("https://accd.vermont.gov/")

# -----------------------------
# 4. Layout: Table + Map
# -----------------------------
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Town Economic Metrics")

    df_table = merged[[
        "Town",
        "Median Income",
        "Unemployment Rate (%)",
        "Poverty Rate (%)",
        "Bachelor's Degree + (%)",
        "Policy Initiative"
    ]].copy()

    # Display as HTML table with clickable links
    df_table_display = df_table.copy()
    df_table_display["Policy Initiative"] = df_table_display["Policy Initiative"].apply(
        lambda x: f'<a href="{x}" target="_blank">View Policy</a>'
    )

    st.write(
        df_table_display.to_html(escape=False, index=False),
        unsafe_allow_html=True
    )

with col2:
    st.subheader("Median Income by Town (Map)")

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

    # Add popup for each town
    for _, row in merged.iterrows():
        if pd.notna(row["Median Income"]):
            folium.Marker(
                location=[row.geometry.centroid.y, row.geometry.centroid.x],
                popup=f"<b>{row['Town']}</b><br>Income: ${row['Median Income']:,}<br>"
                      f"Poverty: {row['Poverty Rate (%)']}%<br>"
                      f"<a href='{row['Policy Initiative']}' target='_blank'>Policy</a>"
            ).add_to(m)

    st_folium(m, width=700, height=600)

# -----------------------------
# 5. Attribution / Sources
# -----------------------------
st.markdown("---")
st.markdown("""
**Sources:**  
- [U.S. Census Bureau, ACS 2023 5-Year](https://www.census.gov/programs-surveys/acs)  
- [Vermont Center for Geographic Information (VCGI)](https://geodata.vermont.gov/)  
""")
