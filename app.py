from flask import Flask, jsonify, request, send_file
import json
import os
import shutil
import glob
import base64
import zipfile
import hashlib
import datetime
import mimetypes
import csv
from pathlib import Path
import re

app = Flask(__name__)
# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRASH_DIR = os.path.join(BASE_DIR, ".trash")
SHEETS_DIR = os.path.join(BASE_DIR, "sheets")
DOCS_DIR = os.path.join(BASE_DIR, "docs")

# Ensure directories exist
os.makedirs(TRASH_DIR, exist_ok=True)
os.makedirs(SHEETS_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)

# Load OpenAPI JSON
try:
    with open("openapi.json", "r", encoding="utf-8") as f:
        openapi_spec = json.load(f)
except Exception as e:
    print(f"Error loading openapi.json: {str(e)}")
    # Create minimal spec if file is missing
    openapi_spec = {
        "openapi": "3.1.0",
        "info": {"title": "File System API", "version": "1.0.0"},
        "paths": {}
    }

@app.route("/openapi.json", methods=["GET"])
def serve_openapi():
    return jsonify(openapi_spec)

# Drive operations
@app.route("/drive/list", methods=["GET"])
def list_files():
    """List root folder contents"""
    try:
        path = "."
        files = os.listdir(path)
        results = []
        for f in files:
            try:
                full_path = os.path.join(path, f)
                file_type = "folder" if os.path.isdir(full_path) else "file"
                
                # Get basic stats
                stats = os.stat(full_path)
                item = {
                    "name": f,
                    "type": file_type,
                    "path": full_path,
                    "size": stats.st_size,
                    "modified": datetime.datetime.fromtimestamp(stats.st_mtime).isoformat()
                }
                
                # Only try to get children if it's a folder and not too big
                if file_type == "folder" and len(os.listdir(full_path)) < 50:
                    try:
                        children = []
                        for child in os.listdir(full_path):
                            child_path = os.path.join(full_path, child)
                            child_type = "folder" if os.path.isdir(child_path) else "file"
                            children.append({
                                "name": child,
                                "type": child_type
                            })
                        item["children"] = children
                    except Exception:
                        pass
                
                results.append(item)
            except Exception as e:
                # Skip files with access issues but log them
                results.append({
                    "name": f,
                    "type": "error",
                    "error": str(e)
                })
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/drive/list-path", methods=["GET"])
def list_by_path():
    """List folder contents"""
    subpath = request.args.get("subpath")
    if not subpath:
        return jsonify({"error": "Subpath parameter is required"}), 400
    
    # Normalize path for security
    subpath = os.path.normpath(subpath)
        
    if not os.path.exists(subpath):
        return jsonify({"error": f"Path not found: {subpath}"}), 404
        
    if not os.path.isdir(subpath):
        return jsonify({"error": f"Not a directory: {subpath}"}), 400
        
    try:
        files = os.listdir(subpath)
        results = []
        for f in files:
            try:
                full_path = os.path.join(subpath, f)
                file_type = "folder" if os.path.isdir(full_path) else "file"
                
                # Get basic stats
                stats = os.stat(full_path)
                item = {
                    "name": f,
                    "type": file_type,
                    "path": full_path,
                    "size": stats.st_size,
                    "modified": datetime.datetime.fromtimestamp(stats.st_mtime).isoformat()
                }
                
                # Only try to get children if it's a folder and not too big
                if file_type == "folder" and len(os.listdir(full_path)) < 50:
                    try:
                        children = []
                        for child in os.listdir(full_path):
                            child_path = os.path.join(full_path, child)
                            child_type = "folder" if os.path.isdir(child_path) else "file"
                            children.append({
                                "name": child,
                                "type": child_type
                            })
                        item["children"] = children
                    except Exception:
                        pass
                
                results.append(item)
            except Exception as e:
                # Skip files with access issues but log them
                results.append({
                    "name": f,
                    "type": "error",
                    "error": str(e)
                })
        return jsonify(results)
    except PermissionError:
        return jsonify({"error": f"Permission denied: {subpath}"}), 403
    except Exception as e:
        return jsonify({"error": f"Error listing directory: {str(e)}"}), 500

@app.route("/drive/read-file", methods=["GET"])
def read_file():
    """Read contents of a file"""
    filename = request.args.get("filename")
    if not filename:
        return jsonify({"error": "Filename parameter is required"}), 400
        
    # Normalize path for security
    filename = os.path.normpath(filename)
    
    if not os.path.exists(filename):
        return jsonify({"error": f"File not found: {filename}"}), 404
        
    if not os.path.isfile(filename):
        return jsonify({"error": f"Not a file: {filename}"}), 400
        
    try:
        # Try multiple encodings
        encodings = ['utf-8', 'latin-1', 'cp1252']
        content = None
        
        for encoding in encodings:
            try:
                with open(filename, "r", encoding=encoding) as f:
                    content = f.read()
                break  # Successfully read the file
            except UnicodeDecodeError:
                continue  # Try next encoding
                
        if content is None:
            # If all encodings fail, try binary mode and decode to base64
            with open(filename, "rb") as f:
                binary_content = f.read()
                # Let's try to detect if it's binary by checking for nulls and control chars
                is_binary = bool(binary_content.translate(None, bytes(range(32, 127))))
                if is_binary:
                    content = f"[Binary content, size: {len(binary_content)} bytes]"
                else:
                    # Last resort: try to decode as latin-1 which can handle any byte
                    content = binary_content.decode('latin-1', errors='replace')
                
        return jsonify({"content": content})
    except PermissionError:
        return jsonify({"error": f"Permission denied: {filename}"}), 403
    except Exception as e:
        return jsonify({"error": f"Error reading file: {str(e)}"}), 500

