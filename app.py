import pandas as pd
import os
import re
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- 1. CONFIGURATION ---
# We still use these purely for COLOR matching, but not for text replacement.
CATEGORY_COLORS = {
    "ADM": "bg-slate-100 text-slate-700 border-slate-200",
    "FIN": "bg-emerald-50 text-emerald-700 border-emerald-200",
    "GUR": "bg-amber-50 text-amber-700 border-amber-200",
    "ZON": "bg-indigo-50 text-indigo-700 border-indigo-200",
    "EDU": "bg-sky-50 text-sky-700 border-sky-200",
    "LAW": "bg-rose-50 text-rose-700 border-rose-200"
}

# --- 2. INTELLIGENCE ENGINE ---
RESOLUTION_META = {} 
REVERSE_LINKS = {} 

def clean_id_list(id_str):
    if pd.isna(id_str) or not str(id_str).strip(): return []
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

        # 1. Clean Data
        df['Year'] = pd.to_numeric(df['Year'], errors='coerce').fillna(0).astype(int)
        df['Is_Active'] = df['Status'].astype(str).str.lower() == 'active'

        # 2. EXACT WORDING ENGINE
        def process_row(row):
            # A. Get the EXACT text from Excel (No shortening)
            raw_ministry = str(row.get('Section_Ministry', '')).strip()
            raw_category = str(row.get('Category', '')).strip()
            
            # Use Section_Ministry if valid, otherwise Category, otherwise "General"
            if raw_ministry and raw_ministry.lower() != 'nan':
                display_name = raw_ministry
            elif raw_category and raw_category.lower() != 'nan':
                display_name = raw_category
            else:
                display_name = "General Administrative"
                
            # B. Determine Color Code (ADM, FIN, etc.) based on keywords
            # We ONLY use this for the CSS class, not for the text.
            text_for_color = f"{display_name} {raw_category} {str(row.get('Title', ''))}".upper()
            
            if "LAW" in text_for_color or "LEGAL" in text_for_color or "JUSTICE" in text_for_color: code = "LAW"
            elif "FIN" in text_for_color or "BUDGET" in text_for_color or "AUDIT" in text_for_color: code = "FIN"
            elif "EDU" in text_for_color or "ACADEMIC" in text_for_color: code = "EDU"
            elif "GUR" in text_for_color or "INITIATION" in text_for_color: code = "GUR"
            elif "ZON" in text_for_color or "ZONE" in text_for_color: code = "ZON"
            else: code = "ADM"
            
            return pd.Series([display_name, code])

        df[['Display_Ministry', 'Style_Code']] = df.apply(process_row, axis=1)
        df['Shelf'] = df['Year'].apply(lambda y: f"{int(y//10 * 10)}s")

        # 3. BUILD TRACEABILITY INDEX
        for idx, row in df.iterrows():
            rid = str(row['Resolution_ID']).strip()
            RESOLUTION_META[rid] = {
                "year": row['Year'],
                "date": str(row.get('Date_Passed', row['Year'])),
                "title": row['Title']
            }

            # Forward Links (Amends/Repeals) -> Reverse Logic
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

DF = load_data()
ALL_YEARS = sorted(DF['Year'].unique(), reverse=True) if not DF.empty else []
NAV_TREE = {shelf: sorted(DF[DF['Shelf']==shelf]['Year'].unique()) for shelf in sorted(DF['Shelf'].unique())} if not DF.empty else {}

# --- HELPER: Resolve Links ---
def resolve_links(id_list_str, rel_type):
    links = []
    for rid in clean_id_list(id_list_str):
        meta = RESOLUTION_META.get(rid, {"year": "Unknown", "date": "Unknown"})
        links.append({"id": rid, "type": rel_type, "year": meta['year'], "date": meta['date']})
    return links

# --- ROUTES ---
@app.get("/")
async def index(request: Request, q: str = None):
    results = []
    if q and not DF.empty:
        mask = DF['Full_Text'].str.contains(q, case=False, na=False) | DF['Resolution_ID'].str.contains(q, case=False, na=False)
        results = DF[mask].to_dict('records')
    return templates.TemplateResponse("base.html", {"request": request, "nav": NAV_TREE, "years": ALL_YEARS, "results": results, "query": q, "cat_colors": CATEGORY_COLORS})

@app.get("/book/{year}")
async def book_overview(request: Request, year: int):
    if DF.empty: return templates.TemplateResponse("base.html", {"request": request, "nav": NAV_TREE})
    book_df = DF[DF['Year'] == year]
    
    # We group by Style_Code (Color) for layout, but the items inside keep their Exact Name
    chapters = {code: book_df[book_df['Style_Code'] == code].to_dict('records') for code in CATEGORY_COLORS}
    
    stats = {
        "total": len(book_df),
        "active": len(book_df[book_df['Is_Active']]),
        "primary": book_df['Display_Ministry'].mode()[0] if not book_df.empty else "General"
    }
    
    return templates.TemplateResponse("year_overview.html", {
        "request": request, "year": year, "years": ALL_YEARS, "stats": stats, "chapters": chapters, 
        "nav": NAV_TREE, "cat_colors": CATEGORY_COLORS
    })

@app.get("/page/{res_id}")
async def page_view(request: Request, res_id: str):
    if DF.empty: return templates.TemplateResponse("base.html", {"request": request, "nav": NAV_TREE})
    try:
        res = DF[DF['Resolution_ID'] == res_id].iloc[0].to_dict()
        
        forward = resolve_links(res.get('Amends_IDs'), "AMENDS") + resolve_links(res.get('Repeals_IDs'), "REPEALS")
        backward = resolve_links(res.get('Superseded_By'), "SUPERSEDED BY")
        if res_id in REVERSE_LINKS: backward += REVERSE_LINKS[res_id]

        return templates.TemplateResponse("resolution.html", {
            "request": request, "res": res, "years": ALL_YEARS, "nav": NAV_TREE,
            "cat_colors": CATEGORY_COLORS,
            "trace": {"forward": forward, "backward": backward}
        })
    except IndexError:
        return templates.TemplateResponse("base.html", {"request": request, "nav": NAV_TREE})