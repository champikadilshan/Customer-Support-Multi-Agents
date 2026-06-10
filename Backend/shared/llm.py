import os
from typing import Literal

from langchain_google_vertexai import ChatVertexAI

AgentRole = Literal["orchestrator", "specialist"]


def _resolve_model( *, role: AgentRole | None = None,model: str | None = None,) -> str:
    if model:
        return model

    if role == "orchestrator":
        return os.getenv("GEMINI_ORCHESTRATOR_MODEL", "gemini-2.5-pro")

    if role == "specialist":
        return os.getenv("GEMINI_SPECIALIST_MODEL", "gemini-2.5-flash")

    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def get_vertex_llm( *, temperature: float = 0, role: AgentRole | None = None, model: str | None = None,) -> ChatVertexAI:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    model_name = _resolve_model(role=role, model=model)

    if not project:
        raise ValueError("GOOGLE_CLOUD_PROJECT is not set.")

    return ChatVertexAI(
        model_name=model_name,
        project=project,
        location=location,
        temperature=temperature,
    )