@app.route("/drive/write-file", methods=["POST"])
def write_file():
    """Create or update a file"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    filename = data.get("filename")
    content = data.get("content")
    folder_path = data.get("folder_path")
    
    if not filename:
        return jsonify({"error": "Filename is required"}), 400
    
    if content is None:  # Allow empty strings
        return jsonify({"error": "Content is required"}), 400
    
    # Handle folder path if provided
    target_path = filename
    if folder_path:
        try:
            os.makedirs(folder_path, exist_ok=True)
            target_path = os.path.join(folder_path, os.path.basename(filename))
        except Exception as e:
            return jsonify({"error": f"Error creating folder: {str(e)}"}), 500
    
    # Ensure parent directories exist
    try:
        parent_dir = os.path.dirname(os.path.abspath(target_path))
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        
        # Write the file with explicit encoding
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        return jsonify({"success": True})
    except PermissionError:
        return jsonify({"error": f"Permission denied: {target_path}"}), 403
    except Exception as e:
        return jsonify({"error": f"Error writing file: {str(e)}"}), 500

@app.route("/drive/create-folder", methods=["POST"])
def create_folder():
    """Create a new folder"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    folder_path = data.get("folder_path")
    if not folder_path:
        return jsonify({"error": "folder_path is required"}), 400
        
    # Normalize path for security
    folder_path = os.path.normpath(folder_path)
        
    try:
        os.makedirs(folder_path, exist_ok=True)
        return jsonify({"success": True})
    except PermissionError:
        return jsonify({"error": f"Permission denied: {folder_path}"}), 403
    except Exception as e:
        return jsonify({"error": f"Error creating folder: {str(e)}"}), 500

@app.route("/drive/move-file", methods=["POST"])
def move_file():
    """Move a file or folder"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    src = data.get("src")
    dst = data.get("dst")
    
    if not src or not dst:
        return jsonify({"error": "Source (src) and destination (dst) are required"}), 400
        
    # Normalize paths for security
    src = os.path.normpath(src)
    dst = os.path.normpath(dst)
        
    try:
        if not os.path.exists(src):
            return jsonify({"error": f"Source file or folder not found: {src}"}), 404
            
        # Make sure the destination directory exists
        dst_dir = os.path.dirname(dst)
        if dst_dir and not os.path.exists(dst_dir):
            os.makedirs(dst_dir, exist_ok=True)
            
        shutil.move(src, dst)
        return jsonify({"success": True})
    except PermissionError:
        return jsonify({"error": f"Permission denied. Check both source and destination paths."}), 403
    except shutil.Error as e:
        return jsonify({"error": f"Error moving file: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Error moving file: {str(e)}"}), 500

@app.route("/drive/delete-file", methods=["DELETE"])
def delete_file():
    """Soft-delete (move to .trash/)"""
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "Path parameter is required"}), 400
        
    # Normalize path for security  
    path = os.path.normpath(path)
        
    try:
        if not os.path.exists(path):
            return jsonify({"error": f"File/folder not found: {path}"}), 404
            
        # Move to trash instead of deleting
        trash_path = os.path.join(TRASH_DIR, os.path.basename(path))
        # If file exists in trash, append timestamp to avoid name collision
        if os.path.exists(trash_path):
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename, ext = os.path.splitext(os.path.basename(path))
            trash_path = os.path.join(TRASH_DIR, f"{filename}_{timestamp}{ext}")
        
        # Store original path in a metadata file
        meta_path = f"{trash_path}.meta"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "original_path": path,
                "deleted_time": datetime.datetime.now().isoformat()
            }, f, ensure_ascii=False)
            
        shutil.move(path, trash_path)
        return jsonify({"success": True})
    except PermissionError:
        return jsonify({"error": f"Permission denied: {path}"}), 403
    except Exception as e:
        return jsonify({"error": f"Error deleting file: {str(e)}"}), 500

# Google Sheets operations - implemented with CSV files
def find_sheet_by_id(spreadsheet_id):
    """Helper function to find a sheet file based on ID"""
    # Try direct filename lookup
    direct_path = os.path.join(SHEETS_DIR, f"{spreadsheet_id}.csv")
    if os.path.exists(direct_path):
        return direct_path
        
    # Look for matching ID in metadata files
    for filename in os.listdir(SHEETS_DIR):
        if filename.endswith(".meta"):
            meta_path = os.path.join(SHEETS_DIR, filename)
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    if meta.get("spreadsheet_id") == spreadsheet_id:
                        sheet_filename = filename[:-5]  # Remove .meta
                        return os.path.join(SHEETS_DIR, sheet_filename)
            except:
                continue
                
    return None

@app.route("/sheets/create", methods=["POST"])
def create_sheet():
    """Create a Google Sheet (implemented as CSV)"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    name = data.get("name")
    if not name:
        return jsonify({"error": "Name is required"}), 400
    
    # Create safe filename from name
    safe_name = re.sub(r'[^\w\-_\.]', '_', name)
    
    # Generate a unique ID
    spreadsheet_id = f"sheet_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # Create a CSV file to represent the sheet
    folder_path = data.get("folder_path")
    if folder_path:
        target_dir = os.path.normpath(folder_path)
        os.makedirs(target_dir, exist_ok=True)
    else:
        target_dir = SHEETS_DIR
    
    # Use the safe name as the filename
    file_path = os.path.join(target_dir, f"{safe_name}.csv")
    meta_path = os.path.join(target_dir, f"{safe_name}.meta")
    
    # If file exists, append timestamp
    if os.path.exists(file_path):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = f"{safe_name}_{timestamp}"
        file_path = os.path.join(target_dir, f"{safe_name}.csv")
        meta_path = os.path.join(target_dir, f"{safe_name}.meta")
    
    try:
        # Write initial data if provided
        sheet_data = data.get("data", [])
        
        with open(file_path, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            if isinstance(sheet_data, list):
                for row in sheet_data:
                    writer.writerow(row)
            elif isinstance(sheet_data, str) and sheet_data:
                # Parse string as CSV
                for line in sheet_data.splitlines():
                    writer.writerow(line.split(','))
        
        # Create metadata file linking ID to filename
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "spreadsheet_id": spreadsheet_id,
                "name": name,
                "created_at": datetime.datetime.now().isoformat(),
                "file_path": file_path
            }, f, ensure_ascii=False)
            
        return jsonify({
            "spreadsheetId": spreadsheet_id,
            "name": name,
            "file": file_path
        })
    except Exception as e:
        return jsonify({"error": f"Error creating sheet: {str(e)}"}), 500

