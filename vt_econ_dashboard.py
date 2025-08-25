import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
import requests
from io import StringIO

# --------------------------
# CONFIG
# --------------------------
st.set_page_config(page_title="Vermont Local Economic Dashboard", layout="wide")

# Background styling (Vermont Green Mountains theme)
st.markdown(
    """
    <style>
    .stApp {
        background-image: url('https://upload.wikimedia.org/wikipedia/commons/3/30/Green_Mountains_in_Vermont_2009.jpg');
        background-size: cover;
        background-attachment: fixed;
    }
    .block-container {
        background-color: rgba(255, 255, 255, 0.9);
        border-radius: 12px;
        padding: 2rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --------------------------
# FETCH VERMONT TOWN BOUNDARIES
# --------------------------
VCGI_TOWN_FEATURESERVICE = (
    "https://services.arcgis.com/pwNwIGBE7M7VOXjQ/"
    "arcgis/rest/services/VT_Town_Boundaries__VCGI_/FeatureServer/0/query"
)

@st.cache_data
def fetch_vcgi_town_boundaries():
    params = {
        "where": "1=1",
        "outFields": "*",
        "f": "geojson"
    }
    r = requests.get(VCGI_TOWN_FEATURESERVICE, params=params, timeout=60)
    r.raise_for_status()
    return gpd.read_file(StringIO(r.text))

# --------------------------
# LOAD DATA (placeholder demo data)
# --------------------------
@st.cache_data
def load_demo_data():
    data = {
        "Town": ["Burlington", "Montpelier", "Rutland", "Brattleboro"],
        "Population": [44000, 7900, 15500, 11800],
        "Median Income": [55000, 60000, 48000, 47000],
        "Unemployment Rate": [3.2, 2.8, 4.1, 3.9],
        "Policy Initiative": [
            "Affordable Housing Program",
            "Green Energy Transition",
            "Downtown Revitalization",
            "Small Business Grants",
        ],
        "Policy Link": [
            "https://www.burlingtonvt.gov/CEDO/Housing",
            "https://www.montpelier-vt.org/122/Energy-Committee",
            "https://www.rutlanddowntown.com/",
            "https://www.brattleboro.org/business",
        ]
    }
    return pd.DataFrame(data)

econ_df = load_demo_data()
gdf = fetch_vcgi_town_boundaries()

# --------------------------
# LAYOUT
# --------------------------
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Town Data")

    # Prepare display DataFrame
    df_display = econ_df.copy()
    df_display["Policy Initiative"] = df_display.apply(
        lambda row: f"[{row['Policy Initiative']}]({row['Policy Link']})", axis=1
    )
    df_display = df_display.drop(columns=["Policy Link"])

    # Show interactive table (no index, clean headers)
    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True
    )

with col2:
    st.subheader("Economic Map of Vermont Towns")

    # Create map
    m = folium.Map(location=[44.0, -72.7], zoom_start=7, tiles="cartodbpositron")

    # Add town boundaries
    folium.GeoJson(
        gdf,
        name="Vermont Towns",
        tooltip=folium.GeoJsonTooltip(fields=["TOWNNAME"], aliases=["Town:"]),
        style_function=lambda x: {
            "color": "green",
            "weight": 1,
            "fillOpacity": 0.1,
        },
    ).add_to(m)

    # Add markers for demo towns
    town_coords = {
        "Burlington": [44.4759, -73.2121],
        "Montpelier": [44.2601, -72.5754],
        "Rutland": [43.6106, -72.9726],
        "Brattleboro": [42.8509, -72.5579],
    }

    for _, row in econ_df.iterrows():
        town = row["Town"]
        if town in town_coords:
            folium.Marker(
                location=town_coords[town],
                popup=f"<b>{town}</b><br>Pop: {row['Population']}<br>"
                      f"Income: ${row['Median Income']:,}<br>"
                      f"Unemployment: {row['Unemployment Rate']}%<br>"
                      f"<a href='{row['Policy Link']}' target='_blank'>Policy: {row['Policy Initiative']}</a>",
                tooltip=town
            ).add_to(m)

    st_data = st_folium(m, width=700, height=500)

# --------------------------
# SOURCES
# --------------------------
st.markdown("### Sources")
st.markdown(
    """
    - [Vermont Center for Geographic Information (VCGI)](https://vcgi.vermont.gov/)
    - [US Census Bureau](https://data.census.gov/)
    - [Individual Town Economic Development Pages](https://www.vermont.gov/)
    """
)
