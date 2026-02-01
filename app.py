import pandas as pd
import os
import re
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

# Mount Static Assets
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- 1. CONSTANTS: The 6 Ministries ---
CATEGORY_MAP = {
    "ADM": "Administrative & Appointments",
    "FIN": "Financial & Budgetary",
    "GUR": "Sannyasa & Guru Matters",
    "ZON": "Zonal Assignments",
    "EDU": "Education & Training",
    "LAW": "Legal & Constitution"
}

# Professional Color Palette for Ministries
CATEGORY_COLORS = {
    "ADM": "bg-slate-100 text-slate-700 border-slate-200 ring-slate-200",
    "FIN": "bg-emerald-50 text-emerald-700 border-emerald-200 ring-emerald-200",
    "GUR": "bg-amber-50 text-amber-700 border-amber-200 ring-amber-200",
    "ZON": "bg-indigo-50 text-indigo-700 border-indigo-200 ring-indigo-200",
    "EDU": "bg-sky-50 text-sky-700 border-sky-200 ring-sky-200",
    "LAW": "bg-rose-50 text-rose-700 border-rose-200 ring-rose-200"
}

# --- 2. LOGIC: Advanced Classification ---
def classify_chapter(row):
    """Determines the Ministry Code based on keywords in multiple columns."""
    # Combine relevant columns to search for keywords (Active search)
    text = f"{str(row.get('Section_Ministry', ''))} {str(row.get('Category', ''))} {str(row.get('Resolution_ID', ''))} {str(row.get('Title', ''))}".upper()
    
    # Priority Logic (Specific beats General)
    if "LAW" in text or "LEGAL" in text or "CONSTITUTION" in text or "JUSTICE" in text: return "LAW"
    if "FIN" in text or "BUDGET" in text or "AUDIT" in text or "BBT" in text: return "FIN"
    if "EDU" in text or "EDUCATION" in text or "ACADEMIC" in text or "SASTRIC" in text: return "EDU"
    if "GUR" in text or "GURU" in text or "SANNYASA" in text or "INITIATION" in text: return "GUR"
    if "ZON" in text or "ZONE" in text or "GBC ZONAL" in text: return "ZON"
    
    # Default fallback
    return "ADM"

# --- 3. DATA ENGINE: Smart Loader ---
def load_data():
    data_folder = "data"
    if not os.path.exists(data_folder): return pd.DataFrame()
    
    files = [f for f in os.listdir(data_folder) if f.endswith('.csv') or f.endswith('.xlsx')]
    if not files: return pd.DataFrame()
    
    filepath = os.path.join(data_folder, files[0])
    print(f"✅ SYSTEM: Loading data from {files[0]}...")
    
    try:
        if filepath.endswith('.csv'): df = pd.read_csv(filepath)
        else: df = pd.read_excel(filepath)

        # 1. Clean Year
        df['Year'] = pd.to_numeric(df['Year'], errors='coerce').fillna(0).astype(int)
        
        # 2. Apply Classification
        df['Chapter_Code'] = df.apply(classify_chapter, axis=1)
        df['Chapter_Name'] = df['Chapter_Code'].map(CATEGORY_MAP)
        
        # 3. Create Eras (Shelves)
        df['Shelf'] = df['Year'].apply(lambda y: f"{int(y//10 * 10)}s")
        
        # 4. Normalize Status for easy checking
        df['Is_Active'] = df['Status'].astype(str).str.lower() == 'active'
        
        # 5. Sort by Year then Resolution ID
        return df.sort_values(['Year', 'Resolution_ID'])
        
    except Exception as e:
        print(f"❌ DATA ERROR: {e}")
        return pd.DataFrame()

DF = load_data()
ALL_YEARS = sorted(DF['Year'].unique(), reverse=True) if not DF.empty else []

def build_nav():
    nav = {}
    if DF.empty: return nav
    for shelf in sorted(DF['Shelf'].unique()):
        nav[shelf] = sorted(DF[DF['Shelf'] == shelf]['Year'].unique())
    return nav

NAV_TREE = build_nav()

# --- ROUTES ---

@app.get("/")
async def index(request: Request, q: str = None):
    """Homepage & Global Search"""
    results = []
    if q and not DF.empty:
        mask = (
            DF['Resolution_ID'].str.contains(q, case=False, na=False) |
            DF['Title'].str.contains(q, case=False, na=False) |
            DF['Full_Text'].str.contains(q, case=False, na=False)
        )
        results = DF[mask].to_dict('records')
        
    return templates.TemplateResponse("base.html", {
        "request": request, "nav": NAV_TREE, "years": ALL_YEARS, 
        "results": results, "query": q,
        "cat_map": CATEGORY_MAP, "cat_colors": CATEGORY_COLORS
    })

@app.get("/book/{year}")
async def book_overview(request: Request, year: int):
    """Year Overview"""
    if DF.empty: return templates.TemplateResponse("base.html", {"request": request, "nav": NAV_TREE})

    book_df = DF[DF['Year'] == year]
    
    stats = {
        "total": len(book_df),
        "active": len(book_df[book_df['Is_Active'] == True]),
        "primary_code": book_df['Chapter_Code'].mode()[0] if not book_df.empty else "ADM"
    }
    stats['primary_name'] = CATEGORY_MAP.get(stats['primary_code'], "Administrative")

    # Grouping
    chapters = {}
    for code, name in CATEGORY_MAP.items():
        chapters[code] = book_df[book_df['Chapter_Code'] == code].to_dict('records')

    return templates.TemplateResponse("year_overview.html", {
        "request": request, "year": year, "years": ALL_YEARS,
        "shelf": book_df.iloc[0]['Shelf'] if not book_df.empty else "",
        "stats": stats, "chapters": chapters, "nav": NAV_TREE,
        "cat_map": CATEGORY_MAP, "cat_colors": CATEGORY_COLORS
    })

@app.get("/page/{res_id}")
async def page_view(request: Request, res_id: str):
    """Single Resolution View"""
    if DF.empty: return templates.TemplateResponse("base.html", {"request": request, "nav": NAV_TREE})
    try:
        res = DF[DF['Resolution_ID'] == res_id].iloc[0].to_dict()
        return templates.TemplateResponse("resolution.html", {
            "request": request, "res": res, "years": ALL_YEARS, "nav": NAV_TREE,
            "cat_map": CATEGORY_MAP, "cat_colors": CATEGORY_COLORS
        })
    except IndexError:
        return templates.TemplateResponse("base.html", {"request": request, "nav": NAV_TREE})