@app.route("/sheets/read", methods=["GET"])
def read_sheet():
    """Read a Google Sheet range (implemented from CSV)"""
    spreadsheet_id = request.args.get("spreadsheet_id")
    range_param = request.args.get("range")
    
    if not spreadsheet_id:
        return jsonify({"error": "spreadsheet_id parameter is required"}), 400
    
    # Find the sheet file
    sheet_path = find_sheet_by_id(spreadsheet_id)
    if not sheet_path:
        return jsonify({"error": "Spreadsheet not found"}), 404
    
    try:
        # Parse the range (e.g., "A1:C5") - A simplified parser
        start_row, start_col, end_row, end_col = 0, 0, None, None
        if range_param:
            # Extract range components (e.g., "A1:C5" -> "A1", "C5")
            parts = range_param.split(":")
            if len(parts) == 2:
                start_cell, end_cell = parts
                # Convert column letters to indices (A=0, B=1, ...)
                start_col_letter = ''.join(filter(str.isalpha, start_cell))
                start_col = sum(26 ** i * (ord(c) - ord('A') + 1) for i, c in enumerate(reversed(start_col_letter))) - 1
                
                end_col_letter = ''.join(filter(str.isalpha, end_cell))
                end_col = sum(26 ** i * (ord(c) - ord('A') + 1) for i, c in enumerate(reversed(end_col_letter)))
                
                # Extract row numbers
                start_row = int(''.join(filter(str.isdigit, start_cell))) - 1  # 0-indexed
                if ''.join(filter(str.isdigit, end_cell)):
                    end_row = int(''.join(filter(str.isdigit, end_cell)))  # Inclusive
        
        # Read the CSV file
        rows = []
        with open(sheet_path, "r", newline='', encoding="utf-8") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if start_row is not None and i < start_row:
                    continue
                if end_row is not None and i >= end_row:
                    break
                    
                # Apply column filtering if specified
                if start_col is not None and end_col is not None:
                    row = row[start_col:end_col]
                
                rows.append(row)
        
        return jsonify({"values": rows})
    except Exception as e:
        return jsonify({"error": f"Error reading sheet: {str(e)}"}), 500

