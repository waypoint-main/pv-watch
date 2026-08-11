"""Reusable Streamlit UI building blocks shared by every PV Watch page.

Centralizing header rendering, semantic color/icon mapping, KPI cards, map
construction, and disclaimer banners here keeps the individual page scripts
thin and visually consistent, and means a single palette/design change
updates every map, table, card, and badge in the app at once.
"""

from __future__ import annotations

from typing import Optional

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from folium.plugins import Fullscreen, LocateControl

from src.config import AppConfig
from src.models import ChangeType, HostingCapacityStatus, Priority, ReviewAction

# -----------------------------------------------------------------------------
# Semantic color & icon palette (used consistently across maps/tables/charts)
# -----------------------------------------------------------------------------
# Map colors follow one semantic system throughout the app, independent of
# the Waypoint brand accent (teal, reserved for chrome/interactive elements):
# items that are just context (baseline geometry, low priority, already
# resolved) recede into muted but genuinely colored tones; items that need a
# reviewer's attention use two colors reserved for that purpose everywhere in
# the app — gold (#F2A93B, "worth a look") and urgent crimson (#C4291C, "act
# now" — reused verbatim from Priority 1 / hosting-capacity "Review
# recommended" so red means the same thing on every map). Green stays
# reserved for genuinely resolved/good outcomes so it doesn't compete
# visually with the two "needs action" colors.
#
# The basemap tile (CartoDB Positron) is itself essentially greyscale, so a
# literal grey polygon fill disappears into it — every "recede" tone below
# is desaturated but still carries real hue (slate blue or warm taupe)
# instead of grey, so it stays visible as a shape even at low opacity.
NEUTRAL_BLUE = "#6E90A8"        # medium — administrative / non-actionable context
NEUTRAL_BLUE_LIGHT = "#A9C2D0"  # pale — lowest priority / historical-only, still visible
NEUTRAL_TAUPE = "#A69684"       # warm — a second, distinguishable "unclear" tone for maps
# that already use NEUTRAL_BLUE for something else in the same legend

CHANGE_TYPE_COLORS = {
    ChangeType.EXISTING.value: NEUTRAL_BLUE,          # muted but visibly blue — baseline, not actionable
    ChangeType.NEWLY_OBSERVED.value: "#C4291C",       # urgent red — the headline actionable signal
    ChangeType.EXPANDED.value: "#F2A93B",             # accent gold — worth a second look
    ChangeType.POTENTIALLY_REMOVED.value: "#A13D3D",  # muted red-brown — verify, lower urgency than new
    ChangeType.UNCERTAIN.value: "#B8934A",            # dusty gold-brown — low confidence, needs more data
}
CHANGE_TYPE_ICONS = {
    ChangeType.EXISTING.value: "●",
    ChangeType.NEWLY_OBSERVED.value: "▲",
    ChangeType.EXPANDED.value: "◆",
    ChangeType.POTENTIALLY_REMOVED.value: "✕",
    ChangeType.UNCERTAIN.value: "?",
}
# Per-category stroke weight / fill opacity for map polygons — actionable
# categories get a heavier outline and denser fill on top of a more
# saturated color, so they visually dominate the muted contextual layers
# sharing the same map rather than relying on hue alone.
CHANGE_TYPE_EMPHASIS = {
    ChangeType.EXISTING.value: (1.0, 0.35),
    ChangeType.UNCERTAIN.value: (1.2, 0.45),
    ChangeType.POTENTIALLY_REMOVED.value: (1.6, 0.55),
    ChangeType.EXPANDED.value: (2.0, 0.65),
    ChangeType.NEWLY_OBSERVED.value: (2.5, 0.78),
}
PRIORITY_COLORS = {
    Priority.P1.value: "#C4291C",        # urgent red — same semantic red as everywhere else
    Priority.P2.value: "#E07B00",        # elevated orange
    Priority.P3.value: NEUTRAL_BLUE,     # muted but visibly blue — recedes without vanishing into the basemap
    Priority.P4.value: NEUTRAL_BLUE_LIGHT,  # pale version of the same hue — lowest priority
}
PRIORITY_EMPHASIS = {
    Priority.P1.value: (2.5, 0.78),
    Priority.P2.value: (1.8, 0.6),
    Priority.P3.value: (1.0, 0.35),
    Priority.P4.value: (1.0, 0.25),
}
CLOSED_COLOR = "#2E7D32"  # verified / closed — green
HOSTING_STATUS_COLORS = {
    HostingCapacityStatus.LOW_CONCERN.value: "#2E7D32",
    HostingCapacityStatus.MONITOR.value: "#F2A93B",
    HostingCapacityStatus.REVIEW_RECOMMENDED.value: "#C4291C",
    HostingCapacityStatus.DATA_INCOMPLETE.value: NEUTRAL_BLUE,
}
# Reviewer case-management state colors — used for the Alert Inbox state
# breakdown, the Review & Decide state-group picker, and the case-history
# timeline. End states (Registered / False positive) use CLOSED_COLOR-style
# tones so they read as "done" at a glance.
REVIEW_STATE_COLORS = {
    ReviewAction.FOR_INSPECTION.value: "#5B7A9C",
    ReviewAction.FOR_REGISTRATION.value: "#F2A93B",
    ReviewAction.ONGOING_REGISTRATION.value: "#F57C00",
    ReviewAction.REGISTERED.value: "#2E7D32",
    ReviewAction.FALSE_POSITIVE.value: "#8A8A8A",
}

