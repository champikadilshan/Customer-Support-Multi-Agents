"""
Seed Neo4j AuraDB with the sales product catalogue and promotions.

Run once after creating your AuraDB instance:
    python -m sales_agent.seed

Uses MERGE so re-running is safe — no duplicate nodes or relationships.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from neo4j import GraphDatabase
from shared.config import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD


# DRIVER

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))


def run(session, cypher: str, params: dict = {}) -> None:
    session.run(cypher, params)


# SEED DATA

def seed_categories(session) -> None:
    categories = [
        {"id": "internet", "name": "Internet Plans"},
        {"id": "mobile",   "name": "Mobile Plans"},
        {"id": "tv",       "name": "TV Plans"},
        {"id": "bundle",   "name": "Bundles"},
    ]
    for cat in categories:
        run(session,
            "MERGE (c:Category {id: $id}) SET c.name = $name",
            cat,
        )
    print(f"  Merged {len(categories)} Category nodes")


def seed_products(session) -> None:
    products = [
        # Internet
        {
            "id": "INT-001", "name": "Fiber Basic",
            "speed": "100 Mbps", "price": "$39.99/mo",
            "description": "Great for light browsing and streaming",
            "available": True, "activation": "Same day",
            "contract": "No contract", "category": "internet",
        },
        {
            "id": "INT-002", "name": "Fiber Pro",
            "speed": "500 Mbps", "price": "$59.99/mo",
            "description": "Perfect for remote work and HD streaming",
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
        # Mobile
        {
            "id": "MOB-001", "name": "Starter SIM",
            "data": "5 GB", "price": "$15.00/mo",
            "description": "For light mobile users",
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
        # TV
        {
            "id": "TV-001", "name": "Basic TV",
            "channels": "50+", "price": "$25.00/mo",
            "description": "Essential channels including local and news",
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
            "available": False, "activation": "Coming soon",
            "contract": "N/A", "category": "tv",
        },
        # Bundles
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
            "description": "Fiber Pro + Entertainment + Standard SIM — our best value pack",
            "available": True, "activation": "Next business day",
            "contract": "12-month recommended", "category": "bundle",
        },
    ]

    for p in products:
        category = p.pop("category")
        # Merge product node
        run(session,
            """
            MERGE (p:Product {id: $id})
            SET p += $props
            """,
            {"id": p["id"], "props": p},
        )
        # Merge BELONGS_TO relationship
        run(session,
            """
            MATCH (p:Product {id: $pid})
            MATCH (c:Category {id: $cid})
            MERGE (p)-[:BELONGS_TO]->(c)
            """,
            {"pid": p["id"], "cid": category},
        )

    print(f"  Merged {len(products)} Product nodes with BELONGS_TO relationships")


def seed_bundles(session) -> None:
    """Create INCLUDES relationships from bundle products to their components."""
    includes = [
        ("BND-001", "INT-001"),
        ("BND-001", "TV-001"),
        ("BND-002", "INT-002"),
        ("BND-002", "TV-002"),
        ("BND-002", "MOB-002"),
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
    """Create COMPATIBLE_WITH relationships between products that pair well."""
    pairs = [
        ("INT-002", "MOB-002"),   # Fiber Pro + Standard SIM
        ("INT-003", "MOB-003"),   # Fiber Ultra + Unlimited SIM
        ("INT-001", "TV-001"),    # Fiber Basic + Basic TV
        ("INT-002", "TV-002"),    # Fiber Pro + Entertainment
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
            "applies_to":  ["BND-001", "BND-002"],
        },
        {
            "id":          "PROMO-NEWSIM",
            "title":       "New SIM Offer",
            "description": "First month free when you sign up for any mobile plan",
            "discount":    "First month free",
            "expires":     "2024-07-31",
            "applies_to":  ["MOB-001", "MOB-002", "MOB-003"],
        },
    ]

    for promo in promotions:
        applies_to = promo.pop("applies_to")

        # Merge promotion node
        run(session,
            """
            MERGE (promo:Promotion {id: $id})
            SET promo += $props
            """,
            {"id": promo["id"], "props": promo},
        )

        # Merge APPLIES_TO relationships
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


# MAIN

def seed() -> None:
    print("Connecting to Neo4j...")
    driver.verify_connectivity()
    print("Connected.\n")

    with driver.session() as session:
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


if __name__ == "__main__":
    seed()