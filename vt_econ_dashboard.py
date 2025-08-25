# vt_econ_dashboard.py
# Streamlit dashboard to explore Vermont towns (county subdivisions) with ACS economic indicators
# and attach local policy/initiative links.
#
# How to run:
#   1) pip install streamlit geopandas pandas requests folium streamlit-folium shapely pyproj
#   2) (optional) export CENSUS_API_KEY=your_key_here  # get one at https://api.census.gov/data/key_signup.html
#   3) streamlit run vt_econ_dashboard.py
#
# Notes:
#  - Boundaries are pulled from Vermont's Open Geodata Portal (VCGI) Feature Service as GeoJSON.
#  - Economic data come from the ACS 5-year Data Profile and Detailed tables at the county subdivision (MCD) level.
#  - Policy links are loaded from an optional CSV (policy_links.csv) with columns: town, url, title, tags.
#  - You can extend with BLS LAUS monthly unemployment by merging a prepared CSV keyed by MCD GEOID (060).

import os
import io
import json
import time
import textwrap
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape

import streamlit as st
from streamlit_folium import st_folium
import folium

APP_TITLE = "Vermont Town & City Economic Explorer"
STATE_FIPS = "50"  # Vermont
DEFAULT_ACS_YEAR = 2023  # latest 5-year available as of 2025
ACCEPTABLE_YEARS = list(range(2017, 2024))  # 2017–2023 inclusive

# ----------------------
# Data sources (official)
# ----------------------
VCGI_TOWN_FEATURESERVICE = (
    "https://geodata.vermont.gov/arcgis/rest/services/VCGI/VT_Data_Boundaries/FeatureServer/9/query"
)
# Layer 9 = Town Boundaries (current as of portal config). If the layer id changes, you can browse the portal item and update.
# Query parameters for full GeoJSON
VCGI_QUERY_PARAMS = {
    "where": "1=1",
    "outFields": "*",
    "f": "geojson",
}

CENSUS_BASE = "https://api.census.gov/data/{year}/acs/acs5"
CENSUS_PROFILE = "https://api.census.gov/data/{year}/acs/acs5/profile"

# Variables (you can add more)
ACS_VARS_DETAILED = {
    # Median household income (inflation-adjusted dollars of ACS year)
    "B19013_001E": "Median household income ($)",
}
ACS_VARS_PROFILE = {
    # Unemployment rate (percent, civilian labor force)
    "DP03_0009PE": "Unemployment rate (%)",
    # Bachelor's degree or higher (percent of 25+)
    "DP02_0068PE": "Bachelor's degree or higher (%)",
    # Poverty rate (percent of population in poverty)
    "DP03_0119PE": "Individuals in poverty (%)",  # Note: DP03_0119PE is common; if it changes in later years, adjust.
}

# ----------------------
# Helpers
# ----------------------
@st.cache_data(show_spinner=False, ttl=60*60)
def fetch_vcgi_town_boundaries() -> gpd.GeoDataFrame:
    """Fetch Vermont town boundaries from VCGI as GeoJSON and return a GeoDataFrame.
    The returned data include TOWNNAME and FIPS codes where available. We will build a GEOID (060) key as state(2)+county(3)+cousub(5).
    """
    params = VCGI_QUERY_PARAMS.copy()
    r = requests.get(VCGI_TOWN_FEATURESERVICE, params=params, timeout=60)
    r.raise_for_status()
    gj = r.json()
    # Convert to GeoDataFrame
    features = gj.get("features", [])
    records = []
    geoms = []
    for f in features:
        props = f.get("properties", {})
        geom = f.get("geometry")
        if geom:
            geoms.append(shape(geom))
            records.append(props)
    gdf = gpd.GeoDataFrame(pd.DataFrame(records), geometry=geoms, crs="EPSG:4326")

    # Normalize key fields
    # Many VCGI layers expose attributes like TOWNNAME, COUNTY, TOWNCODE or FIPS6. We'll try common ones.
    # We'll build GEOID (060) if we can: state(50) + county (3-digit) + county subdivision (5-digit)
    # If exact codes are missing, we will join by town name later.
    # Create helper lowercase for joins
    for col in ["TOWNNAME", "TOWN", "NAME", "CNTYNAME", "COUNTY", "CO_NAME", "CO_FIPS", "TOWNCODE", "FIPS6", "GEOID"]:
        if col not in gdf.columns:
            gdf[col] = None
    gdf["town_clean"] = (
        gdf[["TOWNNAME", "TOWN", "NAME"]]
        .bfill(axis=1)
        .iloc[:, 0]
        .astype(str)
        .str.strip()
        .str.lower()
    )
    gdf["county_clean"] = (
        gdf[["CNTYNAME", "COUNTY", "CO_NAME"]]
        .bfill(axis=1)
        .iloc[:, 0]
        .astype(str)
        .str.strip()
        .str.lower()
    )
    return gdf


