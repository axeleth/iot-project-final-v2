import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy import signal
from pathlib import Path

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Indoor Environment Monitor",
    page_icon="🌡️",
    layout="wide",
)

# Consistent colours (tuned for dark background)
INDOOR_COLOR = "#4a9eff"   # bright blue
OUTDOOR_COLOR = "#ff8c42"  # warm orange
LIGHT_COLOR = "#f5d547"    # gold for light
PEAK_COLOR = "#ff5555"     # red for peak markers

# Dark plotly template applied to all charts
PLOT_TEMPLATE = "plotly_dark"
PLOT_BG = "rgba(0,0,0,0)"
PAPER_BG = "rgba(0,0,0,0)"
GRID_COLOR = "rgba(255,255,255,0.08)"
AXIS_COLOR = "#888888"

DARK_LAYOUT = dict(
    template=PLOT_TEMPLATE,
    plot_bgcolor=PLOT_BG,
    paper_bgcolor=PAPER_BG,
    font=dict(color="#e0e0e0"),
    xaxis=dict(gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, zerolinecolor=GRID_COLOR),
    yaxis=dict(gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, zerolinecolor=GRID_COLOR),
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data_collection" / "data"


@st.cache_data(ttl=300)  # re-read CSVs every 5 minutes
def load_data():
    indoor = pd.read_csv(
        DATA_DIR / "indoor_sensor_data.csv",
        parse_dates=["timestamp_utc"],
    )
    outdoor = pd.read_csv(
        DATA_DIR / "outdoor_weather_data.csv",
        parse_dates=["timestamp_utc"],
    )

    # Sort and deduplicate
    indoor = indoor.sort_values("timestamp_utc").drop_duplicates(subset="timestamp_utc")
    outdoor = outdoor.sort_values("timestamp_utc").drop_duplicates(subset="timestamp_utc")

    # Drop anomalous DHT22 readings (isolated spikes where temp and humidity both drop)
    indoor = indoor[indoor["temperature_c"] >= 18]

    # Merge on nearest timestamp
    merged = pd.merge_asof(
        indoor, outdoor,
        on="timestamp_utc",
        tolerance=pd.Timedelta("5min"),
        direction="nearest",
        suffixes=("", "_outdoor"),
    )
    merged = merged.set_index("timestamp_utc")
    merged.index = merged.index.tz_localize(None)  # strip tz for plotly compat

    # Invert light readings (LDR gives high values in dark, low in light)
    merged["light_pct"] = 100.0 - merged["light_pct"]

    # Day/night flag based on light_pct threshold
    merged["is_daylight"] = merged["light_pct"] > 10

    return merged


df = load_data()

# ---------------------------------------------------------------------------
# Sidebar -- controls
# ---------------------------------------------------------------------------
st.sidebar.title("Controls")

date_min = df.index.min().date()
date_max = df.index.max().date()
date_range = st.sidebar.date_input(
    "Date range",
    value=(date_min, date_max),
    min_value=date_min,
    max_value=date_max,
)

# Handle single date selection
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date = end_date = date_range if not isinstance(date_range, tuple) else date_range[0]

mask = (df.index.date >= start_date) & (df.index.date <= end_date)
dff = df.loc[mask]

st.sidebar.markdown("---")
st.sidebar.subheader("Time-Series Toggles")
show_indoor_temp = st.sidebar.checkbox("Indoor temperature", value=True)
show_outdoor_temp = st.sidebar.checkbox("Outdoor temperature", value=True)
show_indoor_hum = st.sidebar.checkbox("Indoor humidity", value=True)
show_outdoor_hum = st.sidebar.checkbox("Outdoor humidity", value=True)

st.sidebar.markdown("---")
st.sidebar.subheader("Lag Analysis")
max_lag_hours = st.sidebar.slider("Max lag (hours)", 1, 12, 6)

st.sidebar.markdown("---")
st.sidebar.subheader("Comfort Settings")
comfort_low = st.sidebar.slider("Lower comfort bound (°C)", 15.0, 25.0, 19.0, 0.5)
comfort_high = st.sidebar.slider("Upper comfort bound (°C)", 18.0, 30.0, 24.0, 0.5)

# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------
st.title("Indoor Environment Monitor")
st.caption(
    "Real-time comparison of indoor sensor readings (ESP32 + DHT22 + LDR) "
    "with outdoor weather data (OpenWeatherMap API) -- collected every 2.5 minutes."
)

# ---------------------------------------------------------------------------
# 1. Current Readings Panel
# ---------------------------------------------------------------------------
st.header("Current Readings")

latest = df.iloc[-1]
time_since = pd.Timestamp.now() - df.index[-1]
hours_ago = time_since.total_seconds() / 3600

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Indoor Temp", f"{latest['temperature_c']:.1f} °C")
    st.metric("Indoor Humidity", f"{latest['humidity_pct']:.1f} %")

with col2:
    light_status = "☀️ Daylight" if latest["light_pct"] > 10 else "🌙 Dark"
    st.metric("Light Status", light_status)
    st.metric("Light Level", f"{latest['light_pct']:.0f} %")

with col3:
    st.metric("Outdoor Temp", f"{latest['outdoor_temp_c']:.1f} °C")
    st.metric("Outdoor Humidity", f"{latest['outdoor_humidity_pct']:.0f} %")

with col4:
    st.metric("Cloud Cover", f"{latest['outdoor_clouds_pct']:.0f} %")
    st.metric("Conditions", latest["weather_description"].title())

if hours_ago < 1:
    st.info(f"Last reading: {int(time_since.total_seconds() / 60)} minutes ago")
else:
    st.info(f"Last reading: {hours_ago:.1f} hours ago")

# ---------------------------------------------------------------------------
# 2. Time-Series Charts
# ---------------------------------------------------------------------------
st.header("Time-Series Charts")
st.caption("Use the toggles in the sidebar to show/hide individual traces. "
           "Charts are interactive -- zoom, pan, and hover for details.")

# --- Temperature ---
times = dff.index.tolist()

fig_temp = go.Figure()
if show_indoor_temp:
    fig_temp.add_trace(go.Scatter(
        x=times, y=dff["temperature_c"].tolist(),
        name="Indoor", line=dict(color=INDOOR_COLOR, width=1.5),
        hovertemplate="%{y:.1f} °C<extra>Indoor</extra>",
    ))
if show_outdoor_temp:
    fig_temp.add_trace(go.Scatter(
        x=times, y=dff["outdoor_temp_c"].tolist(),
        name="Outdoor", line=dict(color=OUTDOOR_COLOR, width=1.5),
        hovertemplate="%{y:.1f} °C<extra>Outdoor</extra>",
    ))
fig_temp.add_hrect(
    y0=comfort_low, y1=comfort_high,
    fillcolor="rgba(74,255,128,0.07)", line_width=0,
    layer="below",
)
fig_temp.add_hline(y=comfort_low, line_dash="dot", line_color="rgba(255,85,85,0.5)",
                   annotation_text=f"{comfort_low}°C", annotation_position="bottom left")
fig_temp.add_hline(y=comfort_high, line_dash="dot", line_color="rgba(255,85,85,0.5)",
                   annotation_text=f"{comfort_high}°C", annotation_position="top left")
fig_temp.update_layout(
    **DARK_LAYOUT,
    title="Temperature",
    yaxis_title="Temperature (°C)",
    xaxis_title="Time (UTC)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=400, margin=dict(t=50, b=40),
    hovermode="x unified",
)
st.plotly_chart(fig_temp, use_container_width=True)

# --- Humidity ---
fig_hum = go.Figure()
if show_indoor_hum:
    fig_hum.add_trace(go.Scatter(
        x=times, y=dff["humidity_pct"].tolist(),
        name="Indoor", line=dict(color=INDOOR_COLOR, width=1.5),
        hovertemplate="%{y:.1f} %<extra>Indoor</extra>",
    ))
if show_outdoor_hum:
    fig_hum.add_trace(go.Scatter(
        x=times, y=dff["outdoor_humidity_pct"].tolist(),
        name="Outdoor", line=dict(color=OUTDOOR_COLOR, width=1.5),
        hovertemplate="%{y:.0f} %<extra>Outdoor</extra>",
    ))
fig_hum.update_layout(
    **DARK_LAYOUT,
    title="Humidity",
    yaxis_title="Relative Humidity (%)",
    xaxis_title="Time (UTC)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=400, margin=dict(t=50, b=40),
    hovermode="x unified",
)
st.plotly_chart(fig_hum, use_container_width=True)

# --- Light with day/night shading ---
fig_light = go.Figure()
fig_light.add_trace(go.Scatter(
    x=times, y=dff["light_pct"].tolist(),
    name="Indoor Light", line=dict(color=LIGHT_COLOR, width=1.5),
    fill="tozeroy", fillcolor="rgba(245,213,71,0.15)",
    hovertemplate="%{y:.0f} %<extra>Light</extra>",
))
fig_light.update_layout(
    **DARK_LAYOUT,
    title="Indoor Light Level (LDR)",
    yaxis_title="Light (%)",
    xaxis_title="Time (UTC)",
    height=350, margin=dict(t=50, b=40),
    hovermode="x unified",
)
st.plotly_chart(fig_light, use_container_width=True)

# ---------------------------------------------------------------------------
# 3. Cross-Correlation / Lag Analysis
# ---------------------------------------------------------------------------
st.header("Cross-Correlation Lag Analysis")
st.caption(
    "This section analyses how quickly indoor conditions respond to outdoor changes. "
    "A positive lag means indoor readings **follow** outdoor changes by that many hours. "
    "The peak of the cross-correlation function indicates the optimal delay."
)


def compute_cross_correlation(indoor_series, outdoor_series, max_lag_samples):
    """Compute normalised cross-correlation and return lags + correlation values."""
    x = outdoor_series.values.copy()
    y = indoor_series.values.copy()

    # Remove means for proper correlation
    x = x - np.nanmean(x)
    y = y - np.nanmean(y)

    # Replace NaN with 0 for correlation computation
    x = np.nan_to_num(x, nan=0.0)
    y = np.nan_to_num(y, nan=0.0)

    corr = signal.correlate(y, x, mode="full")
    # Normalise
    norm = np.sqrt(np.sum(x**2) * np.sum(y**2))
    if norm > 0:
        corr = corr / norm

    mid = len(x) - 1
    lags = np.arange(-max_lag_samples, max_lag_samples + 1)
    corr_window = corr[mid + lags[0]: mid + lags[-1] + 1]

    return lags, corr_window


# Sampling interval in hours
dt_hours = 2.5 / 60  # 2.5 minutes
max_lag_samples = int(max_lag_hours / dt_hours)

col_temp_lag, col_hum_lag = st.columns(2)

# --- Temperature lag ---
with col_temp_lag:
    st.subheader("Temperature")
    temp_indoor = dff["temperature_c"].interpolate()
    temp_outdoor = dff["outdoor_temp_c"].interpolate()

    if len(temp_indoor.dropna()) > 10:
        lags_t, corr_t = compute_cross_correlation(temp_indoor, temp_outdoor, max_lag_samples)
        lag_hours_t = lags_t * dt_hours

        peak_idx = np.argmax(corr_t)
        optimal_lag_t = lag_hours_t[peak_idx]
        peak_corr_t = corr_t[peak_idx]

        fig_lag_t = go.Figure()
        fig_lag_t.add_trace(go.Scatter(
            x=lag_hours_t.tolist(), y=corr_t.tolist(),
            line=dict(color=INDOOR_COLOR, width=2),
            hovertemplate="Lag: %{x:.1f}h<br>Correlation: %{y:.3f}<extra></extra>",
        ))
        fig_lag_t.add_vline(x=optimal_lag_t, line_dash="dash", line_color=PEAK_COLOR,
                            annotation_text=f"Peak: {optimal_lag_t:.1f}h")
        fig_lag_t.update_layout(
            **DARK_LAYOUT,
            xaxis_title="Lag (hours)",
            yaxis_title="Cross-correlation",
            height=350, margin=dict(t=30, b=40),
        )
        st.plotly_chart(fig_lag_t, use_container_width=True)
        st.success(
            f"Indoor temperature follows outdoor temperature with an estimated "
            f"delay of **{abs(optimal_lag_t):.1f} hours** (r = {peak_corr_t:.3f})."
        )
    else:
        st.warning("Not enough data for temperature lag analysis.")

# --- Humidity lag ---
with col_hum_lag:
    st.subheader("Humidity")
    hum_indoor = dff["humidity_pct"].interpolate()
    hum_outdoor = dff["outdoor_humidity_pct"].interpolate()

    if len(hum_indoor.dropna()) > 10:
        lags_h, corr_h = compute_cross_correlation(hum_indoor, hum_outdoor, max_lag_samples)
        lag_hours_h = lags_h * dt_hours

        peak_idx_h = np.argmax(corr_h)
        optimal_lag_h = lag_hours_h[peak_idx_h]
        peak_corr_h = corr_h[peak_idx_h]

        fig_lag_h = go.Figure()
        fig_lag_h.add_trace(go.Scatter(
            x=lag_hours_h.tolist(), y=corr_h.tolist(),
            line=dict(color=OUTDOOR_COLOR, width=2),
            hovertemplate="Lag: %{x:.1f}h<br>Correlation: %{y:.3f}<extra></extra>",
        ))
        fig_lag_h.add_vline(x=optimal_lag_h, line_dash="dash", line_color=PEAK_COLOR,
                            annotation_text=f"Peak: {optimal_lag_h:.1f}h")
        fig_lag_h.update_layout(
            **DARK_LAYOUT,
            xaxis_title="Lag (hours)",
            yaxis_title="Cross-correlation",
            height=350, margin=dict(t=30, b=40),
        )
        st.plotly_chart(fig_lag_h, use_container_width=True)
        st.success(
            f"Indoor humidity follows outdoor humidity with an estimated "
            f"delay of **{abs(optimal_lag_h):.1f} hours** (r = {peak_corr_h:.3f})."
        )
    else:
        st.warning("Not enough data for humidity lag analysis.")

# ---------------------------------------------------------------------------
# 4. Comfort & Heating Analysis
# ---------------------------------------------------------------------------
st.header("Comfort & Heating Analysis")
st.caption(
    "Analyse how well the apartment maintains a comfortable temperature. "
    "Adjust the comfort range in the sidebar to explore different thresholds."
)

SAMPLE_INTERVAL_H = 2.5 / 60  # each reading represents 2.5 minutes

temp_series = dff["temperature_c"].dropna()
below_mask = temp_series < comfort_low
above_mask = temp_series > comfort_high
outside_mask = below_mask | above_mask
in_comfort_mask = ~outside_mask

total_hours = len(temp_series) * SAMPLE_INTERVAL_H
hours_outside = outside_mask.sum() * SAMPLE_INTERVAL_H
comfort_score = (in_comfort_mask.sum() / len(temp_series) * 100) if len(temp_series) > 0 else 100.0

# Count separate breach episodes (contiguous runs of outside-comfort readings)
breach_diff = outside_mask.astype(int).diff().fillna(0)
num_breaches = int((breach_diff == 1).sum())

# Longest single breach duration
if num_breaches > 0:
    breach_groups = (outside_mask != outside_mask.shift()).cumsum()
    breach_lengths = outside_mask.groupby(breach_groups).sum()
    longest_breach_h = breach_lengths.max() * SAMPLE_INTERVAL_H
else:
    longest_breach_h = 0.0

# --- Comfort breach summary ---
st.subheader("Comfort Breach Summary")
cb1, cb2, cb3, cb4 = st.columns(4)
with cb1:
    st.metric("Comfort Score", f"{comfort_score:.1f} %")
with cb2:
    st.metric("Hours Outside Range", f"{hours_outside:.1f} h")
with cb3:
    st.metric("Breach Episodes", str(num_breaches))
with cb4:
    st.metric("Longest Breach", f"{longest_breach_h:.1f} h")

# --- Daily comfort breakdown ---
st.subheader("Daily Comfort Breakdown")

daily = dff[["temperature_c"]].copy()
daily["date"] = daily.index.date
daily["below"] = (daily["temperature_c"] < comfort_low).astype(int)
daily["above"] = (daily["temperature_c"] > comfort_high).astype(int)
daily["in_range"] = ((daily["temperature_c"] >= comfort_low) & (daily["temperature_c"] <= comfort_high)).astype(int)

daily_summary = daily.groupby("date").agg(
    below_hours=("below", "sum"),
    above_hours=("above", "sum"),
    in_range_hours=("in_range", "sum"),
).reset_index()
# Convert sample counts to hours
for col in ["below_hours", "above_hours", "in_range_hours"]:
    daily_summary[col] = (daily_summary[col] * SAMPLE_INTERVAL_H).round(1)

daily_dates = daily_summary["date"].astype(str).tolist()

fig_daily_comfort = go.Figure()
fig_daily_comfort.add_trace(go.Bar(
    x=daily_dates, y=daily_summary["in_range_hours"].tolist(),
    name="In Range", marker_color="rgba(74,255,128,0.7)",
))
fig_daily_comfort.add_trace(go.Bar(
    x=daily_dates, y=daily_summary["below_hours"].tolist(),
    name=f"Below {comfort_low}°C", marker_color="rgba(74,158,255,0.7)",
))
fig_daily_comfort.add_trace(go.Bar(
    x=daily_dates, y=daily_summary["above_hours"].tolist(),
    name=f"Above {comfort_high}°C", marker_color="rgba(255,85,85,0.7)",
))
fig_daily_comfort.update_layout(
    **DARK_LAYOUT,
    barmode="stack",
    yaxis_title="Hours",
    xaxis_title="Date",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=350, margin=dict(t=30, b=40),
)
st.plotly_chart(fig_daily_comfort, use_container_width=True)

# --- Simulated heating trigger analysis ---
st.subheader("Simulated Heating Trigger Analysis")
st.caption(
    "*Phase 1 analysis for a future smart heating actuator system* -- "
    "this sensor data informs the control logic for a boiler relay that would be added in a future iteration."
)

trigger_temp = comfort_low  # heating trigger = lower comfort bound
below_trigger = (temp_series < trigger_temp).astype(int)

# Count activations (transitions from above to below threshold)
trigger_transitions = below_trigger.diff().fillna(0)
num_activations = int((trigger_transitions == 1).sum())

# Total time below trigger
heating_runtime_h = below_trigger.sum() * SAMPLE_INTERVAL_H

# Average time between triggers
if num_activations > 1:
    activation_times = temp_series.index[trigger_transitions == 1]
    gaps = pd.Series(activation_times).diff().dropna()
    avg_gap_h = gaps.dt.total_seconds().mean() / 3600
else:
    avg_gap_h = 0.0

ht1, ht2, ht3 = st.columns(3)
with ht1:
    st.metric("Boiler Activations", str(num_activations))
with ht2:
    st.metric("Est. Heating Runtime", f"{heating_runtime_h:.1f} h")
with ht3:
    if num_activations > 1:
        st.metric("Avg. Time Between Triggers", f"{avg_gap_h:.1f} h")
    else:
        st.metric("Avg. Time Between Triggers", "N/A")

if num_activations == 0:
    st.info(f"Indoor temperature never dropped below {trigger_temp}°C in the selected range -- no heating would have been required.")
else:
    st.info(
        f"A heating system would have activated **{num_activations} time(s)** to maintain "
        f"the apartment above {trigger_temp}°C, running for an estimated **{heating_runtime_h:.1f} hours** total."
    )

# ---------------------------------------------------------------------------
# 5. Daily Patterns
# ---------------------------------------------------------------------------
st.header("Daily Patterns")
st.caption(
    "Average hourly profiles showing how indoor and outdoor conditions vary across the day. "
    "This reveals the apartment's thermal behaviour -- how it warms during the day and cools at night."
)

hourly = dff.copy()
hourly["hour_bin"] = pd.to_datetime(hourly["timestamp_local"]).dt.hour

temp_profile = hourly.groupby("hour_bin").agg(
    indoor_temp=("temperature_c", "mean"),
    outdoor_temp=("outdoor_temp_c", "mean"),
    indoor_hum=("humidity_pct", "mean"),
    outdoor_hum=("outdoor_humidity_pct", "mean"),
).reset_index()

col_dp1, col_dp2 = st.columns(2)

with col_dp1:
    hours_list = temp_profile["hour_bin"].tolist()
    fig_dp_temp = go.Figure()
    fig_dp_temp.add_trace(go.Scatter(
        x=hours_list, y=temp_profile["indoor_temp"].tolist(),
        name="Indoor", line=dict(color=INDOOR_COLOR, width=2.5),
        mode="lines+markers",
    ))
    fig_dp_temp.add_trace(go.Scatter(
        x=hours_list, y=temp_profile["outdoor_temp"].tolist(),
        name="Outdoor", line=dict(color=OUTDOOR_COLOR, width=2.5),
        mode="lines+markers",
    ))
    fig_dp_temp.update_layout(
        **DARK_LAYOUT,
        title="Temperature -- Hourly Profile",
        xaxis_title="Hour of Day",
        yaxis_title="Mean Temperature (°C)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=380, margin=dict(t=50, b=40),
    )
    fig_dp_temp.update_xaxes(tickmode="linear", dtick=2)
    st.plotly_chart(fig_dp_temp, use_container_width=True)

with col_dp2:
    fig_dp_hum = go.Figure()
    fig_dp_hum.add_trace(go.Scatter(
        x=hours_list, y=temp_profile["indoor_hum"].tolist(),
        name="Indoor", line=dict(color=INDOOR_COLOR, width=2.5),
        mode="lines+markers",
    ))
    fig_dp_hum.add_trace(go.Scatter(
        x=hours_list, y=temp_profile["outdoor_hum"].tolist(),
        name="Outdoor", line=dict(color=OUTDOOR_COLOR, width=2.5),
        mode="lines+markers",
    ))
    fig_dp_hum.update_layout(
        **DARK_LAYOUT,
        title="Humidity -- Hourly Profile",
        xaxis_title="Hour of Day",
        yaxis_title="Mean Relative Humidity (%)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=380, margin=dict(t=50, b=40),
    )
    fig_dp_hum.update_xaxes(tickmode="linear", dtick=2)
    st.plotly_chart(fig_dp_hum, use_container_width=True)

# ---------------------------------------------------------------------------
# 5. Scatter Plots / Correlation Explorer
# ---------------------------------------------------------------------------
st.header("Correlation Explorer")
st.caption(
    "Scatter plots showing the relationship between indoor and outdoor measurements. "
    "The trend-line slope quantifies thermal and humidity sensitivity -- how much indoor "
    "conditions shift per unit change outdoors."
)

# Pre-compute slopes for sensitivity display
_scatter_t = dff[["temperature_c", "outdoor_temp_c"]].dropna()
_scatter_h = dff[["humidity_pct", "outdoor_humidity_pct"]].dropna()
_z_temp = np.polyfit(_scatter_t["outdoor_temp_c"], _scatter_t["temperature_c"], 1)
_z_hum = np.polyfit(_scatter_h["outdoor_humidity_pct"], _scatter_h["humidity_pct"], 1)
slope_temp = _z_temp[0]
slope_hum = _z_hum[0]


def _insulation_text(slope):
    s = abs(slope)
    if s < 0.2:
        return "Very well insulated -- indoor conditions are largely decoupled from outdoor changes"
    elif s < 0.5:
        return "Moderately insulated -- indoor conditions respond partially to outdoor changes"
    else:
        return "Poorly insulated -- indoor conditions closely track outdoor changes"


sens_col1, sens_col2 = st.columns(2)
with sens_col1:
    st.metric("Thermal Sensitivity", f"{slope_temp:.2f} °C indoor per 1 °C outdoor")
    st.caption(_insulation_text(slope_temp))
with sens_col2:
    st.metric("Humidity Sensitivity", f"{slope_hum:.2f} % indoor per 1 % outdoor")
    st.caption(_insulation_text(slope_hum))

col_sc1, col_sc2 = st.columns(2)

# --- Temperature scatter ---
with col_sc1:
    scatter_data = _scatter_t
    hour_for_color = pd.to_datetime(dff.loc[scatter_data.index, "timestamp_local"]).dt.hour

    r_temp = scatter_data["temperature_c"].corr(scatter_data["outdoor_temp_c"])

    # Trend line
    z_temp = _z_temp
    x_range = np.linspace(scatter_data["outdoor_temp_c"].min(), scatter_data["outdoor_temp_c"].max(), 50)
    y_trend = np.polyval(z_temp, x_range)

    fig_sc_t = go.Figure()
    fig_sc_t.add_trace(go.Scatter(
        x=scatter_data["outdoor_temp_c"].tolist(),
        y=scatter_data["temperature_c"].tolist(),
        mode="markers",
        marker=dict(
            color=hour_for_color.tolist(),
            colorscale="Plasma",
            size=4, opacity=0.7,
            colorbar=dict(title="Hour"),
        ),
        hovertemplate="Outdoor: %{x:.1f}°C<br>Indoor: %{y:.1f}°C<extra></extra>",
    ))
    fig_sc_t.add_trace(go.Scatter(
        x=x_range.tolist(), y=y_trend.tolist(),
        mode="lines", name="Trend",
        line=dict(color=PEAK_COLOR, width=2, dash="dash"),
    ))
    fig_sc_t.update_layout(
        **DARK_LAYOUT,
        title=f"Temperature (r = {r_temp:.3f}, slope = {slope_temp:.2f} °C/°C)",
        xaxis_title="Outdoor Temp (°C)",
        yaxis_title="Indoor Temp (°C)",
        height=400, margin=dict(t=50, b=40),
        showlegend=False,
    )
    st.plotly_chart(fig_sc_t, use_container_width=True)

# --- Humidity scatter ---
with col_sc2:
    scatter_hum = _scatter_h
    hour_for_color_h = pd.to_datetime(dff.loc[scatter_hum.index, "timestamp_local"]).dt.hour

    r_hum = scatter_hum["humidity_pct"].corr(scatter_hum["outdoor_humidity_pct"])

    z_hum = _z_hum
    x_range_h = np.linspace(scatter_hum["outdoor_humidity_pct"].min(), scatter_hum["outdoor_humidity_pct"].max(), 50)
    y_trend_h = np.polyval(z_hum, x_range_h)

    fig_sc_h = go.Figure()
    fig_sc_h.add_trace(go.Scatter(
        x=scatter_hum["outdoor_humidity_pct"].tolist(),
        y=scatter_hum["humidity_pct"].tolist(),
        mode="markers",
        marker=dict(
            color=hour_for_color_h.tolist(),
            colorscale="Plasma",
            size=4, opacity=0.7,
            colorbar=dict(title="Hour"),
        ),
        hovertemplate="Outdoor: %{x:.0f}%<br>Indoor: %{y:.1f}%<extra></extra>",
    ))
    fig_sc_h.add_trace(go.Scatter(
        x=x_range_h.tolist(), y=y_trend_h.tolist(),
        mode="lines", name="Trend",
        line=dict(color=PEAK_COLOR, width=2, dash="dash"),
    ))
    fig_sc_h.update_layout(
        **DARK_LAYOUT,
        title=f"Humidity (r = {r_hum:.3f}, slope = {slope_hum:.2f} %/%)",
        xaxis_title="Outdoor Humidity (%)",
        yaxis_title="Indoor Humidity (%)",
        height=400, margin=dict(t=50, b=40),
        showlegend=False,
    )
    st.plotly_chart(fig_sc_h, use_container_width=True)

# ---------------------------------------------------------------------------
# 6. Summary Statistics
# ---------------------------------------------------------------------------
st.header("Summary Statistics")

time_span = dff.index[-1] - dff.index[0]
days_span = time_span.total_seconds() / 86400

st.markdown(
    f"**{len(dff):,} data points** collected over **{days_span:.1f} days** "
    f"({dff.index[0].strftime('%d %b %Y %H:%M')} to {dff.index[-1].strftime('%d %b %Y %H:%M')} UTC)"
)

stats_cols = {
    "Indoor Temp (°C)": dff["temperature_c"],
    "Indoor Humidity (%)": dff["humidity_pct"],
    "Indoor Light (%)": dff["light_pct"],
    "Outdoor Temp (°C)": dff["outdoor_temp_c"],
    "Outdoor Humidity (%)": dff["outdoor_humidity_pct"],
    "Cloud Cover (%)": dff["outdoor_clouds_pct"],
    "Wind Speed (m/s)": dff["outdoor_wind_speed_ms"],
    "Pressure (hPa)": dff["outdoor_pressure_hpa"],
}

stats_df = pd.DataFrame({
    name: {
        "Min": s.min(),
        "Max": s.max(),
        "Mean": s.mean(),
        "Std Dev": s.std(),
    }
    for name, s in stats_cols.items()
}).T.round(2)

st.dataframe(stats_df, use_container_width=True)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "IoT Indoor Environment Monitor -- ELEC70126 Coursework | "
    "Imperial College London | Axel Ehrnrooth (aje125)"
)
