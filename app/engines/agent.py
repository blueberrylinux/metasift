"""Interface layer — LangChain agent wired to MCP tools + custom REST tools."""
from __future__ import annotations

from loguru import logger

from app.clients.llm import get_llm
from app.config import settings


def build_agent():
    """Create a tool-calling agent over MCP + local tools.

    MCP discovery is lazy because the AI SDK is heavy and we want app startup fast.
    """
    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    tools = _load_tools()

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are Stew, the MetaSift AI wizard. You help users analyze, clean, and improve "
         "their OpenMetadata catalog. Always show your reasoning. Be concise."),
        MessagesPlaceholder("chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])

    llm = get_llm("toolcall")
    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True, handle_parsing_errors=True)


def _load_tools() -> list:
    """Load MCP tools from OpenMetadata AI SDK. Returns [] if SDK unavailable."""
    try:
        from ai_sdk import AISdk, AISdkConfig  # noqa: F401
        # TODO: exact instantiation depends on AI SDK version
        # client = AISdk(AISdkConfig(host=settings.ai_sdk_host, token=settings.ai_sdk_token))
        # return client.mcp.as_langchain_tools()
        logger.warning("MCP tool loading not yet wired — returning empty tool list.")
        return []
    except ImportError:
        logger.warning("data-ai-sdk not installed — agent will have no MCP tools.")
        return []