def _census_get(url: str, params: dict) -> pd.DataFrame:
    params = params.copy()
    key = os.getenv("CENSUS_API_KEY")
    if key:
        params["key"] = key
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    rows = r.json()
    cols = rows[0]
    data = rows[1:]
    return pd.DataFrame(data, columns=cols)


@st.cache_data(show_spinner=False, ttl=60*60)
def fetch_acs_profile(year: int) -> pd.DataFrame:
    """Fetch ACS profile variables at county subdivision (MCD) level for Vermont."""
    vars_ = ",".join(list(ACS_VARS_PROFILE.keys()))
    params = {
        "get": vars_ + ",NAME,place",
        # Use county subdivision (MCD) geography for New England towns
        "for": "county subdivision:*",
        "in": f"state:{STATE_FIPS}",
    }
    df = _census_get(CENSUS_PROFILE.format(year=year), params)
    # Add 060 GEOID
    # county subdivision responses also include county; some endpoints include county field; ensure presence
    if "county" not in df.columns:
        # older profile endpoints sometimes omit county; try detailed endpoint to get county codes or leave blank
        df["county"] = None
    df["GEOID"] = STATE_FIPS + df.get("county", "").fillna("") + df["county subdivision"]
    # Cast numeric fields
    for v in ACS_VARS_PROFILE.keys():
        df[v] = pd.to_numeric(df[v], errors="coerce")
    return df


@st.cache_data(show_spinner=False, ttl=60*60)
def fetch_acs_detailed(year: int) -> pd.DataFrame:
    vars_ = ",".join(list(ACS_VARS_DETAILED.keys()))
    params = {
        "get": vars_ + ",NAME",
        "for": "county subdivision:*",
        "in": f"state:{STATE_FIPS}",
    }
    df = _census_get(CENSUS_BASE.format(year=year), params)
    if "county" not in df.columns:
        df["county"] = None
    df["GEOID"] = STATE_FIPS + df.get("county", "").fillna("") + df["county subdivision"]
    for v in ACS_VARS_DETAILED.keys():
        df[v] = pd.to_numeric(df[v], errors="coerce")
    return df


@st.cache_data(show_spinner=False, ttl=60*60)
def load_policy_links(path: str = "policy_links.csv") -> pd.DataFrame:
    """Load a CSV of policy links with columns: town, url, title, tags.
    If not found, return a seeded sample for a few places to demonstrate the UI.
    """
    if os.path.exists(path):
        df = pd.read_csv(path)
        for col in ["town", "url", "title", "tags"]:
            if col not in df.columns:
                df[col] = None
    else:
        df = pd.DataFrame(
            [
                {
                    "town": "Burlington",
                    "url": "https://www.burlingtonvt.gov/157/Community-Economic-Development-Office-CE",
                    "title": "Community & Economic Development Office (CEDO)",
                    "tags": "strategic-plan,housing,workforce",
                },
                {
                    "town": "Montpelier",
                    "url": "https://www.montpelier-vt.org/602/Economic-Development",
                    "title": "City Economic Development (links & plan)",
                    "tags": "strategic-plan,grants,regional",
                },
                {
                    "town": "Rutland",
                    "url": "https://www.rutlandvtbusiness.com/",
                    "title": "Rutland Redevelopment Authority (RRA)",
                    "tags": "redevelopment,tif,small-business",
                },
                {
                    "town": "South Burlington",
                    "url": "https://www.southburlingtonvt.gov/595/Economic-Development-Strategic-Plan",
                    "title": "Economic Development Strategic Plan",
                    "tags": "strategic-plan,engagement",
                },
                {
                    "town": "Essex",
                    "url": "https://www.essexvt.gov/1469/ECONOMIC-DEVELOPMENT-STUDY",
                    "title": "Economic Development Study",
                    "tags": "study,priorities",
                },
            ]
        )
    df["town_clean"] = df["town"].astype(str).str.strip().str.lower()
    return df


