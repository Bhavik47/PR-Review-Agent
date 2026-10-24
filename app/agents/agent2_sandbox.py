import re
import logging
from typing import Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from app.config import settings
from app.github.client import github_client
from app.agents.state import AgentState, SandboxReviewOutput, SandboxBugProof
from app.agents.sandbox_runner import run_pytest_in_sandbox

logger = logging.getLogger(__name__)

AGENT2_SYSTEM_PROMPT = """You are Agent 2: Dynamic Sandbox & Edge-Case Prover.
Your role is to empirically test Python code modified in a Pull Request by writing targeted pytest edge-case tests.

You must look for real runtime vulnerabilities and boundary conditions:
1. None / missing parameters where a value is expected.
2. Division by zero, negative numbers, or invalid numeric ranges.
3. Empty collections (empty lists `[]`, empty strings `""`, empty dictionaries `{}`).
4. Missing dictionary keys or indexing errors (`KeyError`, `IndexError`).
5. Unexpected types causing `TypeError` or `AttributeError`.

Strict Rules:
- Write clean, executable pytest code.
- Import the function(s) directly from the module under test (e.g. if the file is `feature.py`, import from `feature`).
- Write short, clear test functions (e.g. `def test_calculate_discount_zero_division(): ...`).
- Return ONLY valid Python code inside a ```python ``` block.
"""

SELF_CORRECTION_PROMPT = """Your generated pytest test script failed to run because of a syntax, import, or framework error in the test file itself.

Here is the error from pytest:
{error_output}

Here is your previous test code:
```python
{previous_test_code}
```

Please fix the error in the test script. Ensure imports match the module name and syntax is valid Python 3.11.
Return ONLY the corrected Python test code inside a ```python ``` block.
"""

def extract_python_code(text: str) -> str:
    """Extracts python code from markdown code fences if present."""
    if "```python" in text:
        return text.split("```python")[1].split("```")[0].strip()
    elif "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text.strip()

def extract_touched_python_files(diff_text: str) -> List[str]:
    """Extracts list of modified or added .py file paths from the git diff."""
    matches = re.findall(r"^\+\+\+ b/(.*?)$", diff_text, re.MULTILINE)
    py_files = [f.strip() for f in matches if f.strip().endswith(".py") and f.strip() != "/dev/null"]
    # Return unique paths maintaining order
    return list(dict.fromkeys(py_files))

def is_test_script_error(output: str) -> bool:
    """Detects if pytest failed due to an error in the test script itself rather than the target code."""
    indicators = [
        "SyntaxError",
        "IndentationError",
        "ModuleNotFoundError",
        "ImportError",
        "fixture '",
        "collection failure",
        "INTERNALERROR",
    ]
    return any(ind in output for ind in indicators)

