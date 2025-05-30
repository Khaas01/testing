from flask import Flask, request, jsonify
import os, json, shutil, datetime, csv, mimetypes

app = Flask(__name__)

BASE_DIR = "/data/AI-Agency"
TRASH_DIR = os.path.join(BASE_DIR, ".trash")
SHEETS_DIR = os.path.join(BASE_DIR, "sheets")
DOCS_DIR = os.path.join(BASE_DIR, "docs")

for d in [TRASH_DIR, SHEETS_DIR, DOCS_DIR]:
    os.makedirs(d, exist_ok=True)

@app.route("/openapi.json")
def openapi():
    return jsonify({"status": "ok"})

@app.route("/drive/list", methods=["GET"])
def drive_list():
    items = []
    for item in os.listdir(BASE_DIR):
        path = os.path.join(BASE_DIR, item)
        items.append({"name": item, "type": "folder" if os.path.isdir(path) else "file"})
    return jsonify(items)

@app.route("/drive/list-path", methods=["GET"])
def drive_list_path():
    subpath = request.args.get("subpath")
    path = os.path.join(BASE_DIR, subpath)
    if not os.path.exists(path):
        return jsonify({"error": "Path not found"}), 404
    items = []
    for item in os.listdir(path):
        full_path = os.path.join(path, item)
        items.append({"name": item, "type": "folder" if os.path.isdir(full_path) else "file"})
    return jsonify(items)

@app.route("/drive/read-file", methods=["GET"])
def drive_read_file():
    filename = request.args.get("filename")
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    with open(path, "r", encoding="utf-8") as f:
        return jsonify({"content": f.read()})

@app.route("/drive/write-file", methods=["POST"])
def drive_write_file():
    data = request.json
    filename = os.path.join(BASE_DIR, data["filename"])
    content = data["content"]
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"success": True})

@app.route("/drive/create-folder", methods=["POST"])
def drive_create_folder():
    data = request.json
    folder_path = os.path.join(BASE_DIR, data["folder_path"])
    os.makedirs(folder_path, exist_ok=True)
    return jsonify({"success": True})

@app.route("/drive/move-file", methods=["POST"])
def drive_move_file():
    data = request.json
    src = os.path.join(BASE_DIR, data["src"])
    dst = os.path.join(BASE_DIR, data["dst"])
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    return jsonify({"success": True})

@app.route("/drive/delete-file", methods=["DELETE"])
def drive_delete_file():
    path = os.path.join(BASE_DIR, request.args.get("path"))
    if not os.path.exists(path):
        return jsonify({"error": "Path not found"}), 404
    os.makedirs(TRASH_DIR, exist_ok=True)
    trash_path = os.path.join(TRASH_DIR, os.path.basename(path))
    shutil.move(path, trash_path)
    return jsonify({"success": True})

@app.route("/drive/get_metadata", methods=["GET"])
def drive_get_metadata():
    path = os.path.join(BASE_DIR, request.args.get("path"))
    if not os.path.exists(path):
        return jsonify({"error": "Path not found"}), 404
    stat = os.stat(path)
    return jsonify({
        "path": path,
        "size": stat.st_size,
        "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "type": "folder" if os.path.isdir(path) else "file"
    })

