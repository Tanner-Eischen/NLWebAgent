__all__ = ["WebAutomationAgent"]


def __getattr__(name):
    if name == "WebAutomationAgent":
        from agent.orchestrator import WebAutomationAgent

        return WebAutomationAgent
    raise AttributeError(name)
