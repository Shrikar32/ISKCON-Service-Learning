import pandas as pd
import os
import re
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- 1. MINISTRIES & CATEGORIES ---
CATEGORY_MAP = {
    "ADM": "Administrative & Appointments",
    "FIN": "Financial & Budgetary",
    "GUR": "Sannyasa & Guru Matters",
    "ZON": "Zonal Assignments",
    "EDU": "Education & Training",
    "LAW": "Legal & Constitution"
}

CATEGORY_COLORS = {
    "ADM": "bg-slate-100 text-slate-700 border-slate-200",
    "FIN": "bg-emerald-50 text-emerald-700 border-emerald-200",
    "GUR": "bg-amber-50 text-amber-700 border-amber-200",
    "ZON": "bg-indigo-50 text-indigo-700 border-indigo-200",
    "EDU": "bg-sky-50 text-sky-700 border-sky-200",
    "LAW": "bg-rose-50 text-rose-700 border-rose-200"
}

# --- 2. GLOBAL INDEXES (The Brain) ---
# We store metadata here so we can look up dates/years instantly
RESOLUTION_META = {} 
# We store reverse links here (e.g., who amended whom)
REVERSE_LINKS = {} 

def clean_id_list(id_str):
    """Splits 'GBC-01, GBC-02' into a clean list."""
    if pd.isna(id_str) or not str(id_str).strip():
        return []
    return [x.strip() for x in re.split(r'[,;]', str(id_str)) if x.strip()]

def load_data():
    global RESOLUTION_META, REVERSE_LINKS
    RESOLUTION_META = {}
    REVERSE_LINKS = {}
    
    data_folder = "data"
    if not os.path.exists(data_folder): return pd.DataFrame()
    files = [f for f in os.listdir(data_folder) if f.endswith(('.csv', '.xlsx'))]
    if not files: return pd.DataFrame()
    
    filepath = os.path.join(data_folder, files[0])
    
    try:
        if filepath.endswith('.csv'): df = pd.read_csv(filepath)
        else: df = pd.read_excel(filepath)

        # 1. Clean & Classify
        df['Year'] = pd.to_numeric(df['Year'], errors='coerce').fillna(0).astype(int)
        
        # Smart Ministry Classifier
        def get_ministry_code(row):
            # If the file specifically says "FIN" or "EDU", trust it first
            code = str(row.get('Section_Ministry', '')).upper()
            if code in CATEGORY_MAP: return code
            
            # Otherwise, guess based on keywords
            text = f"{code} {str(row.get('Category', ''))} {str(row.get('Resolution_ID', ''))} {str(row.get('Title', ''))}".upper()
            if "LAW" in text or "LEGAL" in text: return "LAW"
            if "FIN" in text or "BUDGET" in text: return "FIN"
            if "EDU" in text or "ACADEMIC" in text: return "EDU"
            if "GUR" in text or "INITIATION" in text: return "GUR"
            if "ZON" in text: return "ZON"
            return "ADM"

        df['Chapter_Code'] = df.apply(get_ministry_code, axis=1)
        df['Chapter_Name'] = df['Chapter_Code'].map(CATEGORY_MAP)
        df['Shelf'] = df['Year'].apply(lambda y: f"{int(y//10 * 10)}s")
        df['Is_Active'] = df['Status'].astype(str).str.lower() == 'active'

        # 2. POPULATE INTELLIGENCE INDEXES
        for idx, row in df.iterrows():
            rid = str(row['Resolution_ID']).strip()
            
            # A. Store Metadata for Lookup
            RESOLUTION_META[rid] = {
                "year": row['Year'],
                "date": str(row.get('Date_Passed', row['Year'])),
                "title": row['Title']
            }

            # B. Build Reverse Links (The Time Machine)
            # If This Res (A) amends Old Res (B), we tell B about it.
            
            # Handle Amendments
            for target in clean_id_list(row.get('Amends_IDs')):
                if target not in REVERSE_LINKS: REVERSE_LINKS[target] = []
                REVERSE_LINKS[target].append({
                    "type": "AMENDED BY",
                    "source_id": rid,
                    "date": row.get('Date_Passed', row['Year']),
                    "year": row['Year']
                })

            # Handle Repeals
            for target in clean_id_list(row.get('Repeals_IDs')):
                if target not in REVERSE_LINKS: REVERSE_LINKS[target] = []
                REVERSE_LINKS[target].append({
                    "type": "REPEALED BY",
                    "source_id": rid,
                    "date": row.get('Date_Passed', row['Year']),
                    "year": row['Year']
                })

        return df.sort_values(['Year', 'Resolution_ID'])
        
    except Exception as e:
        print(f"❌ DATA ERROR: {e}")
        return pd.DataFrame()

