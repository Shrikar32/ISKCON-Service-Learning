from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import pandas as pd
import os

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Load Data
EXCEL_FILE = "data/service_learning_data.xlsx"

# Global Data Cache
DF = None
NAV_TREE = {}
ALL_YEARS = []

# Constants
CATEGORY_MAP = {
    "C": "Culture",
    "E": "Education",
    "S": "Social Media",
    "L": "Life Skills",
    "V": "Values",
    "O": "Outreach"
}

CATEGORY_COLORS = {
    "C": "bg-blue-100 text-blue-800",
    "E": "bg-green-100 text-green-800",
    "S": "bg-purple-100 text-purple-800",
    "L": "bg-yellow-100 text-yellow-800",
    "V": "bg-red-100 text-red-800",
    "O": "bg-gray-100 text-gray-800"
}

def load_data():
    """Loads Excel data and builds the navigation tree."""
    global DF, NAV_TREE, ALL_YEARS
    if not os.path.exists(EXCEL_FILE):
        print(f"Error: {EXCEL_FILE} not found.")
        return

    # Load Excel with header in row 2 (index 1)
    df = pd.read_excel(EXCEL_FILE, header=1)
    
    # Clean column names (strip spaces)
    df.columns = df.columns.str.strip()
    
    # Filter rows where 'Year' is valid
    df = df.dropna(subset=['Year'])
    df['Year'] = df['Year'].astype(int).astype(str)
    
    # Ensure Chapter column exists, default to "Unknown" if missing
    if 'Chapter' not in df.columns:
        df['Chapter'] = "General"

    # Sort by Year, then Month
    if 'Month' in df.columns:
        month_order = {
            'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6,
            'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12
        }
        df['MonthNum'] = df['Month'].map(month_order).fillna(0)
        df = df.sort_values(by=['Year', 'MonthNum'])
    else:
        df = df.sort_values(by=['Year'])

    DF = df
    ALL_YEARS = sorted(df['Year'].unique(), reverse=True)

    # Build Navigation Tree: Year -> Chapter -> Month
    nav = {}
    for year in ALL_YEARS:
        year_df = df[df['Year'] == year]
        chapters = sorted(year_df['Chapter'].unique())
        nav[year] = {}
        for chap in chapters:
            chap_df = year_df[year_df['Chapter'] == chap]
            months = []
            if 'Month' in chap_df.columns:
                # Get unique months preserving sorted order
                months = list(dict.fromkeys(chap_df['Month'].dropna()))
            nav[year][chap] = months
    
    NAV_TREE = nav
    print("Data loaded successfully.")

# Load data on startup
load_data()

@app.get("/")
async def home(request: Request):
    if not ALL_YEARS:
        return templates.TemplateResponse("error.html", {"request": request, "message": "No data found."})
    # Redirect to the most recent year
    return RedirectResponse(url=f"/book/{ALL_YEARS[0]}")

@app.get("/book/{year}")
async def book_overview(request: Request, year: str):
    if year not in NAV_TREE:
        raise HTTPException(status_code=404, detail="Year not found")
    
    year_df = DF[DF['Year'] == year]
    
    # Statistics for the dashboard
    total_hours = year_df['Hours'].sum() if 'Hours' in year_df.columns else 0
    total_volunteers = year_df['Volunteers'].sum() if 'Volunteers' in year_df.columns else 0
    total_activities = len(year_df)
    
    # Group activities by Chapter, then by Category
    # Structure: { "ChapterName": { "CategoryCode": [rows...] } }
    chapters_data = {}
    
    chapters = NAV_TREE[year].keys()
    for chap in chapters:
        chap_df = year_df[year_df['Chapter'] == chap]
        
        # Group by Category Code (e.g., C, E, S)
        # Assuming there is a 'Code' or 'Category' column. 
        # Adjust 'Code' below to match your Excel column name exactly.
        cat_groups = {}
        if 'Code' in chap_df.columns:
            # Group by existing codes
            for code, group in chap_df.groupby('Code'):
                cat_groups[code] = group.to_dict(orient="records")
        else:
            # Fallback if no Code column
            cat_groups["O"] = chap_df.to_dict(orient="records")
            
        chapters_data[chap] = cat_groups

    return templates.TemplateResponse("year_overview.html", {
        "request": request,
        "year": year,
        "years": ALL_YEARS,
        "stats": {
            "hours": total_hours,
            "volunteers": total_volunteers,
            "activities": total_activities
        },
        "chapters": chapters_data,
        "nav": NAV_TREE,
        "cat_colors": CATEGORY_COLORS,
        "cat_map": CATEGORY_MAP   # <--- FIX WAS APPLIED HERE
    })

@app.get("/refresh")
async def refresh_data():
    load_data()
    return {"status": "Data reloaded"}
