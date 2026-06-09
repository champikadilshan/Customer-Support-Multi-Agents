"""
Sales MCP Server — exposes Neo4j product graph as MCP tools.

The LangGraph sales agent connects to this server via SSE transport
and discovers tools automatically through the MCP protocol.

Start with:
    python sales_agent/mcp_server.py

The server listens on SALES_MCP_PORT (default 8005).
The SSE endpoint the agent connects to is: http://localhost:8005/sse
"""
import sys, os
import uvicorn

from mcp.server.fastmcp import FastMCP
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, AuthError
from shared.config import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, SALES_MCP_PORT

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# NEO4J DRIVER — created once reused across all tool calls
try:
    driver = GraphDatabase.driver(NEO4J_URI,auth=(NEO4J_USERNAME, NEO4J_PASSWORD),)
    driver.verify_connectivity()

    print(f"Connected to Neo4j at {NEO4J_URI}")
except (ServiceUnavailable, AuthError) as e:
    print(f"WARNING: Could not connect to Neo4j at startup: {e}")
    driver = None


def run_query(cypher: str, params: dict = {}) -> list[dict]:
    """
    Execute a Cypher query and return results as a list of plain dicts.
    Raises RuntimeError if driver is not available so MCP returns an error
    message back to the LLM rather than crashing silently.
    """
    if driver is None:
        raise RuntimeError("Neo4j connection is unavailable")

    with driver.session() as session:
        result = session.run(cypher, params)
        return [dict(record) for record in result]


# MCP SERVER | Tools defined here — NOT in the agent, The LLM discovers these automatically when the agent connects via SSE.
mcp = FastMCP("Sales MCP")


# TOOL 1 — Product catalogue
@mcp.tool()
def get_product_catalog(category: str) -> list[dict]:
    """
    Retrieve products available in a given category with descriptions and prices.
    Use this when the user asks about what products are available,
    wants to compare options, or is looking for something specific.
    Categories: internet, mobile, tv, bundle.
    Pass 'all' to get every product across all categories.
    """
    try:
        if category == "all":
            cypher = """
                MATCH (p:Product)-[:BELONGS_TO]->(c:Category)
                RETURN p { .*, category: c.id }
                ORDER BY c.id, p.id
            """
            params = {}

        else:
            cypher = """
                MATCH (p:Product)-[:BELONGS_TO]->(c:Category {id: $category})
                RETURN p { .*, category: c.id }
                ORDER BY p.id
            """
            params = {"category": category}

        rows = run_query(cypher, params)

        if not rows:
            return [{"error": f"No products found for category '{category}'. "
                              f"Valid categories: internet, mobile, tv, bundle, all"}]

        return [row["p"] for row in rows]

    except RuntimeError as e:
        return [{"error": str(e)}]


# TOOL 2 — Active promotions
@mcp.tool()
def get_active_promotions(product_id: str = "") -> list[dict]:
    """
    Retrieve all currently active promotions, discounts, and special offers.
    Use this when the user asks about deals, discounts, promotions,
    or ways to save money.
    Optionally pass a product_id to filter promotions for a specific product.
    Leave product_id empty to get all promotions.
    """
    try:
        if product_id:
            cypher = """
                MATCH (promo:Promotion)-[:APPLIES_TO]->(target:Product {id: $product_id})
                MATCH (promo)-[:APPLIES_TO]->(all_products:Product)
                RETURN promo { .* } AS promo,
                       collect(DISTINCT all_products.id) AS applicable_to
                ORDER BY promo.id
            """
            params = {"product_id": product_id}

        else:
            cypher = """
                MATCH (promo:Promotion)-[:APPLIES_TO]->(p:Product)
                RETURN promo { .* } AS promo,
                       collect(DISTINCT p.id) AS applicable_to
                ORDER BY promo.id
            """
            params = {}

        rows = run_query(cypher, params)

        if not rows:
            return []   # no promotions is valid — empty list not an error

        return [
            {**row["promo"], "applicable_to": row["applicable_to"]}
            for row in rows
        ]

    except RuntimeError as e:
        return [{"error": str(e)}]


# TOOL 3 — Product availability
@mcp.tool()
def check_product_availability(product_id: str) -> dict:
    """
    Check whether a specific product is currently available and
    how quickly it can be activated.
    Use this when the user is ready to purchase or wants to know
    if a product is in stock or can be set up.
    """
    try:
        cypher = """
            MATCH (p:Product {id: $product_id})
            RETURN p { .* } AS p
        """
        rows = run_query(cypher, {"product_id": product_id})

        if not rows:
            return {
                "product_id": product_id,
                "available":  False,
                "error":      f"No product found with id '{product_id}'",
            }

        product = rows[0]["p"]

        return {
            "product_id": product.get("id"),
            "name":       product.get("name"),
            "available":  product.get("available", False),
            "activation": product.get("activation", "N/A"),
            "contract":   product.get("contract",   "N/A"),
        }

    except RuntimeError as e:
        return {"error": str(e)}


# ASGI APP — expose the FastMCP SSE app for uvicorn
app = mcp.sse_app()

if __name__ == "__main__":
    print(f"Starting Sales MCP Server on port {SALES_MCP_PORT}...")
    print(f"Agent should connect to: http://localhost:{SALES_MCP_PORT}/sse")

    uvicorn.run(app, host="0.0.0.0", port=SALES_MCP_PORT)