DF = load_data()
ALL_YEARS = sorted(DF['Year'].unique(), reverse=True) if not DF.empty else []
NAV_TREE = {shelf: sorted(DF[DF['Shelf']==shelf]['Year'].unique()) for shelf in sorted(DF['Shelf'].unique())} if not DF.empty else {}

# --- HELPER: Resolve Links ---
def resolve_links(id_list_str, rel_type):
    """Turns 'ID1, ID2' into detailed objects with dates."""
    links = []
    for rid in clean_id_list(id_list_str):
        meta = RESOLUTION_META.get(rid, {"year": "Unknown", "date": "Unknown"})
        links.append({
            "id": rid,
            "type": rel_type,
            "year": meta['year'],
            "date": meta['date']
        })
    return links

# --- ROUTES ---
@app.get("/")
async def index(request: Request, q: str = None):
    results = []
    if q and not DF.empty:
        mask = DF['Full_Text'].str.contains(q, case=False, na=False) | DF['Resolution_ID'].str.contains(q, case=False, na=False)
        results = DF[mask].to_dict('records')
    return templates.TemplateResponse("base.html", {"request": request, "nav": NAV_TREE, "years": ALL_YEARS, "results": results, "query": q})

@app.get("/book/{year}")
async def book_overview(request: Request, year: int):
    if DF.empty: return templates.TemplateResponse("base.html", {"request": request, "nav": NAV_TREE})
    book_df = DF[DF['Year'] == year]
    stats = {
        "total": len(book_df),
        "active": len(book_df[book_df['Is_Active']]),
        "primary": book_df['Chapter_Code'].mode()[0] if not book_df.empty else "ADM"
    }
    chapters = {code: book_df[book_df['Chapter_Code'] == code].to_dict('records') for code in CATEGORY_MAP}
    return templates.TemplateResponse("year_overview.html", {
        "request": request, "year": year, "years": ALL_YEARS, "stats": stats, "chapters": chapters, 
        "nav": NAV_TREE, "cat_map": CATEGORY_MAP, "cat_colors": CATEGORY_COLORS
    })

@app.get("/page/{res_id}")
async def page_view(request: Request, res_id: str):
    if DF.empty: return templates.TemplateResponse("base.html", {"request": request, "nav": NAV_TREE})
    try:
        res = DF[DF['Resolution_ID'] == res_id].iloc[0].to_dict()
        
        # 1. Forward Traces (What this resolution does to others)
        forward_trace = []
        forward_trace += resolve_links(res.get('Amends_IDs'), "AMENDS")
        forward_trace += resolve_links(res.get('Repeals_IDs'), "REPEALS")
        
        # 2. Backward Traces (What others did to this resolution)
        # We check both the CSV column 'Superseded_By' AND our computed REVERSE_LINKS
        backward_trace = []
        backward_trace += resolve_links(res.get('Superseded_By'), "SUPERSEDED BY")
        
        if res_id in REVERSE_LINKS:
            # Add the computed reverse links (avoiding duplicates if possible)
            backward_trace += REVERSE_LINKS[res_id]

        return templates.TemplateResponse("resolution.html", {
            "request": request, "res": res, "years": ALL_YEARS, "nav": NAV_TREE,
            "cat_map": CATEGORY_MAP, "cat_colors": CATEGORY_COLORS,
            "trace": {"forward": forward_trace, "backward": backward_trace}
        })
    except IndexError:
        return templates.TemplateResponse("base.html", {"request": request, "nav": NAV_TREE})