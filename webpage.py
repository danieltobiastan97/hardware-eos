import os
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, redirect, session, url_for, send_file
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
import time
from io import BytesIO

# Import pipeline functions from prompt.py
from prompt import keys_and_prompt_setup, client_setup, process_line
from classes import Helper, Processing

# Import database models
from models import init_database, ProductEOSRepo, parse_date

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "change-this-secret-key")
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.getenv("APP_ADMIN_PASSWORD", "changeme")
ADMIN_PASSWORD_HASH = os.getenv("APP_ADMIN_PASSWORD_HASH")

# Initialize database connection (persistent)
db_engine, db_session = init_database('sqlite:////app/data/asset_cache.db')
product_repo = ProductEOSRepo(db_session)

# Store the last uploaded lists and AI results cache
# Results are keyed by item name so re-running skips already-processed items
_last_upload = {"hw_list": [], "sw_list": []}
_results_cache = {}   # name -> result dict


def _is_authenticated():
    return session.get("user") == ADMIN_USERNAME


def _password_matches(password):
    if ADMIN_PASSWORD_HASH:
        return check_password_hash(ADMIN_PASSWORD_HASH, password)
    return password == ADMIN_PASSWORD


def _unauthorized_response():
    if request.path == "/run-pipeline":
        payload = {"error": "Authentication required."}
        return Response(
            f"event: pipeline-error\ndata: {json.dumps(payload)}\n\n",
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            status=401,
        )
    if request.path in {"/upload", "/upload-manual", "/pipeline-cache"}:
        return jsonify({"error": "Authentication required."}), 401
    return redirect(url_for("login"))


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not _is_authenticated():
            return _unauthorized_response()
        return view_func(*args, **kwargs)

    return wrapped


def _build_upload_payload(hw_list, sw_list, elapsed_time, error=None):
    """Normalize preprocess/manual lists into a consistent upload response."""
    if error:
        return {
            "error": error,
            "hw_data": [],
            "sw_data": [],
            "hw_count": 0,
            "sw_count": 0,
            "elapsed_time": elapsed_time,
        }

    hw_data = []
    if hw_list:
        if isinstance(hw_list[0], dict):
            hw_data = hw_list
        else:
            hw_data = [
                {
                    "Name": str(item),
                    "Hardware/Software": "Hardware",
                    "EOS Date": "N/A",
                    "Confidence": 0.0,
                }
                for item in hw_list
            ]

    sw_data = []
    if sw_list:
        if isinstance(sw_list[0], dict):
            sw_data = sw_list
        else:
            sw_data = [
                {
                    "Name": str(item),
                    "Hardware/Software": "Software",
                    "EOS Date": "N/A",
                    "Confidence": 0.0,
                }
                for item in sw_list
            ]

    return {
        "hw_data": hw_data,
        "sw_data": sw_data,
        "hw_count": len(hw_list),
        "sw_count": len(sw_list),
        "elapsed_time": elapsed_time,
        "error": None,
    }


def _parse_selected_indices(arg_name):
    values = request.args.getlist(arg_name)
    indices = set()
    for value in values:
        try:
            indices.add(int(value))
        except (TypeError, ValueError):
            continue
    return indices


def _parse_name_overrides(type_key):
    """Read edited names from query params like name_hw_0=New Name."""
    prefix = f"name_{type_key}_"
    overrides = {}
    for key, value in request.args.items():
        if not key.startswith(prefix):
            continue
        try:
            index = int(key[len(prefix):])
        except (TypeError, ValueError):
            continue
        if value is None:
            continue
        cleaned = str(value).strip()
        if cleaned:
            overrides[index] = cleaned
    return overrides