# --- Core design tokens -------------------------------------------------------
# Follows the Waypoint semantic design language (WAYPOINT_DESIGN_LANGUAGE.md),
# light-theme adaptation: Inter at controlled weights, a conservative token
# palette, and one intentional accent (teal, #0F5E7A) rather than a
# multi-color gradient — restraint over decoration, per the "Trust" and
# "Professionalism" principles. The teal accent is reserved for genuine
# emphasis and interactive elements; it is not used decoratively.
INK = "#141414"
INK_MUTED = "#63676B"
PRIMARY = "#0F5E7A"       # Waypoint primary teal
PRIMARY_DARK = "#0A4A5F"
ACCENT = "#0F5E7A"        # Waypoint teal accent — the one intentional accent color
SURFACE = "#F7F7F5"
CARD_BG = "#FFFFFF"
BORDER = "#DEDEDA"

# Inter — the Waypoint brand typeface, used for every piece of UI text (not
# just headlines), at controlled weights rather than a decorative display font.
FONT_STACK = (
    "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)
# Reserved for figures and short technical values (KPI numbers, factsheet
# values) — a monospace gives measurements/IDs a "precision instrument" feel
# without setting entire paragraphs in mono, which would hurt readability.
MONO_STACK = (
    "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
)

# Small, self-contained stroke icons (no external icon-font/network dependency).
_ICONS = {
    "sun": '<path d="M12 4V2M12 22v-2M4 12H2m20 0h-2M5.6 5.6 4.2 4.2m15.6 15.6-1.4-1.4M5.6 18.4l-1.4 1.4M18.4 5.6l1.4-1.4"/><circle cx="12" cy="12" r="4.2"/>',
    "building": '<path d="M4 21V5a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v16"/><path d="M14 21V9a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v12"/><path d="M8 8h1M8 11h1M8 14h1M17 12h1M17 15h1M2 21h20"/>',
    "trending": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 6h6v6"/>',
    "bolt": '<path d="M12.5 2 4 14h6l-1 8 9.5-13h-6l1-7Z"/>',
    "bell": '<path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
    "pin": '<path d="M12 22s7-6.2 7-12a7 7 0 1 0-14 0c0 5.8 7 12 7 12Z"/><circle cx="12" cy="10" r="2.4"/>',
    "layers": '<path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
    "check": '<path d="m4 12 6 6 10-13"/>',
    # Two overlapping circles — the standard single-line-diagram symbol for
    # a transformer's coupled windings. Used for transformer map markers
    # instead of a plain colored dot, so the marker itself reads as "this is
    # a transformer" rather than an unlabeled shape.
    "transformer": '<circle cx="9" cy="12" r="6.2"/><circle cx="15" cy="12" r="6.2"/>',
}


def _icon_svg(name: str, size: int = 18, color: str = "currentColor", stroke_width: float = 1.8) -> str:
    body = _ICONS.get(name, _ICONS["sun"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="{stroke_width}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )


_KPI_ICON_CYCLE = ["building", "trending", "bolt", "bell", "pin", "layers"]


def _flatten_html(html: str) -> str:
    """Strip each line's leading/trailing whitespace from a multi-line HTML
    string.

    CommonMark treats 4+ leading spaces on a line as an "indented code
    block", which would otherwise cause the nicely source-indented,
    multi-line HTML literals used throughout this module to render as
    literal escaped text instead of being interpreted as HTML. Flattening
    avoids that entirely, regardless of how deeply nested the original
    Python source indentation was.
    """
    return "\n".join(line.strip() for line in html.strip().splitlines())


def render_html(html: str) -> None:
    """Render a (possibly indented, multi-line) HTML string as raw HTML in
    the main content area. See ``_flatten_html`` for why this is needed."""
    st.markdown(_flatten_html(html), unsafe_allow_html=True)


def render_sidebar_html(html: str) -> None:
    """Same as ``render_html``, but renders into the sidebar."""
    st.sidebar.markdown(_flatten_html(html), unsafe_allow_html=True)


def safe_number(value, default: float = 0.0) -> float:
    """Return ``value`` as a plain number, or ``default`` if it is None/NaN.

    Pandas silently coerces ``None`` to ``NaN`` in numeric (float) columns,
    so both must be treated as "missing" wherever a value is formatted into
    a string (``f"{value:.0f}"`` on NaN prints the literal text "nan").
    """
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return value


def inject_base_style() -> None:
    """The PV Watch design system: fonts, cards, header, badges, KPI grid,
    and light restyling of native Streamlit controls (metrics, buttons,
    tables, sidebar, radio pills)."""
    render_html(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

        /* Streamlit's own widgets (buttons, inputs, dataframes, radios, the
           file uploader, etc.) set their font-family via higher-specificity
           generated styles, so a plain "html, body" rule only reaches our
           own custom-HTML blocks (headers, cards, sidebar) — not native
           controls in the main content area. ".stApp *" plus !important
           forces the typeface everywhere; the mono-value rules further down
           this stylesheet use !important too, so they still win on ties by
           source order. */
        html, body, [class*="css"], .stApp, .stApp * {{ font-family: {FONT_STACK} !important; }}

        /* The blanket rule above also overrides Streamlit's own Material
           Symbols icon font, which chrome controls (like the sidebar
           collapse/expand chevron) rely on to turn a ligature name such as
           "keyboard_double_arrow_right" into an actual glyph. Restore the
           icon font specifically for icon-rendering elements — these
           selectors carry extra attribute/class specificity so they win
           over the blanket rule regardless of source order. */
        .stApp [data-testid="stIconMaterial"],
        .stApp [data-testid*="Icon"] span[class*="material"],
        .stApp span[class*="material-symbols"],
        .stApp span[class*="material-icons"],
        .stApp i[class*="material"] {{
            font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', 'Material Icons' !important;
        }}

        /* Use the full viewport width — no centered/capped content column,
           so there's no dead whitespace down the left/right edges on wide
           monitors. Keep a small side gutter purely for breathing room. */
        .block-container {{
            padding-top: 1.6rem; padding-bottom: 2rem;
            padding-left: 2.2rem; padding-right: 2.2rem;
            max-width: 100%;
        }}
        [data-testid="stAppViewContainer"] > .main {{ width: 100%; }}
        #MainMenu {{ visibility: hidden; }}
        footer {{ visibility: hidden; }}

        /* ---------- Header banner ---------- */
        /* Flat, solid ink — no gradient/glow — reads closer to a precise,
           structured masthead than a decorative SaaS hero. */
        .pv-header-banner {{
            background: {INK}; border-radius: 12px; padding: 2.1rem 2.4rem; margin-bottom: 1.4rem;
            min-height: 108px;
            display: flex; align-items: center; gap: 1.3rem; flex-wrap: wrap;
        }}
        .pv-header-icon {{
            flex: 0 0 auto; width: 58px; height: 58px; border-radius: 10px;
            background: rgba(255,255,255,0.12); display: flex; align-items: center; justify-content: center;
            color: {ACCENT};
        }}
        .pv-header-text {{ flex: 1 1 auto; min-width: 240px; }}
        .pv-header-title {{ font-size: 2.05rem; font-weight: 700; color: #FFFFFF; letter-spacing: -0.01em; line-height: 1.15; }}
        .pv-header-tagline {{ font-size: 1.02rem; color: #C9CCCF; margin-top: 0.25rem; font-weight: 500; }}
        .pv-page-pill {{
            flex: 0 0 auto; align-self: center; background: rgba(255,255,255,0.1); color: #EDEDED;
            border: 1px solid rgba(255,255,255,0.22); border-radius: 4px; padding: 8px 16px;
            font-size: 0.84rem; font-weight: 600; white-space: nowrap; letter-spacing: 0.01em;
        }}

        /* ---------- Section headers ---------- */
        .pv-section-title {{
            font-size: 1.02rem; font-weight: 700; color: {INK}; margin-top: 0.2rem;
            padding-left: 0.6rem; border-left: 3px solid {ACCENT}; line-height: 1.3;
        }}
        .pv-caption {{ font-size: 0.82rem; color: {INK_MUTED}; padding-left: 0.6rem; margin-top: 0.1rem; }}

        /* ---------- Badges ---------- */
        .pv-badge {{
            display: inline-flex; align-items: center; gap: 4px; border-radius: 4px; padding: 3px 10px;
            font-size: 0.75rem; font-weight: 600; color: white; white-space: nowrap; letter-spacing: 0.02em;
        }}

        /* ---------- Notices ---------- */
        .pv-disclaimer {{
            background-color: #FAFAF8; border: 1px solid {BORDER}; border-left: 3px solid {ACCENT};
            padding: 0.7rem 1rem; border-radius: 4px; font-size: 0.86rem; color: {INK}; margin: 0.5rem 0 1.1rem 0;
            display: flex; gap: 0.55rem; align-items: flex-start;
        }}
        .pv-synthetic-note {{
            display: inline-flex; align-items: center; gap: 0.4rem; background: {SURFACE}; color: {INK};
            border: 1px solid {BORDER}; border-radius: 4px; padding: 0.45rem 0.75rem; font-size: 0.82rem;
            margin: 0.2rem 0 0.9rem 0;
        }}

        /* ---------- KPI cards ---------- */
        .pv-kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0.7rem; margin-bottom: 0.6rem; }}
        .pv-kpi-card {{
            background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 8px; padding: 0.95rem 1.05rem;
            transition: border-color 0.12s ease;
        }}
        .pv-kpi-card:hover {{ border-color: {INK}; }}
        .pv-kpi-top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.35rem; }}
        .pv-kpi-icon {{
            width: 28px; height: 28px; border-radius: 5px; background: {SURFACE};
            color: {INK}; display: flex; align-items: center; justify-content: center;
        }}
        .pv-kpi-value {{ font-family: {MONO_STACK} !important; font-size: 1.4rem; font-weight: 700; color: {INK}; line-height: 1.1; }}
        .pv-kpi-label {{
            font-size: 0.72rem; color: {INK_MUTED}; font-weight: 600; margin-top: 0.25rem;
            text-transform: uppercase; letter-spacing: 0.03em;
        }}

        /* ---------- Cards / containers ---------- */
        .pv-card {{
            background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 8px; padding: 1rem 1.15rem;
            margin-bottom: 0.8rem;
        }}

        /* ---------- Factsheets (clean label/value detail grids) ---------- */
        .pv-factsheet-title {{
            font-size: 0.74rem; font-weight: 700; color: {INK_MUTED}; text-transform: uppercase;
            letter-spacing: 0.05em; margin-bottom: 0.55rem;
        }}
        .pv-factsheet {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 0.75rem 1.4rem; }}
        .pv-factsheet-label {{
            font-size: 0.7rem; font-weight: 600; color: {INK_MUTED}; text-transform: uppercase; letter-spacing: 0.04em;
        }}
        .pv-factsheet-value {{ font-family: {MONO_STACK} !important; font-size: 0.94rem; font-weight: 600; color: {INK}; margin-top: 0.15rem; line-height: 1.3; }}
        .pv-factsheet-divider {{ border-top: 1px solid {BORDER}; margin: 0.9rem 0; }}

        /* ---------- Map legend ---------- */
        .pv-legend {{
            display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem 1rem;
            background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 6px;
            padding: 0.5rem 0.85rem; margin: 0.5rem 0 0.6rem 0; font-size: 0.8rem; color: {INK};
        }}
        .pv-legend-title {{
            font-weight: 700; color: {INK_MUTED}; margin-right: 0.2rem; text-transform: uppercase;
            letter-spacing: 0.03em; font-size: 0.72rem;
        }}
        .pv-legend-item {{ display: inline-flex; align-items: center; gap: 0.35rem; white-space: nowrap; }}
        .pv-legend-dot {{ width: 9px; height: 9px; border-radius: 2px; flex: 0 0 auto; }}

        /* ---------- Tabs ---------- */
        button[data-baseweb="tab"] {{ font-weight: 600; color: {INK_MUTED}; }}
        button[data-baseweb="tab"][aria-selected="true"] {{ color: {INK}; }}
        [data-baseweb="tab-highlight"] {{ background-color: {ACCENT}; }}

        /* ---------- Footer ---------- */
        .pv-footer {{
            margin-top: 2.2rem; padding-top: 0.9rem; border-top: 1px solid {BORDER};
            font-size: 0.76rem; color: {INK_MUTED}; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.4rem;
        }}

        /* ---------- Native Streamlit control restyling ---------- */
        [data-testid="stMetric"] {{
            background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 8px; padding: 0.85rem 1rem 0.7rem 1rem;
        }}
        [data-testid="stMetricLabel"] {{ color: {INK_MUTED}; font-weight: 600; }}
        [data-testid="stMetricValue"] {{ font-family: {MONO_STACK} !important; color: {INK}; font-weight: 700; }}

        div.stButton > button {{
            border-radius: 4px; border: 1px solid {INK}; color: {INK}; font-weight: 600;
            background: white; transition: background 0.12s ease, color 0.12s ease;
        }}
        div.stButton > button:hover {{ background: {INK}; color: white; border-color: {INK}; }}
        div.stButton > button[kind="primary"] {{ background: {INK}; color: white; }}

        /* Download buttons: filled dark by default (not outline-then-fill),
           matching the flat ink chrome used elsewhere. */
        div.stDownloadButton > button {{
            border-radius: 4px; border: 1px solid {INK}; color: white; font-weight: 600;
            background: {INK}; transition: background 0.12s ease;
        }}
        div.stDownloadButton > button:hover {{ background: {INK_MUTED}; border-color: {INK_MUTED}; color: white; }}
        div.stDownloadButton > button:disabled {{
            background: {SURFACE}; border-color: {BORDER}; color: {INK_MUTED};
        }}

        [data-testid="stDataFrame"] {{ border-radius: 8px; overflow: hidden; border: 1px solid {BORDER}; }}

        /* Match the sidebar's background to the main content area (both
           {CARD_BG}) instead of the slightly darker {SURFACE} tone used for
           card interiors elsewhere — the color contrast plus a solid
           {BORDER} line was reading as two separate panels rather than one
           continuous interface. A faint ink-tinted hairline (not the full
           {BORDER} gray) still marks where the sidebar ends for wayfinding,
           without drawing a hard seam. */
        section[data-testid="stSidebar"] {{ background: {CARD_BG}; border-right: 1px solid rgba(20, 20, 20, 0.07); }}
        section[data-testid="stSidebar"] .stMultiSelect, section[data-testid="stSidebar"] .stSlider {{
            margin-bottom: 0.35rem;
        }}

        /* ---------- Custom sidebar navigation (built with st.page_link,
           since the native pages/ auto-nav can't be reordered, grouped, or
           selectively styled) ---------- */
        .pv-nav-section-title {{
            font-size: 0.7rem; font-weight: 700; color: {INK_MUTED}; text-transform: uppercase;
            letter-spacing: 0.05em; margin: 0.3rem 0 0.2rem 0.5rem;
        }}
        .pv-nav-divider {{ border-top: 1px solid {BORDER}; margin: 0.7rem 0.5rem; }}
        section[data-testid="stSidebar"] [data-testid="stPageLink"] {{ margin-bottom: -0.15rem; }}
        section[data-testid="stSidebar"] [data-testid="stPageLink"] p {{ font-size: 0.8rem; }}

        /* Company/product credit block, pinned to the bottom of the sidebar
           (not just the end of the nav list) via position:sticky against
           the sidebar's own scroll container — so it reads as permanent
           chrome (lower-left of the screen) rather than another nav row. */
        .pv-sidebar-brand {{
            position: sticky; bottom: 0; background: {CARD_BG};
            padding: 0.9rem 0 0.4rem 0; margin-top: 1.4rem; border-top: 1px solid {BORDER};
        }}

        div[role="radiogroup"] {{ gap: 0.4rem; }}
        div[role="radiogroup"] label {{
            border: 1px solid {BORDER}; border-radius: 4px; padding: 0.28rem 0.85rem !important;
            background: {CARD_BG}; transition: border-color 0.12s ease;
        }}
        div[role="radiogroup"] label:hover {{ border-color: {INK}; }}

        [data-testid="stExpander"] {{ border: 1px solid {BORDER}; border-radius: 8px; }}
        </style>
        """
    )


def render_app_header(config: AppConfig, page_subtitle: Optional[str] = None) -> None:
    """Render the shared PV Watch gradient header banner, tagline, and demo badge."""
    inject_base_style()
    pill_html = f"<div class='pv-page-pill'>{page_subtitle}</div>" if page_subtitle else ""
    render_html(
        f"""
        <div class="pv-header-banner">
            <div class="pv-header-icon">{_icon_svg("sun", size=30, color=ACCENT)}</div>
            <div class="pv-header-text">
                <div class="pv-header-title">{config.app.name}</div>
                <div class="pv-header-tagline">{config.app.tagline}</div>
            </div>
            {pill_html}
        </div>
        """
    )


def render_disclaimer(text: str) -> None:
    st.markdown(
        f"<div class='pv-disclaimer'><span style='flex:0 0 auto;margin-top:1px;'>{_icon_svg('bell', size=16, color='#B8860B')}</span>"
        f"<span>{text}</span></div>",
        unsafe_allow_html=True,
    )


def render_synthetic_data_notice(scope: str = "registry and network") -> None:
    st.markdown(
        f"<div class='pv-synthetic-note'>{_icon_svg('layers', size=14, color=INK)}"
        f"<span>The {scope} data shown here are <b>synthetic demonstration data</b> — not real utility records.</span></div>",
        unsafe_allow_html=True,
    )


def change_badge_html(change_type: str) -> str:
    color = CHANGE_TYPE_COLORS.get(change_type, "#8A8A8A")
    icon = CHANGE_TYPE_ICONS.get(change_type, "•")
    return f"<span class='pv-badge' style='background-color:{color}'>{icon} {change_type}</span>"


def priority_badge_html(priority: str) -> str:
    color = PRIORITY_COLORS.get(priority, "#8A8A8A")
    return f"<span class='pv-badge' style='background-color:{color}'>{priority}</span>"


def status_badge_html(label: str, closed: bool = False) -> str:
    color = CLOSED_COLOR if closed else "#5B7A9C"
    return f"<span class='pv-badge' style='background-color:{color}'>{label}</span>"


def review_state_badge_html(state: str) -> str:
    color = REVIEW_STATE_COLORS.get(state, "#5B7A9C")
    suffix = " (end state)" if state in {ReviewAction.REGISTERED.value, ReviewAction.FALSE_POSITIVE.value} else ""
    return f"<span class='pv-badge' style='background-color:{color}'>{state}{suffix}</span>"


def kpi_row(items: list[tuple[str, str, Optional[str]]]) -> None:
    """Render a responsive grid of polished KPI cards.

    ``items`` is a list of ``(label, value, help_text)`` tuples — the same
    signature used throughout the app, now rendered as custom HTML cards
    (with a rotating icon set) instead of bare ``st.metric`` widgets for a
    more polished, consistent look across every page.
    """
    cards = []
    for i, (label, value, help_text) in enumerate(items):
        icon = _KPI_ICON_CYCLE[i % len(_KPI_ICON_CYCLE)]
        title_attr = f' title="{help_text}"' if help_text else ""
        cards.append(
            _flatten_html(
                f"""
                <div class="pv-kpi-card"{title_attr}>
                    <div class="pv-kpi-top">
                        <div class="pv-kpi-icon">{_icon_svg(icon, size=16)}</div>
                    </div>
                    <div class="pv-kpi-value">{value}</div>
                    <div class="pv-kpi-label">{label}</div>
                </div>
                """
            )
        )
    render_html(f"<div class='pv-kpi-grid'>{''.join(cards)}</div>")


def section_title(title: str, caption: Optional[str] = None) -> None:
    st.markdown(f"<div class='pv-section-title'>{title}</div>", unsafe_allow_html=True)
    if caption:
        st.markdown(f"<div class='pv-caption'>{caption}</div>", unsafe_allow_html=True)


def render_footer(config: AppConfig) -> None:
    render_html(
        f"""
        <div class="pv-footer">
            <span>{config.app.name} · {config.app.tagline}</span>
            <span>Demonstration build · v{config.app.version}</span>
        </div>
        """
    )


def render_sidebar_brand(config: AppConfig) -> None:
    """A branded block anchored at the bottom of the sidebar, below the page nav.

    Two levels of identity, consistent with external materials (e.g. the
    pitch deck): the "PV Watch" product lockup (icon + name + tagline), and
    beneath it — separated by a hairline, with its own small geo-dot mark —
    an explicit "A product of Waypoint" company credit line, so the sidebar
    reads unambiguously as a company-made product rather than a standalone
    tool. Pinned to the bottom of the viewport (not just the end of the nav
    list) via a flex-column sidebar with this block's ``margin-top: auto``.
    """
    geo_dot = (
        f'<div style="width:13px;height:13px;border-radius:50%;border:1.4px solid {ACCENT};'
        f'display:flex;align-items:center;justify-content:center;flex:0 0 auto;">'
        f'<div style="width:5px;height:5px;border-radius:50%;background:{ACCENT};"></div></div>'
    )
    render_sidebar_html(
        f"""
        <div class="pv-sidebar-brand">
            <div style="display:flex;align-items:center;gap:0.5rem;">
                <div style="width:28px;height:28px;border-radius:5px;background:{INK};
                            display:flex;align-items:center;justify-content:center;color:{ACCENT};flex:0 0 auto;">
                    {_icon_svg("sun", size=15, color=ACCENT)}
                </div>
                <div>
                    <div style="font-weight:700;font-size:0.94rem;color:{INK};line-height:1.1;">{config.app.name}</div>
                    <div style="font-size:0.71rem;color:{INK_MUTED};">{config.app.tagline}</div>
                </div>
            </div>
            <div style="display:flex;align-items:center;gap:0.45rem;margin-top:0.65rem;
                        padding-top:0.6rem;border-top:1px solid {BORDER};">
                {geo_dot}
                <div style="font-size:0.72rem;color:{INK_MUTED};">
                    A product of <span style="color:{INK};font-weight:700;">Waypoint</span>
                </div>
            </div>
        </div>
        """
    )


# -----------------------------------------------------------------------------
# Map helpers
# -----------------------------------------------------------------------------

def make_base_map(center_lat: float, center_lon: float, zoom: int = 15, locate: bool = False) -> folium.Map:
    """A clean, light basemap suitable for a utility demonstration.

    Adds a fullscreen control to every map by default so reviewers can
    expand a map to inspect detail without leaving the page.
    """
    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, tiles="CartoDB positron", control_scale=True)
    Fullscreen(position="topright", title="Expand map", title_cancel="Exit fullscreen").add_to(fmap)
    if locate:
        LocateControl(position="topright").add_to(fmap)
    _inject_geojson_detail_style(fmap)
    return fmap


def render_map_legend(items: list[tuple[str, str]], title: Optional[str] = None) -> None:
    """Render a compact color-key legend for a map (folium has no built-in
    legend, so this renders one as a small HTML strip directly above/below
    the map)."""
    title_html = f'<span class="pv-legend-title">{title}</span>' if title else ""
    swatches = "".join(
        f'<span class="pv-legend-item"><span class="pv-legend-dot" style="background:{color}"></span>{label}</span>'
        for label, color in items
    )
    render_html(f'<div class="pv-legend">{title_html}{swatches}</div>')


def render_factsheet_sections(sections: list[tuple[Optional[str], list[tuple[str, str]]]]) -> None:
    """Render one or more label/value "factsheet" groups inside a single card.

    A flat grid of short uppercase labels over bold values reads faster and
    scales better to any number of fields than paragraph text stitched
    together with manual ``<br>``/``<hr>`` separators — used for structured
    detail panels like the alert case card (registry/network context).

    ``sections`` is a list of ``(title_or_None, [(label, value), ...])``.
    """
    blocks = []
    for i, (title, fields) in enumerate(sections):
        title_html = f'<div class="pv-factsheet-title">{title}</div>' if title else ""
        items = "".join(
            f'<div class="pv-factsheet-item"><div class="pv-factsheet-label">{label}</div>'
            f'<div class="pv-factsheet-value">{value}</div></div>'
            for label, value in fields
        )
        sep = '<div class="pv-factsheet-divider"></div>' if i > 0 else ""
        blocks.append(f'{sep}{title_html}<div class="pv-factsheet">{items}</div>')
    render_html(f'<div class="pv-card">{"".join(blocks)}</div>')


# Shared ``style=`` value for ``folium.GeoJsonPopup``/``GeoJsonTooltip`` —
# this is a documented, reliable override point (it sets the wrapping div's
# inline style, so font/background/border are guaranteed to apply, unlike
# trying to reach into folium's internally-generated table markup). Used
# everywhere a layer has too many features for a per-row custom
# ``factsheet_popup_html`` popup to be practical, so those popups/tooltips
# still match the rest of the app's look.
GEOJSON_POPUP_STYLE = (
    f"font-family:{FONT_STACK};font-size:0.82rem;color:{INK};background:{CARD_BG};"
    f"border:1px solid {BORDER};border-radius:8px;padding:6px 8px;"
)

# Every GeoJsonPopup/GeoJsonTooltip built for "polygon metadata" (installation
# label/value panels) shares this class name so a single injected stylesheet
# (see _inject_geojson_detail_style) can style the actual <table>/<th>/<td>
# markup folium generates internally. GEOJSON_POPUP_STYLE alone only reaches
# the outer wrapping div — folium's own default CSS gives cells no borders
# and no padding on values, which is why these looked more like a loose list
# than a table.
GEOJSON_DETAIL_CLASS = "pv-geo-detail"
GEOJSON_DETAIL_TABLE_CSS = f"""
<style>
.{GEOJSON_DETAIL_CLASS} table {{ border-collapse: collapse !important; margin: 0 !important; }}
.{GEOJSON_DETAIL_CLASS} tr {{ text-align: left !important; }}
.{GEOJSON_DETAIL_CLASS} th, .{GEOJSON_DETAIL_CLASS} td {{
    border: 1px solid {BORDER} !important;
    padding: 4px 10px !important;
    font-family: {FONT_STACK} !important;
    font-size: 0.76rem !important;
    line-height: 1.3 !important;
}}
.{GEOJSON_DETAIL_CLASS} th {{
    background: {SURFACE} !important;
    color: {INK_MUTED} !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.03em !important;
    font-size: 0.64rem !important;
    white-space: nowrap !important;
}}
.{GEOJSON_DETAIL_CLASS} td {{
    color: {INK} !important;
    font-weight: 600 !important;
    font-family: {MONO_STACK} !important;
}}
.{GEOJSON_DETAIL_CLASS} tr:nth-child(even) th,
.{GEOJSON_DETAIL_CLASS} tr:nth-child(even) td {{ background: #FBFBFA !important; }}
</style>
"""


def _inject_geojson_detail_style(fmap: folium.Map) -> None:
    """Add the ``.pv-geo-detail`` table stylesheet to this map's own HTML head.

    Each ``st_folium`` map renders inside its own isolated iframe (see the
    note on ``GEOJSON_POPUP_STYLE``/``factsheet_popup_html``), so this has to
    be injected per-map rather than relying on the page's shared ``<style>``
    block — called once from ``make_base_map`` so every map picks it up
    automatically.
    """
    fmap.get_root().header.add_child(folium.Element(GEOJSON_DETAIL_TABLE_CSS), name="pv-geojson-detail-style")


def factsheet_popup_html(fields: list[tuple[str, str]], title: Optional[str] = None, width: int = 230) -> str:
    """Build a clean, fully self-contained (inline-styled) label/value popup.

    Map popups from ``streamlit-folium`` render inside an iframe, so they
    cannot see this app's injected ``<style>`` block — every style has to be
    inline. Used for per-feature ``folium.Popup`` markers (small feature
    counts only; large GeoJson layers should keep using
    ``folium.GeoJsonPopup`` for performance).
    """
    title_html = (
        f'<div style="font-weight:800;font-size:0.85rem;color:{INK};margin-bottom:0.4rem;'
        f'font-family:{FONT_STACK};">{title}</div>'
        if title else ""
    )
    rows = "".join(
        f'<div style="margin-bottom:0.4rem;">'
        f'<div style="font-size:0.68rem;font-weight:600;color:{INK_MUTED};text-transform:uppercase;'
        f'letter-spacing:0.03em;font-family:{FONT_STACK};">{label}</div>'
        f'<div style="font-size:0.86rem;font-weight:700;color:{INK};font-family:{FONT_STACK};">{value}</div>'
        f'</div>'
        for label, value in fields
    )
    return f'<div style="width:{width}px;">{title_html}{rows}</div>'


def add_polygon_layer(
    fmap: folium.Map,
    gdf: gpd.GeoDataFrame,
    color: str,
    layer_name: str,
    tooltip_fields: Optional[list[str]] = None,
    tooltip_aliases: Optional[list[str]] = None,
    show: bool = True,
    weight: float = 1.5,
    fill_opacity: float = 0.55,
) -> None:
    """Add a polygon GeoDataFrame as a styled, tooltip-enabled GeoJson layer.

    ``weight``/``fill_opacity`` default to a neutral mid-emphasis style;
    callers rendering multiple categories on one map (e.g. change type,
    priority) should pass heavier values for actionable categories — see
    ``CHANGE_TYPE_EMPHASIS`` / ``PRIORITY_EMPHASIS`` — so those layers pop
    visually rather than relying on color alone.
    """
    if gdf is None or gdf.empty:
        return
    tooltip = None
    if tooltip_fields:
        available = [f for f in tooltip_fields if f in gdf.columns]
        aliases = tooltip_aliases[: len(available)] if tooltip_aliases else available
        if available:
            tooltip = folium.GeoJsonTooltip(
                fields=available, aliases=aliases, sticky=True,
                style=GEOJSON_POPUP_STYLE, class_name=GEOJSON_DETAIL_CLASS,
            )

    folium.GeoJson(
        gdf.to_json(),
        name=layer_name,
        style_function=lambda _f, c=color, w=weight, fo=fill_opacity: {"fillColor": c, "color": c, "weight": w, "fillOpacity": fo},
        highlight_function=lambda _f, w=weight, fo=fill_opacity: {"weight": w + 1.5, "fillOpacity": min(fo + 0.2, 0.92)},
        tooltip=tooltip,
        show=show,
    ).add_to(fmap)


def add_point_layer(
    fmap: folium.Map,
    gdf: gpd.GeoDataFrame,
    color: str,
    layer_name: str,
    tooltip_fields: Optional[list[str]] = None,
    radius: int = 7,
    show: bool = True,
) -> None:
    if gdf is None or gdf.empty:
        return
    fg = folium.FeatureGroup(name=layer_name, show=show)
    for _, row in gdf.iterrows():
        pt = row.geometry
        tooltip_text = None
        if tooltip_fields:
            tooltip_text = "<br>".join(f"<b>{f}:</b> {row.get(f, '')}" for f in tooltip_fields if f in gdf.columns)
        folium.CircleMarker(
            location=[pt.y, pt.x],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            tooltip=tooltip_text,
        ).add_to(fg)
    fg.add_to(fmap)


def transformer_marker_icon(color: str, size: int = 26, urgent: bool = False) -> folium.DivIcon:
    """A compact colored icon badge for a transformer marker, in place of a
    plain colored circle.

    ``size`` is the outer diameter in pixels — pass one of a few discrete
    tiers (e.g. 22 / 28 / 34) rather than a continuously-scaled value, so
    markers stay compact instead of growing into large blobs for bigger
    transformers. ``urgent`` (Review-recommended transformers) adds a
    colored glow ring so those badges still pop against calmer ones on the
    same map, mirroring the emphasis used for other map layers.
    """
    icon_px = max(int(size * 0.56), 12)
    ring = "box-shadow:0 0 0 3px rgba(196,41,28,0.45);" if urgent else "box-shadow:0 1px 3px rgba(0,0,0,0.28);"
    html = (
        f'<div style="width:{size}px;height:{size}px;border-radius:50%;background:{color};'
        f'border:2px solid #FFFFFF;{ring}display:flex;align-items:center;justify-content:center;">'
        f'{_icon_svg("transformer", size=icon_px, color="#FFFFFF", stroke_width=2)}'
        f'</div>'
    )
    return folium.DivIcon(html=html, icon_size=(size, size), icon_anchor=(size // 2, size // 2))


def dataframe_download_button(label: str, data: bytes, file_name: str, mime: str, key: Optional[str] = None) -> None:
    st.download_button(label=label, data=data, file_name=file_name, mime=mime, key=key, use_container_width=False)


def size_class(area_m2: float) -> str:
    """Bucket an installation's area into a human-readable size class."""
    if area_m2 is None:
        return "Unknown"
    if area_m2 < 20:
        return "Small (<20 m²)"
    if area_m2 < 50:
        return "Medium (20–50 m²)"
    if area_m2 < 90:
        return "Large (50–90 m²)"
    return "Very large (90+ m²)"
