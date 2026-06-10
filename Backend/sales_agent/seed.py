"""
Seed Neo4j AuraDB with the sales product catalogue and promotions.

Run once after creating your AuraDB instance:
    python -m sales_agent.seed

Uses MERGE so re-running without WIPE_AND_RESEED is always safe — no duplicates.

WIPE_AND_RESEED = True  → deletes ALL nodes and relationships, then inserts fresh data
WIPE_AND_RESEED = False → uses MERGE — safe to re-run, updates existing nodes in place
"""
import sys
from pathlib import Path
from neo4j import GraphDatabase
from shared.config import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD

sys.path.append(str(Path(__file__).resolve().parent.parent))

# ─────────────────────────────────────────────
#  CONTROL FLAG  ← change this to wipe & reseed
# ─────────────────────────────────────────────
WIPE_AND_RESEED: bool = False

# ── DRIVER ───────────────────────────────────────────────────────────────────
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))


def run(session, cypher: str, params: dict = {}) -> None:
    session.run(cypher, params)


# ── WIPE ──────────────────────────────────────────────────────────────────────

def wipe_all(session) -> None:
    """Delete every node and relationship in the database."""
    session.run("MATCH (n) DETACH DELETE n")
    print("  All nodes and relationships deleted.")


# ── SEED DATA ─────────────────────────────────────────────────────────────────

def seed_categories(session) -> None:
    categories = [
        {"id": "internet",    "name": "Internet Plans"},
        {"id": "mobile",      "name": "Mobile Plans"},
        {"id": "tv",          "name": "TV Plans"},
        {"id": "bundle",      "name": "Bundles"},
        {"id": "landline",    "name": "Landline Plans"},
        {"id": "smart_home",  "name": "Smart Home"},
    ]
    for cat in categories:
        run(session, "MERGE (c:Category {id: $id}) SET c.name = $name", cat)
    print(f"  Merged {len(categories)} Category nodes")


