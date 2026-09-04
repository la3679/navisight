"""LLM provider implementations.

Each module here implements :class:`app.agent.provider.LLMProvider` and nothing
else. Selection happens in :mod:`app.agent.factory`, so adding a provider never
touches the agent loop.
"""
