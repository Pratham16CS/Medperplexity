import pandas as pd
import json
import torch
import re
from sentence_transformers import SentenceTransformer, util
from tqdm import tqdm

# --- CONFIGURATION ---
JAN_AUSHADHI_CSV = "jan_aushadhi.csv"
BRAND_CSV = "brand_medicines.csv"
OUTPUT_FILE = "safe_medicine_db.json"
MODEL_NAME = 'pritamdeka/S-PubMedBert-MS-MARCO'

# --- HELPER: TEXT TOKENIZER (Crucial for Chemical Safety) ---
def get_tokens(text):
    """
    Splits text into significant chemical words to prevent hallucinations.
    Ex: "Carbamazepine Prolonged Release" -> {'carbamazepine'}
    """
    if not isinstance(text, str): return set()
    text = text.lower()

    # Remove noise words so we focus on the DRUG NAME
    noise = [
        "tablets", "tablet", "capsules", "capsule", "injection", "inj", "ip", "bp", "usp",
        "mg", "ml", "mcg", "gm", "w/v", "w/w", "syr", "syrup", "suspension", "solution",
        "prolonged", "release", "sustained", "extended", "coated", "enteric", "dispersible",
        "soft", "gelatin", "mouth", "wash", "paint", "drops", "eye", "ear", "nasal"
    ]
    for w in noise:
        text = text.replace(f" {w} ", " ")
        text = text.replace(f" {w}", " ")
        text = text.replace(f"{w} ", " ")

    # Remove special chars
    text = re.sub(r'[^a-z\s]', '', text)

    # Return unique words with len > 3 (avoids 'a', 'of', 'in')
    return {w for w in text.split() if len(w) > 3}

# --- SAFETY LOGIC: THE VALIDATOR ---
def validate_match(gov_name, brand_name, brand_salt):
    """
    Returns True only if:
    1. Form matches (Tablet == Tablet)
    2. Dosage matches (400 == 400)
    3. Chemical matches (Carbamazepine in Gov == Carbamazepine in Salt)
    """
    gov_lower = gov_name.lower()
    brand_lower = brand_name.lower()
    brand_salt_lower = str(brand_salt).lower()

    # --- CHECK 1: NON-DRUG FILTER ---
    devices = ["binder", "support", "belt", "device", "mask", "needle", "syringe", "crutch", "canula"]
    if any(d in gov_lower for d in devices):
        gov_tokens = get_tokens(gov_lower)
        brand_tokens = get_tokens(brand_lower)
        if not gov_tokens.intersection(brand_tokens):
            return False

    # --- CHECK 2: FORM CHECK ---
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
        if gov_form in gov_lower:
            if not any(kw in brand_lower for kw in brand_keywords):
                return False

    # --- CHECK 3: CHEMICAL OVERLAP (The Missing Piece in your code) ---
    gov_tokens = get_tokens(gov_lower)
    salt_tokens = get_tokens(brand_salt_lower)

    # Exception: Multi-vitamins often fail token match, allow them if generic
    if "vitamin" not in gov_lower and "mineral" not in gov_lower:
        if gov_tokens and salt_tokens:
            # There MUST be at least one common chemical word
            # e.g. Gov: {'carbamazepine'} | Brand Salt: {'itraconazole'} -> Overlap: Empty -> FAIL
            if not gov_tokens.intersection(salt_tokens):
                return False

    # --- CHECK 4: DOSAGE CHECK ---
    gov_nums = set(re.findall(r"(\d+(?:\.\d+)?)", gov_lower))
    brand_nums = set(re.findall(r"(\d+(?:\.\d+)?)", brand_lower))

    if gov_nums:
        common_nums = gov_nums.intersection(brand_nums)
        # Rule A: Must share at least one number
        if not common_nums: return False

        # Rule B: Major Dosage Guard (>100mg must match exact)
        for num in gov_nums:
            if float(num) >= 100:
                if num not in brand_nums: return False

    return True

def build_vector_bridge():
    print(f"🚀 Starting CHEMICALLY SAFE Bridge...")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"⚙️  Loading AI on {device.upper()}...")
    try:
        model = SentenceTransformer(MODEL_NAME, device=device)
    except: return

    print("📂 Loading CSVs...")
    df_gov = pd.read_csv(JAN_AUSHADHI_CSV)
    df_gov['search_text'] = df_gov['Generic Name'] + " " + df_gov['Unit Size'].astype(str)

    df_brands = pd.read_csv(BRAND_CSV, usecols=['Name', 'MRP', 'Salt_Composition', 'Manufacturer'])
    df_brands.dropna(subset=['Name', 'MRP', 'Salt_Composition'], inplace=True)
    df_brands['search_text'] = df_brands['Name'] + " (" + df_brands['Salt_Composition'] + ")"

    print("🧠 Encoding Vectors...")
    brand_embeddings = model.encode(df_brands['search_text'].tolist(), convert_to_tensor=True, show_progress_bar=True)
    gov_embeddings = model.encode(df_gov['search_text'].tolist(), convert_to_tensor=True, show_progress_bar=True)

    print("🔍 Searching & Validating...")
    hits = util.semantic_search(gov_embeddings, brand_embeddings, top_k=20)

    final_db = []

    for i, match_list in enumerate(tqdm(hits)):
        gov_row = df_gov.iloc[i]
        gov_name = gov_row['Generic Name']
        try: jan_price = float(gov_row['MRP'])
        except: continue

        valid_brands = []

        for match in match_list:
            brand_idx = match['corpus_id']
            brand_row = df_brands.iloc[brand_idx]

            # PASS SALT COMPOSITION TO VALIDATOR
            if not validate_match(gov_name, brand_row['Name'], brand_row['Salt_Composition']):
                continue

            if float(brand_row['MRP']) > jan_price:
                valid_brands.append({
                    "brand": brand_row['Name'],
                    "price": float(brand_row['MRP'])
                })

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

    print(f"✅ Chemically Safe Database Built: {OUTPUT_FILE}")

if __name__ == "__main__":
    build_vector_bridge()