# ----------------------
# UI & App
# ----------------------
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)
st.caption(
    "Explore ACS economic indicators for Vermont county subdivisions (towns & cities). "
    "Click a place on the map or use the list to see metrics and policy links."
)

colA, colB = st.columns([3, 2])

with st.sidebar:
    st.header("Controls")
    acs_year = st.selectbox("ACS 5-year dataset year", ACCEPTABLE_YEARS, index=ACCEPTABLE_YEARS.index(DEFAULT_ACS_YEAR))
    metric = st.selectbox(
        "Choropleth metric",
        [
            ("Unemployment rate (%)", "DP03_0009PE"),
            ("Median household income ($)", "B19013_001E"),
            ("Bachelor's degree or higher (%)", "DP02_0068PE"),
            ("Individuals in poverty (%)", "DP03_0119PE"),
        ],
        index=0,
        format_func=lambda x: x[0],
    )
    display_label, metric_var = metric
    st.markdown(
        "**Tip**: Add your own policy links by placing a `policy_links.csv` with columns `town,url,title,tags` in the app folder."
    )

# Fetch data
with st.spinner("Loading town boundaries from VCGI…"):
    gdf = fetch_vcgi_town_boundaries()

with st.spinner("Fetching ACS data…"):
    prof = fetch_acs_profile(acs_year)
    detl = fetch_acs_detailed(acs_year)
    acs = prof.merge(detl[["GEOID"] + list(ACS_VARS_DETAILED.keys())], on="GEOID", how="left")

# Join: try by GEOID first; fall back to name join
# Note: If VCGI attributes include GEOID (060), this will be perfect; otherwise, we'll fuzzy join by town name.
if "GEOID" in gdf.columns and gdf["GEOID"].notna().any():
    joined = gdf.merge(acs, on="GEOID", how="left")
else:
    # build town name from ACS NAME like "Burlington town, Chittenden County, Vermont"
    acs_temp = acs.copy()
    acs_temp["town_clean"] = (
        acs_temp["NAME"].str.extract(r"^(.*?)(?:\s+(?:town|city|gore|grant|plantation))?,\s+")
    )
    acs_temp["town_clean"] = acs_temp["town_clean"].fillna(acs_temp["NAME"]).str.lower()
    joined = gdf.merge(acs_temp, on="town_clean", how="left")

# Load policy links and attach
pol = load_policy_links()
# Token-join by lowercase town name
joined = joined.merge(pol[["town_clean", "url", "title", "tags"]], on="town_clean", how="left")

# Prepare map dataframe
map_df = joined.copy()

# Build Folium Map
m = folium.Map(location=[44.0, -72.7], zoom_start=7, tiles="cartodbpositron")

# Choropleth
# Convert to GeoJSON string to avoid serialization issues
gjson = json.loads(map_df.to_json())

# Build a properties dict keyed by a stable id
# Use either GEOID or town name as key
id_field = "GEOID" if "GEOID" in map_df.columns and map_df["GEOID"].notna().any() else "town_clean"

# Build data frame for choropleth
choropleth_df = map_df[[id_field, metric_var]].copy()
choropleth_df[metric_var] = pd.to_numeric(choropleth_df[metric_var], errors="coerce")

# Create choropleth layer
folium.Choropleth(
    geo_data=gjson,
    data=choropleth_df,
    columns=[id_field, metric_var],
    key_on=f"feature.properties.{id_field}",
    fill_opacity=0.75,
    line_opacity=0.5,
    nan_fill_opacity=0.15,
    legend_name=display_label,
).add_to(m)

# Add tooltips/popups
tooltip_fields = [
    ("Town", "town_clean"),
    ("County subdivision GEOID", "GEOID"),
    ("Unemployment (%)", "DP03_0009PE"),
    ("Median income ($)", "B19013_001E"),
    ("BA+ (%)", "DP02_0068PE"),
    ("Poverty (%)", "DP03_0119PE"),
]

