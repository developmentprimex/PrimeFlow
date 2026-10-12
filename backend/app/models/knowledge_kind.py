from typing import Literal

KnowledgeType = Literal["PROMPT", "DEFINITION", "REGULATION"]
KNOWLEDGE_TYPES = ("PROMPT", "DEFINITION", "REGULATION")
KNOWLEDGE_ROUTES = {"PROMPT": "prompts", "DEFINITION": "definime", "REGULATION": "rregullore"}
KNOWLEDGE_TITLES = {"PROMPT": "PROMPT", "DEFINITION": "DEFINIM", "REGULATION": "RREGULLORE"}


def review_task_title(title: str, knowledge_type: str = "PROMPT") -> str:
    action = "TESTO" if knowledge_type == "PROMPT" else "KONTROLLO"
    return f"{KNOWLEDGE_TITLES[knowledge_type]}: {action}: {title.strip()}"


def author_task_title(title: str, knowledge_type: str = "PROMPT") -> str:
    return f"{KNOWLEDGE_TITLES[knowledge_type]}: {title.strip()}"