@app.route("/sheets/update", methods=["POST"])
def update_sheet():
    """Update a Google Sheet range (implemented with CSV)"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    spreadsheet_id = data.get("spreadsheet_id")
    range_param = data.get("range")
    values = data.get("values")
    
    if not spreadsheet_id or not values:
        return jsonify({"error": "spreadsheet_id and values are required"}), 400
    
    # Find the sheet file
    sheet_path = find_sheet_by_id(spreadsheet_id)
    if not sheet_path:
        return jsonify({"error": "Spreadsheet not found"}), 404
    
    try:
        # Parse the range (e.g., "A1:C5") - Simplified parser
        start_row, start_col = 0, 0
        if range_param:
            # Extract start cell (e.g., "A1:C5" -> "A1")
            start_cell = range_param.split(":")[0]
            
            # Convert column letter to index (A=0, B=1, ...)
            start_col_letter = ''.join(filter(str.isalpha, start_cell))
            if start_col_letter:
                start_col = sum(26 ** i * (ord(c) - ord('A') + 1) for i, c in enumerate(reversed(start_col_letter))) - 1
            
            # Extract row number
            row_digits = ''.join(filter(str.isdigit, start_cell))
            if row_digits:
                start_row = int(row_digits) - 1  # 0-indexed
        
        # Read existing data
        existing_data = []
        with open(sheet_path, "r", newline='', encoding="utf-8") as f:
            reader = csv.reader(f)
            existing_data = list(reader)
        
        # Ensure there are enough rows
        while len(existing_data) <= start_row + len(values) - 1:
            existing_data.append([])
        
        # Update the cells
        for i, row in enumerate(values):
            row_index = start_row + i
            # Ensure there are enough columns
            while len(existing_data[row_index]) < start_col + len(row):
                existing_data[row_index].append("")
            
            # Update the cells in this row
            for j, value in enumerate(row):
                existing_data[row_index][start_col + j] = value
        
        # Write back the updated data
        with open(sheet_path, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(existing_data)
        
        return jsonify({
            "success": True,
            "updatedRows": len(values),
            "updatedColumns": max(len(row) for row in values) if values else 0
        })
    except Exception as e:
        return jsonify({"error": f"Error updating sheet: {str(e)}"}), 500

@app.route("/sheets/append", methods=["POST"])
def append_sheet():
    """Append rows to a Google Sheet (implemented with CSV)"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    spreadsheet_id = data.get("spreadsheet_id")
    values = data.get("values")
    insert_data_option = data.get("insert_data_option", "INSERT_ROWS")
    
    if not spreadsheet_id or not values:
        return jsonify({"error": "spreadsheet_id and values are required"}), 400
    
    # Find the sheet file
    sheet_path = find_sheet_by_id(spreadsheet_id)
    if not sheet_path:
        return jsonify({"error": "Spreadsheet not found"}), 404
    
    try:
        # Read existing data
        existing_data = []
        with open(sheet_path, "r", newline='', encoding="utf-8") as f:
            reader = csv.reader(f)
            existing_data = list(reader)
        
        # Determine where to insert data
        if insert_data_option == "OVERWRITE" and existing_data:
            # Find the first completely empty row
            insert_row = 0
            for i, row in enumerate(existing_data):
                if not any(row):
                    insert_row = i
                    break
            else:
                insert_row = len(existing_data)
                
            # Update or append rows
            for i, row in enumerate(values):
                if insert_row + i < len(existing_data):
                    # Replace existing row
                    existing_data[insert_row + i] = row
                else:
                    # Append new row
                    existing_data.append(row)
        else:
            # Simply append to the end
            existing_data.extend(values)
        
        # Write back the updated data
        with open(sheet_path, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(existing_data)
        
        return jsonify({
            "success": True,
            "updatedRows": len(values),
            "updatedColumns": max(len(row) for row in values) if values else 0
        })
    except Exception as e:
        return jsonify({"error": f"Error appending to sheet: {str(e)}"}), 500

@app.route("/sheets/batch-update", methods=["POST"])
def batch_update_sheet():
    """Batch update a Google Sheet (implemented with CSV)"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    spreadsheet_id = data.get("spreadsheet_id")
    requests = data.get("requests", [])
    
    if not spreadsheet_id:
        return jsonify({"error": "spreadsheet_id is required"}), 400
    
    if not requests:
        return jsonify({"error": "No update requests provided"}), 400
    
    # Find the sheet file
    sheet_path = find_sheet_by_id(spreadsheet_id)
    if not sheet_path:
        return jsonify({"error": "Spreadsheet not found"}), 404
    
    try:
        # Read existing data
        existing_data = []
        with open(sheet_path, "r", newline='', encoding="utf-8") as f:
            reader = csv.reader(f)
            existing_data = list(reader)
        
        # Process each request (simplified version - handles basic updates)
        applied_requests = 0
        for request in requests:
            if "updateCells" in request:
                # Handle cell updates
                fields = request["updateCells"].get("fields", "userEnteredValue")
                start = request["updateCells"].get("start", {})
                
                # Get start coordinates
                start_row = start.get("rowIndex", 0)
                start_col = start.get("columnIndex", 0)
                
                rows = request["updateCells"].get("rows", [])
                
                # Update cells
                for i, row_data in enumerate(rows):
                    cells = row_data.get("values", [])
                    row_index = start_row + i
                    
                    # Ensure we have enough rows
                    while len(existing_data) <= row_index:
                        existing_data.append([])
                    
                    # Update cells in this row
                    for j, cell in enumerate(cells):
                        col_index = start_col + j
                        
                        # Ensure we have enough columns
                        while len(existing_data[row_index]) <= col_index:
                            existing_data[row_index].append("")
                        
                        # Extract cell value (simplified)
                        value = ""
                        if "userEnteredValue" in cell:
                            if "stringValue" in cell["userEnteredValue"]:
                                value = cell["userEnteredValue"]["stringValue"]
                            elif "numberValue" in cell["userEnteredValue"]:
                                value = str(cell["userEnteredValue"]["numberValue"])
                            elif "boolValue" in cell["userEnteredValue"]:
                                value = str(cell["userEnteredValue"]["boolValue"])
                        
                        # Update the cell
                        existing_data[row_index][col_index] = value
                
                applied_requests += 1
            
            elif "appendCells" in request:
                # Handle appending cells
                rows = request["appendCells"].get("rows", [])
                sheet_id = request["appendCells"].get("sheetId", 0)
                
                # Simply append rows to the end
                for row_data in rows:
                    cells = row_data.get("values", [])
                    new_row = []
                    
                    for cell in cells:
                        value = ""
                        if "userEnteredValue" in cell:
                            if "stringValue" in cell["userEnteredValue"]:
                                value = cell["userEnteredValue"]["stringValue"]
                            elif "numberValue" in cell["userEnteredValue"]:
                                value = str(cell["userEnteredValue"]["numberValue"])
                            elif "boolValue" in cell["userEnteredValue"]:
                                value = str(cell["userEnteredValue"]["boolValue"])
                        
                        new_row.append(value)
                    
                    existing_data.append(new_row)
                
                applied_requests += 1
        
        # Write back the updated data
        with open(sheet_path, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(existing_data)
        
        return jsonify({
            "success": True,
            "appliedRequests": applied_requests,
            "totalRequests": len(requests)
        })
    except Exception as e:
        return jsonify({"error": f"Error batch updating sheet: {str(e)}"}), 500

@app.route("/sheets/list-tabs", methods=["GET"])
def list_spreadsheet_sheets():
    """List tabs in a spreadsheet (single tab for CSV implementation)"""
    spreadsheet_id = request.args.get("spreadsheet_id")
    if not spreadsheet_id:
        return jsonify({"error": "spreadsheet_id parameter is required"}), 400
    
    # Find the sheet file
    sheet_path = find_sheet_by_id(spreadsheet_id)
    if not sheet_path:
        return jsonify({"error": "Spreadsheet not found"}), 404
    
    try:
        # Get sheet name from filename
        sheet_name = os.path.splitext(os.path.basename(sheet_path))[0]
        
        # For CSV, we only have one sheet
        return jsonify([
            {
                "title": sheet_name,
                "sheetId": 0,
                "index": 0,
                "sheetType": "GRID",
                "hidden": False,
                "gridProperties": {"rowCount": 1000, "columnCount": 26}
            }
        ])
    except Exception as e:
        return jsonify({"error": f"Error listing sheets: {str(e)}"}), 500

@app.route("/sheets/add-tab", methods=["POST"])
def add_spreadsheet_sheet():
    """Add a new tab to a spreadsheet (creates a new CSV file)"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    spreadsheet_id = data.get("spreadsheet_id")
    title = data.get("title")
    
    if not spreadsheet_id or not title:
        return jsonify({"error": "spreadsheet_id and title are required"}), 400
    
    # Find the original sheet's metadata
    original_sheet_path = find_sheet_by_id(spreadsheet_id)
    if not original_sheet_path:
        return jsonify({"error": "Spreadsheet not found"}), 404
    
    try:
        # Create safe filename from title
        safe_title = re.sub(r'[^\w\-_\.]', '_', title)
        
        # Create a new CSV file for this tab
        dir_path = os.path.dirname(original_sheet_path)
        original_name = os.path.splitext(os.path.basename(original_sheet_path))[0]
        new_sheet_path = os.path.join(dir_path, f"{original_name}_{safe_title}.csv")
        
        # Create an empty CSV file
        with open(new_sheet_path, "w", newline='', encoding="utf-8") as f:
            pass
        
        # Generate a new ID for this tab
        sheet_id = int(datetime.datetime.now().timestamp())
        
        # Create metadata file for this tab
        meta_path = os.path.join(dir_path, f"{original_name}_{safe_title}.meta")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "spreadsheet_id": spreadsheet_id,
                "sheet_id": sheet_id,
                "title": title,
                "parent_sheet": original_sheet_path,
                "created_at": datetime.datetime.now().isoformat()
            }, f, ensure_ascii=False)
        
        return jsonify({
            "title": title,
            "sheetId": sheet_id
        })
    except Exception as e:
        return jsonify({"error": f"Error adding tab: {str(e)}"}), 500

