import pandas as pd
import os
import re
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

# --- 1. INITIALIZATION ---
app = FastAPI()

if not os.path.exists("static"):
    os.makedirs("static")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- 2. CONFIGURATION ---
CATEGORY_COLORS = {
    "ADM": "bg-slate-100 text-slate-700 border-slate-200",
    "FIN": "bg-emerald-50 text-emerald-700 border-emerald-200",
    "GUR": "bg-amber-50 text-amber-700 border-amber-200",
    "ZON": "bg-indigo-50 text-indigo-700 border-indigo-200",
    "EDU": "bg-sky-50 text-sky-700 border-sky-200",
    "LAW": "bg-rose-50 text-rose-700 border-rose-200"
}
MINISTRY_CODE_MAP = ["ADM", "FIN", "GUR", "ZON", "EDU", "LAW"]

RESOLUTION_META = {}
REVERSE_LINKS = {}

# --- 3. HELPERS ---
def clean_id_list(id_str):
    if pd.isna(id_str) or not str(id_str).strip(): return []
    return [x.strip() for x in re.split(r'[,;]', str(id_str)) if x.strip()]

def resolve_links(id_list_str, rel_type):
    links = []
    for rid in clean_id_list(id_list_str):
        rid_clean = str(rid).strip()
        meta = RESOLUTION_META.get(rid_clean)
        if meta:
            links.append({"id": rid_clean, "type": rel_type, "year": meta.get('year', 'N/A'), "date": meta.get('date', 'N/A')})
        else:
            links.append({"id": rid_clean, "type": rel_type, "year": "Ref", "date": "External"})
    return links

def get_era(year):
    try:
        y = int(year)
        return f"{int(y//10 * 10)}s" if y > 0 else "Unknown"
    except: return "Unknown"

# --- 4. DATA ENGINE ---
def load_data():
    global RESOLUTION_META, REVERSE_LINKS
    RESOLUTION_META, REVERSE_LINKS = {}, {}
    data_folder = "data"
    if not os.path.exists(data_folder): return pd.DataFrame()
    files = [f for f in os.listdir(data_folder) if f.endswith(('.csv', '.xlsx')) and not f.startswith('~$')]
    if not files: return pd.DataFrame()
    
    filepath = os.path.join(data_folder, files[0])
    try:
        df = pd.read_csv(filepath) if filepath.endswith('.csv') else pd.read_excel(filepath)
        df.columns = [c.strip() for c in df.columns]
        col_map = {c.lower().replace(" ", "").replace("_", ""): c for c in df.columns}
        
        target_id = col_map.get('resolutionid', 'Resolution_ID')
        target_text = col_map.get('fulltext', 'Full_Text')
        target_title = col_map.get('title', 'Title')
        target_year = col_map.get('year', 'Year')

        df['Resolution_ID'] = df[target_id].fillna("MISSING-ID").astype(str)
        df['Full_Text'] = df[target_text].fillna("").astype(str)
        df['Title'] = df[target_title].fillna("Untitled").astype(str)
        df['Year'] = pd.to_numeric(df[target_year], errors='coerce').fillna(0).astype(int)
        df['Is_Active'] = df.get('Status', pd.Series(['active']*len(df))).astype(str).str.lower() == 'active'
        df['Shelf'] = df['Year'].apply(get_era)

        if 'Section_Ministry' not in df.columns: df['Section_Ministry'] = 'Uncategorized'
        if 'Category' not in df.columns: df['Category'] = 'General'
        if 'Scope' not in df.columns: df['Scope'] = 'Global'

        def get_min_code(row):
            code = str(row.get('Section_Ministry', '')).upper()
            if code in MINISTRY_CODE_MAP: return code
            return "ADM"
        df['Chapter_Code'] = df.apply(get_min_code, axis=1)

        for _, row in df.iterrows():
            rid = str(row['Resolution_ID']).strip()
            RESOLUTION_META[rid] = {"year": row['Year'], "date": str(row.get('Date_Passed', row['Year'])), "title": row['Title']}
            for target in clean_id_list(row.get('Amends_IDs', '')):
                REVERSE_LINKS.setdefault(str(target).strip(), []).append({"type": "AMENDED BY", "source_id": rid, "date": str(row.get('Date_Passed', row['Year']))})
        
        print(f"✅ Data Loaded: {len(df)} records.")
        return df.sort_values(['Year', 'Resolution_ID'], ascending=[False, True])
    except Exception as e:
        print(f"❌ Load Error: {e}")
        return pd.DataFrame()