def seed_products(session) -> None:
    products = [

        # ── INTERNET ──────────────────────────────────────────────────────────
        {
            "id": "INT-001", "name": "Fiber Basic",
            "speed": "100 Mbps", "price": "$39.99/mo",
            "description": "Great for light browsing and streaming on 1-2 devices",
            "available": True, "activation": "Same day",
            "contract": "No contract", "category": "internet",
        },
        {
            "id": "INT-002", "name": "Fiber Pro",
            "speed": "500 Mbps", "price": "$59.99/mo",
            "description": "Perfect for remote work and HD streaming on up to 5 devices",
            "available": True, "activation": "Same day",
            "contract": "12-month option for discount", "category": "internet",
        },
        {
            "id": "INT-003", "name": "Fiber Ultra",
            "speed": "1 Gbps", "price": "$89.99/mo",
            "description": "Best for heavy users, gamers, and large households",
            "available": True, "activation": "Next business day",
            "contract": "12-month option for discount", "category": "internet",
        },
        {
            "id": "INT-004", "name": "Fiber Max",
            "speed": "2 Gbps", "price": "$119.99/mo",
            "description": "Maximum speed for smart homes, 4K streaming and power users",
            "available": True, "activation": "Next business day",
            "contract": "12-month required", "category": "internet",
        },
        {
            "id": "INT-005", "name": "Wireless Home Broadband",
            "speed": "50 Mbps", "price": "$29.99/mo",
            "description": "No engineer needed — plug in and go. Great for renters and light users",
            "available": True, "activation": "Delivered in 2-3 days, self-install",
            "contract": "No contract", "category": "internet",
        },

        # ── MOBILE ────────────────────────────────────────────────────────────
        {
            "id": "MOB-001", "name": "Starter SIM",
            "data": "5 GB", "price": "$15.00/mo",
            "description": "For light mobile users — calls, texts and a little data",
            "available": True, "activation": "SIM delivered in 2-3 days",
            "contract": "No contract", "category": "mobile",
        },
        {
            "id": "MOB-002", "name": "Standard SIM",
            "data": "20 GB", "price": "$29.00/mo",
            "description": "Balanced data plan for everyday use",
            "available": True, "activation": "SIM delivered in 2-3 days",
            "contract": "No contract", "category": "mobile",
        },
        {
            "id": "MOB-003", "name": "Unlimited SIM",
            "data": "Unlimited", "price": "$45.00/mo",
            "description": "No limits — calls, texts, and data",
            "available": True, "activation": "SIM delivered in 2-3 days",
            "contract": "No contract", "category": "mobile",
        },
        {
            "id": "MOB-004", "name": "Family SIM Pack",
            "data": "100 GB shared", "price": "$69.00/mo",
            "description": "Share 100 GB across up to 4 SIM cards — great for families",
            "available": True, "activation": "SIMs delivered in 2-3 days",
            "contract": "12-month recommended", "category": "mobile",
        },
        {
            "id": "MOB-005", "name": "Roaming SIM",
            "data": "20 GB + roaming in 40 countries", "price": "$49.00/mo",
            "description": "Standard data plus free roaming in 40 countries — ideal for frequent travellers",
            "available": True, "activation": "SIM delivered in 2-3 days",
            "contract": "No contract", "category": "mobile",
        },

        # ── TV ────────────────────────────────────────────────────────────────
        {
            "id": "TV-001", "name": "Basic TV",
            "channels": "50+", "price": "$25.00/mo",
            "description": "Essential channels including local news and free-to-air",
            "available": True, "activation": "Same day (streaming app)",
            "contract": "No contract", "category": "tv",
        },
        {
            "id": "TV-002", "name": "Entertainment",
            "channels": "150+", "price": "$45.00/mo",
            "description": "Movies, sports, and lifestyle channels",
            "available": True, "activation": "Same day (streaming app)",
            "contract": "No contract", "category": "tv",
        },
        {
            "id": "TV-003", "name": "Premium TV",
            "channels": "300+", "price": "$65.00/mo",
            "description": "Full package with premium and international channels",
            "available": True, "activation": "Same day (streaming app)",
            "contract": "No contract", "category": "tv",
        },
        {
            "id": "TV-004", "name": "Sports Add-on",
            "channels": "15 sports channels", "price": "$15.00/mo",
            "description": "All major sports including football, basketball, and motorsport — add to any TV plan",
            "available": True, "activation": "Same day",
            "contract": "No contract", "category": "tv",
        },
        {
            "id": "TV-005", "name": "Kids Pack",
            "channels": "20 kids channels", "price": "$8.00/mo",
            "description": "Safe, ad-free viewing for children — add to any TV plan",
            "available": True, "activation": "Same day",
            "contract": "No contract", "category": "tv",
        },

        # ── LANDLINE ──────────────────────────────────────────────────────────
        {
            "id": "LAN-001", "name": "Basic Landline",
            "calls": "Local & national included", "price": "$10.00/mo",
            "description": "Reliable home phone with free local and national calls",
            "available": True, "activation": "Same day (uses broadband line)",
            "contract": "No contract", "category": "landline",
        },
        {
            "id": "LAN-002", "name": "Unlimited Calls",
            "calls": "Unlimited local, national & mobile", "price": "$18.00/mo",
            "description": "Call anyone in the country for free — landlines and mobiles included",
            "available": True, "activation": "Same day (uses broadband line)",
            "contract": "No contract", "category": "landline",
        },
        {
            "id": "LAN-003", "name": "International Caller",
            "calls": "Unlimited to 35 countries", "price": "$28.00/mo",
            "description": "Unlimited calls to landlines and mobiles in 35 countries",
            "available": True, "activation": "Same day (uses broadband line)",
            "contract": "12-month recommended", "category": "landline",
        },
        {
            "id": "LAN-004", "name": "Business Landline",
            "calls": "Unlimited + 3 lines", "price": "$45.00/mo",
            "description": "Three lines, unlimited calls, and a dedicated business number",
            "available": True, "activation": "2-3 business days",
            "contract": "12-month required", "category": "landline",
        },

        # ── SMART HOME ────────────────────────────────────────────────────────
        {
            "id": "SMH-001", "name": "Smart Home Starter",
            "devices": "Hub + 2 sensors", "price": "$25.00/mo",
            "description": "Get started with home automation — hub, two motion sensors and app control",
            "available": True, "activation": "Hardware delivered in 3-5 days",
            "contract": "No contract", "category": "smart_home",
        },
        {
            "id": "SMH-002", "name": "Smart Home Plus",
            "devices": "Hub + 5 sensors + smart lock", "price": "$45.00/mo",
            "description": "Full home security and automation with smart lock, five sensors and 24/7 monitoring",
            "available": True, "activation": "Hardware delivered in 3-5 days",
            "contract": "12-month recommended", "category": "smart_home",
        },
        {
            "id": "SMH-003", "name": "Smart Home Pro",
            "devices": "Hub + 10 sensors + lock + cameras", "price": "$75.00/mo",
            "description": "Professional-grade security with indoor/outdoor cameras, 10 sensors, smart lock and cloud storage",
            "available": True, "activation": "Engineer installation within 5 days",
            "contract": "12-month required", "category": "smart_home",
        },
        {
            "id": "SMH-004", "name": "Energy Monitor Add-on",
            "devices": "Smart meter + app", "price": "$8.00/mo",
            "description": "Track your energy usage in real time and get tips to reduce your bills",
            "available": True, "activation": "Hardware delivered in 3-5 days",
            "contract": "No contract", "category": "smart_home",
        },

        # ── BUNDLES ───────────────────────────────────────────────────────────
        {
            "id": "BND-001", "name": "Home Bundle",
            "price": "$54.99/mo", "saving": "Save $10/mo",
            "description": "Fiber Basic + Basic TV — great value for home use",
            "available": True, "activation": "Same day",
            "contract": "12-month recommended", "category": "bundle",
        },
        {
            "id": "BND-002", "name": "Pro Bundle",
            "price": "$99.99/mo", "saving": "Save $34/mo",
            "description": "Fiber Pro + Entertainment TV + Standard SIM — our best value pack",
            "available": True, "activation": "Next business day",
            "contract": "12-month recommended", "category": "bundle",
        },
        {
            "id": "BND-003", "name": "Ultimate Bundle",
            "price": "$169.99/mo", "saving": "Save $55/mo",
            "description": "Fiber Ultra + Premium TV + Unlimited SIM + Basic Landline — everything in one",
            "available": True, "activation": "Next business day",
            "contract": "12-month required", "category": "bundle",
        },
        {
            "id": "BND-004", "name": "Smart Home Bundle",
            "price": "$89.99/mo", "saving": "Save $25/mo",
            "description": "Fiber Pro + Smart Home Starter + Basic Landline — the connected home package",
            "available": True, "activation": "Hardware delivered in 3-5 days",
            "contract": "12-month required", "category": "bundle",
        },
        {
            "id": "BND-005", "name": "Family Bundle",
            "price": "$134.99/mo", "saving": "Save $45/mo",
            "description": "Fiber Ultra + Entertainment TV + Family SIM Pack + Basic Landline",
            "available": True, "activation": "Next business day",
            "contract": "12-month required", "category": "bundle",
        },
    ]

    for p in products:
        category = p.pop("category")
        run(session,
            "MERGE (p:Product {id: $id}) SET p += $props",
            {"id": p["id"], "props": p},
        )
        run(session,
            """
            MATCH (p:Product {id: $pid})
            MATCH (c:Category {id: $cid})
            MERGE (p)-[:BELONGS_TO]->(c)
            """,
            {"pid": p["id"], "cid": category},
        )

    print(f"  Merged {len(products)} Product nodes")


