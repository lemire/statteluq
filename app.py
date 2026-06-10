#!/usr/bin/env python3
"""
Explorateur interactif des inscriptions TELUQ
Interface inspirée de Our World in Data — Cours et Programmes
Backend: DuckDB + Plotly
"""

import json
import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# CONFIG & THEME
# =============================================================================
st.set_page_config(
    page_title="Explorateur inscriptions TELUQ",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for polish (cards, tighter spacing, nice badges)
st.markdown("""
<style>
:root {
  --primary: #0ea5e9;
}
.block-container { padding-top: 1.2rem; }
h1, h2, h3 { font-weight: 600; letter-spacing: -0.02em; }
.stMetric { background: #f8fafc; border-radius: 8px; padding: 8px 12px; }
.group-pill {
  display: inline-flex; align-items: center; gap: 6px;
  background: #f1f5f9; border-radius: 9999px; padding: 4px 12px; margin: 3px 4px 3px 0;
  font-size: 0.9rem;
}
.group-pill .count { color: #64748b; font-size: 0.8rem; }
.small { font-size: 0.85rem; color: #64748b; }
.source { font-size: 0.75rem; color: #94a3b8; margin-top: -8px; }
.plot-container { border: 1px solid #e2e8f0; border-radius: 10px; padding: 4px; }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# DATA LOADING (DuckDB backend)
# =============================================================================
def get_connection():
    """Fresh DuckDB connection each time (native objects are not safe to cache across Streamlit reruns)."""
    con = duckdb.connect()
    # Programs view
    con.execute("""
        CREATE OR REPLACE VIEW programmes AS
        SELECT 
            "Uad Code" AS uad,
            Cycle,
            "Prg Code" AS prg_code,
            Nom AS nom,
            CAST("Ses Code" AS VARCHAR) AS ses_code,
            Trimestre,
            Total
        FROM read_csv(
            'Nbre inscriptions par programmes.csv',
            delim=';',
            header=true,
            encoding='latin-1'
        )
    """)
    # Raw courses (includes extraction date for deduplication)
    con.execute("""
        CREATE OR REPLACE VIEW cours_raw AS
        SELECT 
            "Date Extraction" AS date_extraction,
            CAST("Trim." AS VARCHAR) AS trim_code,
            Sigle,
            "Dépt." AS dept,
            "INSC TÉLUQ" AS insc_teluq,
            "INSC BCI" AS insc_bci,
            "INSC. NON COMPLÉTÉES" AS non_completes,
            "ABAN RMB" AS aban,
            "TOTAL INSC." AS total_insc,
            "EETP TÉLUQ" AS eetp_teluq,
            "ETUD ANC" AS etud_anc,
            "ETUD NOUV" AS etud_nouv
        FROM read_csv(
            'Statistiques par cours avec MATCI.csv',
            delim=';',
            header=true,
            encoding='latin-1',
            decimal_separator=','
        )
    """)

    # Deduplicated: for each (trim, Sigle) keep only the row with the most recent extraction date.
    # This avoids overcounting the multiple sub-rows (MATCI/sections) that exist in the source for the same course-trimester.
    con.execute("""
        CREATE OR REPLACE VIEW cours AS
        SELECT 
            date_extraction,
            trim_code,
            Sigle,
            dept,
            insc_teluq,
            insc_bci,
            non_completes,
            aban,
            total_insc,
            eetp_teluq,
            etud_anc,
            etud_nouv
        FROM (
            SELECT 
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY trim_code, Sigle 
                    ORDER BY date_extraction DESC
                ) AS rn
            FROM cours_raw
        ) 
        WHERE rn = 1
    """)
    return con


@st.cache_data(ttl=3600)
def load_meta_cours():
    con = get_connection()
    df = con.execute("""
        SELECT DISTINCT Sigle, dept
        FROM cours
        ORDER BY Sigle
    """).df()
    return df


@st.cache_data(ttl=3600)
def load_meta_programmes():
    con = get_connection()
    df = con.execute("""
        SELECT DISTINCT prg_code, nom, Cycle, uad
        FROM programmes
        ORDER BY prg_code
    """).df()
    return df


@st.cache_data(ttl=3600)
def load_trims_cours():
    con = get_connection()
    df = con.execute("""
        SELECT DISTINCT trim_code
        FROM cours
        ORDER BY trim_code
    """).df()
    return df["trim_code"].tolist()


@st.cache_data(ttl=3600)
def load_trims_programmes():
    con = get_connection()
    df = con.execute("""
        SELECT DISTINCT ses_code
        FROM programmes
        ORDER BY ses_code
    """).df()
    return df["ses_code"].tolist()


@st.cache_data(ttl=3600)
def load_uads_programmes():
    """Distinct UAD (départements) present in the programmes data."""
    con = get_connection()
    df = con.execute("""
        SELECT DISTINCT uad
        FROM programmes
        WHERE uad IS NOT NULL
        ORDER BY uad
    """).df()
    return df["uad"].tolist()


@st.cache_data(ttl=3600)
def load_depts_cours():
    """Distinct departments (Dépt.) present in the cours data."""
    con = get_connection()
    df = con.execute("""
        SELECT DISTINCT dept
        FROM cours
        WHERE dept IS NOT NULL
        ORDER BY dept
    """).df()
    return df["dept"].tolist()


# =============================================================================
# TIME UTILITIES (French academic calendar)
# =============================================================================
SAISONS = {1: "Hiver", 2: "Été", 3: "Automne"}


def parse_trim(code: str):
    """Return (year:int, season:int 1-3, season_name)"""
    if not code or len(code) < 5:
        return 0, 0, "?"
    y = int(code[:4])
    s = int(code[4])
    return y, s, SAISONS.get(s, "?")


def trim_label(code: str, with_code: bool = True) -> str:
    y, s, sn = parse_trim(code)
    base = f"{y} — {sn}"
    return f"{base} ({code})" if with_code else base


def to_academic_year(code: str) -> str:
    """Academic year label starting in fall (automne). Example: 2007-2008"""
    y, s, _ = parse_trim(code)
    start = y if s == 3 else y - 1
    return f"{start}-{start + 1}"


def to_civil_year(code: str) -> str:
    y, _, _ = parse_trim(code)
    return str(y)


def get_course_family(sigle: str) -> str:
    """Extract the prefix/family of a course sigle, e.g. 'INF 1220' -> 'INF', 'ADM 1002' -> 'ADM'."""
    if not sigle:
        return "OTHER"
    s = str(sigle).upper().strip()
    # Leading letters (handles most cases like INF, ADM, ENV, SCO, etc.)
    import re
    match = re.match(r'^([A-Z]+)', s)
    if match:
        return match.group(1)
    # Fallback: first token before space
    if " " in s:
        return s.split()[0]
    return s[:4] if len(s) > 4 else s


def aggregate_period(raw_df: pd.DataFrame, granularity: str) -> pd.DataFrame:
    """
    raw_df has columns: trim_code, valeur, ensemble
    Returns aggregated with columns: ordre, periode, ensemble, valeur
    """
    if raw_df.empty:
        return raw_df
    df = raw_df.copy()
    df["year"] = df["trim_code"].str[:4].astype(int)
    df["season"] = df["trim_code"].str[4].astype(int)

    if granularity == "Par trimestre":
        df["periode"] = df.apply(lambda r: f"{r.year} {SAISONS.get(r.season, '?')}", axis=1)
        df["ordre"] = df["trim_code"].astype(int)
    elif granularity == "Par année civile":
        df["periode"] = df["year"].astype(str)
        df["ordre"] = df["year"]
    else:  # Par année académique (début automne)
        df["ac_start"] = df.apply(lambda r: r.year if r.season == 3 else r.year - 1, axis=1)
        df["periode"] = df["ac_start"].astype(str) + "-" + (df["ac_start"] + 1).astype(str)
        df["ordre"] = df["ac_start"]

    agg = (
        df.groupby(["ordre", "periode", "ensemble"], as_index=False)["valeur"]
        .sum()
        .sort_values(["ordre", "ensemble"])
    )
    return agg


# =============================================================================
# QUERY HELPERS (core analytics via DuckDB)
# =============================================================================
def query_course_groups(
    groups: dict, selected: list[str], start_trim: str, end_trim: str, metric: str
) -> pd.DataFrame:
    """Return long df: trim_code, valeur, ensemble for selected course groups.
    Opens a fresh short-lived DuckDB connection (safer with Streamlit caching).
    """
    con = get_connection()
    if not selected:
        return pd.DataFrame(columns=["trim_code", "valeur", "ensemble"])
    frames = []
    metric_col = {
        "Inscriptions TELUQ (étudiants de la TELUQ)": "insc_teluq",
        "Inscriptions totales (toutes provenances, inclut BCI)": "total_insc",
        "Étudiants nouveaux": "etud_nouv",
        "Étudiants anciens": "etud_anc",
        "EETP TELUQ": "eetp_teluq",
    }[metric]

    for gname in selected:
        group_content = groups.get(gname, [])
        if group_content == "__ALL__":
            # Special case: all courses - no Sigle filter for performance
            sql = f"""
                SELECT trim_code, SUM("{metric_col}") AS valeur
                FROM cours
                WHERE trim_code >= '{start_trim}' AND trim_code <= '{end_trim}'
                GROUP BY trim_code
            """
            df = con.execute(sql).df()
            if not df.empty:
                df["ensemble"] = gname
                frames.append(df)
            continue

        sigles = group_content if isinstance(group_content, list) else []
        if not sigles:
            continue
        # Safe IN clause
        in_list = ",".join(f"'{s.replace(chr(39), chr(39)+chr(39))}'" for s in sigles)
        sql = f"""
            SELECT trim_code, SUM("{metric_col}") AS valeur
            FROM cours
            WHERE trim_code >= '{start_trim}' AND trim_code <= '{end_trim}'
              AND Sigle IN ({in_list})
            GROUP BY trim_code
        """
        df = con.execute(sql).df()
        if not df.empty:
            df["ensemble"] = gname
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["trim_code", "valeur", "ensemble"])
    return pd.concat(frames, ignore_index=True)


def query_program_groups(
    groups: dict, selected: list[str], start_ses: str, end_ses: str
) -> pd.DataFrame:
    """Return long df for program groups. Metric is always Total.
    Opens a fresh short-lived DuckDB connection (safer with Streamlit caching).
    """
    con = get_connection()
    if not selected:
        return pd.DataFrame(columns=["trim_code", "valeur", "ensemble"])
    frames = []
    for gname in selected:
        codes = groups.get(gname, [])
        if not codes:
            continue
        in_list = ",".join(f"'{c.replace(chr(39), chr(39)+chr(39))}'" for c in codes)
        sql = f"""
            SELECT ses_code AS trim_code, SUM(Total) AS valeur
            FROM programmes
            WHERE ses_code >= '{start_ses}' AND ses_code <= '{end_ses}'
              AND prg_code IN ({in_list})
            GROUP BY ses_code
        """
        df = con.execute(sql).df()
        if not df.empty:
            df["ensemble"] = gname
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["trim_code", "valeur", "ensemble"])
    return pd.concat(frames, ignore_index=True)


def get_program_ranking(start_ses: str, end_ses: str, uads: list[str] | None = None) -> pd.DataFrame:
    """Programs ranked by total registrations (SUM Total) for the given ses_code range.
    If uads is provided (non-empty), only programs whose UAD is in the list are included.
    Returns columns: prg_code, nom, uad, cycle, total (sorted desc by total).
    """
    con = get_connection()
    uad_clause = ""
    if uads:
        in_list = ",".join(f"'{u.replace(chr(39), chr(39)+chr(39))}'" for u in uads)
        uad_clause = f"AND uad IN ({in_list})"

    sql = f"""
        SELECT 
            prg_code,
            ANY_VALUE(nom) AS nom,
            ANY_VALUE(uad) AS uad,
            ANY_VALUE(Cycle) AS cycle,
            SUM(Total) AS total
        FROM programmes
        WHERE ses_code >= '{start_ses}' AND ses_code <= '{end_ses}'
        {uad_clause}
        GROUP BY prg_code
        ORDER BY total DESC
    """
    return con.execute(sql).df()


def get_course_ranking(trim_code: str, depts: list[str] | None = None, metric: str = "insc_teluq") -> pd.DataFrame:
    """Courses for a specific trimestre, sorted by the chosen metric (desc).
    Optionally filtered to one or more departments.
    metric: one of 'insc_teluq', 'total_insc', 'etud_nouv', 'etud_anc', 'eetp_teluq'
    """
    con = get_connection()
    dept_clause = ""
    if depts:
        in_list = ",".join(f"'{d.replace(chr(39), chr(39)+chr(39))}'" for d in depts)
        dept_clause = f"AND dept IN ({in_list})"

    sql = f"""
        SELECT 
            Sigle,
            dept,
            insc_teluq,
            total_insc,
            etud_nouv,
            etud_anc,
            eetp_teluq,
            non_completes,
            aban
        FROM cours
        WHERE trim_code = '{trim_code}'
        {dept_clause}
        ORDER BY {metric} DESC
    """
    return con.execute(sql).df()


# =============================================================================
# PLOTTING
# =============================================================================
def make_time_series_figure(
    agg_df: pd.DataFrame, title: str, y_label: str, granularity: str, is_area: bool = False, is_relative: bool = False
) -> go.Figure:
    if agg_df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Aucune donnée pour la sélection", showarrow=False, font={"size": 16})
        fig.update_layout(
            height=420,
            yaxis=dict(rangemode="tozero"),
        )
        return fig

    ordered_periods = (
        agg_df.sort_values("ordre")["periode"].drop_duplicates().tolist()
    )

    color_seq = px.colors.qualitative.Bold + px.colors.qualitative.Set3

    plot_y_label = y_label
    if is_area and is_relative:
        plot_y_label = "% du total"

    if is_area:
        fig = px.area(
            agg_df,
            x="periode",
            y="valeur",
            color="ensemble",
            title=title,
            labels={"valeur": plot_y_label, "periode": "Période"},
            groupnorm="percent" if is_relative else None,
            category_orders={"periode": ordered_periods},
            color_discrete_sequence=color_seq,
        )
    else:
        fig = px.line(
            agg_df,
            x="periode",
            y="valeur",
            color="ensemble",
            markers=True,
            title=title,
            labels={"valeur": y_label, "periode": "Période"},
            category_orders={"periode": ordered_periods},
            color_discrete_sequence=color_seq,
        )

    fig.update_traces(
        line=dict(width=2.8),
        marker=dict(size=5.5, line=dict(width=0.5, color="white")),
        hovertemplate="<b>%{fullData.name}</b><br>%{x}<br>%{y:,.0f}<extra></extra>",
    )
    fig.update_layout(
        template="plotly_white",
        height=520,
        hovermode="x unified",
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, font=dict(size=11), title_text=""),
        margin=dict(l=40, r=20, t=60, b=40),
        xaxis=dict(tickangle=-30 if granularity == "Par trimestre" else 0),
        yaxis=dict(gridcolor="#e2e8f0", zerolinecolor="#cbd5e1", rangemode="tozero"),
        title=dict(font=dict(size=15, color="#0f172a")),
    )
    # Subtle grid like OWID
    fig.update_yaxes(showgrid=True, gridwidth=0.6)
    fig.update_xaxes(showgrid=False)
    return fig


# =============================================================================
# UI HELPERS
# =============================================================================
def get_available_periods(raw_trims: list[str], granularity: str):
    """Build the list of selectable periods adapted to the chosen granularity.
    Each entry has a nice label for the UI and the raw trim bounds to use for filtering.
    This ensures the user can only select full years/academic years when in yearly mode.
    """
    if not raw_trims:
        return []

    if granularity == "Par trimestre":
        return [
            {
                "label": trim_label(t),
                "start_trim": t,
                "end_trim": t,
                "sort_key": t
            }
            for t in raw_trims
        ]

    elif granularity == "Par année civile":
        year_map = {}
        for t in raw_trims:
            y = to_civil_year(t)
            if y not in year_map:
                year_map[y] = []
            year_map[y].append(t)
        years = sorted(year_map.keys())
        res = []
        for y in years:
            trs = year_map[y]
            res.append({
                "label": y,
                "start_trim": min(trs),
                "end_trim": max(trs),
                "sort_key": y
            })
        return res

    else:  # Par année académique (début automne)
        ac_map = {}
        for t in raw_trims:
            ac = to_academic_year(t)
            if ac not in ac_map:
                ac_map[ac] = []
            ac_map[ac].append(t)
        # sort by the starting year of the academic year
        acs = sorted(ac_map.keys(), key=lambda x: int(x.split("-")[0]))
        res = []
        for ac in acs:
            trs = ac_map[ac]
            res.append({
                "label": ac,
                "start_trim": min(trs),
                "end_trim": max(trs),
                "sort_key": ac
            })
        return res


def period_selector(trims: list[str], key_prefix: str, granularity: str, default_recent: int = 12):
    """Two selects for start/end + preset buttons. Returns (start, end) raw trim codes
    that cover complete periods according to the current granularity.
    """
    if not trims:
        return None, None

    periods = get_available_periods(trims, granularity)
    if not periods:
        return None, None

    labels = [p["label"] for p in periods]
    label_to_period = {p["label"]: p for p in periods}

    # sensible look-back depending on granularity
    if "trimestre" in granularity.lower():
        n_back = default_recent
    else:
        n_back = 5  # last 5 full years/academic years

    start_idx = max(0, len(periods) - n_back)

    # dynamic box labels
    if granularity == "Par trimestre":
        box_start = "Du trimestre"
        box_end = "Au trimestre"
    elif granularity == "Par année civile":
        box_start = "De l'année"
        box_end = "À l'année"
    else:
        box_start = "De l'année académique"
        box_end = "À l'année académique"

    c1, c2, c3 = st.columns([1.6, 1.6, 1])

    with c1:
        start_label = st.selectbox(
            box_start,
            options=labels,
            index=start_idx,
            key=f"{key_prefix}_start",
        )
    with c2:
        end_label = st.selectbox(
            box_end,
            options=labels,
            index=len(labels) - 1,
            key=f"{key_prefix}_end",
        )
    with c3:
        st.write("")
        st.write("")
        if st.button("5 dernières années", key=f"{key_prefix}_5y"):
            n = 5 if "trimestre" not in granularity.lower() else 15
            start_idx = max(0, len(periods) - n)
            st.session_state[f"{key_prefix}_start"] = labels[start_idx]
            st.session_state[f"{key_prefix}_end"] = labels[-1]
            st.rerun()
        if st.button("Toute la période", key=f"{key_prefix}_all"):
            st.session_state[f"{key_prefix}_start"] = labels[0]
            st.session_state[f"{key_prefix}_end"] = labels[-1]
            st.rerun()

    start_p = label_to_period[start_label]
    end_p = label_to_period[end_label]

    # compute the overall raw trim range that covers only full selected periods
    s_idx = labels.index(start_label)
    e_idx = labels.index(end_label)
    if s_idx > e_idx:
        s_idx, e_idx = e_idx, s_idx

    sel = periods[s_idx : e_idx + 1]
    overall_start = min(pp["start_trim"] for pp in sel)
    overall_end = max(pp["end_trim"] for pp in sel)

    return overall_start, overall_end


def group_manager(
    title: str,
    all_items: list[str],
    current_groups: dict,
    key_prefix: str,
    quick_prefixes: list[str] | None = None,
    item_display: dict | None = None,
):
    """
    Renders group creation UI + active groups list.
    Returns (possibly mutated) current_groups.
    all_items: list of identifiers (sigle or prg_code)
    item_display: optional map id -> pretty label for multiselect
    """
    st.markdown(f"#### {title}")

    # Active groups display + delete
    if current_groups:
        st.caption(f"{len(current_groups)} ensemble(s) défini(s)")
        for gname, items in list(current_groups.items()):
            cols = st.columns([5.5, 1.2, 1.2, 0.8])
            if items == "__ALL__":
                display_count = "tous les cours"
            else:
                display_count = f"{len(items)} cours" if key_prefix == "cours" else f"{len(items)} programmes"
            cols[0].markdown(f"**{gname}** <span class='count'>({display_count})</span>", unsafe_allow_html=True)
            if cols[1].button("Voir", key=f"see_{key_prefix}_{gname}"):
                if items == "__ALL__":
                    st.info("Tous les cours (environ 2200 sigles différents)")
                else:
                    st.info(", ".join(items[:12]) + (" …" if len(items) > 12 else ""))
            if cols[2].button("Supprimer", key=f"del_{key_prefix}_{gname}"):
                del current_groups[gname]
                st.rerun()
            if cols[3].button("✕", key=f"kill_{key_prefix}_{gname}"):
                del current_groups[gname]
                st.rerun()
    else:
        st.caption("Aucun ensemble. Créez-en ci-dessous.")

    st.divider()

    # Quick prefix helpers (especially useful for courses)
    if quick_prefixes:
        st.caption("Création rapide par préfixe")
        qp_cols = st.columns(len(quick_prefixes))
        for i, pref in enumerate(quick_prefixes):
            if qp_cols[i].button(f"{pref}*", key=f"qp_{key_prefix}_{i}"):
                matches = [it for it in all_items if it.upper().startswith(pref.upper()) or it.upper().startswith(pref.upper() + " ")]
                if matches:
                    current_groups[f"{pref}*"] = matches
                    st.success(f"Ensemble « {pref}* » créé ({len(matches)} éléments)")
                    st.rerun()
                else:
                    st.warning(f"Aucun élément trouvé pour {pref}")

        # Special button to select ALL courses (efficient - no huge IN list)
        st.caption("Ensemble spécial")
        if st.button("➕ Créer 'Tous les cours' (tous les ~2200 sigles)", key=f"all_{key_prefix}"):
            current_groups["Tous les cours"] = "__ALL__"
            st.success("Ensemble « Tous les cours » créé (sélectionne tout automatiquement)")
            st.rerun()

    # Manual / filtered creation
    with st.form(key=f"form_{key_prefix}", clear_on_submit=True):
        filter_text = st.text_input(
            "Filtrer la liste (sigle ou nom contient…)",
            placeholder="INF  ou  ADM  ou  PSY",
            key=f"filt_{key_prefix}",
        )

        filtered = all_items
        if filter_text:
            ft = filter_text.upper()
            filtered = [it for it in all_items if ft in (item_display.get(it, it).upper() if item_display else it.upper())]

        display_opts = [item_display.get(it, it) for it in filtered] if item_display else filtered
        id_for_display = {d: it for d, it in zip(display_opts, filtered)}

        chosen_display = st.multiselect(
            f"Éléments à ajouter ({len(filtered)} correspondants)",
            options=display_opts,
            default=[],
            key=f"ms_{key_prefix}",
            help="Tapez pour rechercher dans la liste",
        )
        chosen_ids = [id_for_display[d] for d in chosen_display]

        gname = st.text_input("Nom de l'ensemble", value=filter_text.strip() or "Nouvel ensemble", key=f"name_{key_prefix}")

        submitted = st.form_submit_button("➕ Créer / Mettre à jour l'ensemble", use_container_width=True)

        if submitted and gname and chosen_ids:
            current_groups[gname] = chosen_ids
            st.success(f"Ensemble « {gname} » mis à jour ({len(chosen_ids)} éléments)")
            st.rerun()

    # Export / import for power users
    with st.expander("Exporter / Importer les ensembles (JSON)"):
        if current_groups:
            json_str = json.dumps(current_groups, ensure_ascii=False, indent=2)
            st.download_button("Télécharger JSON", json_str, file_name=f"ensembles_{key_prefix}.json", mime="application/json")
        uploaded = st.file_uploader("Importer un fichier JSON d'ensembles", type=["json"], key=f"up_{key_prefix}")
        if uploaded:
            try:
                imported = json.load(uploaded)
                current_groups.update(imported)
                st.success("Ensembles importés avec succès")
                st.rerun()
            except Exception as e:
                st.error(f"Erreur import: {e}")

    return current_groups


# =============================================================================
# MAIN APP
# =============================================================================
def main():
    con = get_connection()

    # Header
    st.title("📊 Explorateur des inscriptions — TELUQ")
    st.caption(
        "Analyse interactive des effectifs par cours et par programme. "
        "Créez des ensembles, ajustez la granularité temporelle et explorez les tendances — style Our World in Data."
    )

    # Preload meta (these are cached; each opens a short-lived connection internally)
    meta_cours = load_meta_cours()
    meta_prog = load_meta_programmes()
    trims_cours = load_trims_cours()
    trims_prog = load_trims_programmes()
    uads_prog = load_uads_programmes()
    depts_cours = load_depts_cours()

    all_sigles = meta_cours["Sigle"].tolist()
    all_prg_codes = meta_prog["prg_code"].tolist()
    prg_display = {
        row.prg_code: f"{row.prg_code} — {row.nom[:70]}" for _, row in meta_prog.iterrows()
    }

    # Session state for groups (persists during session)
    if "course_groups" not in st.session_state:
        st.session_state.course_groups = {}
    if "program_groups" not in st.session_state:
        st.session_state.program_groups = {}

    # Quick default examples on first load (nice for demo) — full prefixes, DuckDB handles it
    if not st.session_state.course_groups and all_sigles:
        infs = [s for s in all_sigles if s.upper().startswith("INF")]
        adms = [s for s in all_sigles if s.upper().startswith("ADM 1")]
        if infs:
            st.session_state.course_groups["Cours INF*"] = infs
        if adms:
            st.session_state.course_groups["ADM 1000-1999"] = adms

    if not st.session_state.program_groups and all_prg_codes:
        # Pick a couple of recognizable programs for the first-run demo
        demo = []
        for _, row in meta_prog.iterrows():
            nom = (row.nom or "").lower()
            if any(k in nom for k in ["informatique", "administration", "comptabilité", "psychologie", "éducation"]):
                demo.append(row.prg_code)
            if len(demo) >= 5:
                break
        if not demo:
            demo = all_prg_codes[:3]
        st.session_state.program_groups["Exemple (admin / info / psycho…)"] = demo

    tab_cours, tab_prog = st.tabs(["📘 Cours", "🎓 Programmes"])

    # ==========================================================================
    # TAB COURS
    # ==========================================================================
    with tab_cours:
        st.markdown("### Ensembles de cours")
        st.session_state.course_groups = group_manager(
            "Définissez des ensembles (ex: tous les INF, ou une sélection précise)",
            all_items=all_sigles,
            current_groups=st.session_state.course_groups,
            key_prefix="cours",
            quick_prefixes=["INF", "ADM", "FIN", "COM", "EDU", "PSY", "ENV", "SCO"],
            item_display=None,
        )

        # === Groupes automatiques par département + préfixe de sigle ===
        st.markdown("#### Groupes automatiques par département et préfixe de sigle")
        depts = sorted(meta_cours["dept"].dropna().unique().tolist())
        selected_depts = st.multiselect(
            "Filtrer par département(s)",
            options=depts,
            default=[],
            key="auto_depts_cours",
            help="Sélectionnez un ou plusieurs départements pour générer automatiquement les groupes par préfixe de sigle (ex: ST-INF, ST-ENV, ESA-ADM...)"
        )

        auto_groups = {}  # label -> list of sigles
        if selected_depts:
            for dept in selected_depts:
                dept_mask = meta_cours["dept"] == dept
                dept_sigles = meta_cours.loc[dept_mask, "Sigle"].unique().tolist()
                prefix_map = {}
                for sig in dept_sigles:
                    pref = get_course_family(sig)
                    if pref not in prefix_map:
                        prefix_map[pref] = []
                    prefix_map[pref].append(sig)
                for pref, sigs in sorted(prefix_map.items()):
                    label = f"{dept}-{pref}"
                    auto_groups[label] = sorted(sigs)

            if auto_groups:
                auto_labels = sorted(auto_groups.keys())
                selected_auto_groups = st.multiselect(
                    f"Groupes automatiques à tracer ({len(auto_labels)})",
                    options=auto_labels,
                    default=[],
                    format_func=lambda lbl: f"{lbl} ({len(auto_groups[lbl])} cours)",
                    key="auto_groups_cours",
                    help="Chaque groupe (ex: ST-INF) correspond à tous les cours du département dont le sigle commence par le préfixe. Ils sont tracés comme des ensembles séparés (somme)."
                )

                # NEW: option to explode into individual courses
                available_prefixes = sorted({lbl.split('-', 1)[1] for lbl in auto_labels if '-' in lbl})
                if available_prefixes:
                    explode_prefixes = st.multiselect(
                        "Préfixes à exploser : voir CHAQUE cours individuellement (une ligne par sigle)",
                        options=available_prefixes,
                        default=[],
                        key="explode_prefixes",
                        help="Exemple : choisis 'INF' → tous les cours comme INF 1100, INF 1130, etc. apparaîtront comme des lignes séparées sur le même graphique. Idéal pour comparer l'évolution de chaque cours spécifique."
                    )
                    prefix_individuals = []
                    for pref in explode_prefixes:
                        for lbl, sigs in auto_groups.items():
                            if lbl.endswith('-' + pref):
                                prefix_individuals.extend(sigs)
                    prefix_individuals = sorted(set(prefix_individuals))
                else:
                    explode_prefixes = []
                    prefix_individuals = []
            else:
                selected_auto_groups = []
                explode_prefixes = []
                prefix_individuals = []
                st.caption("Aucun sigle trouvé pour ces départements.")
        else:
            selected_auto_groups = []
            explode_prefixes = []
            prefix_individuals = []
            st.caption("Sélectionnez un ou plusieurs départements pour voir les groupes automatiques par préfixe de sigle (ST-INF, ST-ENV, etc.).")

        st.divider()

        # Controls
        ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1.8, 2.2, 1.4, 1.4])

        # Combine custom + auto for the main selector
        custom_group_names = list(st.session_state.course_groups.keys())
        auto_group_names = list(auto_groups.keys())
        all_plot_options = custom_group_names + auto_group_names
        with ctrl1:
            selected_groups = st.multiselect(
                "Groupes à afficher (ensembles personnalisés + auto par dept/préfixe)",
                options=all_plot_options,
                default=[],  # start empty so first load is fast; user picks what to plot
                key="sel_cours",
            )
        with ctrl2:
            metric = st.selectbox(
                "Métrique",
                options=[
                    "Inscriptions TELUQ (étudiants de la TELUQ)",
                    "Inscriptions totales (toutes provenances, inclut BCI)",
                    "Étudiants nouveaux",
                    "Étudiants anciens",
                    "EETP TELUQ",
                ],
                index=0,
                key="metric_cours",
            )
        with ctrl3:
            granularity = st.selectbox(
                "Granularité",
                ["Par trimestre", "Par année civile", "Par année académique (début automne)"],
                index=0,
                key="gran_cours",
            )
        with ctrl4:
            is_area = st.checkbox("Aires empilées", value=False, key="area_cours")
            is_relative = st.checkbox("Empilage relatif (0-100 %)", value=False, key="relative_cours", disabled=not is_area)

        st.caption(
            "Pour chaque trimestre et chaque sigle, on conserve **uniquement l'enregistrement le plus récent** (basé sur la colonne Date Extraction du fichier source). "
            "Cela évite de sommer les multiples sous-lignes (sections / MATCI / cohortes) présentes dans les données brutes. "
            "Les cours populaires peuvent quand même atteindre plusieurs centaines d'inscriptions par trimestre. "
            "Utilisez la granularité « Par trimestre » + métrique « Inscriptions TELUQ » pour des vues plus précises."
        )

        # Time range
        start_t, end_t = period_selector(trims_cours, "cours", granularity, default_recent=18)

        if not selected_groups and not prefix_individuals:
            st.info("Sélectionnez des groupes dans « Groupes à afficher » (ci-dessus) ou des préfixes à exploser pour générer le graphique.")
        elif not start_t or not end_t:
            st.warning("Aucune période disponible.")
        else:
            # Build effective groups from the unified selection (custom + auto summed)
            effective_groups = {}
            for name in selected_groups:
                if name in st.session_state.course_groups:
                    effective_groups[name] = st.session_state.course_groups[name]
                elif name in auto_groups:
                    effective_groups[name] = auto_groups[name]
                else:
                    effective_groups[name] = [name]  # fallback

            # Add individuals from exploded prefixes (each sigle as its own 1-item group/line)
            for sig in prefix_individuals:
                effective_groups[sig] = [sig]

            effective_selected = list(selected_groups) + prefix_individuals
            raw = query_course_groups(effective_groups, effective_selected, start_t, end_t, metric)
            agg = aggregate_period(raw, granularity)

            y_label = metric
            title = f"Évolution des inscriptions — {granularity.lower()}"
            fig = make_time_series_figure(agg, title, y_label, granularity, is_area=is_area, is_relative=is_relative)

            st.markdown('<div class="plot-container">', unsafe_allow_html=True)
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={
                    "displayModeBar": True,
                    "displaylogo": False,
                    "toImageButtonOptions": {
                        "format": "svg",
                        "filename": "evolution_inscriptions",
                        "scale": 1.0
                    }
                }
            )
            st.markdown("</div>", unsafe_allow_html=True)

            # Explicit SVG download (requires kaleido)
            try:
                svg_bytes = fig.to_image(format="svg", width=1400, height=700)
                st.download_button(
                    "⬇️ Télécharger le graphique (SVG)",
                    data=svg_bytes,
                    file_name=f"evolution_inscriptions_{granularity.replace(' ', '_').replace('(', '').replace(')', '')}.svg",
                    mime="image/svg+xml",
                    key=f"svg_cours_{granularity}_{hash(str(selected_groups)) % 100000}"
                )
            except Exception:
                st.caption("Export SVG : installez `kaleido` (pip install kaleido) pour activer le téléchargement haute qualité.")

            st.markdown(
                f"<div class='source'>Source : TELUQ — Fichier « Statistiques par cours avec MATCI.csv » | "
                f"Période brute : {trim_label(start_t, False)} → {trim_label(end_t, False)}</div>",
                unsafe_allow_html=True,
            )

            # Summary metrics
            if not agg.empty:
                total_val = int(agg["valeur"].sum())
                n_periods = agg["periode"].nunique()
                c1, c2, c3 = st.columns(3)
                c1.metric("Total inscriptions (sélection)", f"{total_val:,}".replace(",", " "))
                c2.metric("Périodes couvertes", n_periods)
                c3.metric("Groupes / lignes tracés", len(selected_groups) + len(prefix_individuals))

            # Data table (pivoted for readability)
            with st.expander("📋 Données du graphique (tableau)"):
                if not agg.empty:
                    pivot = agg.pivot_table(index=["ordre", "periode"], columns="ensemble", values="valeur", aggfunc="sum").reset_index().sort_values("ordre")
                    pivot = pivot.drop(columns=["ordre"], errors="ignore")
                    st.dataframe(pivot, use_container_width=True, hide_index=True)
                    csv = pivot.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "⬇️ Télécharger CSV",
                        csv,
                        file_name=f"cours_{granularity.replace(' ', '_')}.csv",
                        mime="text/csv",
                    )

        # ======================================================================
        # NEW: Single-trim course ranking (parallel to Programmes ranking)
        # ======================================================================
        st.divider()

        st.markdown("### 📈 Classement des cours — inscriptions pour une session")
        st.caption(
            "Sélectionnez une session (trimestre) précise pour voir les cours triés par nombre d'inscriptions "
            "(selon la métrique choisie). Vous pouvez optionnellement filtrer par département."
        )

        # Specific trimestre (session)
        if not trims_cours:
            st.warning("Aucune session disponible dans les données cours.")
        else:
            # Most recent first in the list for convenience; default to latest
            default_trim_idx = len(trims_cours) - 1
            chosen_trim = st.selectbox(
                "Session / Trimestre",
                options=trims_cours,
                index=default_trim_idx,
                format_func=trim_label,
                key="rank_cours_trim",
            )

            # Metric (reuse the same options as the main Cours trend UI)
            metric_label = st.selectbox(
                "Métrique",
                options=[
                    "Inscriptions TELUQ (étudiants de la TELUQ)",
                    "Inscriptions totales (toutes provenances, inclut BCI)",
                    "Étudiants nouveaux",
                    "Étudiants anciens",
                    "EETP TELUQ",
                ],
                index=0,
                key="rank_cours_metric",
            )
            metric_map = {
                "Inscriptions TELUQ (étudiants de la TELUQ)": "insc_teluq",
                "Inscriptions totales (toutes provenances, inclut BCI)": "total_insc",
                "Étudiants nouveaux": "etud_nouv",
                "Étudiants anciens": "etud_anc",
                "EETP TELUQ": "eetp_teluq",
            }
            chosen_metric = metric_map[metric_label]

            # Optional department filter
            selected_depts = st.multiselect(
                "Départements — optionnel (vide = tous)",
                options=depts_cours,
                default=[],
                key="rank_cours_depts",
                help="Ne conserver que les cours dont le département est dans la sélection.",
            )

            cours_rank_df = get_course_ranking(
                chosen_trim,
                selected_depts if selected_depts else None,
                metric=chosen_metric,
            )

            if cours_rank_df.empty:
                st.info("Aucune donnée pour cette session / ces filtres.")
            else:
                # Friendly display columns + the chosen metric highlighted
                display_c = cours_rank_df.rename(
                    columns={
                        "Sigle": "Sigle",
                        "dept": "Dépt.",
                        "insc_teluq": "Insc. TELUQ",
                        "total_insc": "Total Insc.",
                        "etud_nouv": "Nouveaux",
                        "etud_anc": "Anciens",
                        "eetp_teluq": "EETP TELUQ",
                        "non_completes": "Non complétées",
                        "aban": "Abandons",
                    }
                )

                total_metric = int(cours_rank_df[chosen_metric].sum())
                n_courses = len(cours_rank_df)
                n_pos = int((cours_rank_df[chosen_metric] > 0).sum())

                m1, m2, m3 = st.columns(3)
                short_label = metric_label.split("(")[0].strip()
                m1.metric(f"Total {short_label}", f"{total_metric:,}".replace(",", " "))
                m2.metric("Cours", n_courses)
                m3.metric("Avec inscriptions > 0", n_pos)

                # Top N for the table
                max_show_c = min(200, n_courses)
                top_n_c = st.slider(
                    "Nombre de cours à afficher (Top N)",
                    min_value=10,
                    max_value=max_show_c,
                    value=min(50, max_show_c),
                    step=10,
                    key="rank_cours_topn",
                )

                # The ranked table
                st.dataframe(
                    display_c.head(top_n_c),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Insc. TELUQ": st.column_config.NumberColumn(format="%d"),
                        "Total Insc.": st.column_config.NumberColumn(format="%d"),
                        "Nouveaux": st.column_config.NumberColumn(format="%d"),
                        "Anciens": st.column_config.NumberColumn(format="%d"),
                        "EETP TELUQ": st.column_config.NumberColumn(format="%d"),
                        "Non complétées": st.column_config.NumberColumn(format="%d"),
                        "Abandons": st.column_config.NumberColumn(format="%d"),
                    },
                )

                # Download full ranking for this exact scope
                csv_c_rank = display_c.to_csv(index=False).encode("utf-8")
                safe_trim = chosen_trim.replace(" ", "_")
                st.download_button(
                    "⬇️ Télécharger le classement complet (CSV)",
                    data=csv_c_rank,
                    file_name=f"classement_cours_{safe_trim}.csv",
                    mime="text/csv",
                    key=f"dl_rank_cours_{chosen_trim}",
                )

                dept_info = "tous" if not selected_depts else ", ".join(selected_depts)
                st.markdown(
                    f"<div class='source'>Session : {trim_label(chosen_trim, False)} ({chosen_trim}) | Dépt. : {dept_info} | Métrique : {metric_label}</div>",
                    unsafe_allow_html=True,
                )

    # ==========================================================================
    # TAB PROGRAMMES
    # ==========================================================================
    with tab_prog:
        st.markdown("### Ensembles de programmes")
        st.session_state.program_groups = group_manager(
            "Regroupez des programmes (ex: plusieurs baccalauréats, certificats d'un même domaine)",
            all_items=all_prg_codes,
            current_groups=st.session_state.program_groups,
            key_prefix="prog",
            quick_prefixes=None,
            item_display=prg_display,
        )

        st.divider()

        ctrl1, ctrl2, ctrl3 = st.columns([2.5, 1.8, 1.8])
        defined_pgroups = list(st.session_state.program_groups.keys())
        with ctrl1:
            selected_pgroups = st.multiselect(
                "Ensembles de programmes à afficher",
                options=defined_pgroups,
                default=[],  # start empty for fast initial load
                key="sel_prog",
            )
        with ctrl2:
            granularity_p = st.selectbox(
                "Granularité",
                ["Par trimestre", "Par année civile", "Par année académique (début automne)"],
                index=0,
                key="gran_prog",
            )
        with ctrl3:
            is_area_p = st.checkbox("Aires empilées", value=False, key="area_prog")
            is_relative_p = st.checkbox("Empilage relatif (0-100 %)", value=False, key="relative_prog", disabled=not is_area_p)

        start_p, end_p = period_selector(trims_prog, "prog", granularity_p, default_recent=24)

        if not selected_pgroups:
            st.info("Sélectionnez un ou plusieurs ensembles dans « Ensembles de programmes à afficher » (ci-dessus) pour générer le graphique.")
        elif not start_p or not end_p:
            st.warning("Aucune période disponible dans les données programmes.")
        else:
            raw_p = query_program_groups(st.session_state.program_groups, selected_pgroups, start_p, end_p)
            agg_p = aggregate_period(raw_p, granularity_p)

            fig_p = make_time_series_figure(
                agg_p,
                f"Évolution des inscriptions par programmes — {granularity_p.lower()}",
                "Inscriptions (Total)",
                granularity_p,
                is_area=is_area_p,
                is_relative=is_relative_p,
            )

            st.markdown('<div class="plot-container">', unsafe_allow_html=True)
            st.plotly_chart(
                fig_p,
                use_container_width=True,
                config={
                    "displayModeBar": True,
                    "displaylogo": False,
                    "toImageButtonOptions": {
                        "format": "svg",
                        "filename": "evolution_inscriptions_programmes",
                        "scale": 1.0
                    }
                }
            )
            st.markdown("</div>", unsafe_allow_html=True)

            # Explicit SVG download
            try:
                svg_bytes = fig_p.to_image(format="svg", width=1400, height=700)
                st.download_button(
                    "⬇️ Télécharger le graphique (SVG)",
                    data=svg_bytes,
                    file_name=f"evolution_programmes_{granularity_p.replace(' ', '_').replace('(', '').replace(')', '')}.svg",
                    mime="image/svg+xml",
                    key=f"svg_prog_{granularity_p}_{hash(str(selected_pgroups)) % 100000}"
                )
            except Exception:
                st.caption("Export SVG : installez `kaleido` (pip install kaleido) pour activer le téléchargement.")

            st.markdown(
                f"<div class='source'>Source : TELUQ — « Nbre inscriptions par programmes.csv » | "
                f"Période : {trim_label(start_p, False)} → {trim_label(end_p, False)}</div>",
                unsafe_allow_html=True,
            )

            if not agg_p.empty:
                c1, c2, c3 = st.columns(3)
                c1.metric("Total inscriptions (sélection)", f"{int(agg_p['valeur'].sum()):,}".replace(",", " "))
                c2.metric("Périodes", agg_p["periode"].nunique())
                c3.metric("Ensembles", len(selected_pgroups))

            with st.expander("📋 Données du graphique (tableau)"):
                if not agg_p.empty:
                    pivot_p = agg_p.pivot_table(index=["ordre", "periode"], columns="ensemble", values="valeur", aggfunc="sum").reset_index().sort_values("ordre")
                    pivot_p = pivot_p.drop(columns=["ordre"], errors="ignore")
                    st.dataframe(pivot_p, use_container_width=True, hide_index=True)
                    csv_p = pivot_p.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "⬇️ Télécharger CSV",
                        csv_p,
                        file_name=f"programmes_{granularity_p.replace(' ', '_')}.csv",
                        mime="text/csv",
                    )

        # ======================================================================
        # NEW: Single-period program ranking / leaderboard
        # ======================================================================
        st.divider()

        st.markdown("### 📈 Classement des programmes — inscriptions pour une période")
        st.caption(
            "Choisissez un semestre ou une année complète pour voir tous les programmes "
            "triés par nombre total d'inscriptions (colonne Total du fichier source). "
            "Vous pouvez optionnellement filtrer par département (UAD)."
        )

        rank_gran_label = st.selectbox(
            "Granularité",
            ["Par semestre", "Par année civile", "Par année académique (début automne)"],
            index=0,
            key="rank_granularity",
        )

        gran_for_periods = {
            "Par semestre": "Par trimestre",
            "Par année civile": "Par année civile",
            "Par année académique (début automne)": "Par année académique (début automne)",
        }[rank_gran_label]

        periods_rank = get_available_periods(trims_prog, gran_for_periods)
        if not periods_rank:
            st.warning("Aucune période disponible dans les données programmes.")
        else:
            labels_rank = [p["label"] for p in periods_rank]
            label_to_p = {p["label"]: p for p in periods_rank}

            # Most recent by default
            default_idx = len(labels_rank) - 1
            chosen_label = st.selectbox(
                "Période",
                options=labels_rank,
                index=default_idx,
                key="rank_period",
            )
            chosen_period = label_to_p[chosen_label]
            r_start, r_end = chosen_period["start_trim"], chosen_period["end_trim"]

            # Optional department filter
            selected_uads = st.multiselect(
                "Départements (UAD) — optionnel (vide = tous)",
                options=uads_prog,
                default=[],
                key="rank_uads",
                help="Ne conserver que les programmes dont le code UAD est dans la sélection.",
            )

            ranking_df = get_program_ranking(r_start, r_end, selected_uads if selected_uads else None)

            if ranking_df.empty:
                st.info("Aucune inscription trouvée pour cette sélection.")
            else:
                # Friendly column names
                display_df = ranking_df.rename(
                    columns={
                        "prg_code": "Code",
                        "nom": "Programme",
                        "uad": "UAD",
                        "cycle": "Cycle",
                        "total": "Inscriptions",
                    }
                )

                total_insc = int(display_df["Inscriptions"].sum())
                n_programs = len(display_df)
                n_with = int((display_df["Inscriptions"] > 0).sum())

                m1, m2, m3 = st.columns(3)
                m1.metric("Inscriptions totales", f"{total_insc:,}".replace(",", " "))
                m2.metric("Programmes", n_programs)
                m3.metric("Avec inscriptions > 0", n_with)

                # Top N control (table only)
                max_show = min(100, n_programs)
                top_n = st.slider(
                    "Nombre de programmes à afficher (Top N)",
                    min_value=5,
                    max_value=max_show,
                    value=min(30, max_show),
                    step=5,
                    key="rank_topn",
                )

                # The ranked table (no chart)
                st.dataframe(
                    display_df.head(top_n),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Inscriptions": st.column_config.NumberColumn("Inscriptions", format="%d"),
                    },
                )

                # Download the full result for the chosen scope
                csv_rank = display_df.to_csv(index=False).encode("utf-8")
                safe_label = (
                    chosen_label.replace(" ", "_")
                    .replace("—", "-")
                    .replace("(", "")
                    .replace(")", "")
                )
                st.download_button(
                    "⬇️ Télécharger le classement complet (CSV)",
                    data=csv_rank,
                    file_name=f"classement_programmes_{safe_label}.csv",
                    mime="text/csv",
                    key=f"dl_rank_{chosen_label}",
                )

                uad_info = "tous" if not selected_uads else ", ".join(selected_uads)
                st.markdown(
                    f"<div class='source'>Période : {r_start} → {r_end} | UAD : {uad_info}</div>",
                    unsafe_allow_html=True,
                )

    # Sidebar info
    with st.sidebar:
        st.markdown("## ⚙️ À propos")
        st.markdown(
            "Application d'exploration des données d'inscription de la TELUQ. "
            "Les ensembles permettent de comparer des regroupements arbitraires de cours ou de programmes dans le temps."
        )
        st.markdown("**Fonctionnalités**")
        st.markdown("- Groupes par préfixe (INF*, ADM…)\n- 3 granularités dont année académique automne\n- Filtrage temporel précis\n- Métriques multiples (cours)\n- Tableaux exportables")
        st.markdown("**Tech** : DuckDB (backend), Plotly (graphiques), Streamlit")
        st.divider()
        st.caption("Données brutes dans le dossier. Les fichiers CSV sont lus directement.")
        if st.button("♻️ Vider tous les ensembles"):
            st.session_state.course_groups = {}
            st.session_state.program_groups = {}
            st.rerun()


if __name__ == "__main__":
    main()
