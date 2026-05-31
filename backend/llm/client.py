"""Groq LLM client wrapper to explain static diagnostics."""

from __future__ import annotations

import json
import os
from groq import Groq
from .prompts import SYSTEM_PROMPT, USER_TEMPLATE

def explain_diagnostic(
    category: str,
    message: str,
    code_snippet: str,
    start_line: int,
    end_line: int,
) -> tuple[str, str]:
    """Invoke Groq to explain a diagnostic and generate a minimal concrete fix."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is not configured. "
            "Please create a .env file with your Groq API key."
        )
        
    client = Groq(api_key=api_key)
    
    user_content = USER_TEMPLATE.format(
        category=category,
        message=message,
        start_line=start_line,
        end_line=end_line,
        snippet=code_snippet,
    )
    
    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        model="llama-3.3-70b-versatile",
        temperature=0.1,
    )
    
    content = response.choices[0].message.content.strip()
    
    # Strip markdown code fences if present in the LLM response
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    
    try:
        data = json.loads(content)
        return (
            data.get("explanation", "").strip(),
            data.get("fix_suggestion", "").strip(),
        )
    except Exception:
        # Fallback in case of json parsing errors
        return content, "Please check the code manually."
