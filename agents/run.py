import os, json, time, requests, logging
from typing import Dict, Any, Optional

# Optional Google APIs for Proof docs
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except Exception:
    service_account = None
    build = None
    HttpError = Exception

# Optional OpenAI
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DB_ID        = os.environ.get("NOTION_AGENT_DB")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL   = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# Load RaNemoOS system prompt
def load_ranemos_prompt() -> str:
    """Load RaNemoOS alignment preamble from .ranemos/system-prompt.json"""
    try:
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prompt_path = os.path.join(script_dir, ".ranemos", "system-prompt.json")
        with open(prompt_path, "r") as f:
            data = json.load(f)

        instructions = data.get("instructions", {})
        identity = instructions.get("identity", {})
        mission = instructions.get("mission", "")
        tone_style = instructions.get("tone_and_style", {})
        behavioral = instructions.get("behavioral_anchors", {})
        forbidden = instructions.get("forbidden", [])

        # Build system prompt from RaNemoOS alignment
        lines = []
        lines.append(f"IDENTITY: {identity.get('role', 'RaNemoOS')}")
        lines.append(f"CONTEXT: {identity.get('context', '')}")
        lines.append(f"\nMISSION: {mission}")
        lines.append(f"\nVOICE: {tone_style.get('voice', 'Philosopher × Operator × Coach')}")
        lines.append(f"PERSONA: {tone_style.get('persona', 'Builder energy')}")
        lines.append(f"ATTITUDE: {tone_style.get('attitude', '')}")

        core_traits = tone_style.get('core', [])
        if core_traits:
            lines.append(f"\nCORE TRAITS: {', '.join(core_traits)}")

        focus_areas = behavioral.get('focus', [])
        if focus_areas:
            lines.append(f"\nFOCUS: {', '.join(focus_areas)}")

        lines.append(f"\nMOTIVATION: {behavioral.get('motivation', '')}")

        if forbidden:
            lines.append(f"\nFORBIDDEN: {', '.join(forbidden)}")

        lines.append("\n" + data.get("instructions", {}).get("mission_tagline", ""))

        return "\n".join(lines)
    except Exception as e:
        logging.warning(f"Could not load RaNemoOS prompt: {e}")
        return "You are RaNEMOS Agent Writer. Deliver signal, not noise."

RANEMOS_SYSTEM_PROMPT = load_ranemos_prompt()

DRIVE_SA_JSON = os.environ.get("DRIVE_SA_JSON")  # JSON string
GDRIVE_PARENT_FOLDER_ID = os.environ.get("GDRIVE_PARENT_FOLDER_ID")  # optional
GOOGLE_WORKSPACE_IMPERSONATE = os.environ.get("GOOGLE_WORKSPACE_IMPERSONATE")  # optional

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

def _now_date():
    return time.strftime("%Y-%m-%d")

def notion_query_queued() -> list[Dict[str, Any]]:
    """Query Notion for queued items that are due on or before today."""
    url = f"https://api.notion.com/v1/databases/{DB_ID}/query"
    body = {
        "filter": {
            "and": [
                {"property": "Status", "select": {"equals": "Queued"}},
                {"property": "Due", "date": {"on_or_before": _now_date()}}
            ]
        }
    }
    r = requests.post(url, headers=NOTION_HEADERS, data=json.dumps(body))
    r.raise_for_status()
    data = r.json()
    return data.get("results", [])

def notion_get_prop(page: Dict[str, Any], prop: str, kind: str) -> Optional[Any]:
    props = page.get("properties", {})
    p = props.get(prop)
    if not p: return None
    if kind == "title":
        arr = p.get("title", [])
        return arr[0]["plain_text"] if arr else None
    if kind == "rich_text":
        arr = p.get("rich_text", [])
        return "\n".join([x.get("plain_text","") for x in arr])
    if kind == "select":
        s = p.get("select")
        return s.get("name") if s else None
    if kind == "number":
        return p.get("number")
    if kind == "date":
        d = p.get("date")
        return d.get("start") if d else None
    if kind == "url":
        return p.get("url")
    if kind == "files":
        return p.get("files", [])
    if kind == "people":
        return p.get("people", [])
    return None

def notion_update_status(page_id: str, status: str, proof_url: Optional[str], confidence: Optional[float], note: Optional[str] = None):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    props = {
        "Status": {"select": {"name": status}},
    }
    if proof_url is not None:
        props["ProofURL"] = {"url": proof_url}
    if confidence is not None:
        props["Confidence"] = {"number": float(confidence)}
    if note is not None:
        props["ProofNote"] = {"rich_text": [{"type":"text","text":{"content": note[:2000]}}]}
    payload = {"properties": props}
    r = requests.patch(url, headers=NOTION_HEADERS, data=json.dumps(payload))
    r.raise_for_status()

def init_gdrive_clients():
    """Initialize Google Drive and Docs clients from SA JSON in env."""
    if not DRIVE_SA_JSON or not build or not service_account:
        return None, None
    info = json.loads(DRIVE_SA_JSON)
    scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/documents"]
    credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    if GOOGLE_WORKSPACE_IMPERSONATE:
        credentials = credentials.with_subject(GOOGLE_WORKSPACE_IMPERSONATE)
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    docs = build("docs", "v1", credentials=credentials, cache_discovery=False)
    return drive, docs

