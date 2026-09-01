import os
import json
import base64
import html
import urllib.request
import urllib.parse
import logging
from urllib.parse import parse_qs

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ADMIN_KEY = os.environ["ADMIN_KEY"]

PIPELINE_BASE = "https://api.pipelinecrm.com/api/v3"
PIPELINE_AUTH = "api_key=" + os.environ["PIPELINE_API_KEY"] + "&app_key=" + os.environ["PIPELINE_APP_KEY"]

BEDROCK_MODEL = "us.anthropic.claude-sonnet-4-6"

INDUSTRY_ID_TO_NAME = {
    5080477: "Advanced Materials", 6041686: "Advertising", 6291286: "Aerospace",
    6411460: "AgTech", 5079682: "AI", 6323896: "Analytics", 6041689: "Apps",
    6497595: "Augmented Reality", 6041692: "Autonomous Vehicles", 6498389: "B2B",
    6498390: "B2C", 5080480: "Batteries", 5079691: "Big Data", 5079685: "BioTech",
    7041664: "Business Intelligence", 6348286: "Cannabis", 6559224: "Construction",
    6692138: "Consumer", 6548509: "CRM", 6437357: "Crypto/Blockchain",
    5080471: "Cybersecurity", 6543471: "Database", 6773331: "Defense",
    6558585: "Delivery", 6584819: "Design", 6584820: "Developer Tools",
    6323887: "Drones", 5079694: "E-Commerce", 5639584: "EdTech",
    6560147: "Education", 6925054: "Electric Vehicles", 6925055: "Electronics",
    5099446: "Energy", 6874488: "Fashion/Retail", 6348289: "Finance",
    5079676: "FinTech", 6687285: "Food Delivery", 5622097: "Food&Beverage",
    6411463: "FoodTech", 6681863: "Funding Platform", 6589044: "Gaming",
    7005277: "GreenTech", 6437358: "Hardware", 5622091: "Healthcare",
    6661451: "Human Resources", 5891584: "IaaS", 6771364: "Impact Investing",
    5865601: "Information Services", 6323899: "Infrastructure", 6558456: "Insurance",
    6755652: "Internet", 6687287: "IoT", 6538857: "IT", 6668597: "Legal",
    5079697: "Lifestyle", 6674874: "Logistics", 6323902: "Machine Learning",
    6323905: "Management", 6322129: "Manufacturing", 6041695: "Marketing",
    6674875: "Marketplace", 6322132: "Media", 6774700: "Mining",
    6506196: "Movies, Music and Entertainment", 6925056: "NanoTech",
    6755654: "Oil & Gas", 6876091: "Packaging", 6755653: "Pharma",
    6563263: "Publishing", 6446568: "Real Estate",
    5527627: "Renewables / Clean Energy", 6771365: "Resources",
    6973702: "Restaurant", 6323890: "Robotics", 6041698: "Saas",
    5141053: "Sharing Economy", 5079688: "Social Media", 5080483: "Software",
    6751585: "Sports", 6438707: "SRI / ESG", 6323893: "Technology",
    5080474: "Telecom", 6543472: "TMT", 5079679: "Transport", 6323884: "Travel",
    6755655: "Utilities", 6774699: "Virtual Reality", 5527624: "Water",
    6786914: "Web3", 6726243: "Wellness", 7129933: "PropTech",
}

PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Deal Matcher</title>
<link rel="stylesheet" href="https://s3.us-east-1.amazonaws.com/main.css/master.css">
<style>
.dm-wrap { max-width: 760px; margin: 40px auto; padding: 0 20px; }
.dm-wrap textarea { width: 100%; min-height: 220px; font-size: 15px; padding: 12px; box-sizing: border-box; }
.dm-wrap input[type=text] { width: 260px; font-size: 15px; padding: 8px; }
.dm-label { font-weight: 600; margin: 18px 0 6px; display: block; }
.dm-btn { margin-top: 22px; font-size: 16px; padding: 10px 28px; cursor: pointer; }
.dm-result { white-space: pre-wrap; background: #f6f6f4; border: 1px solid #ddd; padding: 20px; margin-top: 30px; font-size: 15px; line-height: 1.5; }
.dm-copy { margin-top: 10px; padding: 8px 18px; cursor: pointer; }
</style>
</head>
<body>
<div class="dm-wrap">
<h1>Deal Matcher</h1>
<p>Paste an inbound inquiry. Optionally add the Pipeline person ID for context from notes.</p>
<form method="POST" action="/?key=__KEY__">
<label class="dm-label">Inquiry text</label>
<textarea name="inquiry" required>__INQUIRY__</textarea>
<label class="dm-label">Person ID (optional)</label>
<input type="text" name="person_id" inputmode="numeric" value="__PID__">
<br>
<button class="dm-btn" type="submit">Find matches &amp; draft email</button>
</form>
__RESULT__
</div>
<script>
function dmCopy() {
  var el = document.getElementById("dm-output");
  if (!el) return;
  navigator.clipboard.writeText(el.innerText);
}
</script>
</body>
</html>"""


def respond(status, body, content_type="text/html"):
    return {
        "statusCode": status,
        "headers": {"Content-Type": content_type},
        "body": body,
    }


def render(inquiry="", pid="", result_html=""):
    page = PAGE.replace("__KEY__", ADMIN_KEY)
    page = page.replace("__INQUIRY__", html.escape(inquiry))
    page = page.replace("__PID__", html.escape(pid))
    page = page.replace("__RESULT__", result_html)
    return respond(200, page)


# ── S3 loaders ────────────────────────────────────────────────────────────────

def load_s3_json(bucket, key):
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def get_live_deals():
    data = load_s3_json("pipeline-public-deal-data", "pipeline_deals.json")
    if isinstance(data, dict):
        data = data.get("deals") or []
    deals = []
    for d in data:
        if not isinstance(d, dict):
            continue
        slim = {k: v for k, v in d.items() if v not in (None, "", [])}
        deals.append(slim)
    return deals


def get_companies_snapshot():
    data = load_s3_json("full-pipeline-cache", "companies.json")
    if isinstance(data, dict):
        data = data.get("companies") or []
    out = {}
    for c in data:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        raw = (c.get("custom_fields") or {}).get("custom_label_3065122")
        ids = raw if isinstance(raw, list) else ([raw] if raw else [])
        industries = [INDUSTRY_ID_TO_NAME.get(int(i)) for i in ids
                      if str(i).strip().isdigit() and int(i) in INDUSTRY_ID_TO_NAME]
        out[name.lower()] = {"name": name, "industries": [x for x in industries if x]}
    return out


def get_holder_interest():
    """Best-effort parse of holder_counts.json into
    [{company, buy_count, sell_count}] regardless of exact shape.
    Person-ID lists are reduced to counts and never passed onward."""
    try:
        data = load_s3_json("full-pipeline-cache", "holder_counts.json")
    except Exception as e:
        logger.warning(f"holder_counts.json load failed: {e}")
        return []

    def numify(v):
        if isinstance(v, int):
            return v
        if isinstance(v, list):
            return len(v)
        return None

    results = []
    if isinstance(data, dict):
        inner = data
        for wrapper in ("companies", "counts", "holder_counts", "securities"):
            if wrapper in data and isinstance(data[wrapper], (dict, list)):
                inner = data[wrapper]
                break
        if isinstance(inner, dict):
            for name, v in inner.items():
                if isinstance(v, dict):
                    buy = None
                    sell = None
                    for k2, v2 in v.items():
                        lk = str(k2).lower()
                        n = numify(v2)
                        if n is None:
                            continue
                        if "buy" in lk:
                            buy = n if buy is None else max(buy, n)
                        elif "sell" in lk:
                            sell = n if sell is None else max(sell, n)
                    if buy or sell:
                        results.append({"company": name, "buy_count": buy or 0, "sell_count": sell or 0})
                elif numify(v):
                    results.append({"company": name, "buy_count": numify(v), "sell_count": 0})
        elif isinstance(inner, list):
            for item in inner:
                if not isinstance(item, dict):
                    continue
                name = item.get("company") or item.get("name") or item.get("security")
                if not name:
                    continue
                buy = 0
                sell = 0
                for k2, v2 in item.items():
                    lk = str(k2).lower()
                    n = numify(v2)
                    if n is None:
                        continue
                    if "buy" in lk:
                        buy = max(buy, n)
                    elif "sell" in lk:
                        sell = max(sell, n)
                if buy or sell:
                    results.append({"company": name, "buy_count": buy, "sell_count": sell})
    logger.info(f"holder_interest parsed: {len(results)} companies")
    return results


# ── Pipeline live pulls (person context) ──────────────────────────────────────

def pipeline_get(path_and_query):
    sep = "&" if "?" in path_and_query else "?"
    url = f"{PIPELINE_BASE}{path_and_query}{sep}{PIPELINE_AUTH}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def get_person_context(person_id):
    ctx = {}
    try:
        person = pipeline_get(f"/people/{person_id}.json")
        slim = {}
        for k in ("first_name", "last_name", "company_name", "position", "title",
                  "email", "home_country", "work_country", "summary"):
            if person.get(k):
                slim[k] = person[k]
        if not slim:
            slim = {"raw": json.dumps(person)[:800]}
        ctx["person"] = slim
    except Exception as e:
        logger.warning(f"person fetch failed for {person_id}: {e}")

    try:
        notes_data = pipeline_get(f"/notes.json?person_id={person_id}")
        entries = notes_data.get("entries") if isinstance(notes_data, dict) else notes_data
        notes = []
        for n in (entries or [])[:15]:
            if not isinstance(n, dict):
                continue
            text = n.get("content") or n.get("body") or n.get("note") or ""
            text = urllib.parse.unquote(str(text))
            text = " ".join(html.unescape(text).replace("<br>", " ").split())
            if text:
                notes.append({"created_at": n.get("created_at", ""), "note": text[:500]})
        ctx["notes"] = notes
    except Exception as e:
        logger.warning(f"notes fetch failed for {person_id}: {e}")
    return ctx


# ── Bedrock ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You assist Chad Gracia, a FINRA-registered representative at Rainmaker "
    "Securities running Gracia Group, a pre-IPO secondary market brokerage. "
    "An accredited or institutional investor has sent an inbound inquiry. Your "
    "job: (1) identify which of Chad's live deals and tracked companies match "
    "the inquirer's stated interests (sector, deal size, structure, geography), "
    "and (2) draft a factual introduction email Chad can send.\n\n"
    "STRICT RULES:\n"
    "- Use ONLY facts present in the data provided. Never invent pricing, "
    "valuations, availability, or company facts.\n"
    "- If a deal has catalyst text, you may quote or paraphrase it as 'recent "
    "developments'. No hype, no superlatives, no performance predictions.\n"
    "- For live deals, include the link https://trades.graciagroup.com/deals/{id} "
    "using that deal's actual id field. Only link deals that appear in the data.\n"
    "- Tracked companies with buyer/seller interest but no live deal may be "
    "mentioned as 'we also track X and see active buyer interest' — no counts "
    "in the email itself unless they strengthen credibility (rounding is fine, "
    "e.g. 'several buyers').\n"
    "- Match on sector first, then respect any size or structure constraints "
    "the inquirer stated. If their stated minimum exceeds a deal's max size, "
    "exclude it or flag the mismatch.\n"
    "- Email tone: professional, concise, factual, first person as Chad. No "
    "emojis, no exclamation marks. Sign off as 'Chad'. Do not include a "
    "subject line unless useful; if included, keep it plain.\n"
    "- The email must not read as a mass blast — reference the inquirer's "
    "specifics.\n\n"
    "OUTPUT FORMAT (plain text, exactly these two sections):\n"
    "=== MATCHES ===\n"
    "Bullet list: each match with company, live deal or tracked-only, and one "
    "line of reasoning. Note any near-misses with the constraint that "
    "excluded them.\n"
    "=== EMAIL DRAFT ===\n"
    "The complete email body."
)


def run_matcher(inquiry, person_ctx, deals, tracked):
    user_content = {
        "inquiry": inquiry,
        "person_context": person_ctx or "none provided",
        "live_deals": deals,
        "tracked_companies_no_live_deal": tracked,
    }
    client = boto3.client("bedrock-runtime", region_name="us-east-1")
    resp = client.converse(
        modelId=BEDROCK_MODEL,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": json.dumps(user_content, default=str)}]}],
        inferenceConfig={"maxTokens": 3000, "temperature": 0.2},
    )
    parts = resp.get("output", {}).get("message", {}).get("content", [])
    return "\n".join(p.get("text", "") for p in parts if p.get("text"))


# ── Handler ───────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    params = event.get("queryStringParameters") or {}
    if params.get("key") != ADMIN_KEY:
        return respond(403, "Forbidden")

    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    if method == "GET":
        return render()

    if method == "POST":
        body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        form = parse_qs(body)
        inquiry = form.get("inquiry", [""])[0].strip()
        person_id = form.get("person_id", [""])[0].strip()

        if not inquiry:
            return render(result_html='<div class="dm-result">No inquiry text received.</div>')

        try:
            deals = get_live_deals()
        except Exception as e:
            logger.error(f"deals load failed: {e}")
            return render(inquiry, person_id,
                          '<div class="dm-result">Failed to load deals data: '
                          + html.escape(str(e)) + "</div>")

        deal_companies = set()
        for d in deals:
            c = d.get("company")
            if isinstance(c, str):
                deal_companies.add(c.lower())
            elif isinstance(c, dict) and c.get("name"):
                deal_companies.add(c["name"].lower())

        tracked = []
        try:
            interest = get_holder_interest()
            companies = get_companies_snapshot()
            for item in interest:
                lname = item["company"].lower()
                if lname in deal_companies:
                    continue
                comp = companies.get(lname)
                tracked.append({
                    "company": item["company"],
                    "industries": comp["industries"] if comp else [],
                    "buy_interest_count": item["buy_count"],
                    "sell_interest_count": item["sell_count"],
                })
        except Exception as e:
            logger.warning(f"tracked-company build failed: {e}")

        person_ctx = None
        if person_id:
            person_ctx = get_person_context(person_id)

        try:
            output = run_matcher(inquiry, person_ctx, deals, tracked)
        except Exception as e:
            logger.error(f"bedrock call failed: {e}")
            return render(inquiry, person_id,
                          '<div class="dm-result">Matching call failed: '
                          + html.escape(str(e)) + "</div>")

        result_html = (
            '<div class="dm-result" id="dm-output">' + html.escape(output) + "</div>"
            '<button class="dm-copy" type="button" onclick="dmCopy()">Copy output</button>'
        )
        return render(inquiry, person_id, result_html)

    return respond(405, "Method not allowed")