@app.route("/sheets/delete-tab", methods=["DELETE"])
def delete_spreadsheet_sheet():
    """Delete a tab from a spreadsheet"""
    spreadsheet_id = request.args.get("spreadsheet_id")
    sheet_id = request.args.get("sheet_id")
    
    if not spreadsheet_id or not sheet_id:
        return jsonify({"error": "spreadsheet_id and sheet_id parameters are required"}), 400
    
    try:
        # Convert sheet_id to integer if it's not already
        try:
            sheet_id = int(sheet_id)
        except ValueError:
            return jsonify({"error": "sheet_id must be an integer"}), 400
        
        # Find all sheets with this spreadsheet_id
        sheets = []
        for filename in os.listdir(SHEETS_DIR):
            if filename.endswith(".meta"):
                meta_path = os.path.join(SHEETS_DIR, filename)
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        if meta.get("spreadsheet_id") == spreadsheet_id:
                            sheets.append((meta, filename[:-5]))
                except:
                    continue
        
        # Find the sheet with matching sheet_id
        for meta, filename in sheets:
            if meta.get("sheet_id") == sheet_id:
                # Delete the sheet file
                sheet_path = os.path.join(SHEETS_DIR, filename)
                if os.path.exists(sheet_path):
                    os.remove(sheet_path)
                
                # Delete the metadata file
                meta_path = os.path.join(SHEETS_DIR, filename + ".meta")
                if os.path.exists(meta_path):
                    os.remove(meta_path)
                
                return jsonify({"status": "deleted"})
        
        return jsonify({"error": "Sheet not found"}), 404
    except Exception as e:
        return jsonify({"error": f"Error deleting sheet: {str(e)}"}), 500

@app.route("/sheets/format", methods=["POST"])
def format_sheet_cells():
    """Format cells in a Google Sheet (minimal implementation)"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    spreadsheet_id = data.get("spreadsheet_id")
    sheet_id = data.get("sheet_id")
    range_param = data.get("range")
    formatting = data.get("formatting")
    
    if not spreadsheet_id or not sheet_id or not range_param or not formatting:
        return jsonify({"error": "spreadsheet_id, sheet_id, range, and formatting are required"}), 400
    
    # Find the sheet file
    sheet_path = find_sheet_by_id(spreadsheet_id)
    if not sheet_path:
        return jsonify({"error": "Spreadsheet not found"}), 404
    
    # For our CSV implementation, we don't actually apply formatting
    # but we can store it in a metadata file
    try:
        format_meta_path = sheet_path + ".format"
        
        # Load existing formats
        formats = {}
        if os.path.exists(format_meta_path):
            with open(format_meta_path, "r", encoding="utf-8") as f:
                formats = json.load(f)
        
        # Add this format
        format_key = f"sheet{sheet_id}_{range_param}"
        formats[format_key] = {
            "sheet_id": sheet_id,
            "range": range_param,
            "formatting": formatting,
            "updated_at": datetime.datetime.now().isoformat()
        }
        
        # Save formats
        with open(format_meta_path, "w", encoding="utf-8") as f:
            json.dump(formats, f, ensure_ascii=False)
        
        return jsonify({
            "success": True,
            "range": range_param,
            "sheet_id": sheet_id
        })
    except Exception as e:
        return jsonify({"error": f"Error formatting cells: {str(e)}"}), 500

@app.route("/sheets/create-filter", methods=["POST"])
def create_sheet_filter():
    """Create filter view (minimal implementation)"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    spreadsheet_id = data.get("spreadsheet_id")
    sheet_id = data.get("sheet_id")
    range_param = data.get("range")
    
    if not spreadsheet_id or not sheet_id or not range_param:
        return jsonify({"error": "spreadsheet_id, sheet_id, and range are required"}), 400
    
    # Find the sheet file
    sheet_path = find_sheet_by_id(spreadsheet_id)
    if not sheet_path:
        return jsonify({"error": "Spreadsheet not found"}), 404
    
    try:
        # Store filter info in metadata
        filter_meta_path = sheet_path + ".filters"
        
        # Load existing filters
        filters = {}
        if os.path.exists(filter_meta_path):
            with open(filter_meta_path, "r", encoding="utf-8") as f:
                filters = json.load(f)
        
        # Create a filter ID
        filter_id = str(int(datetime.datetime.now().timestamp()))
        title = data.get("title", f"Filter {filter_id}")
        
        # Add this filter
        filters[filter_id] = {
            "sheet_id": sheet_id,
            "range": range_param,
            "title": title,
            "created_at": datetime.datetime.now().isoformat()
        }
        
        # Save filters
        with open(filter_meta_path, "w", encoding="utf-8") as f:
            json.dump(filters, f, ensure_ascii=False)
        
        return jsonify({
            "success": True,
            "filter_id": filter_id,
            "title": title
        })
    except Exception as e:
        return jsonify({"error": f"Error creating filter: {str(e)}"}), 500