@app.route('/login', methods=['GET', 'POST'])
def login():
    if _is_authenticated():
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        username = str(request.form.get('username', '')).strip()
        password = str(request.form.get('password', ''))
        if username == ADMIN_USERNAME and _password_matches(password):
            session.clear()
            session['user'] = ADMIN_USERNAME
            return redirect(url_for('index'))
        error = 'Invalid username or password.'

    return render_template('login.html', error=error, username=ADMIN_USERNAME)


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    return render_template('file-inspector.html', current_user=session.get('user'))

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    file = request.files.get('file')
    if not file:
        return jsonify({"error": "No file received"}), 400

    # Save file
    filename = secure_filename(file.filename)
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(file_path)

    start_time = time.time()
    
    try:
        # Process using the preprocess function from Helper class
        processor = Helper()
        hw_list, sw_list = processor.preprocess(file_path, sheet='Asset List')
        
        elapsed_time = time.time() - start_time
        
        # Cache the raw lists for the pipeline endpoint (preprocess always returns plain strings)
        _last_upload["hw_list"] = hw_list
        _last_upload["sw_list"] = sw_list
        # Clear AI results cache since this is a new file
        _results_cache.clear()

        if not hw_list and not sw_list:
            payload = _build_upload_payload(
                hw_list,
                sw_list,
                elapsed_time,
                error="The Excel file seems to be invalid. Please check your file to ensure that the template is correct.",
            )
            return jsonify(payload), 200

        return jsonify(_build_upload_payload(hw_list, sw_list, elapsed_time)), 200
    
    except Exception as e:
        elapsed_time = time.time() - start_time
        return jsonify({
            "error": f"Processing failed: {str(e)}",
            "hw_data": [],
            "sw_data": [],
            "hw_count": 0,
            "sw_count": 0,
            "elapsed_time": elapsed_time
        }), 500


@app.route('/upload-manual', methods=['POST'])
@login_required
def upload_manual():
    """Accept a single manually entered query from the UI and stage it for pipeline processing."""
    start_time = time.time()
    try:
        data = request.get_json(silent=True) or {}
        query = str(data.get('query', '')).strip()
        if not query:
            return jsonify(_build_upload_payload([], [], 0.0, error='No manual query provided.')), 400

        # Support semicolon-delimited multiple items
        items = [q.strip() for q in query.split(';') if q.strip()]
        if not items:
            return jsonify(_build_upload_payload([], [], 0.0, error='No manual query provided.')), 400

        # Stage all items for pipeline (pipeline classifies HW vs SW per item)
        hw_list = []
        sw_list = items

        _last_upload["hw_list"] = hw_list
        _last_upload["sw_list"] = sw_list
        _results_cache.clear()

        elapsed_time = time.time() - start_time
        return jsonify(_build_upload_payload(hw_list, sw_list, elapsed_time)), 200
    except Exception as e:
        elapsed_time = time.time() - start_time
        return jsonify(_build_upload_payload([], [], elapsed_time, error=f"Manual input failed: {str(e)}")), 500