def seed_bundles(session) -> None:
    """INCLUDES relationships — what each bundle contains."""
    includes = [
        ("BND-001", "INT-001"),
        ("BND-001", "TV-001"),

        ("BND-002", "INT-002"),
        ("BND-002", "TV-002"),
        ("BND-002", "MOB-002"),

        ("BND-003", "INT-003"),
        ("BND-003", "TV-003"),
        ("BND-003", "MOB-003"),
        ("BND-003", "LAN-001"),

        ("BND-004", "INT-002"),
        ("BND-004", "SMH-001"),
        ("BND-004", "LAN-001"),

        ("BND-005", "INT-003"),
        ("BND-005", "TV-002"),
        ("BND-005", "MOB-004"),
        ("BND-005", "LAN-001"),
    ]
    for bundle_id, component_id in includes:
        run(session,
            """
            MATCH (b:Product {id: $bid})
            MATCH (c:Product {id: $cid})
            MERGE (b)-[:INCLUDES]->(c)
            """,
            {"bid": bundle_id, "cid": component_id},
        )
    print(f"  Merged {len(includes)} INCLUDES relationships")


def seed_compatible_with(session) -> None:
    """COMPATIBLE_WITH — products that pair well together."""
    pairs = [
        # Internet + Mobile
        ("INT-001", "MOB-001"),
        ("INT-002", "MOB-002"),
        ("INT-003", "MOB-003"),
        ("INT-004", "MOB-003"),
        ("INT-002", "MOB-005"),
        # Internet + TV
        ("INT-001", "TV-001"),
        ("INT-002", "TV-002"),
        ("INT-003", "TV-003"),
        ("INT-004", "TV-003"),
        # Internet + Smart Home
        ("INT-002", "SMH-001"),
        ("INT-003", "SMH-002"),
        ("INT-004", "SMH-003"),
        # Internet + Landline
        ("INT-001", "LAN-001"),
        ("INT-002", "LAN-002"),
        ("INT-003", "LAN-002"),
        # TV add-ons
        ("TV-002", "TV-004"),
        ("TV-003", "TV-004"),
        ("TV-001", "TV-005"),
        ("TV-002", "TV-005"),
        # Smart Home add-ons
        ("SMH-001", "SMH-004"),
        ("SMH-002", "SMH-004"),
        ("SMH-003", "SMH-004"),
    ]
    for a, b in pairs:
        run(session,
            """
            MATCH (a:Product {id: $aid})
            MATCH (b:Product {id: $bid})
            MERGE (a)-[:COMPATIBLE_WITH]->(b)
            MERGE (b)-[:COMPATIBLE_WITH]->(a)
            """,
            {"aid": a, "bid": b},
        )
    print(f"  Merged {len(pairs) * 2} COMPATIBLE_WITH relationships")


