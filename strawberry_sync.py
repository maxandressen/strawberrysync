import requests
import csv
import io
import time
from dotenv import load_dotenv
import os
load_dotenv()
# ============================================================
# APNI DETAILS YAHAN DAALO
# ============================================================
SHOP_URL = "authormagazine.myshopify.com"
ACCESS_TOKEN = os.getenv("SHOPIFY_TOKEN")
CSV_URL = "https://strawberry.omnisuiteai.com/csv"
# ============================================================

HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}
API_BASE = f"https://{SHOP_URL}/admin/api/2024-04"


def fetch_csv():
    """CSV se products fetch karo"""
    print("📥 CSV fetch ho rahi hai...")
    response = requests.get(CSV_URL)
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text))
    products = list(reader)
    print(f"✅ {len(products)} products mile CSV mein")
    return products


def get_location_id():
    """Shopify ka default location ID lo"""
    url = f"{API_BASE}/locations.json"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    locations = response.json().get("locations", [])
    if not locations:
        raise Exception("Koi location nahi mili Shopify mein!")
    location_id = locations[0]["id"]
    print(f"📍 Location ID: {location_id}")
    return location_id


def get_existing_products():
    """Shopify ke existing products fetch karo (SKU -> product/variant info)"""
    print("🔍 Shopify products check ho rahe hain...")
    sku_map = {}
    url = f"{API_BASE}/products.json?limit=250"
    
    while url:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        data = response.json()
        
        for product in data.get("products", []):
            for variant in product.get("variants", []):
                sku = str(variant.get("sku", "")).strip()
                if sku:
                    sku_map[sku] = {
                        "product_id": product["id"],
                        "variant_id": variant["id"],
                        "inventory_item_id": variant["inventory_item_id"],
                        "title": product["title"]
                    }
        
        # Next page check karo
        link_header = response.headers.get("Link", "")
        url = None
        if 'rel="next"' in link_header:
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>")
                    break
    
    print(f"✅ {len(sku_map)} existing products mile Shopify mein")
    return sku_map


def clean_price(price_str):
    """Price ko clean karo (€49,50 -> 49.50)"""
    if not price_str:
        return "0.00"
    cleaned = price_str.replace("€", "").replace(",", ".").strip()
    try:
        return f"{float(cleaned):.2f}"
    except:
        return "0.00"


def create_product(row):
    """Naya product banao Shopify mein"""
    price = clean_price(row.get("price", "0"))
    sku = str(row.get("product_id", "")).strip()
    title = f"{row.get('brand', '')} {row.get('name', '')}".strip()
    
    product_data = {
        "product": {
            "title": title,
            "vendor": row.get("brand", ""),
            "product_type": row.get("category", ""),
            "variants": [{
                "sku": sku,
                "price": price,
                "inventory_management": "shopify",
                "inventory_policy": "deny"
            }],
            "tags": row.get("category", "")
        }
    }
    
    url = f"{API_BASE}/products.json"
    response = requests.post(url, headers=HEADERS, json=product_data)
    
    if response.status_code == 201:
        product = response.json()["product"]
        variant = product["variants"][0]
        return {
            "product_id": product["id"],
            "variant_id": variant["id"],
            "inventory_item_id": variant["inventory_item_id"]
        }
    else:
        print(f"  ❌ Product create failed: {response.status_code} - {response.text[:100]}")
        return None


def update_inventory(inventory_item_id, location_id, quantity):
    """Inventory update karo"""
    url = f"{API_BASE}/inventory_levels/set.json"
    data = {
        "location_id": location_id,
        "inventory_item_id": inventory_item_id,
        "available": quantity
    }
    response = requests.post(url, headers=HEADERS, json=data)
    return response.status_code == 200


def sync_products():
    """Main sync function"""
    print("\n🚀 Strawberry → Shopify Sync Shuru...\n")
    
    # Data fetch karo
    csv_products = fetch_csv()
    location_id = get_location_id()
    existing_products = get_existing_products()
    
    # Counters
    created = 0
    updated = 0
    failed = 0
    
    for i, row in enumerate(csv_products):
        sku = str(row.get("product_id", "")).strip()
        if not sku:
            continue
        
        quantity_str = row.get("quantity", "0").strip()
        try:
            quantity = int(quantity_str) if quantity_str else 0
        except:
            quantity = 0
        
        title = f"{row.get('brand', '')} {row.get('name', '')}".strip()
        
        print(f"[{i+1}/{len(csv_products)}] {title[:50]}...")
        
        if sku in existing_products:
            # Product exist karta hai — sirf inventory update karo
            item = existing_products[sku]
            success = update_inventory(item["inventory_item_id"], location_id, quantity)
            if success:
                print(f"  ✅ Inventory updated: {quantity} units")
                updated += 1
            else:
                print(f"  ⚠️  Inventory update fail")
                failed += 1
        else:
            # Naya product banao
            print(f"  🆕 Naya product bana raha hoon...")
            result = create_product(row)
            if result:
                time.sleep(0.5)  # Rate limit avoid karne ke liye
                success = update_inventory(result["inventory_item_id"], location_id, quantity)
                if success:
                    print(f"  ✅ Created + Inventory set: {quantity} units")
                    created += 1
                else:
                    print(f"  ⚠️  Created but inventory fail")
                    created += 1
            else:
                failed += 1
        
        # Shopify rate limit: 2 requests/second
        time.sleep(0.5)
    
    print(f"\n{'='*50}")
    print(f"✅ Sync Complete!")
    print(f"   🆕 Naye Products: {created}")
    print(f"   🔄 Updated: {updated}")
    print(f"   ❌ Failed: {failed}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    sync_products()