@app.route("/sheets/freeze-panes", methods=["POST"])
def freeze_sheet_panes():
    """Freeze rows or columns"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    spreadsheet_id = data.get("spreadsheet_id")
    sheet_id = data.get("sheet_id")
    
    if not spreadsheet_id or not sheet_id:
        return jsonify({"error": "spreadsheet_id and sheet_id are required"}), 400
    
    rows = data.get("rows", 0)
    columns = data.get("columns", 0)
    
    # Find the sheet file
    sheet_path = find_sheet_by_id(spreadsheet_id)
    if not sheet_path:
        return jsonify({"error": "Spreadsheet not found"}), 404
    
    # Store in metadata
    try:
        format_meta_path = sheet_path + ".format"
        
        # Load existing formats
        formats = {}
        if os.path.exists(format_meta_path):
            with open(format_meta_path, "r", encoding="utf-8") as f:
                formats = json.load(f)
        
        # Add freezing info
        format_key = f"sheet{sheet_id}_freeze"
        formats[format_key] = {
            "sheet_id": sheet_id,
            "frozen_rows": rows,
            "frozen_columns": columns,
            "updated_at": datetime.datetime.now().isoformat()
        }
        
        # Save formats
        with open(format_meta_path, "w", encoding="utf-8") as f:
            json.dump(formats, f, ensure_ascii=False)
        
        return jsonify({
            "success": True,
            "sheet_id": sheet_id,
            "rows": rows,
            "columns": columns
        })
    except Exception as e:
        return jsonify({"error": f"Error freezing panes: {str(e)}"}), 500

@app.route("/sheets/conditional-format", methods=["POST"])
def conditional_format_sheet():
    """Add conditional formatting"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    spreadsheet_id = data.get("spreadsheet_id")
    sheet_id = data.get("sheet_id")
    range_param = data.get("range")
    rule_type = data.get("rule_type")
    
    if not spreadsheet_id or not sheet_id or not range_param or not rule_type:
        return jsonify({"error": "spreadsheet_id, sheet_id, range, and rule_type are required"}), 400
    
    rule_config = data.get("rule_config", {})
    
    # Find the sheet file
    sheet_path = find_sheet_by_id(spreadsheet_id)
    if not sheet_path:
        return jsonify({"error": "Spreadsheet not found"}), 404
    
    # Store conditional formatting
    try:
        format_meta_path = sheet_path + ".format"
        
        # Load existing formats
        formats = {}
        if os.path.exists(format_meta_path):
            with open(format_meta_path, "r", encoding="utf-8") as f:
                formats = json.load(f)
        
        # Create ID for this formatting
        format_id = str(int(datetime.datetime.now().timestamp()))
        
        # Add conditional formatting
        format_key = f"sheet{sheet_id}_cond_{format_id}"
        formats[format_key] = {
            "sheet_id": sheet_id,
            "range": range_param,
            "rule_type": rule_type,
            "rule_config": rule_config,
            "created_at": datetime.datetime.now().isoformat()
        }
        
        # Save formats
        with open(format_meta_path, "w", encoding="utf-8") as f:
            json.dump(formats, f, ensure_ascii=False)
        
        return jsonify({
            "success": True,
            "format_id": format_id,
            "sheet_id": sheet_id
        })
    except Exception as e:
        return jsonify({"error": f"Error creating conditional formatting: {str(e)}"}), 500

