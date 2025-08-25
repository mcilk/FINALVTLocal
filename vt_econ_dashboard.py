import streamlit as st
import pandas as pd
import geopandas as gpd
import requests
from io import StringIO
import folium
from streamlit_folium import st_folium

st.set_page_config(layout="wide", page_title="Vermont Local Economic Dashboard")

# -------------------------------------------------------------------
# Vermont Town Boundaries Feature Service (working as of Aug 2025)
# -------------------------------------------------------------------
VCGI_TOWN_FEATURESERVICE = (
    "https://services.arcgis.com/pwNwIGBE7M7VOXjQ/"
    "arcgis/rest/services/VT_Town_Boundaries__VCGI_/FeatureServer/0/query"
)

# -------------------------------------------------------------------
# Fetch Vermont Town Boundaries
# -------------------------------------------------------------------
@st.cache_data
def fetch_vcgi_town_boundaries():
    params = {
        "where": "1=1",
        "outFields": "*",
        "f": "geojson"
    }
    try:
        r = requests.get(VCGI_TOWN_FEATURESERVICE, params=params, timeout=60)
        r.raise_for_status()
        gdf = gpd.read_file(StringIO(r.text))
        return gdf
    except Exception as e:
        st.error(f"Could not fetch Vermont town boundaries: {e}")
        return gpd.GeoDataFrame()  # return empty GeoDataFrame if fetch fails

# -------------------------------------------------------------------
# Placeholder for economic + policy data
# (replace this later with real data sources)
# -------------------------------------------------------------------
def load_economic_data():
    # Example dummy dataset
    data = {
        "town": ["Burlington", "Montpelier", "Rutland", "Brattleboro"],
        "population": [44000, 7900, 15500, 12000],
        "median_income": [55000, 60000, 48000, 45000],
        "unemployment_rate": [3.2, 2.8, 4.1, 3.7],
        "policy_initiatives": [
            "Affordable housing, Green energy grants",
            "Small business support program",
            "Downtown revitalization fund",
            "Arts & cultural tourism support"
        ]
    }
    return pd.DataFrame(data)

# -------------------------------------------------------------------
# Build Folium Map
# -------------------------------------------------------------------
def make_map(town_gdf, econ_df):
    m = folium.Map(location=[44.0, -72.7], zoom_start=7, tiles="cartodbpositron")

    if town_gdf.empty:
        return m

    merged = town_gdf.merge(econ_df, how="left", left_on="TOWNNAME", right_on="town")

    for _, row in merged.iterrows():
        if row["geometry"] is None:
            continue

        popup_html = f"""
        <b>{row.get('town', row['TOWNNAME'])}</b><br>
        Population: {row.get('population', 'N/A')}<br>
        Median Income: {row.get('median_income', 'N/A')}<br>
        Unemployment Rate: {row.get('unemployment_rate', 'N/A')}%<br>
        Policies: {row.get('policy_initiatives', 'N/A')}
        """
        folium.GeoJson(
            row["geometry"],
            name=row.get("town", row["TOWNNAME"]),
            tooltip=row.get("town", row["TOWNNAME"]),
            popup=popup_html
        ).add_to(m)

    return m

# -------------------------------------------------------------------
# Streamlit App Layout
# -------------------------------------------------------------------
st.title("📊 Vermont Local Economic Dashboard")
st.write("Explore economic data and policy initiatives by Vermont town.")

with st.spinner("Loading Vermont town boundaries..."):
    gdf = fetch_vcgi_town_boundaries()

econ_df = load_economic_data()

col1, col2 = st.columns([2, 1])

with col1:
    m = make_map(gdf, econ_df)
    st_folium(m, width=900, height=600)

with col2:
    st.subheader("Town Data")
    st.dataframe(econ_df)

    st.markdown("### Sources")
    st.markdown(
        "- Vermont Center for Geographic Information (VCGI) "
        "[Town Boundaries Service](https://services.arcgis.com/pwNwIGBE7M7VOXjQ/arcgis/rest/services/VT_Town_Boundaries__VCGI_/FeatureServer/0)"
    )
    st.markdown(
        "- Placeholder economic data — replace with official datasets "
        "(e.g., Census Bureau, Vermont Department of Labor, town websites)"
    )