def seed_promotions(session) -> None:
    promotions = [
        {
            "id":          "PROMO-SUMMER24",
            "title":       "Summer Upgrade Deal",
            "description": "Upgrade to Fiber Pro and get 3 months at half price",
            "discount":    "50% off for 3 months",
            "expires":     "2024-08-31",
            "applies_to":  ["INT-002"],
        },
        {
            "id":          "PROMO-BUNDLE10",
            "title":       "Bundle & Save",
            "description": "Take any bundle and get an extra $10 off per month",
            "discount":    "$10/mo additional discount",
            "expires":     "2024-12-31",
            "applies_to":  ["BND-001", "BND-002", "BND-003", "BND-004", "BND-005"],
        },
        {
            "id":          "PROMO-NEWSIM",
            "title":       "New SIM Offer",
            "description": "First month free when you sign up for any mobile plan",
            "discount":    "First month free",
            "expires":     "2024-07-31",
            "applies_to":  ["MOB-001", "MOB-002", "MOB-003", "MOB-004", "MOB-005"],
        },
        {
            "id":          "PROMO-SMARTHOME",
            "title":       "Smart Home Launch Offer",
            "description": "Sign up for any Smart Home plan and get the first month free plus free installation",
            "discount":    "First month free + free installation",
            "expires":     "2024-09-30",
            "applies_to":  ["SMH-001", "SMH-002", "SMH-003"],
        },
        {
            "id":          "PROMO-LANDLINE",
            "title":       "Landline Loyalty Reward",
            "description": "Existing customers adding a landline plan get 20% off for 6 months",
            "discount":    "20% off for 6 months",
            "expires":     "2024-10-31",
            "applies_to":  ["LAN-001", "LAN-002", "LAN-003"],
        },
        {
            "id":          "PROMO-FIBERMAX",
            "title":       "Fiber Max Early Adopter",
            "description": "Be among the first to sign up for Fiber Max and lock in the price for 24 months",
            "discount":    "Price locked for 24 months",
            "expires":     "2024-08-15",
            "applies_to":  ["INT-004"],
        },
        {
            "id":          "PROMO-FAMILY",
            "title":       "Family Bundle Bonus",
            "description": "Sign up for the Family Bundle and get a free Kids Pack add-on for 12 months",
            "discount":    "Free Kids Pack ($8/mo value) for 12 months",
            "expires":     "2024-12-31",
            "applies_to":  ["BND-005"],
        },
    ]

    for promo in promotions:
        applies_to = promo.pop("applies_to")
        run(session,
            "MERGE (promo:Promotion {id: $id}) SET promo += $props",
            {"id": promo["id"], "props": promo},
        )
        for product_id in applies_to:
            run(session,
                """
                MATCH (promo:Promotion {id: $prid})
                MATCH (p:Product {id: $pid})
                MERGE (promo)-[:APPLIES_TO]->(p)
                """,
                {"prid": promo["id"], "pid": product_id},
            )

    print(f"  Merged {len(promotions)} Promotion nodes with APPLIES_TO relationships")


# ── SEED FUNCTION ─────────────────────────────────────────────────────────────

def seed() -> None:
    print("Connecting to Neo4j...")
    driver.verify_connectivity()
    print("Connected.\n")

    with driver.session() as session:

        if WIPE_AND_RESEED:
            print("WIPE_AND_RESEED=True — wiping all nodes and relationships...")
            wipe_all(session)
            print()

        print("Seeding categories...")
        seed_categories(session)

        print("Seeding products...")
        seed_products(session)

        print("Seeding bundle INCLUDES relationships...")
        seed_bundles(session)

        print("Seeding COMPATIBLE_WITH relationships...")
        seed_compatible_with(session)

        print("Seeding promotions...")
        seed_promotions(session)

    driver.close()
    print("\nSeed complete — Neo4j graph is ready")
    print("  Categories : internet, mobile, tv, bundle, landline, smart_home")
    print("  Products   : 25 (5 internet, 5 mobile, 5 TV, 4 landline, 4 smart home, 5 bundle)")
    print("  Promotions : 7")


if __name__ == "__main__":
    seed()