DF = load_data()
UNIQUE_MINISTRIES = sorted(DF['Section_Ministry'].dropna().unique().tolist()) if not DF.empty else []
UNIQUE_CATEGORIES = sorted(DF['Category'].dropna().unique().tolist()) if not DF.empty else []
UNIQUE_SCOPES = sorted(DF['Scope'].dropna().unique().tolist()) if not DF.empty else []
NAV_TREE = {}
if not DF.empty:
    for shelf in sorted(DF['Shelf'].unique(), reverse=True):
        if shelf != "Unknown":
            NAV_TREE[shelf] = sorted(DF[DF['Shelf'] == shelf]['Year'].unique(), reverse=True)

# --- 5. ROUTES ---

@app.get("/")
async def home(request: Request):
    stats = {
        "count": len(DF),
        "min_year": int(DF['Year'].min()) if not DF.empty else 0,
        "max_year": int(DF['Year'].max()) if not DF.empty else 0,
        "ministries": len(UNIQUE_MINISTRIES)
    }
    return templates.TemplateResponse("home.html", {"request": request, "stats": stats})

@app.get("/archive")
async def archive(request: Request, q: Optional[str] = None, ministry: Optional[str] = None, category: Optional[str] = None, scope: Optional[str] = None, year: Optional[str] = None):
    if DF.empty:
        return templates.TemplateResponse("archive.html", {"request": request, "results": [], "nav": {}})
    
    filtered_df = DF.copy()
    if ministry and ministry != "": filtered_df = filtered_df[filtered_df['Section_Ministry'] == ministry]
    if category and category != "": filtered_df = filtered_df[filtered_df['Category'] == category]
    if scope and scope != "": filtered_df = filtered_df[filtered_df['Scope'] == scope]
    if year and year.isdigit(): filtered_df = filtered_df[filtered_df['Year'] == int(year)]
    
    if q:
        mask = filtered_df['Full_Text'].str.contains(q, case=False, na=False) | \
               filtered_df['Resolution_ID'].str.contains(q, case=False, na=False) | \
               filtered_df['Title'].str.contains(q, case=False, na=False)
        filtered_df = filtered_df[mask]

    results = filtered_df.to_dict('records')
    return templates.TemplateResponse("archive.html", {
        "request": request, "results": results, "query": q, "nav": NAV_TREE,
        "ministries": UNIQUE_MINISTRIES, "categories": UNIQUE_CATEGORIES, "scopes": UNIQUE_SCOPES,
        "selected_ministry": ministry, "selected_category": category, "selected_scope": scope, "selected_year": year,
        "cat_colors": CATEGORY_COLORS
    })

@app.get("/page/{res_id}")
async def page_view(request: Request, res_id: str):
    res_id_clean = str(res_id).strip()
    res_row = DF[DF['Resolution_ID'].astype(str).str.strip() == res_id_clean]
    if res_row.empty: return RedirectResponse("/archive")
    
    res = res_row.iloc[0].to_dict()
    trace = {
        "forward": resolve_links(res.get('Amends_IDs'), "AMENDS") + resolve_links(res.get('Repeals_IDs'), "REPEALS"),
        "backward": REVERSE_LINKS.get(res_id_clean, [])
    }
    return templates.TemplateResponse("resolution.html", {
        "request": request, "res": res, "trace": trace, "cat_colors": CATEGORY_COLORS, "nav": NAV_TREE
    })