def create_google_doc(title: str, markdown_text: str) -> str:
    """Create a Google Doc, insert text, and return the share link."""
    drive, docs = init_gdrive_clients()
    if not drive or not docs:
        logging.warning("Google APIs not configured; returning placeholder ProofURL.")
        return f"about:blank#{title.replace(' ', '_')}"
    try:
        # 1) Create an empty Doc
        doc = docs.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]
        # 2) Insert content (simple text; you can enhance to parse markdown)
        requests_body = {
            "requests": [
                {"insertText": {"location": {"index": 1}, "text": markdown_text}}
            ]
        }
        docs.documents().batchUpdate(documentId=doc_id, body=requests_body).execute()
        # 3) Move to folder if provided
        if GDRIVE_PARENT_FOLDER_ID:
            drive.files().update(
                fileId=doc_id,
                addParents=GDRIVE_PARENT_FOLDER_ID,
                fields="id, parents"
            ).execute()
        # 4) Make it link-viewable (adjust if needed)
        drive.permissions().create(
            fileId=doc_id,
            body={"type": "anyone", "role": "reader"},
            fields="id"
        ).execute()
        # 5) Return link
        return f"https://docs.google.com/document/d/{doc_id}/edit"
    except HttpError as e:
        logging.error(f"Google API error: {e}")
        return f"about:blank#error={str(e)}"

def call_model(prompt: str) -> Dict[str, Any]:
    """
    Call OpenAI with structured JSON return.
    The model should return: {"text": "...", "confidence": 0.0, "title": "Optional"}
    """
    system = (
        f"{RANEMOS_SYSTEM_PROMPT}\n\n"
        "AGENT OUTPUT FORMAT:\n"
        "Return strict JSON with keys: text, confidence (0-1), title (optional).\n"
        "Produce clean, shippable text that embodies the RaNemoOS voice.\n"
        "Do not include backticks, code fences, or commentary outside the JSON."
    )
    user = (
        "TASK CONTEXT:\n"
        + prompt.strip()
        + "\n\nReturn JSON only."
    )
    if not OPENAI_API_KEY or OpenAI is None:
        # Offline fallback for testing
        return {"text": f"[OFFLINE DUMMY OUTPUT]\n\n{prompt[:2000]}", "confidence": 0.7, "title": None}
    client = OpenAI(api_key=OPENAI_API_KEY)
    try:
        # Using Responses API if available
        resp = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": [{"type": "text", "text": system}]},
                {"role": "user",   "content": [{"type": "text", "text": user}]},
            ],
            temperature=0.2,
        )
        # Try to extract a JSON blob from the response
        output_text = None
        try:
            output_text = resp.output_text  # newer SDKs
        except Exception:
            try:
                content = resp.output[0].content[0].text  # generic fallback
                output_text = content
            except Exception:
                output_text = str(resp)
        data = None
        try:
            data = json.loads(output_text)
        except Exception:
            start = output_text.find("{")
            end = output_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                data = json.loads(output_text[start:end+1])
        if not isinstance(data, dict):
            raise ValueError("Model did not return dict JSON.")
        text = data.get("text") or ""
        conf = float(data.get("confidence", 0.7))
        title = data.get("title")
        return {"text": text, "confidence": conf, "title": title}
    except Exception as e:
        logging.error(f"Model error: {e}")
        return {"text": f"[MODEL ERROR]\n{e}", "confidence": 0.0, "title": None}

def build_prompt(name: str, agent_type: str, context: str, inputs: list, publish_mode: str) -> str:
    lines = []
    lines.append(f"JOB: {name}")
    lines.append(f"AGENT TYPE: {agent_type or 'General'}")
    lines.append(f"PUBLISH MODE: {publish_mode or 'Needs Review'}")
    if context:
        lines.append("CONTEXT:")
        lines.append(context)
    if inputs:
        lines.append("INPUT LINKS:")
        for f in inputs:
            for k in ("external","file"):
                if k in f:
                    url = f[k].get("url")
                    if url:
                        lines.append(f"- {url}")
    lines.append("\nDELIVERABLE: Draft the artifact in clean Markdown suitable for direct publishing. Avoid placeholders, be specific, add headings where helpful.\n")
    return "\n".join(lines)

def main():
    assert NOTION_TOKEN and DB_ID, "NOTION_TOKEN and NOTION_AGENT_DB required."
    items = notion_query_queued()
    logging.info(f"Found {len(items)} queued items.")
    for page in items:
        page_id = page["id"]
        name     = notion_get_prop(page, "Name", "title") or "Untitled"
        agent    = notion_get_prop(page, "AgentType", "select") or "General"
        context  = notion_get_prop(page, "Prompt / Context", "rich_text") or ""
        inputs   = notion_get_prop(page, "Inputs", "files") or []
        mode     = notion_get_prop(page, "PublishMode", "select") or "Needs Review"
        gate     = notion_get_prop(page, "ConfidenceGate", "number") or 0.7

        logging.info(f"Running: {name} [{agent}]")
        notion_update_status(page_id, "Running", proof_url=None, confidence=None, note="Agent started.")

        prompt = build_prompt(name, agent, context, inputs, mode)
        result = call_model(prompt)
        text   = result.get("text","").strip()
        conf   = float(result.get("confidence", 0.7))

        proof_url = create_google_doc(title=name, markdown_text=text or f"(empty output for {name})")

        status = "Done" if (mode == "Auto" and conf >= gate) else "Needs Review"
        notion_update_status(page_id, status, proof_url, conf, note=f"Output posted. Gate={gate:.2f}, Conf={conf:.2f}")
        logging.info(f"Completed: {name} -> {status} ({conf:.2f}) | {proof_url}")

if __name__ == "__main__":
    main()
