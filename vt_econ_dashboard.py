# vt_econ_dashboard.py
import os
import json
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape
import streamlit as st
from streamlit_folium import st_folium
import folium

# -----------------------------
# Streamlit Page Configuration
# -----------------------------
st.set_page_config(layout="wide", page_title="Vermont Town Economic Dashboard")

# Background image (subtle)
st.markdown(
    """
    <style>
      .stApp {
        background-image: url('https://upload.wikimedia.org/wikipedia/commons/6/6e/Green_Mountains_in_Vermont.jpg');
        background-size: cover;
        background-attachment: fixed;
        background-position: center;
      }
      .block-container {
        backdrop-filter: blur(2px);
        background-color: rgba(255,255,255,0.85);
        border-radius: 12px;
        padding: 1rem 2rem !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🏔 Vermont Town Economic Dashboard")
st.caption("Explore ACS (2019–2023 5-year) indicators for Vermont towns. Click a town or pick from the list to zoom the map. Add your policy links via CSV.")

STATE_FIPS = "50"          # Vermont
ACS_YEAR = 2023            # latest 5-year as of 2025
DEFAULT_MAP_CENTER = [44.0, -72.7]

# -----------------------------
# 1) Town Boundaries (VCGI)
# -----------------------------
@st.cache_data(show_spinner=False, ttl=60*60)
def fetch_town_boundaries() -> gpd.GeoDataFrame:
    """Fetch VT town boundaries (the layer you have with FIPS6, TOWNNAME, etc.)."""
    url = (
        "https://geodata.vermont.gov/arcgis/rest/services/VCGI/VT_Data_Boundaries/FeatureServer/9/query"
    )
    # If the above ever changes, this alternative (same schema) has also worked:
    # url = "https://services.arcgis.com/pwNwIGBE7M7VOXjQ/arcgis/rest/services/VT_Town_Boundaries__VCGI_/FeatureServer/0/query"
    params = {"where": "1=1", "outFields": "*", "f": "geojson"}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    gj = r.json()
    features = gj.get("features", [])
    records, geoms = [], []
    for f in features:
        props = f.get("properties", {})
        geom = f.get("geometry")
        if geom:
            geoms.append(shape(geom))
            records.append(props)
    gdf = gpd.GeoDataFrame(pd.DataFrame(records), geometry=geoms, crs="EPSG:4326")

    # Normalize key fields expected from your layer
    # Columns you reported: ['FID','OBJECTID','FIPS6','TOWNNAME','TOWNNAMEMC','CNTY', ... ,'geometry']
    if "FIPS6" not in gdf.columns:
        gdf["FIPS6"] = None
    if "TOWNNAME" not in gdf.columns:
        # some layers use NAME
        gdf["TOWNNAME"] = gdf.get("NAME", "")

    # Helpers for joins
    gdf["town_clean"] = gdf["TOWNNAME"].astype(str).str.strip().str.lower()
    return gdf

# -----------------------------
# 2) ACS Data (Census 5-year)
# -----------------------------
@st.cache_data(show_spinner=False, ttl=60*60)
def fetch_acs_data(year: int = ACS_YEAR) -> pd.DataFrame:
    """Pull ACS indicators for all VT county subdivisions (towns)."""
    profile_vars = {
        "DP03_0009PE": "Unemployment Rate (%)",        # %
        "DP03_0119PE": "Poverty Rate (%)",             # %
        "DP02_0068PE": "Bachelor's Degree + (%)"       # %
    }
    detailed_vars = {
        "B19013_001E": "Median Income"                 # $
    }

    base = f"https://api.census.gov/data/{year}/acs/acs5"
    prof_url = f"{base}/profile"

    # Profile (percents)
    prof_params = {
        "get": ",".join(profile_vars.keys()) + ",NAME",
        "for": "county subdivision:*",
        "in": f"state:{STATE_FIPS}",
    }
    pr = requests.get(prof_url, params=prof_params, timeout=60)
    pr.raise_for_status()
    p = pr.json()
    prof_df = pd.DataFrame(p[1:], columns=p[0])

    # Detailed (median income)
    det_params = {
        "get": ",".join(detailed_vars.keys()) + ",NAME",
        "for": "county subdivision:*",
        "in": f"state:{STATE_FIPS}",
    }
    dr = requests.get(base, params=det_params, timeout=60)
    dr.raise_for_status()
    d = dr.json()
    det_df = pd.DataFrame(d[1:], columns=d[0])

    # Build GEOID (060): state(2)+county(3)+cousub(5) => 10 chars
    prof_df["GEOID060"] = prof_df["state"] + prof_df["county"] + prof_df["county subdivision"]
    det_df["GEOID060"] = det_df["state"] + det_df["county"] + det_df["county subdivision"]

    acs = prof_df.merge(
        det_df[["GEOID060"] + list(detailed_vars.keys())],
        on="GEOID060",
        how="left"
    )

    # Clean + labels
    acs = acs.rename(columns={**profile_vars, **detailed_vars, "NAME": "ACS_NAME"})
    # Normalize a town name from ACS_NAME (e.g. "Burlington city, Chittenden County, Vermont")
    acs["town_clean"] = (
        acs["ACS_NAME"]
        .str.extract(r"^(.+?)(?:\s+(?:town|city|gore|grant|plantation|gores and grants))?,\s+")[0]
        .fillna(acs["ACS_NAME"])
        .str.strip()
        .str.lower()
    )

    # To help match some tricky cases, keep county name too
    acs["county_clean"] = (
        acs["ACS_NAME"].str.extract(r",\s+(.+?) County,")[0].fillna("").str.strip().str.lower()
    )

    # Cast numeric fields
    for col in ["Unemployment Rate (%)", "Poverty Rate (%)", "Bachelor's Degree + (%)", "Median Income"]:
        if col in acs.columns:
            acs[col] = pd.to_numeric(acs[col], errors="coerce")

    return acs

# -----------------------------
# 3) Optional Policy Links CSV
# -----------------------------
@st.cache_data(show_spinner=False)
def load_policy_links(path: str = "policy_links.csv") -> pd.DataFrame:
    """
    Load optional policy links CSV with columns:
    town,url,title,tags
    """
    if os.path.exists(path):
        df = pd.read_csv(path)
    else:
        # seed a few to demonstrate
        df = pd.DataFrame([
            {"town": "Burlington", "url": "https://www.burlingtonvt.gov/CEDO", "title": "CEDO – Economic Development", "tags": "plan,grants,workforce"},
            {"town": "Montpelier", "url": "https://www.montpelier-vt.org/602/Economic-Development", "title": "Economic Development", "tags": "plan,small-business"},
            {"town": "Rutland", "url": "https://www.rutlandvtbusiness.com/", "title": "Rutland Redevelopment Authority", "tags": "redevelopment,tif"},
            {"town": "Brattleboro", "url": "https://brattleboro.org/economic-development/", "title": "Economic Development", "tags": "downtown,revitalization"},
        ])
    df["town_clean"] = df["town"].astype(str).str.strip().str.lower()
    return df

# -----------------------------
# Fetch data
# -----------------------------
with st.spinner("Loading Vermont town boundaries…"):
    gdf = fetch_town_boundaries()

with st.spinner("Fetching ACS data…"):
    acs = fetch_acs_data(ACS_YEAR)

pol = load_policy_links()

# -----------------------------
# 4) Robust Join: codes first, names as fallback
# -----------------------------
# Your boundary layer has FIPS6 (reported). This often encodes the MCD (town) code but
# not the full 060 GEOID. We'll try both code and name joins to maximize matches.

# Try to coerce FIPS6 into 10-digit form if it looks numeric; otherwise skip.
gdf["FIPS6"] = gdf["FIPS6"].astype(str).str.strip()
# Create town_clean on boundaries too
gdf["town_clean"] = gdf["TOWNNAME"].astype(str).str.strip().str.lower()

# Primary attempt: name-based join (most reliable given FIPS6 ambiguity)
joined = gdf.merge(
    acs[["GEOID060", "town_clean", "county_clean", "ACS_NAME",
         "Unemployment Rate (%)", "Poverty Rate (%)", "Bachelor's Degree + (%)", "Median Income"]],
    on="town_clean",
    how="left"
)

# Attach policy links
joined = joined.merge(
    pol[["town_clean", "url", "title", "tags"]],
    on="town_clean",
    how="left"
)

# -----------------------------
# 5) UI Controls
# -----------------------------
with st.sidebar:
    st.header("Controls")
    metric = st.selectbox(
        "Map metric",
        [
            ("Median Income ($)", "Median Income"),
            ("Unemployment Rate (%)", "Unemployment Rate (%)"),
            ("Poverty Rate (%)", "Poverty Rate (%)"),
            ("Bachelor's Degree + (%)", "Bachelor's Degree + (%)"),
        ],
        index=0,
        format_func=lambda x: x[0],
    )
    metric_label, metric_col = metric

    # Town selector (syncs with map)
    town_options = joined["TOWNNAME"].dropna().sort_values().unique().tolist()
    selected_town = st.selectbox("Jump to town", town_options)

# -----------------------------
# 6) Prepare display table
# -----------------------------
table_cols = [
    ("Town", "TOWNNAME"),
    ("Median Income", "Median Income"),
    ("Unemployment Rate (%)", "Unemployment Rate (%)"),
    ("Poverty Rate (%)", "Poverty Rate (%)"),
    ("Bachelor's Degree + (%)", "Bachelor's Degree + (%)"),
    ("Policy", "title"),
    ("Policy Link", "url"),
]
table_df = joined[[c for _, c in table_cols]].copy()

# Formatting display values (leave NaNs as blanks)
def fmt_money(x):
    return f"${x:,.0f}" if pd.notna(x) else ""

def fmt_pct(x):
    return f"{x:,.1f}" if pd.notna(x) else ""

if "Median Income" in table_df:
    table_df["Median Income"] = table_df["Median Income"].map(fmt_money)
for col in ["Unemployment Rate (%)", "Poverty Rate (%)", "Bachelor's Degree + (%)"]:
    if col in table_df:
        table_df[col] = table_df[col].map(fmt_pct)

# Render table with clickable policy link
# st.dataframe doesn't render HTML links; we'll use to_html
display_df = table_df.rename(columns={c: l for l, c in table_cols}).copy()
if "Policy Link" in display_df:
    display_df["Policy Link"] = display_df["Policy Link"].apply(
        lambda u: f'<a href="{u}" target="_blank">Open</a>' if isinstance(u, str) and u.startswith("http") else ""
    )

# -----------------------------
# 7) Layout: Table (left) + Map (right)
# -----------------------------
left, right = st.columns([1.1, 2])

with left:
    st.subheader("📋 Town Economic Data")
    st.markdown(
        display_df.to_html(index=False, escape=False),
        unsafe_allow_html=True
    )

with right:
    st.subheader(f"🗺️ Map — {metric_label}")
    # Build Folium map
    m = folium.Map(location=DEFAULT_MAP_CENTER, zoom_start=7, tiles="cartodbpositron")

    # Choropleth layer
    gjson = json.loads(joined.to_json())
    # Ensure the property key exists
    id_field = "town_clean"
    choro_df = joined[[id_field, metric_col]].copy()
    choro_df[metric_col] = pd.to_numeric(choro_df[metric_col], errors="coerce")

    folium.Choropleth(
        geo_data=gjson,
        data=choro_df,
        columns=[id_field, metric_col],
        key_on=f"feature.properties.{id_field}",
        fill_opacity=0.8,
        line_opacity=0.4,
        nan_fill_opacity=0.15,
        legend_name=metric_label,
    ).add_to(m)

    # Add clickable markers at representative points
    # (makes it easy to detect clicks in streamlit-folium)
    centroids = joined.copy()
    centroids["__pt"] = centroids.geometry.representative_point()
    for _, r in centroids.iterrows():
        if r["__pt"].is_empty:
            continue
        lat, lon = r["__pt"].y, r["__pt"].x
        town = str(r["TOWNNAME"])
        val = r.get(metric_col)
        if pd.notna(val):
            if "Income" in metric_col:
                disp = f"${val:,.0f}"
            else:
                disp = f"{val:,.1f}%"
        else:
            disp = "n/a"
        popup_html = f"<b>{town}</b><br>{metric_label}: {disp}"
        if isinstance(r.get("url"), str) and r["url"].startswith("http"):
            popup_html += f"<br><a href='{r['url']}' target='_blank'>{r.get('title','Policy')}</a>"
        folium.Marker(
            [lat, lon],
            tooltip=town,
            popup=folium.Popup(popup_html, max_width=320),
            icon=folium.Icon(icon="info-sign"),
        ).add_to(m)

    # If a town is selected in the sidebar, center/zoom to it
    focus = joined.loc[joined["TOWNNAME"] == selected_town]
    if not focus.empty:
        rp = focus.geometry.iloc[0].representative_point()
        m.location = [rp.y, rp.x]
        m.zoom_start = 10

    # Render and capture click data
    map_state = st_folium(m, height=640, use_container_width=True)

# -----------------------------
# 8) Basic map → selection sync (best-effort)
# -----------------------------
# streamlit-folium exposes 'last_object_clicked' (lat/lng). We'll match nearest centroid.
if map_state and map_state.get("last_object_clicked"):
    clicked = map_state["last_object_clicked"]
    latc, lonc = clicked.get("lat"), clicked.get("lng")
    if latc is not None and lonc is not None:
        # simple nearest search
        centroids["dist2"] = (centroids["__pt"].y - latc)**2 + (centroids["__pt"].x - lonc)**2
        nearest = centroids.nsmallest(1, "dist2")
        if not nearest.empty:
            sel = nearest["TOWNNAME"].iloc[0]
            st.experimental_set_query_params(town=sel)  # lightweight way to reflect selection
            st.toast(f"Selected: {sel}", icon="🔎")

# -----------------------------
# 9) Sources / Attribution
# -----------------------------
st.markdown("---")
st.markdown(
    """
**Sources**  
- [U.S. Census Bureau — American Community Survey (ACS) 5-Year (2019–2023)](https://www.census.gov/programs-surveys/acs)  
- [Vermont Center for Geographic Information (VCGI) — Town Boundaries](https://geodata.vermont.gov/)  
- *Tip:* Add a `policy_links.csv` with columns `town,url,title,tags` to show policy links per town.
"""
)
