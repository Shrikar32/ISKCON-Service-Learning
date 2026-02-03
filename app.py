import pandas as pd
import os
import re
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

# --- 1. INITIALIZATION ---
app = FastAPI()

# Ensure static folder exists for images
if not os.path.exists("static"):
    os.makedirs("static")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- 2. CONFIGURATION ---
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

# Intelligence Indexes
RESOLUTION_META = {} 
REVERSE_LINKS = {} 

# --- 3. HELPERS ---
def clean_id_list(id_str):
    if pd.isna(id_str) or not str(id_str).strip():
        return []
    return [x.strip() for x in re.split(r'[,;]', str(id_str)) if x.strip()]

def resolve_links(id_list_str, rel_type):
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

def get_era(year):
    try:
        y = int(year)
        return f"{int(y//10 * 10)}s"
    except:
        return "Unknown"

# --- 4. DATA ENGINE ---
def load_data():
    global RESOLUTION_META, REVERSE_LINKS
    RESOLUTION_META = {}
    REVERSE_LINKS = {}
    
    data_folder = "data"
    if not os.path.exists(data_folder): 
        return pd.DataFrame()
    
    files = [f for f in os.listdir(data_folder) if f.endswith(('.csv', '.xlsx'))]
    if not files: 
        return pd.DataFrame()
    
    filepath = os.path.join(data_folder, files[0])
    
    try:
        if filepath.endswith('.csv'): 
            df = pd.read_csv(filepath)
        else: 
            df = pd.read_excel(filepath)

        # Basic Cleaning
        df['Year'] = pd.to_numeric(df['Year'], errors='coerce').fillna(0).astype(int)
        df['Is_Active'] = df['Status'].astype(str).str.lower() == 'active'
        df['Shelf'] = df['Year'].apply(get_era)

        # Smart Ministry Classifier
        def get_ministry_code(row):
            code = str(row.get('Section_Ministry', '')).upper()
            if code in CATEGORY_MAP: return code
            text = f"{code} {str(row.get('Category', ''))} {str(row.get('Resolution_ID', ''))} {str(row.get('Title', ''))}".upper()
            if "LAW" in text or "LEGAL" in text: return "LAW"
            if "FIN" in text or "BUDGET" in text: return "FIN"
            if "EDU" in text or "ACADEMIC" in text: return "EDU"
            if "GUR" in text or "INITIATION" in text: return "GUR"
            if "ZON" in text: return "ZON"
            return "ADM"

        df['Chapter_Code'] = df.apply(get_ministry_code, axis=1)

        # Build Intelligence Indexes
        for _, row in df.iterrows():
            rid = str(row['Resolution_ID']).strip()
            RESOLUTION_META[rid] = {
                "year": row['Year'],
                "date": str(row.get('Date_Passed', row['Year'])),
                "title": row['Title']
            }

            # Map Amendments/Repeals to create Backward Traces
            for target in clean_id_list(row.get('Amends_IDs')):
                if target not in REVERSE_LINKS: REVERSE_LINKS[target] = []
                REVERSE_LINKS[target].append({"type": "AMENDED BY", "source_id": rid, "date": row.get('Date_Passed', row['Year'])})

            for target in clean_id_list(row.get('Repeals_IDs')):
                if target not in REVERSE_LINKS: REVERSE_LINKS[target] = []
                REVERSE_LINKS[target].append({"type": "REPEALED BY", "source_id": rid, "date": row.get('Date_Passed', row['Year'])})

        return df.sort_values(['Year', 'Resolution_ID'])
        
    except Exception as e:
        print(f"❌ DATA ERROR: {e}")
        return pd.DataFrame()

# Boot Data
DF = load_data()
ALL_YEARS = sorted(DF['Year'].unique(), reverse=True) if not DF.empty else []
NAV_TREE = {shelf: sorted(DF[DF['Shelf']==shelf]['Year'].unique(), reverse=True) 
            for shelf in sorted(DF['Shelf'].unique(), reverse=True)} if not DF.empty else {}

# --- 5. ROUTES ---

@app.get("/")
async def index(request: Request, q: str = None):
    results = []
    if q and not DF.empty:
        mask = DF['Full_Text'].str.contains(q, case=False, na=False) | DF['Resolution_ID'].str.contains(q, case=False, na=False)
        results = DF[mask].to_dict('records')
    return templates.TemplateResponse("base.html", {
        "request": request, "nav": NAV_TREE, "years": ALL_YEARS, 
        "results": results, "query": q, "cat_colors": CATEGORY_COLORS
    })

@app.get("/book/{year}")
async def book_overview(request: Request, year: int):
    if DF.empty: return RedirectResponse("/")
    
    book_df = DF[DF['Year'] == year]
    
    # Safe Stats
    primary_code = "ADM"
    if not book_df.empty:
        valid_modes = book_df['Chapter_Code'].dropna()
        if not valid_modes.empty:
            primary_code = valid_modes.mode()[0]

    stats = {
        "total": len(book_df),
        "active": len(book_df[book_df['Is_Active']]),
        "primary": primary_code
    }

    chapters = {code: book_df[book_df['Chapter_Code'] == code].to_dict('records') for code in CATEGORY_MAP}
    
    return templates.TemplateResponse("year_overview.html", {
        "request": request, 
        "year": year, 
        "shelf": get_era(year),
        "years": ALL_YEARS, 
        "stats": stats, 
        "chapters": chapters, 
        "nav": NAV_TREE, 
        "cat_map": CATEGORY_MAP, 
        "cat_colors": CATEGORY_COLORS
    })

@app.get("/page/{res_id}")
async def page_view(request: Request, res_id: str):
    if DF.empty: return RedirectResponse("/")
    
    try:
        res_row = DF[DF['Resolution_ID'].astype(str).str.strip() == str(res_id).strip()]
        if res_row.empty:
            raise HTTPException(status_code=404)
            
        res = res_row.iloc[0].to_dict()
        
        # Forward Trace
        forward_trace = []
        forward_trace += resolve_links(res.get('Amends_IDs'), "AMENDS")
        forward_trace += resolve_links(res.get('Repeals_IDs'), "REPEALS")
        
        # Backward Trace
        backward_trace = []
        backward_trace += resolve_links(res.get('Superseded_By'), "SUPERSEDED BY")
        if res_id in REVERSE_LINKS:
            backward_trace += REVERSE_LINKS[res_id]

        return templates.TemplateResponse("resolution.html", {
            "request": request, "res": res, "years": ALL_YEARS, "nav": NAV_TREE,
            "cat_map": CATEGORY_MAP, "cat_colors": CATEGORY_COLORS,
            "trace": {"forward": forward_trace, "backward": backward_trace}
        })
    except:
        return RedirectResponse("/")

@app.get("/refresh")
async def refresh():
    global DF, ALL_YEARS, NAV_TREE
    DF = load_data()
    ALL_YEARS = sorted(DF['Year'].unique(), reverse=True)
    NAV_TREE = {shelf: sorted(DF[DF['Shelf']==shelf]['Year'].unique(), reverse=True) for shelf in sorted(DF['Shelf'].unique(), reverse=True)}
    return {"status": "success"}