@app.route('/run-pipeline')
@login_required
def run_pipeline():
    """
    Server-Sent Events endpoint. Streams pipeline progress back to the browser.
    Checks database first for cached results, then calls API for new items.
    Events emitted:
      - item-start   : {"name": str, "type": "hw"|"sw", "index": int}
      - item-done    : {"name": str, "type": "hw"|"sw", "index": int, "result": {...}, "cached_from": "database"|"api"|"memory"}
      - item-error   : {"name": str, "type": "hw"|"sw", "index": int, "error": str}
      - pipeline-done: {"processed": int, "total": int, "elapsed": float}
    """
    def generate():
        def sse(event, data):
            return f"event: {event}\ndata: {json.dumps(data)}\n\n"

        try:
            keys, instruct = keys_and_prompt_setup()
            client, config = client_setup(keys)
        except Exception as e:
            yield sse("pipeline-error", {"error": f"Setup failed: {str(e)}"})
            return

        hw_list = _last_upload.get("hw_list", [])
        sw_list = _last_upload.get("sw_list", [])
        selected_hw = _parse_selected_indices("hw")
        selected_sw = _parse_selected_indices("sw")
        hw_name_overrides = _parse_name_overrides("hw")
        sw_name_overrides = _parse_name_overrides("sw")

        if not hw_list and not sw_list:
            yield sse("pipeline-error", {"error": "No data to process. Please upload a file first."})
            return

        if not selected_hw and not selected_sw:
            yield sse("pipeline-error", {"error": "No items selected. Please select at least one row."})
            return

        pipeline_start = time.time()
        processed = 0

        def process_item(name, item_type, index):
            """Run a single item in its own asyncio event loop (called from a thread)."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(process_line(name, client, config, instruct))
            finally:
                loop.close()

        all_items = (
            [(item, "hw", i) for i, item in enumerate(hw_list) if i in selected_hw] +
            [(item, "sw", i) for i, item in enumerate(sw_list) if i in selected_sw]
        )

        if not all_items:
            yield sse("pipeline-error", {"error": "No valid selected items were found for processing."})
            return

        # ── Check cache sources in priority order: database → memory → API ──
        to_process = []
        for item, item_type, index in all_items:
            original_name = item if isinstance(item, str) else item.get("Name", str(item))
            name = (hw_name_overrides if item_type == "hw" else sw_name_overrides).get(index, original_name)
            cache_key = f"{item_type}:{name.strip().lower()}"

            # 1. Check database first (persistent cache)
            db_product = db_session.query(__import__('models').ProductEOS).filter(
                __import__('sqlalchemy').func.lower(__import__('models').ProductEOS.name) == name.strip().lower()
            ).first()
            
            if db_product:
                # Found in database - return cached result
                result = db_product.to_dict()
                yield sse("item-done", {
                    "name": name, "type": item_type, "index": index,
                    "result": result, "cached": True, "cached_from": "database"
                })
                processed += 1
            # 2. Check in-memory cache (session cache)
            elif cache_key in _results_cache:
                yield sse("item-done", {
                    "name": name, "type": item_type, "index": index,
                    "result": _results_cache[cache_key], "cached": True, "cached_from": "memory"
                })
                processed += 1
            # 3. Queue for API processing
            else:
                yield sse("item-start", {"name": name, "type": item_type, "index": index})
                to_process.append((name, item_type, index, cache_key))

        # ── Process non-cached items concurrently ──────────────────────────
        if to_process:
            max_workers = min(len(to_process), 5)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_meta = {
                    executor.submit(process_item, name, item_type, index): (name, item_type, index, cache_key)
                    for name, item_type, index, cache_key in to_process
                }
                for future in as_completed(future_to_meta):
                    name, item_type, index, cache_key = future_to_meta[future]
                    try:
                        result = future.result()
                        if result is None:
                            yield sse("item-error", {"name": name, "type": item_type, "index": index, "error": "No result returned"})
                        else:
                            processed += 1
                            
                            # Store in both caches (memory and database)
                            _results_cache[cache_key] = result
                            
                            # Store in database for persistence
                            try:
                                product_repo.add_product(
                                    name=name,
                                    summary=result.get('Summary', ''),
                                    hardware_software=result.get('Hardware/Software', item_type),
                                    support_model=result.get('Support Model', 'Unknown'),
                                    eos_date=result.get('EOS Date', '2099-12-31'),
                                    source_urls=result.get('Source URLs', []),
                                    confidence=result.get('Confidence', 0.0)
                                )
                                # Store support tiers if present
                                db_product = db_session.query(__import__('models').ProductEOS).filter(
                                    __import__('sqlalchemy').func.lower(__import__('models').ProductEOS.name) == name.strip().lower()
                                ).first()
                                if db_product and result.get('Support Tiers'):
                                    for tier in result['Support Tiers']:
                                        product_repo.add_support_tier(
                                            product_id=db_product.id,
                                            tier_name=tier.get('Tier', 'Unknown'),
                                            end_date=tier.get('EndDate', '2099-12-31')
                                        )
                            except Exception as db_err:
                                db_session.rollback()
                                # Log but don't fail the pipeline
                                print(f"Warning: Failed to store {name} in database: {db_err}")
                            
                            yield sse("item-done", {
                                "name": name, "type": item_type, "index": index, 
                                "result": result, "cached_from": "api"
                            })
                    except Exception as e:
                        yield sse("item-error", {"name": name, "type": item_type, "index": index, "error": str(e)})

        elapsed = time.time() - pipeline_start
        yield sse("pipeline-done", {
            "processed": processed,
            "total": len(all_items),
            "elapsed": round(elapsed, 2)
        })

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@app.route('/refresh-item', methods=['POST'])
@login_required
def refresh_item():
    """
    Refresh a single item from the API, updating both in-memory and database caches.
    Called when user hovers over a cached icon and clicks refresh button.
    
    Expected JSON payload:
      {
        "item_name": string (the item name to refresh),
        "item_type": "hw" | "sw" (the type of item)
      }
    
    Returns JSON with the fresh result.
    """
    try:
        data = request.get_json(silent=True) or {}
        item_name = str(data.get('item_name', '')).strip()
        item_type = str(data.get('item_type', '')).strip()
        
        if not item_name or item_type not in ('hw', 'sw'):
            return jsonify({"error": "Missing or invalid item_name or item_type"}), 400
        
        # Set up the pipeline
        try:
            keys, instruct = keys_and_prompt_setup()
            client, config = client_setup(keys)
        except Exception as e:
            return jsonify({"error": f"Setup failed: {str(e)}"}), 500
        
        # Process the item fresh from API (bypass cache)
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(process_line(item_name, client, config, instruct))
            finally:
                loop.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        
        if result is None:
            return jsonify({"error": "No result returned from API"}), 500
        
        # Update both caches with the fresh result
        cache_key = f"{item_type}:{item_name.strip().lower()}"
        _results_cache[cache_key] = result
        
        # Update or insert in database
        try:
            from sqlalchemy import func as sql_func
            from models import ProductEOS
            
            # Check if product already exists
            existing_product = db_session.query(ProductEOS).filter(
                sql_func.lower(ProductEOS.name) == item_name.strip().lower()
            ).first()
            
            if existing_product:
                # Update existing product
                existing_product.summary = result.get('Summary', '')
                existing_product.hardware_software = result.get('Hardware/Software', item_type)
                existing_product.support_model = result.get('Support Model', 'Unknown')
                existing_product.eos_date = parse_date(result.get('EOS Date', '2099-12-31'))
                existing_product.source_urls = result.get('Source URLs', [])
                existing_product.confidence = result.get('Confidence', 0.0)
                # Clear old support tiers
                for tier in existing_product.support_tiers:
                    db_session.delete(tier)
                db_session.commit()
            else:
                # Create new product
                product_repo.add_product(
                    name=item_name,
                    summary=result.get('Summary', ''),
                    hardware_software=result.get('Hardware/Software', item_type),
                    support_model=result.get('Support Model', 'Unknown'),
                    eos_date=result.get('EOS Date', '2099-12-31'),
                    source_urls=result.get('Source URLs', []),
                    confidence=result.get('Confidence', 0.0)
                )
                existing_product = db_session.query(ProductEOS).filter(
                    sql_func.lower(ProductEOS.name) == item_name.strip().lower()
                ).first()
            
            # Add support tiers
            if existing_product and result.get('Support Tiers'):
                for tier in result['Support Tiers']:
                    product_repo.add_support_tier(
                        product_id=existing_product.id,
                        tier_name=tier.get('Tier', 'Unknown'),
                        end_date=tier.get('EndDate', '2099-12-31')
                    )
        except Exception as db_err:
            db_session.rollback()
            # Log but don't fail the refresh
            print(f"Warning: Failed to update {item_name} in database: {db_err}")
        
        return jsonify({
            "result": result,
            "cached_from": "api"
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Refresh failed: {str(e)}"}), 500


@app.route('/pipeline-cache')
@login_required
def pipeline_cache():
    """Returns the current in-memory AI results cache so the browser can
    restore row state after a page refresh without re-calling the API."""
    hw_list = _last_upload.get("hw_list", [])
    sw_list = _last_upload.get("sw_list", [])
    cached_items = []
    for i, item in enumerate(hw_list):
        name = item if isinstance(item, str) else item.get("Name", str(item))
        if name in _results_cache:
            cached_items.append({"name": name, "type": "hw", "index": i, "result": _results_cache[name]})
    for i, item in enumerate(sw_list):
        name = item if isinstance(item, str) else item.get("Name", str(item))
        if name in _results_cache:
            cached_items.append({"name": name, "type": "sw", "index": i, "result": _results_cache[name]})
    return jsonify({"cached": cached_items, "total_cached": len(_results_cache)})


@app.route('/export-csv')
@login_required
def export_csv():
    """Export results cache to CSV file and serve it to the user."""
    try:
        if not _results_cache:
            return jsonify({"error": "No results to export. Please run the pipeline first."}), 400
        
        # Convert cache dict to list of results
        results = list(_results_cache.values())
        
        # Use the Processing class to create DataFrame
        df = Processing.export_to_csv(results, filename=None)
        
        if df is None:
            return jsonify({"error": "Failed to process results for export."}), 500
        
        # Create CSV bytes
        csv_buffer = BytesIO()
        df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)
        
        # Return as downloadable file
        return send_file(
            csv_buffer,
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"eos_results_{int(time.time())}.csv"
        )
    except Exception as e:
        return jsonify({"error": f"Export failed: {str(e)}"}), 500




if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3000, threaded=True)