import streamlit as st
import pandas as pd
import geopandas as gpd
import requests
from io import StringIO
import folium
from streamlit_folium import st_folium

# --------------------------------------------------------
# Page config + background
# --------------------------------------------------------
st.set_page_config(layout="wide", page_title="Vermont Local Economic Dashboard")

# Background image CSS
st.markdown(
    """
    <style>
    .stApp {
        background-image: url("https://upload.wikimedia.org/wikipedia/commons/8/87/Green_Mountains_-_Vermont.jpg");
        background-attachment: fixed;
        background-size: cover;
        background-position: center;
    }
    .block-container {
        background-color: rgba(255, 255, 255, 0.9);
        padding: 2rem;
        border-radius: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --------------------------------------------------------
# Vermont Town Boundaries
# --------------------------------------------------------
VCGI_TOWN_FEATURESERVICE = (
    "https://services.arcgis.com/pwNwIGBE7M7VOXjQ/"
    "arcgis/rest/services/VT_Town_Boundaries__VCGI_/FeatureServer/0/query"
)

@st.cache_data
def fetch_vcgi_town_boundaries():
    params = {"where": "1=1", "outFields": "*", "f": "geojson"}
    r = requests.get(VCGI_TOWN_FEATURESERVICE, params=params, timeout=60)
    r.raise_for_status()
    return gpd.read_file(StringIO(r.text))

# --------------------------------------------------------
# Example Economic + Policy Data
# --------------------------------------------------------
def load_economic_data():
    data = {
        "Town": ["Burlington", "Montpelier", "Rutland", "Brattleboro"],
        "Population": [44000, 7900, 15500, 12000],
        "Median Income": [55000, 60000, 48000, 45000],
        "Unemployment Rate": [3.2, 2.8, 4.1, 3.7],
        "Policy Link": [
            "https://www.burlingtonvt.gov/CEDO",
            "https://montpelier-vt.org/",
            "https://www.rutlandcity.org/",
            "https://www.brattleboro.org/"
        ],
        "Policy Initiatives": [
            "Affordable housing, Green energy grants",
            "Small business support program",
            "Downtown revitalization fund",
            "Arts & cultural tourism support"
        ]
    }
    df = pd.DataFrame(data)
    return df

# --------------------------------------------------------
# Build Map
# --------------------------------------------------------
def make_map(town_gdf, econ_df):
    m = folium.Map(location=[44.0, -72.7], zoom_start=7, tiles="cartodbpositron")

    merged = town_gdf.merge(econ_df, how="left", left_on="TOWNNAME", right_on="Town")

    for _, row in merged.iterrows():
        if row["geometry"] is None:
            continue

        popup_html = f"""
        <b>{row.get('Town')}</b><br>
        Population: {row.get('Population', 'N/A')}<br>
        Median Income: {row.get('Median Income', 'N/A')}<br>
        Unemployment Rate: {row.get('Unemployment Rate', 'N/A')}%<br>
        <a href="{row.get('Policy Link', '#')}" target="_blank">Policy Website</a><br>
        Initiatives: {row.get('Policy Initiatives', 'N/A')}
        """
        folium.GeoJson(
            row["geometry"],
            name=row.get("Town"),
            tooltip=row.get("Town"),
            popup=popup_html
        ).add_to(m)

    return m

# --------------------------------------------------------
# Streamlit App Layout
# --------------------------------------------------------
st.title("📊 Vermont Local Economic Dashboard")
st.write("Explore economic data and policy initiatives by Vermont town.")

with st.spinner("Loading Vermont town boundaries..."):
    gdf = fetch_vcgi_town_boundaries()

econ_df = load_economic_data()

# --- Layout: table on left, map on right
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Town Data")

    # Remove index col, add policy link column
    df_display = econ_df.copy()
    df_display["Policy Link"] = df_display["Policy Link"].apply(
        lambda url: f"[Link]({url})"
    )

    # Display as markdown table
    st.markdown(df_display.to_markdown(index=False), unsafe_allow_html=True)

with col2:
    st.subheader("Interactive Map")
    m = make_map(gdf, econ_df)
    st_folium(m, width=900, height=650)

# --- Sources section
st.markdown("---")
st.markdown("### Sources")
st.markdown(
    "- Vermont Center for Geographic Information (VCGI): "
    "[Town Boundaries Service](https://services.arcgis.com/pwNwIGBE7M7VOXjQ/arcgis/rest/services/VT_Town_Boundaries__VCGI_/FeatureServer/0)"
)
st.markdown(
    "- Placeholder economic data — replace with official datasets: "
    "[US Census ACS](https://data.census.gov/) | "
    "[Vermont Department of Labor](https://labor.vermont.gov/) | "
    "[Town/City Websites](https://www.vermont.gov/municipalities)"
)
