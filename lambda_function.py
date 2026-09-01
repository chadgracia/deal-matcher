import os
import base64
import html
from urllib.parse import parse_qs

ADMIN_KEY = os.environ["ADMIN_KEY"]

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
.dm-result { white-space: pre-wrap; background: #f6f6f4; border: 1px solid #ddd; padding: 20px; margin-top: 30px; }
</style>
</head>
<body>
<div class="dm-wrap">
<h1>Deal Matcher</h1>
<p>Paste an inbound inquiry. Optionally add the Pipeline person ID for context from notes and interest fields.</p>
<form method="POST" action="/?key=__KEY__">
<label class="dm-label">Inquiry text</label>
<textarea name="inquiry" required></textarea>
<label class="dm-label">Person ID (optional)</label>
<input type="text" name="person_id" inputmode="numeric">
<br>
<button class="dm-btn" type="submit">Find matches &amp; draft email</button>
</form>
__RESULT__
</div>
</body>
</html>"""

def respond(status, body, content_type="text/html"):
    return {
        "statusCode": status,
        "headers": {"Content-Type": content_type},
        "body": body,
    }

def lambda_handler(event, context):
    params = event.get("queryStringParameters") or {}
    if params.get("key") != ADMIN_KEY:
        return respond(403, "Forbidden")

    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    if method == "GET":
        page = PAGE.replace("__KEY__", ADMIN_KEY).replace("__RESULT__", "")
        return respond(200, page)

    if method == "POST":
        body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        form = parse_qs(body)
        inquiry = form.get("inquiry", [""])[0].strip()
        person_id = form.get("person_id", [""])[0].strip()

        summary = (
            "PARSE CHECK (matching not wired yet)\n\n"
            "Inquiry received: " + str(len(inquiry)) + " characters\n"
            "Person ID: " + (person_id if person_id else "(none)") + "\n\n"
            "First 200 chars of inquiry:\n" + html.escape(inquiry[:200])
        )
        result_html = '<div class="dm-result">' + summary + "</div>"
        page = PAGE.replace("__KEY__", ADMIN_KEY).replace("__RESULT__", result_html)
        return respond(200, page)

    return respond(405, "Method not allowed")