@app.route("/sheets/query", methods=["POST"])
def query_sheet():
    """Query a sheet with SQL-like syntax (simplified version)"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    spreadsheet_id = data.get("spreadsheet_id")
    sheet_name = data.get("sheet_name")
    query = data.get("query")
    
    if not spreadsheet_id or not sheet_name or not query:
        return jsonify({"error": "spreadsheet_id, sheet_name, and query are required"}), 400
    
    # Find the sheet file
    sheet_path = find_sheet_by_id(spreadsheet_id)
    if not sheet_path:
        return jsonify({"error": "Spreadsheet not found"}), 404
    
    try:
        # Read the CSV file
        all_rows = []
        with open(sheet_path, "r", newline='', encoding="utf-8") as f:
            reader = csv.reader(f)
            all_rows = list(reader)
        
        if not all_rows:
            return jsonify({"headers": [], "rows": []})
            
        headers = all_rows[0] if all_rows else []
        data_rows = all_rows[1:] if len(all_rows) > 1 else []
        
        # Very simplified query parser that only supports SELECT, WHERE, ORDER BY
        # This is not a full SQL parser but handles basic queries
        query = query.strip().upper()
        
        # Parse SELECT clause
        selected_cols = []
        if query.startswith("SELECT "):
            # Extract columns from query
            from_pos = query.find("FROM")
            if from_pos == -1:
                from_pos = len(query)
                
            select_clause = query[7:from_pos].strip()
            if select_clause == "*":
                selected_cols = list(range(len(headers)))
            else:
                # Parse column names or indices
                for col in select_clause.split(","):
                    col = col.strip()
                    if col in headers:
                        selected_cols.append(headers.index(col))
                    elif col.isdigit():
                        selected_cols.append(int(col) - 1)
        else:
            # Default to all columns
            selected_cols = list(range(len(headers)))
        
        # Parse WHERE clause (very simplified)
        filtered_rows = []
        where_pos = query.find("WHERE")
        if where_pos != -1:
            order_pos = query.find("ORDER BY")
            if order_pos == -1:
                order_pos = len(query)
            
            where_clause = query[where_pos+6:order_pos].strip()
            
            # Only supports simple equality conditions
            for row in data_rows:
                match = True
                conditions = where_clause.split("AND")
                
                for condition in conditions:
                    condition = condition.strip()
                    if "=" in condition:
                        left, right = condition.split("=", 1)
                        left = left.strip()
                        right = right.strip().strip("'\"")
                        
                        # Check if left is a column name
                        col_idx = -1
                        if left in headers:
                            col_idx = headers.index(left)
                        elif left.isdigit():
                            col_idx = int(left) - 1
                        
                        if col_idx >= 0 and col_idx < len(row):
                            if row[col_idx] != right:
                                match = False
                                break
                
                if match:
                    filtered_rows.append(row)
        else:
            filtered_rows = data_rows
        
        # Parse ORDER BY clause (very simplified)
        order_pos = query.find("ORDER BY")
        if order_pos != -1:
            order_clause = query[order_pos+9:].strip()
            order_col = -1
            
            # Only support ordering by a single column
            if order_clause:
                desc = False
                if "DESC" in order_clause:
                    desc = True
                    order_clause = order_clause.replace("DESC", "").strip()
                    
                if order_clause in headers:
                    order_col = headers.index(order_clause)
                elif order_clause.isdigit():
                    order_col = int(order_clause) - 1
                    
                if order_col >= 0:
                    filtered_rows.sort(key=lambda row: row[order_col] if order_col < len(row) else "", reverse=desc)
        
        # Extract result data using selected columns
        result_headers = [headers[i] for i in selected_cols if i < len(headers)]
        result_rows = []
        
        for row in filtered_rows:
            result_row = [row[i] if i < len(row) else "" for i in selected_cols]
            result_rows.append(result_row)
        
        return jsonify({
            "headers": result_headers,
            "rows": result_rows
        })
    except Exception as e:
        return jsonify({"error": f"Error querying sheet: {str(e)}"}), 500

# Google Docs operations - implemented with text files
@app.route("/docs/create", methods=["POST"])
def create_doc():
    """Create a Google Doc (implemented as a text file)"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    title = data.get("title")
    if not title:
        return jsonify({"error": "title is required"}), 400
        
    content = data.get("content", "")
    
    # Generate a unique ID
    document_id = f"doc_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # Create a safe filename from title
    safe_title = re.sub(r'[^\w\-_\.]', '_', title)
    
    # Determine folder path
    folder_path = data.get("folder_path")
    if folder_path:
        target_dir = os.path.normpath(folder_path)
        os.makedirs(target_dir, exist_ok=True)
    else:
        target_dir = DOCS_DIR
        
    file_path = os.path.join(target_dir, f"{safe_title}.txt")
    meta_path = os.path.join(target_dir, f"{safe_title}.meta")
    
    # If file exists, append timestamp
    if os.path.exists(file_path):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = f"{safe_title}_{timestamp}"
        file_path = os.path.join(target_dir, f"{safe_title}.txt")
        meta_path = os.path.join(target_dir, f"{safe_title}.meta")
    
    try:
        # Write content to text file
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content or "")
        
        # Create metadata
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "document_id": document_id,
                "title": title,
                "created_at": datetime.datetime.now().isoformat(),
                "file_path": file_path
            }, f, ensure_ascii=False)
        
        return jsonify({"documentId": document_id, "title": title, "file": file_path})
    except Exception as e:
        return jsonify({"error": f"Error creating document: {str(e)}"}), 500

def find_doc_by_id(document_id):
    """Helper function to find a document file based on ID"""
    # Look for matching ID in metadata files
    for filename in os.listdir(DOCS_DIR):
        if filename.endswith(".meta"):
            meta_path = os.path.join(DOCS_DIR, filename)
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    if meta.get("document_id") == document_id:
                        doc_filename = filename[:-5]  # Remove .meta
                        return os.path.join(DOCS_DIR, doc_filename + ".txt")
            except:
                continue
                
    return None

@app.route("/docs/update", methods=["POST"])
def update_doc():
    """Update a Google Doc (implemented as a text file)"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    document_id = data.get("document_id")
    new_content = data.get("new_content")
    
    if not document_id or new_content is None:
        return jsonify({"error": "document_id and new_content are required"}), 400
    
    # Find the document
    doc_path = find_doc_by_id(document_id)
    if not doc_path:
        return jsonify({"error": "Document not found"}), 404
    
    try:
        # Write new content
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        # Update metadata (last modified)
        meta_path = doc_path[:-4] + ".meta"  # Change .txt to .meta
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                
                meta["updated_at"] = datetime.datetime.now().isoformat()
                
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False)
            except:
                pass
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"Error updating document: {str(e)}"}), 500

@app.route("/docs/read", methods=["GET"])
def read_doc():
    """Read a Google Doc (implemented as a text file)"""
    document_id = request.args.get("document_id")
    if not document_id:
        return jsonify({"error": "document_id parameter is required"}), 400
    
    # Find the document
    doc_path = find_doc_by_id(document_id)
    if not doc_path:
        return jsonify({"error": "Document not found"}), 404
    
    try:
        # Read content
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"error": f"Error reading document: {str(e)}"}), 500

@app.route("/docs/format", methods=["POST"])
def format_doc():
    """Apply formatting to a Google Doc (storing formatting info in metadata)"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    document_id = data.get("document_id")
    requests = data.get("requests")
    
    if not document_id or not requests:
        return jsonify({"error": "document_id and requests are required"}), 400
    
    # Find the document
    doc_path = find_doc_by_id(document_id)
    if not doc_path:
        return jsonify({"error": "Document not found"}), 404
    
    try:
        # Store formatting requests in metadata
        format_meta_path = doc_path + ".format"
        
        # Load existing formats if any
        formats = []
        if os.path.exists(format_meta_path):
            try:
                with open(format_meta_path, "r", encoding="utf-8") as f:
                    formats = json.load(f)
            except:
                formats = []
        
        # Add new formatting requests
        for req in requests:
            req["timestamp"] = datetime.datetime.now().isoformat()
            formats.append(req)
            
        # Save formatting
        with open(format_meta_path, "w", encoding="utf-8") as f:
            json.dump(formats, f, ensure_ascii=False)
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"Error formatting document: {str(e)}"}), 500