for _, row in map_df.iterrows():
    geom = row.geometry
    if geom is None or geom.is_empty:
        continue
    centroid = list(geom.representative_point().coords)[0][::-1]  # lat, lon
    
    # Build HTML popup
    town_label = str(row.get("TOWNNAME") or row.get("TOWN") or row.get("NAME") or row.get("town_clean", "")).title()
    vals = []
    for label, col in tooltip_fields:
        val = row.get(col)
        if pd.isna(val):
            continue
        if col in ("DP03_0009PE", "DP02_0068PE", "DP03_0119PE"):
            val = f"{val:,.1f}"
        elif col == "B19013_001E":
            val = f"${val:,.0f}"
        vals.append(f"<b>{label}:</b> {val}")

    # Add policy link if present
    if pd.notna(row.get("url")):
        vals.append(f"<a href=\"{row['url']}\" target=\"_blank\">{row.get('title','Policy/Initiative link')}</a>")

    html = f"<div style='font-size:14px'><b>{town_label}</b><br>" + "<br>".join(vals) + "</div>"
    folium.Marker(
        location=centroid,
        tooltip=town_label,
        popup=folium.Popup(html, max_width=350),
        icon=folium.Icon(icon="info-sign"),
    ).add_to(m)

with colA:
    st.subheader("Map")
    st_folium(m, height=640, use_container_width=True)

# Right pane: searchable list
with colB:
    st.subheader("Places list & details")
    # Build a tidy table
    table_cols = [
        ("Place", "NAME"),
        ("Unemp %", "DP03_0009PE"),
        ("Median income", "B19013_001E"),
        ("BA+ %", "DP02_0068PE"),
        ("Poverty %", "DP03_0119PE"),
        ("Policy title", "title"),
        ("Policy link", "url"),
    ]
    tidy = joined[[c for _, c in table_cols]].copy()
    # Format numbers for display but keep raw columns for sorting
    tidy_fmt = tidy.copy()
    if not tidy_fmt.empty:
        if "DP03_0009PE" in tidy_fmt:
            tidy_fmt["DP03_0009PE"] = pd.to_numeric(tidy_fmt["DP03_0009PE"], errors="coerce").map(lambda x: f"{x:,.1f}" if pd.notna(x) else "")
        if "B19013_001E" in tidy_fmt:
            tidy_fmt["B19013_001E"] = pd.to_numeric(tidy_fmt["B19013_001E"], errors="coerce").map(lambda x: f"${x:,.0f}" if pd.notna(x) else "")
        if "DP02_0068PE" in tidy_fmt:
            tidy_fmt["DP02_0068PE"] = pd.to_numeric(tidy_fmt["DP02_0068PE"], errors="coerce").map(lambda x: f"{x:,.1f}" if pd.notna(x) else "")
        if "DP03_0119PE" in tidy_fmt:
            tidy_fmt["DP03_0119PE"] = pd.to_numeric(tidy_fmt["DP03_0119PE"], errors="coerce").map(lambda x: f"{x:,.1f}" if pd.notna(x) else "")

    # Show
    st.dataframe(
        tidy_fmt.rename(columns={c: l for l, c in table_cols}),
        use_container_width=True,
        height=640,
    )

st.divider()
with st.expander("About the data & how to extend", expanded=False):
    st.markdown(
        """
        **Boundaries**: Vermont town/city boundaries are loaded directly from the VCGI ArcGIS Feature Service (Town Boundaries). If the service changes its layer ID,
        update `VCGI_TOWN_FEATURESERVICE`.

        **ACS metrics** (latest 5-year): pulled at the *county subdivision* level (Minor Civil Divisions used in New England — i.e., towns/cities). Variables used:

        - `DP03_0009PE` — Unemployment rate (percent of civilian labor force). Source: ACS Data Profile.
        - `B19013_001E` — Median household income (dollars). Source: ACS Detailed table B19013.
        - `DP02_0068PE` — Bachelor's degree or higher (percent of population 25+). Source: ACS Data Profile.
        - `DP03_0119PE` — Individuals in poverty (percent). Source: ACS Data Profile (adjust if code changes in a later year).

        **Policy links**: Provide a file `policy_links.csv` with columns `town,url,title,tags`. These appear in popups and the list.

        **Tips**:
        - To add more ACS indicators, append codes to `ACS_VARS_PROFILE` or `ACS_VARS_DETAILED` and they will appear in the map/table once referenced.
        - To add BLS LAUS monthly unemployment for towns, prepare a CSV keyed by `GEOID` (060) or by name, then merge into `joined`.
        - For reproducible joins, prefer GEOID-based merges; name-based joins can be ambiguous for villages/gores.
        """
    )