def run_agent2_sandbox(state: AgentState) -> dict:
    repo = state["repo_full_name"]
    head_sha = state["head_sha"]
    diff_text = state["diff_text"]

    py_files = extract_touched_python_files(diff_text)
    if not py_files:
        logger.info(f"[{repo}] No Python files touched in diff. Skipping Agent 2 sandbox testing.")
        return {
            "sandbox_summary": "No modified Python files to test in the sandbox.",
            "sandbox_bugs": [],
        }

    # Fetch complete file contents for each touched python file
    files_to_mount: Dict[str, str] = {}
    for pf in py_files[:3]:  # Limit to top 3 modified python files for token & execution efficiency
        content = github_client.get_file_raw(repo, pf, head_sha)
        if content:
            files_to_mount[pf] = content

    if not files_to_mount:
        return {
            "sandbox_summary": "Could not fetch contents of modified Python files.",
            "sandbox_bugs": [],
        }

    llm = ChatOpenAI(
        model=settings.OPENROUTER_MODEL,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        temperature=0,
        default_headers={
            "HTTP-Referer": "https://github.com/your-username/pr-review-agent",
            "X-Title": "Autonomous PR Reviewer Agent - Sandbox Prover",
        },
    )

    # Step 1: Prompt LLM to generate targeted edge-case pytest code
    context_str = ""
    for path, code in files_to_mount.items():
        context_str += f"### File: {path}\n```python\n{code[:8000]}\n```\n\n"

    prompt_content = (
        f"PR Title: {state['pr_title']}\n"
        f"PR Description: {state['pr_description']}\n\n"
        f"Diff:\n{diff_text[:10000]}\n\n"
        f"Full Code for Modified Files:\n{context_str}\n\n"
        "Generate a targeted `test_edge_cases.py` script testing the edge cases of the modified functions."
    )

    response = llm.invoke([
        SystemMessage(content=AGENT2_SYSTEM_PROMPT),
        HumanMessage(content=prompt_content),
    ])

    test_code = extract_python_code(response.content)
    logger.info(f"[{repo}] Generated initial edge-case test code ({len(test_code)} chars)")

    # Step 2: Self-correction execution loop (max 2 retries)
    max_retries = 2
    sandbox_result = None

    for attempt in range(max_retries + 1):
        test_env = dict(files_to_mount)
        test_env["test_edge_cases.py"] = test_code

        logger.info(f"[{repo}] Running sandbox attempt {attempt + 1}/{max_retries + 1}...")
        sandbox_result = run_pytest_in_sandbox(test_env, test_filename="test_edge_cases.py", timeout_seconds=20)

        # If tests passed or if failure is in target code (not test script syntax), break loop
        if sandbox_result["exit_code"] == 0 or not is_test_script_error(sandbox_result["output"]):
            break

        # If test script itself had an import/syntax error, self-correct
        if attempt < max_retries:
            logger.warning(f"[{repo}] Test script error detected. Self-correcting test code...")
            correction_res = llm.invoke([
                SystemMessage(content=AGENT2_SYSTEM_PROMPT),
                HumanMessage(
                    content=SELF_CORRECTION_PROMPT.format(
                        error_output=sandbox_result["output"][:3000],
                        previous_test_code=test_code,
                    )
                ),
            ])
            test_code = extract_python_code(correction_res.content)

    # Step 3: Interpret Sandbox Results
    if sandbox_result["exit_code"] == 0:
        logger.info(f"[{repo}] Sandbox verification passed: No bugs detected by edge-case tests.")
        return {
            "sandbox_summary": "✅ **Sandbox Verification Passed**: Dynamic edge-case tests executed successfully in Docker with zero runtime errors.",
            "sandbox_bugs": [],
        }

    # Step 4: A test failure occurred in the target PR code — extract structured bug proof
    logger.info(f"[{repo}] Sandbox test failure detected: Extracting empirical bug proof.")
    structured_llm = llm.with_structured_output(SandboxReviewOutput)

    analysis_prompt = (
        f"Pytest executed in an isolated Docker sandbox and caught a failure in the PR code.\n\n"
        f"Sandbox Output:\n{sandbox_result['output'][:10000]}\n\n"
        f"Executed Test Code:\n```python\n{test_code}\n```\n\n"
        f"Modified Code:\n{context_str}\n\n"
        "Analyze the failure. If this was a genuine crash or logic failure in the PR code (e.g. division by zero, unhandled None, missing key, unhandled empty input), "
        "extract the bug proof with exact failing input, error type, stack trace snippet, suggested fix, and the reproducing test code."
    )

    try:
        structured_output: SandboxReviewOutput = structured_llm.invoke(analysis_prompt)
        return {
            "sandbox_summary": structured_output.summary,
            "sandbox_bugs": [b.model_dump() for b in structured_output.bugs_found],
        }
    except Exception as e:
        logger.error(f"[{repo}] Failed to parse structured sandbox bugs: {e}", exc_info=True)
        return {
            "sandbox_summary": f"⚠️ Sandbox caught a test failure, but could not parse structured details: {sandbox_result['output'][:200]}",
            "sandbox_bugs": [],
        }