@app.route("/docs/insert-image", methods=["POST"])
def insert_doc_image():
    """Insert an image reference into a document"""
    data = request.json
    if not data:
        return jsonify({"error": "Request body is required"}), 400
        
    document_id = data.get("document_id")
    image_url = data.get("image_url")
    index = data.get("index")
    
    if not document_id or not image_url or index is None:
        return jsonify({"error": "document_id, image_url, and index are required"}), 400
    
    width = data.get("width")
    height = data.get("height")
    
    # Find the document
    doc_path = find_doc_by_id(document_id)
    if not doc_path:
        return jsonify({"error": "Document not found"}), 404
    
    try:
        # Read current content
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Get image filename from URL
        image_filename = os.path.basename(image_url)
        
        # Create image placeholder text
        dimensions = ""
        if width and height:
            dimensions = f" (width: {width}, height: {height})"
        
        image_tag = f"[IMAGE: {image_filename}{dimensions}]"
        
        # Insert the image tag at the specified index
        index = min(len(content), max(0, index))
        new_content = content[:index] + image_tag + content[index:]
        
        # Write updated content
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        # Store image reference in metadata
        images_meta_path = doc_path + ".images"
        
        # Load existing image references if any
        images = []
        if os.path.exists(images_meta_path):
            try:
                with open(images_meta_path, "r", encoding="utf-8") as f:
                    images = json.load(f)
            except:
                images = []
        
        # Add new image
        image_id = f"img_{len(images) + 1}"
        images.append({
            "id": image_id,
            "url": image_url,
            "index": index,
            "width": width,
            "height": height,
            "inserted_at": datetime.datetime.now().isoformat()
        })
        
        # Save image references
        with open(images_meta_path, "w", encoding="utf-8") as f:
            json.dump(images, f, ensure_ascii=False)
            
        return jsonify({"success": True, "image_id": image_id})
    except Exception as e:
        return jsonify({"error": f"Error inserting image: {str(e)}"}), 500

# Web operations
@app.route("/web/search", methods=["GET"])
def search_web():
    """Simulate web search using local results"""
    query = request.args.get("query")
    if not query:
        return jsonify({"error": "query parameter is required"}), 400
    
    # Create simulated search results
    results = [
        f"Result 1 for '{query}': This would be the first search result from the web.",
        f"Result 2 for '{query}': Another relevant search result matching your query.",
        f"Result 3 for '{query}': Additional information related to what you're looking for."
    ]
    
    # Log the search query for future reference
    try:
        log_dir = os.path.join(BASE_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        log_path = os.path.join(log_dir, "web_searches.log")
        with open(log_path, "a", encoding="utf-8") as f:
            timestamp = datetime.datetime.now().isoformat()
            f.write(f"{timestamp} - Query: {query}\n")
    except:
        pass  # Fail silently if logging fails
    
    return jsonify({"results": results})

@app.route("/web/scrape", methods=["GET"])
def scrape_url():
    """Simulate web scraping by generating content based on URL"""
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "url parameter is required"}), 400
    
    # Extract domain from URL
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
    except:
        domain = url.split('/')[0] if '/' in url else url
    
    # Generate simulated content based on URL
    content = f"""Content scraped from {url}
    
This is a simulation of content that would be found at {domain}.
The real web scraping functionality would connect to this URL and extract the actual content.

For demonstration purposes, here's some sample content:

# Welcome to {domain}

This is a sample page that represents what content might be found at this URL.
The scraper would normally extract the text content from the HTML of the page.

- Item 1: Sample information
- Item 2: More details
- Item 3: Additional content

Thank you for visiting our simulated page.
"""
    
    # Log the scraping request
    try:
        log_dir = os.path.join(BASE_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        log_path = os.path.join(log_dir, "web_scrapes.log")
        with open(log_path, "a", encoding="utf-8") as f:
            timestamp = datetime.datetime.now().isoformat()
            f.write(f"{timestamp} - URL: {url}\n")
    except:
        pass  # Fail silently if logging fails
    
    return jsonify({"content": content})

# Additional utility functions
@app.route("/drive/get_metadata", methods=["GET"])
def get_metadata():
    """Get metadata about a file or folder"""
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "path parameter is required"}), 400
    
    # Normalize path for security
    path = os.path.normpath(path)
        
    try:
        if not os.path.exists(path):
            return jsonify({"error": f"Path not found: {path}"}), 404
            
        stat_info = os.stat(path)
        result = {
            "path": path,
            "size": stat_info.st_size,
            "modified": datetime.datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
            "created": datetime.datetime.fromtimestamp(stat_info.st_ctime).isoformat(),
            "accessed": datetime.datetime.fromtimestamp(stat_info.st_atime).isoformat(),
            "type": "directory" if os.path.isdir(path) else "file"
        }
        
        if result["type"] == "file":
            # Try to get MIME type for files
            mime_type, _ = mimetypes.guess_type(path)
            result["mime_type"] = mime_type if mime_type else "application/octet-stream"
            
        return jsonify(result)
    except PermissionError:
        return jsonify({"error": f"Permission denied: {path}"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
