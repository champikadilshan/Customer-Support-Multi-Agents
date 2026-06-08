import os

from langchain_google_vertexai import ChatVertexAI


def get_vertex_llm(*, temperature: float = 0) -> ChatVertexAI:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    model = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

    if not project:
        raise ValueError("GOOGLE_CLOUD_PROJECT is not set.")

    return ChatVertexAI(
        model_name=model,
        project=project,
        location=location,
        temperature=temperature,
    )