@app.route("/sheets/create", methods=["POST"])
def sheets_create():
    data = request.json
    name = data["name"]
    path = os.path.join(SHEETS_DIR, f"{name}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(data.get("data", []))
    return jsonify({"spreadsheetId": name})

@app.route("/sheets/read", methods=["GET"])
def sheets_read():
    sid = request.args.get("spreadsheet_id")
    path = os.path.join(SHEETS_DIR, f"{sid}.csv")
    if not os.path.exists(path):
        return jsonify({"error": "Sheet not found"}), 404
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        return jsonify({"values": list(reader)})

@app.route("/sheets/update", methods=["POST"])
def sheets_update():
    data = request.json
    sid = data["spreadsheet_id"]
    values = data["values"]
    path = os.path.join(SHEETS_DIR, f"{sid}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(values)
    return jsonify({"success": True})
  
@app.route("/sheets/append", methods=["POST"])
def sheets_append():
    data = request.json
    sid = data["spreadsheet_id"]
    values = data["values"]
    path = os.path.join(SHEETS_DIR, f"{sid}.csv")

    if not os.path.exists(path):
        return jsonify({"error": "Spreadsheet not found"}), 404

    try:
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(values)
        return jsonify({"success": True, "appended_rows": len(values)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/sheets/batch-update", methods=["POST"])
def sheets_batch_update():
    data = request.json
    sid = data["spreadsheet_id"]
    requests = data["requests"]
    path = os.path.join(SHEETS_DIR, f"{sid}.csv")

    if not os.path.exists(path):
        return jsonify({"error": "Spreadsheet not found"}), 404

    try:
        # Load existing data
        with open(path, "r", newline="", encoding="utf-8") as f:
            existing_data = list(csv.reader(f))

        applied_requests = 0

        for req in requests:
            if "updateCells" in req:
                start = req["updateCells"]["start"]
                rows = req["updateCells"]["rows"]

                row_index = start.get("rowIndex", 0)
                col_index = start.get("columnIndex", 0)

                for r, row in enumerate(rows):
                    values = row.get("values", [])
                    while len(existing_data) <= row_index + r:
                        existing_data.append([])

                    for c, cell in enumerate(values):
                        while len(existing_data[row_index + r]) <= col_index + c:
                            existing_data[row_index + r].append("")
                        val = cell.get("userEnteredValue", {}).get("stringValue", "")
                        existing_data[row_index + r][col_index + c] = val
                applied_requests += 1

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(existing_data)

        return jsonify({"success": True, "applied_requests": applied_requests})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/sheets/list-tabs", methods=["GET"])
def sheets_list_tabs():
    sid = request.args.get("spreadsheet_id")
    if not sid:
        return jsonify({"error": "spreadsheet_id parameter is required"}), 400

    path = os.path.join(SHEETS_DIR, f"{sid}.csv")

    if not os.path.exists(path):
        return jsonify({"error": "Spreadsheet not found"}), 404

    try:
        # CSV files have one tab by default
        tabs = [{
            "title": sid,
            "sheetId": 0,
            "index": 0,
            "sheetType": "GRID",
            "hidden": False
        }]
        return jsonify(tabs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/sheets/add-tab", methods=["POST"])
def sheets_add_tab():
    data = request.json
    sid = data.get("spreadsheet_id")
    title = data.get("title")

    if not sid or not title:
        return jsonify({"error": "spreadsheet_id and title required"}), 400

    folder_path = os.path.join(SHEETS_DIR, sid)
    os.makedirs(folder_path, exist_ok=True)

    safe_title = re.sub(r'[^\w\-_\.]', '_', title)
    new_tab_path = os.path.join(folder_path, f"{safe_title}.csv")

    if os.path.exists(new_tab_path):
        return jsonify({"error": "Tab already exists"}), 400

    try:
        with open(new_tab_path, "w", newline="", encoding="utf-8") as f:
            pass

        return jsonify({
            "success": True,
            "sheetId": int(datetime.datetime.now().timestamp()),
            "title": title
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/sheets/delete-tab", methods=["DELETE"])
def sheets_delete_tab():
    sid = request.args.get("spreadsheet_id")
    title = request.args.get("title")

    if not sid or not title:
        return jsonify({"error": "spreadsheet_id and title required"}), 400

    safe_title = re.sub(r'[^\w\-_\.]', '_', title)
    tab_path = os.path.join(SHEETS_DIR, sid, f"{safe_title}.csv")

    if not os.path.exists(tab_path):
        return jsonify({"error": "Tab not found"}), 404

    try:
        os.remove(tab_path)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/sheets/list-tabs", methods=["GET"])
def sheets_list_tabs():
    sid = request.args.get("spreadsheet_id")

    if not sid:
        return jsonify({"error": "spreadsheet_id required"}), 400

    sheet_dir = os.path.join(SHEETS_DIR, sid)

    if not os.path.exists(sheet_dir):
        return jsonify({"error": "Spreadsheet not found"}), 404

    tabs = []
    for filename in os.listdir(sheet_dir):
        if filename.endswith(".csv"):
            tab_name = filename[:-4]
            tabs.append({"title": tab_name})

    return jsonify({"tabs": tabs})

@app.route("/sheets/format", methods=["POST"])
def sheets_format():
    data = request.json
    sid = data["spreadsheet_id"]
    tab = data["tab"]
    formatting = data["formatting"]

    sheet_dir = os.path.join(SHEETS_DIR, sid)
    if not os.path.exists(sheet_dir):
        return jsonify({"error": "Spreadsheet not found"}), 404

    format_file = os.path.join(sheet_dir, f"{tab}.format.json")

    try:
        with open(format_file, "w", encoding="utf-8") as f:
            json.dump(formatting, f, ensure_ascii=False, indent=2)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/sheets/create-filter", methods=["POST"])
def sheets_create_filter():
    data = request.json
    sid = data["spreadsheet_id"]
    tab = data["tab"]
    filter_config = data["filter_config"]

    sheet_dir = os.path.join(SHEETS_DIR, sid)
    if not os.path.exists(sheet_dir):
        return jsonify({"error": "Spreadsheet not found"}), 404

    filters_file = os.path.join(sheet_dir, f"{tab}.filters.json")

    # Load existing filters if any
    filters = []
    if os.path.exists(filters_file):
        with open(filters_file, "r", encoding="utf-8") as f:
            filters = json.load(f)

    filters.append({
        "filter_id": int(datetime.datetime.now().timestamp()),
        "filter": filter_config,
        "created_at": datetime.datetime.now().isoformat()
    })

    try:
        with open(filters_file, "w", encoding="utf-8") as f:
            json.dump(filters, f, ensure_ascii=False, indent=2)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/sheets/freeze-panes", methods=["POST"])
def sheets_freeze_panes():
    data = request.json
    sid = data["spreadsheet_id"]
    tab = data["tab"]
    freeze_config = {
        "rows": data.get("rows", 0),
        "columns": data.get("columns", 0),
        "updated_at": datetime.datetime.now().isoformat()
    }

    sheet_dir = os.path.join(SHEETS_DIR, sid)
    if not os.path.exists(sheet_dir):
        return jsonify({"error": "Spreadsheet not found"}), 404

    freeze_file = os.path.join(sheet_dir, f"{tab}.freeze.json")

    try:
        with open(freeze_file, "w", encoding="utf-8") as f:
            json.dump(freeze_config, f, ensure_ascii=False, indent=2)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/sheets/conditional-format", methods=["POST"])
def sheets_conditional_format():
    data = request.json
    sid = data["spreadsheet_id"]
    tab = data["tab"]
    rule = data["rule"]

    sheet_dir = os.path.join(SHEETS_DIR, sid)
    if not os.path.exists(sheet_dir):
        return jsonify({"error": "Spreadsheet not found"}), 404

    cond_file = os.path.join(sheet_dir, f"{tab}.conditional.json")
    rules = []
    if os.path.exists(cond_file):
        with open(cond_file, "r", encoding="utf-8") as f:
            rules = json.load(f)

    rules.append({
        "rule": rule,
        "created_at": datetime.datetime.now().isoformat()
    })

    try:
        with open(cond_file, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/sheets/query", methods=["POST"])
def sheets_query():
    data = request.json
    sid = data["spreadsheet_id"]
    query = data["query"]

    path = os.path.join(SHEETS_DIR, f"{sid}.csv")
    if not os.path.exists(path):
        return jsonify({"error": "Spreadsheet not found"}), 404

    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        return jsonify({"headers": [], "rows": []})

    headers = rows[0]
    data_rows = rows[1:]

    # Extremely basic query parser: SELECT * ONLY
    if query.strip().upper() == "SELECT *":
        return jsonify({"headers": headers, "rows": data_rows})

    return jsonify({"error": "Only 'SELECT *' supported for now"}), 400

@app.route("/docs/create", methods=["POST"])
def docs_create():
    data = request.json
    title = data["title"]
    content = data.get("content", "")

    # Create safe filename
    safe_title = re.sub(r"[^\w\-_\.]", "_", title)
    path = os.path.join(DOCS_DIR, f"{safe_title}.txt")

    # Ensure docs directory exists
    os.makedirs(DOCS_DIR, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return jsonify({"document_id": safe_title})

@app.route("/docs/read", methods=["GET"])
def docs_read():
    document_id = request.args.get("document_id")
    path = os.path.join(DOCS_DIR, f"{document_id}.txt")

    if not os.path.exists(path):
        return jsonify({"error": "Document not found"}), 404

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    return jsonify({"content": content})

@app.route("/docs/update", methods=["POST"])
def docs_update():
    data = request.json
    document_id = data["document_id"]
    new_content = data["new_content"]

    path = os.path.join(DOCS_DIR, f"{document_id}.txt")

    if not os.path.exists(path):
        return jsonify({"error": "Document not found"}), 404

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)

    return jsonify({"success": True})

@app.route("/docs/format", methods=["POST"])
def docs_format():
    data = request.json
    document_id = data["document_id"]
    requests = data["requests"]

    meta_path = os.path.join(DOCS_DIR, f"{document_id}.format.json")

    # Load existing formats
    formats = []
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            formats = json.load(f)

    formats.extend(requests)

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(formats, f, ensure_ascii=False, indent=2)

    return jsonify({"success": True})

@app.route("/docs/insert-image", methods=["POST"])
def docs_insert_image():
    data = request.json
    document_id = data["document_id"]
    image_url = data["image_url"]
    index = data.get("index", 0)

    file_path = os.path.join(DOCS_DIR, f"{document_id}.txt")
    if not os.path.exists(file_path):
        return jsonify({"error": "Document not found"}), 404

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    image_tag = f"[IMAGE: {image_url}]"
    index = min(len(content), max(0, index))
    new_content = content[:index] + image_tag + content[index:]

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    # log inserted image (optional for agent traceability)
    images_meta = os.path.join(DOCS_DIR, f"{document_id}.images.json")
    images = []
    if os.path.exists(images_meta):
        with open(images_meta, "r", encoding="utf-8") as f:
            images = json.load(f)
    images.append({"url": image_url, "index": index})
    with open(images_meta, "w", encoding="utf-8") as f:
        json.dump(images, f, ensure_ascii=False, indent=2)

    return jsonify({"success": True})

@app.route("/web/search", methods=["GET"])
def web_search():
    query = request.args.get("query")
    if not query:
        return jsonify({"error": "query parameter required"}), 400

    # Simulated search results
    results = [
        {"title": f"Result 1 for '{query}'", "snippet": "First simulated search result.", "link": f"https://example.com/{query}/1"},
        {"title": f"Result 2 for '{query}'", "snippet": "Second simulated search result.", "link": f"https://example.com/{query}/2"},
        {"title": f"Result 3 for '{query}'", "snippet": "Third simulated search result.", "link": f"https://example.com/{query}/3"},
    ]

    return jsonify({"results": results})

@app.route("/web/scrape", methods=["GET"])
def web_scrape():
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "url parameter required"}), 400

    # Simulated scrape output
    simulated_content = f"""
    Simulated content scraped from {url}.
    This is placeholder data representing extracted page content.
    Title: Example Page
    Summary: This page was successfully processed in simulation.
    """

    return jsonify({"content": simulated_content.strip()})












if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
