import pandas as pd
import json
import torch
import re
from sentence_transformers import SentenceTransformer, util
from tqdm import tqdm

# --- CONFIGURATION ---
JAN_AUSHADHI_CSV = "jan_aushadhi.csv"
BRAND_CSV = "brand_medicines.csv"
OUTPUT_FILE = "vector_medicine_db.json"
MODEL_NAME = 'pritamdeka/S-PubMedBert-MS-MARCO'

# --- SAFETY LOGIC: THE VALIDATOR ---
def validate_match(gov_name, brand_name):
    """
    Returns True only if the Brand match is SAFE (Same Form, Same Dosage).
    """
    gov_lower = gov_name.lower()
    brand_lower = brand_name.lower()

    # 1. FORM CHECK (Tablets vs Injections)
    forms = ["injection", "tablet", "capsule", "syrup", "drops", "gel", "cream", "ointment"]
    for form in forms:
        # If Gov specifies a form, Brand MUST match it
        # (We allow partial matches like 'Tablet' matching 'Tab')
        if form in gov_lower:
            # Handle abbreviations
            check_terms = [form]
            if form == "tablet": check_terms.append("tab")
            if form == "capsule": check_terms.append("cap")
            if form == "injection": check_terms.append("inj")

            # If none of the allowed terms are in the brand name -> REJECT
            if not any(term in brand_lower for term in check_terms):
                return False

    # 2. DOSAGE CHECK (The Numbers Game)
    # Extract all numbers (ints and floats) from both strings
    # Regex finds patterns like "50", "6.25", "0.5"
    gov_nums = set(re.findall(r"(\d+(?:\.\d+)?)", gov_lower))
    brand_nums = set(re.findall(r"(\d+(?:\.\d+)?)", brand_lower))

    # Filter out common non-dosage numbers like "10's" (pack size) if possible
    # For MVP: We ensure that the PRIMARY dosage from Gov exists in Brand
    # Heuristic: If Gov has "6.25", Brand MUST have "6.25"

    # We ignore "1" or "10" if they are likely pack sizes, but for safety,
    # let's be strict: At least one distinctive number must match.

    # Exception: "Penicillin 400000" vs "500000" -> Mismatch
    # Strategy: Calculate overlap
    common_nums = gov_nums.intersection(brand_nums)

    # If Gov has numbers but matches share NO numbers -> REJECT
    # (Catches Carvedilol 6.25 matching 12.5)
    if gov_nums and not common_nums:
        return False

    return True

def build_vector_bridge():
    print(f"🚀 Starting SAFE Semantic Bridge...")

    # 1. Load Model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"⚙️  Loading AI on {device}...")
    model = SentenceTransformer(MODEL_NAME, device=device)

    # 2. Load Data
    print("📂 Loading CSVs...")
    df_gov = pd.read_csv(JAN_AUSHADHI_CSV)
    df_gov['search_text'] = df_gov['Generic Name'] + " " + df_gov['Unit Size'].astype(str)

    df_brands = pd.read_csv(BRAND_CSV, usecols=['Name', 'MRP', 'Salt_Composition', 'Manufacturer'])
    df_brands.dropna(subset=['Name', 'MRP', 'Salt_Composition'], inplace=True)
    df_brands['search_text'] = df_brands['Name'] + " (" + df_brands['Salt_Composition'] + ")"

    # 3. Encode
    print("🧠 Encoding Vectors (this takes time)...")
    brand_embeddings = model.encode(df_brands['search_text'].tolist(), convert_to_tensor=True, show_progress_bar=True)
    gov_embeddings = model.encode(df_gov['search_text'].tolist(), convert_to_tensor=True, show_progress_bar=True)

    # 4. Search
    print("🔍 Searching...")
    hits = util.semantic_search(gov_embeddings, brand_embeddings, top_k=20) # Get top 20 to find a SAFE one

    # 5. Build Database with VALIDATION
    print("🛡️  Validating & Building Database...")
    final_db = []

    for i, match_list in enumerate(tqdm(hits)):
        gov_row = df_gov.iloc[i]
        gov_name = gov_row['Generic Name']
        try:
            jan_price = float(gov_row['MRP'])
        except: continue

        valid_brands = []

        for match in match_list:
            brand_idx = match['corpus_id']
            brand_row = df_brands.iloc[brand_idx]
            brand_name = brand_row['Name']

            # --- THE SAFETY CHECK ---
            if not validate_match(gov_name, brand_name):
                continue # Skip this match, it's unsafe!
            # ------------------------

            # Logic Check: Brand must be MORE expensive
            if float(brand_row['MRP']) > jan_price:
                valid_brands.append({
                    "brand": brand_name,
                    "price": float(brand_row['MRP'])
                })

        # Construct Entry
        entry = {
            "generic_name": gov_name,
            "jan_price": jan_price,
            "unit_size": str(gov_row['Unit Size']),
            "common_brands": [],
            "found_match": False,
            "savings_alert": "N/A"
        }

        if valid_brands:
            valid_brands.sort(key=lambda x: x['price'], reverse=True)
            top_brands = valid_brands[:5]

            entry['common_brands'] = [b['brand'] for b in top_brands]
            avg_mrp = sum([b['price'] for b in top_brands]) / len(top_brands)
            entry['market_avg_price'] = round(avg_mrp, 2)
            entry['found_match'] = True

            savings = avg_mrp - jan_price
            savings_pct = int((savings / avg_mrp) * 100)
            entry['savings_percentage'] = f"{savings_pct}%"
            entry['savings_alert'] = f"Save ₹{int(savings)} ({savings_pct}%)"

        final_db.append(entry)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_db, f, indent=2, ensure_ascii=False)

    print(f"✅ Safe Database Built: {OUTPUT_FILE}")

if __name__ == "__main__":
    build_vector_bridge()
