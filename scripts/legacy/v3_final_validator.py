import pandas as pd
import json
import torch
import re
from sentence_transformers import SentenceTransformer, util
from tqdm import tqdm

# --- CONFIGURATION ---
JAN_AUSHADHI_CSV = "jan_aushadhi.csv"
BRAND_CSV = "brand_medicines.csv"
OUTPUT_FILE = "final_medicine_db.json"

# We use a medical-specific model for better semantic understanding
MODEL_NAME = 'pritamdeka/S-PubMedBert-MS-MARCO'

# --- SAFETY LOGIC: THE VALIDATOR ---
def validate_match(gov_name, brand_name):
    """
    Returns True only if the Brand match is SAFE (Same Form, Same Dosage).
    """
    gov_lower = gov_name.lower()
    brand_lower = brand_name.lower()

    # 1. FORM CHECK (Strict Type Matching)
    # Maps generic keywords to specific brand keywords
    form_map = {
        "injection": ["injection", "inj", "vial", "ampoule", "pfs", "cartridge"],
        "tablet": ["tablet", "tab", "caplet"],
        "capsule": ["capsule", "cap", "softgel"],
        "syrup": ["syrup", "syr", "suspension", "solution", "liquid", "oral drop"],
        "drops": ["drops", "drop"],
        "gel": ["gel", "jelly"],
        "cream": ["cream", "ointment", "topical", "lotion"],
        "powder": ["powder", "granules", "sachet"],
        "strip": ["strip", "film", "patch"]
    }

    for gov_form, brand_keywords in form_map.items():
        # If Gov specifies a form (e.g., "Powder")
        if gov_form in gov_lower:
            # Brand MUST contain one of the matching keywords
            if not any(kw in brand_lower for kw in brand_keywords):
                return False

    # 2. DOSAGE CHECK (The "Numbers Game")
    # Extract numbers (integers & floats) from both strings
    gov_nums = set(re.findall(r"(\d+(?:\.\d+)?)", gov_lower))
    brand_nums = set(re.findall(r"(\d+(?:\.\d+)?)", brand_lower))

    # If Gov has numbers
    if gov_nums:
        # Calculate intersection
        common_nums = gov_nums.intersection(brand_nums)

        # RULE A: If Gov has numbers, Brand MUST share at least one.
        # (Prevents matching "Carvedilol 6.25" to "Carvedilol 12.5")
        if not common_nums:
            return False

        # RULE B: Major Dosage Guard
        # If Gov has a large number (like "650", "500", "1000"),
        # that EXACT number must exist in Brand.
        # (Prevents matching "Paracetamol 650" to "Paracetamol 500")
        for num in gov_nums:
            if float(num) >= 100:
                if num not in brand_nums:
                    return False

    return True

def build_vector_bridge():
    print(f"🚀 Starting SAFE Semantic Bridge using {MODEL_NAME}...")

    # --- STEP 1: LOAD AI MODEL ---
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"⚙️  Loading AI on {device.upper()}...")
    try:
        model = SentenceTransformer(MODEL_NAME, device=device)
    except Exception as e:
        print(f"❌ Error loading model: {e}")
        return

    # --- STEP 2: LOAD DATA ---
    print("📂 Loading CSVs...")
    try:
        # Load Gov Data
        df_gov = pd.read_csv(JAN_AUSHADHI_CSV)
        # Combine Name + Unit Size for context (e.g., "Atorvastatin 10mg")
        df_gov['search_text'] = df_gov['Generic Name'] + " " + df_gov['Unit Size'].astype(str)

        # Load Brand Data
        df_brands = pd.read_csv(BRAND_CSV, usecols=['Name', 'MRP', 'Salt_Composition', 'Manufacturer'])
        df_brands.dropna(subset=['Name', 'MRP', 'Salt_Composition'], inplace=True)
        # Search text: "Brand Name (Salt Name)"
        df_brands['search_text'] = df_brands['Name'] + " (" + df_brands['Salt_Composition'] + ")"

        print(f"✅ Loaded {len(df_gov)} Govt & {len(df_brands)} Brand Medicines.")
    except Exception as e:
        print(f"❌ Error loading CSVs: {e}")
        return

    # --- STEP 3: CREATE EMBEDDINGS ---
    print("🧠 Encoding Vectors (this takes time)...")
    brand_embeddings = model.encode(df_brands['search_text'].tolist(), convert_to_tensor=True, show_progress_bar=True)
    gov_embeddings = model.encode(df_gov['search_text'].tolist(), convert_to_tensor=True, show_progress_bar=True)

    # --- STEP 4: SEMANTIC SEARCH ---
    print("🔍 Searching for matches...")
    # Get top 20 candidates to allow Validator to filter out bad ones
    hits = util.semantic_search(gov_embeddings, brand_embeddings, top_k=20)

    # --- STEP 5: BUILD & VALIDATE ---
    print("🛡️  Validating Matches...")

    final_db = []
    matches_found = 0

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
                continue # Skip unsafe match
            # ------------------------

            # Logic Check: Brand must be MORE expensive (otherwise no savings)
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
            # Sort by Price (High -> Low) to show highest value switches
            valid_brands.sort(key=lambda x: x['price'], reverse=True)
            top_brands = valid_brands[:5]

            entry['common_brands'] = [b['brand'] for b in top_brands]

            # Calculate Real Market Average
            avg_mrp = sum([b['price'] for b in top_brands]) / len(top_brands)
            entry['market_avg_price'] = round(avg_mrp, 2)
            entry['found_match'] = True

            # Calculate Savings
            savings = avg_mrp - jan_price
            savings_pct = int((savings / avg_mrp) * 100)
            entry['savings_percentage'] = f"{savings_pct}%"
            entry['savings_alert'] = f"Save ₹{int(savings)} ({savings_pct}%)"

            matches_found += 1

        final_db.append(entry)

    # --- STEP 6: SAVE ---
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_db, f, indent=2, ensure_ascii=False)

    print("\n" + "="*50)
    print(f"✅ SAFE BRIDGE COMPLETE!")
    print(f"🔗 Mapped {matches_found} / {len(df_gov)} generics with Safety Validation.")
    print(f"📂 Database saved to: {OUTPUT_FILE}")
    print("="*50)

if __name__ == "__main__":
    build_vector_bridge()
