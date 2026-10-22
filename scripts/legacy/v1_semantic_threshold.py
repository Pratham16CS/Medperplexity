import pandas as pd
import json
import torch
from sentence_transformers import SentenceTransformer, util
from tqdm import tqdm

# --- CONFIGURATION ---
# 1. Inputs
JAN_AUSHADHI_CSV = "jan_aushadhi.csv"
BRAND_CSV = "brand_medicines.csv"

# 2. Output
OUTPUT_FILE = "vector_medicine_db.json"

# 3. AI Settings
# We use a model pre-trained on medical text (PubMed) for accuracy
MODEL_NAME = 'pritamdeka/S-PubMedBert-MS-MARCO'
SIMILARITY_THRESHOLD = 0.90  # Strict safety threshold (90% match required)

def build_vector_bridge():
    print(f"🚀 Starting Semantic Bridge using {MODEL_NAME}...")

    # --- STEP 1: LOAD AI MODEL ---
    # Detect if GPU is available to speed this up
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"⚙️  Loading AI Model on {device.upper()} (this may take a minute)...")
    try:
        model = SentenceTransformer(MODEL_NAME, device=device)
    except Exception as e:
        print(f"❌ Error loading model: {e}")
        print("Tip: Run 'pip install sentence-transformers torch'")
        return

    # --- STEP 2: LOAD DATA ---
    print("📂 Loading CSVs...")
    try:
        df_gov = pd.read_csv(JAN_AUSHADHI_CSV)
        # Combine Name + Unit Size for better context (e.g. "Atorvastatin 10mg")
        df_gov['search_text'] = df_gov['Generic Name'] + " " + df_gov['Unit Size'].astype(str)
        print(f"✅ Loaded {len(df_gov)} Government Medicines.")

        df_brands = pd.read_csv(BRAND_CSV, usecols=['Name', 'MRP', 'Salt_Composition', 'Manufacturer'])
        df_brands.dropna(subset=['Name', 'MRP', 'Salt_Composition'], inplace=True)
        # Create a search text: "Brand Name (Salt Name)"
        df_brands['search_text'] = df_brands['Name'] + " (" + df_brands['Salt_Composition'] + ")"
        print(f"✅ Loaded {len(df_brands)} Brand Medicines.")
    except Exception as e:
        print(f"❌ Error loading CSVs: {e}")
        return

    # --- STEP 3: CREATE EMBEDDINGS (The Heavy Lifting) ---
    print(f"🧠 Encoding {len(df_brands)} Brand Medicines (Go grab a coffee ☕)...")

    # We encode in batches to show progress
    brand_texts = df_brands['search_text'].tolist()
    gov_texts = df_gov['search_text'].tolist()

    # Encode Brands
    brand_embeddings = model.encode(brand_texts, convert_to_tensor=True, show_progress_bar=True)

    print(f"🧠 Encoding {len(df_gov)} Government Medicines...")
    # Encode Gov Generics
    gov_embeddings = model.encode(gov_texts, convert_to_tensor=True, show_progress_bar=True)

    # --- STEP 4: SEMANTIC SEARCH ---
    print("🔍 Performing Semantic Search (Matching vectors)...")

    # For every Govt drug, find top 10 matches in Brand DB
    # We use Cosine Similarity
    hits = util.semantic_search(gov_embeddings, brand_embeddings, top_k=10)

    # --- STEP 5: CONSTRUCT DATABASE ---
    print("bridge Building Final Database...")

    final_db = []
    matches_found = 0

    # 'hits' is a list of lists (one list of matches per gov drug)
    for i, match_list in enumerate(tqdm(hits)):
        gov_row = df_gov.iloc[i]

        # Get Govt Details
        raw_name = gov_row['Generic Name']
        try:
            jan_price = float(gov_row['MRP'])
        except:
            continue

        # Filter matches by Threshold & Logic
        valid_brands = []
        for match in match_list:
            score = match['score']

            # 1. Safety Check: Score must be high
            if score < SIMILARITY_THRESHOLD:
                continue

            # Get Brand Details
            brand_idx = match['corpus_id']
            brand_row = df_brands.iloc[brand_idx]
            brand_price = float(brand_row['MRP'])

            # 2. Logic Check: Brand must be MORE expensive than Generic
            if brand_price > jan_price:
                valid_brands.append({
                    "brand": brand_row['Name'],
                    "price": brand_price,
                    "score": score
                })

        # Construct Entry
        entry = {
            "generic_name": raw_name,
            "jan_price": jan_price,
            "unit_size": str(gov_row['Unit Size']),
            "common_brands": [],
            "market_avg_price": round(jan_price * 5, 2), # Default Fallback
            "found_match": False,
            "savings_alert": "N/A"
        }

        if valid_brands:
            # Sort by Score (Most relevant first) -> Then Price
            # Actually, let's stick to Price for the "Green Card" value
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
    print(f"✅ SEMANTIC BRIDGE COMPLETE!")
    print(f"🔗 Mapped {matches_found} / {len(df_gov)} generics using AI.")
    print(f"📂 Saved to: {OUTPUT_FILE}")
    print("="*50)

if __name__ == "__main__":
    build_vector_bridge()
