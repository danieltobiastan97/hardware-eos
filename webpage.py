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
from datetime import datetime, timezone, timedelta
import ntplib
from pathlib import Path
from sqlalchemy import text

# Import pipeline functions from prompt.py
from prompt import keys_and_prompt_setup, client_setup, process_line
from classes import Helper, Processing

# Import database models
from models import init_database, ProductEOSRepo, parse_date, Base

# Import AI chat backend
from unified_chat import GeminiChatSession

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "change-this-secret-key")

# Get absolute paths for file operations
SCRIPT_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = str(SCRIPT_DIR / 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.after_request
def add_no_cache_headers(response):
    """Disable browser caching for dynamic pages and static assets during active development."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.getenv("APP_ADMIN_PASSWORD", "changeme")
ADMIN_PASSWORD_HASH = os.getenv("APP_ADMIN_PASSWORD_HASH")

# Initialize database connection (persistent)
# Use /app/data path for Docker, fallback to local data/ directory
if os.path.exists('/app/data'):
    db_path = 'sqlite:////app/data/asset_cache.db'
else:
    db_local = SCRIPT_DIR / 'data'
    db_local.mkdir(parents=True, exist_ok=True)
    db_path = f'sqlite:///{db_local / "asset_cache.db"}'

db_engine, db_session = init_database(db_path)
# Ensure all tables are created
Base.metadata.create_all(db_engine)

# HIGH #7 FIX: Verify all required tables exist after creation
print("📋 Verifying database schema...", end=" ")
try:
    with db_engine.connect() as conn:
        inspector_query = text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('product_eos', 'support_tier', 'asset_cache', 'system', 'product_system')"
        )
        result = conn.execute(inspector_query)
        existing_tables = {row[0] for row in result}
        required_tables = {'product_eos', 'support_tier', 'asset_cache', 'system', 'product_system'}
        
        if existing_tables == required_tables:
            print("✓")
        else:
            missing = required_tables - existing_tables
            print(f"⚠ Missing tables: {missing}")
except Exception as e:
    print(f"⚠ Could not verify tables: {e}")

product_repo = ProductEOSRepo(db_session)

# Store the last uploaded lists and AI results cache
# Results are keyed by item name so re-running skips already-processed items
_last_upload = {"hw_list": [], "sw_list": []}
_results_cache = {}   # name -> result dict

# AI chat sessions keyed by Flask session user (one chat session per logged-in user)
_chat_sessions = {}   # session_user -> GeminiChatSession
_chat_session_activity = {}  # session_user -> last_activity_timestamp

# Token limit configuration (1000 tokens per conversation)
CHAT_TOKEN_LIMIT = 1000
CHAT_INACTIVITY_TIMEOUT = 30 * 60  # 30 minutes in seconds

# NTP time caching/config (keeps logs quiet when UDP/123 is blocked in containers)
_ntp_time_cache = {
    "timestamp": None,
    "cached_at": 0.0,
    "last_warned_at": 0.0,
}
_ntp_client = ntplib.NTPClient()
NTP_SERVER = os.getenv("NTP_SERVER", "pool.ntp.org")
NTP_ENABLED = os.getenv("NTP_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
NTP_CACHE_TTL_SECONDS = int(os.getenv("NTP_CACHE_TTL_SECONDS", "300"))
NTP_WARN_INTERVAL_SECONDS = int(os.getenv("NTP_WARN_INTERVAL_SECONDS", "900"))

def get_ntp_time():
    """Get current UTC time from NTP server, or use local time if NTP fails."""
    now_epoch = time.time()

    # Reuse a recent value to avoid hitting NTP for every EOS comparison.
    cached_time = _ntp_time_cache.get("timestamp")
    cached_at = float(_ntp_time_cache.get("cached_at") or 0.0)
    if cached_time is not None and (now_epoch - cached_at) < NTP_CACHE_TTL_SECONDS:
        return cached_time

    if not NTP_ENABLED:
        local_now = datetime.now(tz=timezone.utc)
        _ntp_time_cache["timestamp"] = local_now
        _ntp_time_cache["cached_at"] = now_epoch
        return local_now

    try:
        response = _ntp_client.request(NTP_SERVER, version=3, timeout=2)
        synced_now = datetime.fromtimestamp(response.tx_time, tz=timezone.utc)
        _ntp_time_cache["timestamp"] = synced_now
        _ntp_time_cache["cached_at"] = now_epoch
        return synced_now
    except Exception as e:
        local_now = datetime.now(tz=timezone.utc)
        last_warned_at = float(_ntp_time_cache.get("last_warned_at") or 0.0)
        if (now_epoch - last_warned_at) >= NTP_WARN_INTERVAL_SECONDS:
            print(f"Warning: NTP request failed ({NTP_SERVER}), using local UTC time: {e}")
            _ntp_time_cache["last_warned_at"] = now_epoch
        _ntp_time_cache["timestamp"] = local_now
        _ntp_time_cache["cached_at"] = now_epoch
        return local_now

def get_current_time_utc8():
    """Get current UTC+8 time from NTP."""
    utc_time = get_ntp_time()
    utc8_offset = timedelta(hours=8)
    utc8_time = utc_time + utc8_offset
    return utc8_time.replace(tzinfo=None)


def _is_persistable_iso_date(value):
    """Return True when a value can be stored in the DATE column."""
    try:
        parse_date(value)
        return True
    except (TypeError, ValueError):
        return False


def _normalize_eos_date_for_storage(value):
    """Normalize EOS dates to a persistable ISO date string."""
    eos_date = str(value or '').strip()
    if eos_date.lower() in ('no eos found', 'n/a', 'unknown', 'not found', ''):
        return '2099-12-31'
    if not _is_persistable_iso_date(eos_date):
        return '2099-12-31'
    return eos_date


def _is_hw_sw_classified(value):
    """Return True only for explicit Hardware/Software classifications."""
    text = str(value or '').strip().lower()
    return ('hardware' in text) or ('software' in text)


def _humanize_eos_for_export(value):
    """Convert internal placeholder date into user-friendly export text."""
    if value is None:
        return "No EOS found"
    text = str(value)
    return "No EOS found" if text == "2099-12-31" else text


def _is_eos_passed(eos_date_str):
    """Check if EOS date has passed compared to current NTP time."""
    if not eos_date_str or eos_date_str in ('2099-12-31', 'No EOS found', 'N/A', ''):
        return False
    
    try:
        # Parse the EOS date
        eos_date = parse_date(eos_date_str)
        if not eos_date:
            return False
        
        # Get current time from NTP
        current_time = get_ntp_time()
        
        # Compare: if current date is past EOS date, it has passed
        return current_time.date() > eos_date
    except Exception as e:
        print(f"Warning: Could not parse EOS date '{eos_date_str}': {e}")
        return False


def _humanize_result_payload(result):
    """Convert placeholder EOS dates inside API/UI payloads and add EOS status."""
    if not isinstance(result, dict):
        return result

    normalized = dict(result)
    eos_date_raw = result.get("EOS Date")
    normalized["EOS Date"] = _humanize_eos_for_export(eos_date_raw)
    
    # Add EOS expiration status flag for frontend rendering
    normalized["is_eos_passed"] = _is_eos_passed(eos_date_raw)

    tiers = result.get("Support Tiers")
    if isinstance(tiers, list):
        normalized["Support Tiers"] = [
            {
                "Tier": tier.get("Tier", "") if isinstance(tier, dict) else "",
                "EndDate": _humanize_eos_for_export(tier.get("EndDate")) if isinstance(tier, dict) else "",
            }
            for tier in tiers
        ]

    return normalized


def _attach_systems_from_db(name, payload):
    """Ensure payload carries latest Systems from DB for the given asset name."""
    try:
        from models import ProductEOS
        from sqlalchemy import func

        db_product = db_session.query(ProductEOS).filter(
            func.lower(ProductEOS.name) == str(name).strip().lower()
        ).first()
        if not db_product:
            return payload

        normalized = dict(payload or {})
        normalized['id'] = normalized.get('id') or db_product.id
        normalized['Systems'] = [{'id': s.id, 'name': s.name} for s in db_product.systems]
        return normalized
    except Exception:
        return payload


def _refresh_memory_cache_for_product(product_id):
    """Update in-memory cache entries so Systems stay in sync after tagging."""
    try:
        from models import ProductEOS

        product = db_session.query(ProductEOS).get(product_id)
        if not product:
            return

        systems_payload = [{'id': s.id, 'name': s.name} for s in product.systems]
        normalized_name = (product.name or '').strip().lower()

        for cache_key, cached in list(_results_cache.items()):
            if ':' not in cache_key:
                continue
            _, cache_name = cache_key.split(':', 1)
            if cache_name.strip().lower() != normalized_name:
                continue
            updated = dict(cached or {})
            updated['id'] = updated.get('id') or product.id
            updated['Systems'] = systems_payload
            _results_cache[cache_key] = updated
    except Exception:
        pass


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


@app.route('/system-overview')
@login_required
def system_overview():
    return render_template('system-overview.html', current_user=session.get('user'))

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
        raw_query = data.get('query')
        if raw_query is None:
            return jsonify(_build_upload_payload([], [], 0.0, error='No manual query provided.')), 400
        query = str(raw_query).strip()
        if not query:
            return jsonify(_build_upload_payload([], [], 0.0, error='No manual query provided.')), 400

        # Support semicolon-delimited multiple items
        items = [q.strip() for q in query.split(';') if q.strip()]
        if not items:
            return jsonify(_build_upload_payload([], [], 0.0, error='No manual query provided.')), 400

        # Stage all manual items with an unknown type until the pipeline classifies them.
        hw_list = []
        sw_list = [
            {
                "Name": item,
                "Hardware/Software": "N.A",
                "EOS Date": "N/A",
                "Confidence": 0.0,
            }
            for item in items
        ]

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
        skip_cache = request.args.get("skip_cache", "").lower() in {"1", "true", "yes"}

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

            if not skip_cache:
                # 1. Check database first (persistent cache)
                try:
                    from models import ProductEOS
                    from sqlalchemy import func
                    
                    # Refresh the session to ensure we see recent commits
                    db_session.expire_all()
                    
                    db_product = db_session.query(ProductEOS).filter(
                        func.lower(ProductEOS.name) == name.strip().lower()
                    ).first()

                    if db_product:
                        # Found in database - return cached result
                        result = _attach_systems_from_db(name, _humanize_result_payload(db_product.to_dict()))
                        print(f"[CACHE] Database HIT: {name}")
                        yield sse("item-done", {
                            "name": name, "type": item_type, "index": index,
                            "result": result, "cached": True, "cached_from": "database"
                        })
                        processed += 1
                        continue
                    else:
                        print(f"[CACHE] Database MISS: {name}")
                except Exception as db_check_err:
                    print(f"[ERROR] Database cache check failed for {name}: {db_check_err}")

                # 2. Check in-memory cache (session cache)
                if cache_key in _results_cache:
                    print(f"[CACHE] Memory HIT: {name}")
                    memory_payload = _attach_systems_from_db(name, _humanize_result_payload(_results_cache[cache_key]))
                    yield sse("item-done", {
                        "name": name, "type": item_type, "index": index,
                        "result": memory_payload, "cached": True, "cached_from": "memory"
                    })
                    processed += 1
                    continue

            # 3. Queue for API processing
            print(f"[PROCESSING] Queuing for API: {name}")
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
                            
                            # Debug: Log the API result
                            print(f"[API] Result for {name}:")
                            print(f"  Hardware/Software: {result.get('Hardware/Software', 'N/A')}")
                            print(f"  EOS Date: {result.get('EOS Date', 'N/A')}")
                            
                            # Persist only explicit Hardware/Software classifications.
                            hw_sw_raw = result.get('Hardware/Software', '')
                            eos_date = result.get('EOS Date', '2099-12-31')
                            if not _is_hw_sw_classified(hw_sw_raw):
                                print(f"[DB] SKIPPING unclassified item: {name} (Hardware/Software={hw_sw_raw})")
                                pass
                            # Store in database - use placeholder if date is missing or invalid
                            else:
                                # Determine date to save
                                if eos_date.lower() in ('no eos found', 'n/a', 'unknown', 'not found', ''):
                                    eos_date_to_save = '2099-12-31'  # Placeholder for unknown date
                                    print(f"[DB] Using placeholder date for {name} (API returned: {eos_date})")
                                elif not _is_persistable_iso_date(eos_date):
                                    eos_date_to_save = '2099-12-31'  # Fallback placeholder
                                    print(f"[DB] Invalid date format, using placeholder for {name}")
                                else:
                                    eos_date_to_save = eos_date
                                
                                try:
                                    # Check if product already exists - if so, update instead of insert
                                    from sqlalchemy import func as sql_func
                                    from models import ProductEOS
                                    
                                    # Refresh session to see recently inserted products
                                    db_session.expire_all()
                                    
                                    existing = db_session.query(ProductEOS).filter(
                                        sql_func.lower(ProductEOS.name) == name.strip().lower()
                                    ).first()
                                    
                                    if existing:
                                        # Update existing product
                                        existing.summary = result.get('Summary', '')
                                        existing.hardware_software = result.get('Hardware/Software', item_type)
                                        existing.support_model = result.get('Support Model', 'Unknown')
                                        existing.eos_date = parse_date(eos_date_to_save)
                                        existing.source_urls = result.get('Source URLs', [])
                                        existing.confidence = result.get('Confidence', 0.0)
                                        # Clear old support tiers
                                        for tier in existing.support_tiers:
                                            db_session.delete(tier)
                                        db_session.commit()
                                        result['id'] = existing.id
                                        print(f"[DB] UPDATED: {existing.name} (ID: {existing.id}) - New EOS Date: {eos_date_to_save}")
                                    else:
                                        # Create new product
                                        ntp_time = get_ntp_time()
                                        product_repo.add_product(
                                            name=name,
                                            summary=result.get('Summary', ''),
                                            hardware_software=result.get('Hardware/Software', item_type),
                                            support_model=result.get('Support Model', 'Unknown'),
                                            eos_date=eos_date_to_save,
                                            source_urls=result.get('Source URLs', []),
                                            confidence=result.get('Confidence', 0.0),
                                            created_timestamp=ntp_time
                                        )
                                        print(f"[DB] INSERTED: {name}")
                                        
                                        # Fetch the newly created product for support tier insertion
                                        from models import ProductEOS
                                        from sqlalchemy import func
                                        existing = db_session.query(ProductEOS).filter(
                                            func.lower(ProductEOS.name) == name.strip().lower()
                                        ).first()
                                        if existing:
                                            result['id'] = existing.id
                                            print(f"[DB] VERIFY: Created product found with ID: {existing.id}")
                                    
                                    # Add support tiers
                                    if existing and result.get('Support Tiers'):
                                        for tier in result['Support Tiers']:
                                            end_date = tier.get('EndDate', '2099-12-31')
                                            if not _is_persistable_iso_date(end_date):
                                                continue
                                            product_repo.add_support_tier(
                                                product_id=existing.id,
                                                tier_name=tier.get('Tier', 'Unknown'),
                                                end_date=end_date
                                            )
                                except Exception as db_err:
                                    db_session.rollback()
                                    # Log clearly so user can see in console
                                    print(f"[ERROR] Failed to store {name} in database: {type(db_err).__name__}: {db_err}")
                            
                            yield sse("item-done", {
                                "name": name, "type": item_type, "index": index, 
                                "result": _attach_systems_from_db(name, _humanize_result_payload(result)), "cached_from": "api"
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


@app.route('/refresh-item', methods=['POST', 'PATCH'])
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

        # POST: retrigger API only (preview), do not persist yet.
        if request.method == 'POST':
            item_name = str(data.get('item_name', '')).strip()
            item_type = str(data.get('item_type', '')).strip()

            if not item_name or item_type not in ('hw', 'sw'):
                return jsonify({"error": "Missing or invalid item_name or item_type"}), 400

            try:
                keys, instruct = keys_and_prompt_setup()
                client, config = client_setup(keys)
            except Exception as e:
                return jsonify({"error": f"Setup failed: {str(e)}"}), 500

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

            db_session.expire_all()
            from sqlalchemy import func as sql_func
            from models import ProductEOS

            existing_product = db_session.query(ProductEOS).filter(
                sql_func.lower(ProductEOS.name) == item_name.strip().lower()
            ).first()

            if existing_product:
                result['id'] = existing_product.id

            cache_key = f"{item_type}:{item_name.strip().lower()}"
            _results_cache[cache_key] = result

            return jsonify({
                "result": _humanize_result_payload(result),
                "old_result": _humanize_result_payload(existing_product.to_dict()) if existing_product else None,
                "asset_id": existing_product.id if existing_product else None,
                "cached_from": "api"
            }), 200

        # PATCH: explicit user-confirmed save to overwrite existing record.
        asset_id = data.get('id')
        result = data.get('result')

        if not isinstance(asset_id, int) or not isinstance(result, dict):
            return jsonify({"error": "Payload must include integer id and result object."}), 400

        required_fields = ['Name', 'Hardware/Software', 'EOS Date']
        missing = [field for field in required_fields if not str(result.get(field, '')).strip()]
        if missing:
            return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

        hw_sw_type = result.get('Hardware/Software', '')
        if not _is_hw_sw_classified(hw_sw_type):
            return jsonify({"error": "Cannot save items that are not classified as Hardware/Software."}), 400

        eos_date_to_save = _normalize_eos_date_for_storage(result.get('EOS Date'))

        from models import ProductEOS
        db_session.expire_all()
        existing_product = db_session.query(ProductEOS).filter(ProductEOS.id == asset_id).first()
        if not existing_product:
            return jsonify({"error": f"Asset id {asset_id} not found."}), 404

        try:
            # Keep record identity stable on overwrite to avoid unique-name collisions.
            existing_product.summary = result.get('Summary', '')
            existing_product.hardware_software = result.get('Hardware/Software', existing_product.hardware_software)
            existing_product.support_model = result.get('Support Model', 'Unknown')
            existing_product.eos_date = parse_date(eos_date_to_save)
            existing_product.source_urls = result.get('Source URLs', [])
            existing_product.confidence = result.get('Confidence', 0.0)

            for tier in existing_product.support_tiers:
                db_session.delete(tier)
            db_session.flush()

            for tier in (result.get('Support Tiers') or []):
                end_date = _normalize_eos_date_for_storage(tier.get('EndDate'))
                product_repo.add_support_tier(
                    product_id=existing_product.id,
                    tier_name=tier.get('Tier', 'Unknown'),
                    end_date=end_date
                )

            db_session.commit()
            updated = _humanize_result_payload(existing_product.to_dict())
            print(f"[DB] PATCH UPDATED: {updated.get('Name')} (ID: {existing_product.id})")
            return jsonify({"success": True, "result": updated, "asset_id": existing_product.id}), 200
        except Exception as db_err:
            db_session.rollback()
            return jsonify({"error": f"Save failed: {str(db_err)}"}), 500

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
            cached_items.append({"name": name, "type": "hw", "index": i, "result": _humanize_result_payload(_results_cache[name])})
    for i, item in enumerate(sw_list):
        name = item if isinstance(item, str) else item.get("Name", str(item))
        if name in _results_cache:
            cached_items.append({"name": name, "type": "sw", "index": i, "result": _humanize_result_payload(_results_cache[name])})
    return jsonify({"cached": cached_items, "total_cached": len(_results_cache)})


@app.route('/cache-debug')
@login_required
def cache_debug():
    """DEBUG: Show raw cache contents and current upload lists."""
    hw_list = _last_upload.get("hw_list", [])
    sw_list = _last_upload.get("sw_list", [])
    
    # Extract names from current lists
    current_names = []
    for item in hw_list:
        name = item if isinstance(item, str) else item.get("Name", str(item))
        current_names.append(name)
    for item in sw_list:
        name = item if isinstance(item, str) else item.get("Name", str(item))
        current_names.append(name)
    
    # Find orphaned cache entries (in cache but not in current lists)
    orphaned = []
    for cache_key in _results_cache.keys():
        if cache_key not in current_names:
            orphaned.append(cache_key)
    
    return jsonify({
        "memory_cache_items": list(_results_cache.keys()),
        "memory_cache_count": len(_results_cache),
        "current_upload_names": current_names,
        "current_upload_count": len(current_names),
        "orphaned_cache_items": orphaned,
        "orphaned_count": len(orphaned)
    })


@app.route('/cache-clear', methods=['POST'])
@login_required
def cache_clear():
    """ADMIN: Clear the in-memory cache."""
    global _results_cache
    count = len(_results_cache)
    _results_cache.clear()
    return jsonify({
        "status": "success",
        "message": f"Cleared {count} items from memory cache",
        "cleared_count": count
    })


@app.route('/export-csv', methods=['GET', 'POST'])
@login_required
def export_csv():
    """Export results cache or database to CSV file and serve it to the user."""
    try:
        results = []

        from models import ProductEOS

        if request.method == 'POST':
            payload = request.get_json(silent=True) or {}
            ids = payload.get('ids', [])
            if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
                return jsonify({"error": "Payload must be JSON with integer ids array."}), 400
            if not ids:
                return jsonify({"error": "Please select at least one row to export."}), 400

            db_products = db_session.query(ProductEOS).filter(ProductEOS.id.in_(ids)).all()
            if not db_products:
                return jsonify({"error": "No matching assets found for selected IDs."}), 404
        else:
            # Backward-compatible fallback behavior for existing GET route usage.
            if _results_cache:
                results = []
                for item in _results_cache.values():
                    normalized = dict(item)
                    normalized["EOS Date"] = _humanize_eos_for_export(item.get("EOS Date"))
                    if isinstance(item.get("Support Tiers"), list):
                        normalized["Support Tiers"] = [
                            {
                                "Tier": tier.get("Tier", ""),
                                "EndDate": _humanize_eos_for_export(tier.get("EndDate")),
                            }
                            for tier in item.get("Support Tiers", [])
                        ]
                    results.append(normalized)
                db_products = []
            else:
                db_products = db_session.query(ProductEOS).all()
                if not db_products:
                    return jsonify({"error": "No results to export. Please run the pipeline first."}), 400

        for product in db_products:
            result = {
                "Name": product.name,
                "Summary": product.summary,
                "Hardware/Software": product.hardware_software,
                "Support Model": product.support_model,
                "EOS Date": _humanize_eos_for_export(product.eos_date.isoformat() if product.eos_date else None),
                "Source URLs": product.source_urls or [],
                "Confidence": product.confidence,
                "Support Tiers": [
                    {
                        "Tier": tier.tier,
                        "EndDate": _humanize_eos_for_export(tier.end_date.isoformat() if tier.end_date else None),
                    }
                    for tier in product.support_tiers
                ]
            }
            results.append(result)
        
        if not results:
            return jsonify({"error": "No results to export. Please run the pipeline first."}), 400
        
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


@app.route('/get-time')
def get_time():
    """Endpoint to get current UTC+8 time from NTP."""
    try:
        current_time = get_current_time_utc8()
        return jsonify({
            "timestamp": current_time.isoformat(),
            "unix_timestamp": current_time.timestamp()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500




# ─────────────────────────────────────────────────────────────────────────────
# AI Chat API routes
# ─────────────────────────────────────────────────────────────────────────────

def _get_chat_session() -> GeminiChatSession:
    """Return the GeminiChatSession for logged-in user, with inactivity timeout.
    
    - Per-user session maintains conversation history within a session
    - Auto-rotates after 30 minutes of inactivity
    - Token limit prevents unbounded growth (1000 tokens per conversation)
    """
    user_key = session.get("user", "anon")
    current_time = time.time()
    
    # Check if session exists and hasn't timed out
    if user_key in _chat_sessions:
        last_activity = _chat_session_activity.get(user_key, current_time)
        time_since_activity = current_time - last_activity
        
        # Auto-rotate if inactive for 30+ minutes
        if time_since_activity > CHAT_INACTIVITY_TIMEOUT:
            print(f"⏱ Session for {user_key} timed out after {time_since_activity:.0f}s")
            del _chat_sessions[user_key]
        else:
            # Update last activity timestamp
            _chat_session_activity[user_key] = current_time
            return _chat_sessions[user_key]
    
    # Create new session (first time or after timeout)
    session_id = f"web_{user_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    new_session = GeminiChatSession(
        session_id=session_id,
        db_session_override=db_session
    )
    _chat_sessions[user_key] = new_session
    _chat_session_activity[user_key] = current_time
    return new_session


@app.route('/chat/send', methods=['POST'])
@login_required
def chat_send():
    """Send a message to the AI and return the response with token tracking."""
    data = request.get_json(silent=True) or {}
    message = str(data.get('message', '')).strip()
    if not message:
        return jsonify({'error': 'No message provided.'}), 400

    try:
        chat = _get_chat_session()
        
        # Check token usage before sending (include the new message cost estimate)
        conv_tokens = chat.get_conversation_tokens()
        new_message_est = len(message) // 4  # Rough token estimate
        projected_tokens = conv_tokens + new_message_est
        
        # Warn if approaching limit (80% = 800 tokens)
        token_limit_warning = projected_tokens > (CHAT_TOKEN_LIMIT * 0.8)
        token_limit_reached = projected_tokens >= CHAT_TOKEN_LIMIT
        
        # Block if limit reached
        if token_limit_reached:
            return jsonify({
                'error': f'Conversation token limit ({CHAT_TOKEN_LIMIT}) reached. Please start a new chat.',
                'conversation_tokens': conv_tokens,
                'token_limit': CHAT_TOKEN_LIMIT,
                'limit_reached': True
            }), 429  # 429 = Too Many Requests
        
        # Send the message
        result = chat.send_message(message, use_rag=True)
        
        if result['success']:
            # Get updated token count after message
            updated_tokens = chat.get_conversation_tokens()
            return jsonify({
                'response': result['response'],
                'session_id': chat.session_id,
                'conversation_tokens': updated_tokens,
                'token_limit': CHAT_TOKEN_LIMIT,
                'token_warning': token_limit_warning,
                'history_length': result.get('history_length', 0)
            })
        else:
            return jsonify({'error': result.get('error', 'AI request failed.')}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/chat/history', methods=['GET'])
@login_required
def chat_history():
    """Return the conversation history for the current user."""
    chat = _get_chat_session()
    return jsonify({'history': chat.get_history(), 'session_id': chat.session_id})


@app.route('/chat/status', methods=['GET'])
@login_required
def chat_status():
    """Return database and chat session status with token usage."""
    try:
        from models import ProductEOS
        count = db_session.query(ProductEOS).count()
        
        # Get current chat session token usage
        chat = _get_chat_session()
        conv_tokens = chat.get_conversation_tokens()
        
        return jsonify({
            'db_ok': True,
            'product_count': count,
            'conversation_tokens': conv_tokens,
            'token_limit': CHAT_TOKEN_LIMIT,
            'token_warning': conv_tokens > (CHAT_TOKEN_LIMIT * 0.8),
            'session_id': chat.session_id
        })
    except Exception as e:
        return jsonify({'db_ok': False, 'product_count': 0, 'error': str(e)})


@app.route('/chat/clear', methods=['POST'])
@login_required
def chat_clear():
    """Clear the current user's chat history and start a fresh session."""
    user_key = session.get("user", "anon")
    if user_key in _chat_sessions:
        del _chat_sessions[user_key]
    if user_key in _chat_session_activity:
        del _chat_session_activity[user_key]
    
    # Create fresh session
    chat = _get_chat_session()
    return jsonify({
        'status': 'cleared',
        'session_id': chat.session_id,
        'conversation_tokens': 0,
        'token_limit': CHAT_TOKEN_LIMIT
    })


# ==================== SYSTEM MANAGEMENT API ROUTES ====================

@app.route('/api/systems', methods=['GET'])
def get_all_systems():
    """Get all systems with asset counts."""
    try:
        systems = product_repo.get_all_systems()
        return jsonify(systems), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch systems: {str(e)}'}), 500


@app.route('/api/systems', methods=['POST'])
def create_system():
    """Create a new system."""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        
        if not name:
            return jsonify({'error': 'System name is required'}), 400
        
        system = product_repo.create_system(name)
        return jsonify({
            'id': system.id,
            'name': system.name,
            'created_date': system.created_date.isoformat(),
            'updated_date': system.updated_date.isoformat(),
            'asset_count': 0
        }), 201
    except Exception as e:
        return jsonify({'error': f'Failed to create system: {str(e)}'}), 500


@app.route('/api/systems/<int:system_id>', methods=['DELETE'])
def delete_system(system_id):
    """Delete a system and its associations."""
    try:
        success = product_repo.delete_system(system_id)
        if not success:
            return jsonify({'error': 'System not found'}), 404
        return jsonify({'message': 'System deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to delete system: {str(e)}'}), 500


@app.route('/api/systems/<int:system_id>', methods=['PUT'])
def update_system(system_id):
    """Rename a system."""
    try:
        data = request.get_json() or {}
        name = str(data.get('name', '')).strip()
        if not name:
            return jsonify({'error': 'System name is required'}), 400

        updated = product_repo.update_system(system_id, name)
        if updated is False:
            return jsonify({'error': 'System not found'}), 404
        if updated is None:
            return jsonify({'error': 'System name already exists or is invalid'}), 409

        return jsonify({
            'id': updated.id,
            'name': updated.name,
            'created_date': updated.created_date.isoformat(),
            'updated_date': updated.updated_date.isoformat()
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to update system: {str(e)}'}), 500


@app.route('/api/products/<int:product_id>/systems', methods=['GET'])
def get_product_systems(product_id):
    """Get all systems associated with a product."""
    try:
        systems = product_repo.get_systems_by_product(product_id)
        return jsonify(systems), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch product systems: {str(e)}'}), 500


@app.route('/api/products/<int:product_id>/systems', methods=['POST'])
def add_system_to_product(product_id):
    """Add a system to a product."""
    try:
        data = request.get_json()
        system_id = data.get('system_id')
        
        if not system_id:
            return jsonify({'error': 'system_id is required'}), 400
        
        success = product_repo.add_system_to_product(product_id, system_id)
        if not success:
            return jsonify({'error': 'Product or system not found'}), 404

        _refresh_memory_cache_for_product(product_id)
        
        return jsonify({'message': 'System added to product successfully'}), 201
    except Exception as e:
        return jsonify({'error': f'Failed to add system to product: {str(e)}'}), 500


@app.route('/api/products/<int:product_id>/systems/<int:system_id>', methods=['DELETE'])
def remove_system_from_product(product_id, system_id):
    """Remove a system from a product."""
    try:
        success = product_repo.remove_system_from_product(product_id, system_id)
        if not success:
            return jsonify({'error': 'Association not found'}), 404

        _refresh_memory_cache_for_product(product_id)
        return jsonify({'message': 'System removed from product successfully'}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to remove system from product: {str(e)}'}), 500


@app.route('/api/products', methods=['GET'])
def filter_products_by_systems():
    """Filter products by systems (OR logic)."""
    try:
        # Get system_ids from query parameter (comma-separated)
        systems_param = request.args.get('systems', '')
        if not systems_param:
            products = product_repo.get_all_products()
        else:
            try:
                system_ids = [int(sid.strip()) for sid in systems_param.split(',')]
                products = product_repo.get_products_by_systems(system_ids)
            except ValueError:
                return jsonify({'error': 'Invalid system IDs format'}), 400
        
        # Convert products to dicts and enrich with NTP-based EOS status flag
        result = [_humanize_result_payload(p.to_dict()) for p in products]
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': f'Failed to filter products: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3000, threaded=True)