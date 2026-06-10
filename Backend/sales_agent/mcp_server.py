import sys, os
import uvicorn

from mcp.server.fastmcp import FastMCP
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, AuthError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.applications import Starlette
from shared.config import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, SALES_MCP_PORT

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


def _create_driver():
    d = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        # Keep connections alive and reconnect automatically
        max_connection_lifetime=200,        # recreate connections older than 200s
        max_connection_pool_size=10,
        connection_acquisition_timeout=30,
        connection_timeout=15,
    )

    return d


try:
    driver = _create_driver()
    driver.verify_connectivity()
    print(f"Connected to Neo4j at {NEO4J_URI}")

except (ServiceUnavailable, AuthError) as e:
    print(f"WARNING: Could not connect to Neo4j at startup: {e}")
    driver = None


def run_query(cypher: str, params: dict = {}) -> list[dict]:
    global driver

    if driver is None:
        try:
            driver = _create_driver()
            driver.verify_connectivity()
            print("Reconnected to Neo4j")

        except Exception as e:
            raise RuntimeError(f"Neo4j connection is unavailable: {e}")

    try:
        with driver.session() as session:
            result = session.run(cypher, params)

            return [dict(record) for record in result]

    except Exception as first_error:
        print(f"Neo4j query failed ({first_error}), reconnecting...")
        try:
            driver.close()
        except Exception:
            pass

        try:
            driver = _create_driver()
            driver.verify_connectivity()

            with driver.session() as session:
                result = session.run(cypher, params)
                return [dict(record) for record in result]

        except Exception as retry_error:
            driver = None
            raise RuntimeError(f"Neo4j query failed after reconnect: {retry_error}")


mcp = FastMCP("Sales MCP")


@mcp.tool(
    description=(
        "Retrieve products available in a given category with descriptions and prices. "
        "Use this when the user asks what products are available, wants to compare options, or is looking for something specific. "
        "Categories: internet, mobile, tv, bundle. Pass 'all' to get every product across all categories."
    )
)
def get_product_catalog(category: str) -> list[dict]:
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
                               "Valid categories: internet, mobile, tv, bundle, all"}]

        return [row["p"] for row in rows]

    except RuntimeError as e:
        return [{"error": str(e)}]


@mcp.tool(
    description=(
        "Retrieve all currently active promotions, discounts, and special offers. "
        "Use this when the user asks about deals, discounts, promotions, or ways to save money. "
        "Optionally pass a product_id to filter promotions for a specific product; leave empty to get all promotions."
    )
)
def get_active_promotions(product_id: str = "") -> list[dict]:
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
            return [{"info": "No active promotions found.", "applicable_to": []}]

        return [
            {**row["promo"], "applicable_to": row["applicable_to"]}
            for row in rows
        ]

    except RuntimeError as e:
        return [{"error": str(e)}]


@mcp.tool(
    description=(
        "Check whether a specific product is currently available and how quickly it can be activated. "
        "Use this when the user is ready to purchase or wants to know if a product is in stock or can be set up."
    )
)
def check_product_availability(product_id: str) -> dict:
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



async def health(request: Request) -> JSONResponse:
    neo4j_status = "unknown"
    try:
        if driver:
            driver.verify_connectivity()
            neo4j_status = "connected"
        else:
            neo4j_status = "disconnected"

    except Exception:
        neo4j_status = "disconnected"

    return JSONResponse({
        "status":       "ok",
        "service":      "sales_mcp",
        "neo4j":        neo4j_status,
    })



mcp_app = mcp.sse_app()

app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
    ]
)


app.mount("/", mcp_app)


if __name__ == "__main__":
    print(f"Starting Sales MCP Server on port {SALES_MCP_PORT}...")
    print(f"Agent should connect to: http://localhost:{SALES_MCP_PORT}/sse")
    print(f"Health check: http://localhost:{SALES_MCP_PORT}/health")
    uvicorn.run(app, host="0.0.0.0", port=SALES_MCP_PORT)