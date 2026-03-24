import os
import json
import asyncio
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from werkzeug.utils import secure_filename
import time

# Import pipeline functions from prompt.py
from prompt import keys_and_prompt_setup, client_setup, process_line
from classes import Helper, Processing

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Store the last uploaded lists and AI results cache
# Results are keyed by item name so re-running skips already-processed items
_last_upload = {"hw_list": [], "sw_list": []}
_results_cache = {}   # name -> result dict


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

@app.route('/')
def index():
    return render_template('file-inspector.html')

@app.route('/upload', methods=['POST'])
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
        hw_list, sw_list = processor.preprocess(file_path, sheet='Sheet1')
        
        elapsed_time = time.time() - start_time
        
        # Check if both lists are empty
        if not hw_list and not sw_list:
            return jsonify({
                "error": "The Excel file seems to be invalid. Please check your file to ensure that the template is correct.",
                "hw_data": [],
                "sw_data": [],
                "hw_count": 0,
                "sw_count": 0,
                "elapsed_time": elapsed_time
            }), 200
        
        # Convert hardware list to table format
        hw_data = []
        if hw_list:
            if isinstance(hw_list[0], dict):
                hw_data = hw_list
            else:
                hw_data = [{"Name": str(item), "Hardware/Software": "Hardware", "EOS Date": "N/A", "Confidence": 0.0} for item in hw_list]
        
        # Convert software list to table format
        sw_data = []
        if sw_list:
            if isinstance(sw_list[0], dict):
                sw_data = sw_list
            else:
                sw_data = [{"Name": str(item), "Hardware/Software": "Software", "EOS Date": "N/A", "Confidence": 0.0} for item in sw_list]

        # Cache the raw lists for the pipeline endpoint (preprocess always returns plain strings)
        _last_upload["hw_list"] = hw_list
        _last_upload["sw_list"] = sw_list
        # Clear AI results cache since this is a new file
        _results_cache.clear()
        
        return jsonify({
            "hw_data": hw_data,
            "sw_data": sw_data,
            "hw_count": len(hw_list),
            "sw_count": len(sw_list),
            "elapsed_time": elapsed_time,
            "error": None
        }), 200
    
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


@app.route('/run-pipeline')
def run_pipeline():
    """
    Server-Sent Events endpoint. Streams pipeline progress back to the browser.
    Events emitted:
      - item-start   : {"name": str, "type": "hw"|"sw", "index": int}
      - item-done    : {"name": str, "type": "hw"|"sw", "index": int, "result": {...}}
      - item-error   : {"name": str, "type": "hw"|"sw", "index": int, "error": str}
      - pipeline-done: {"hw_count": int, "sw_count": int, "elapsed": float}
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

        async def run_item(item, client, config, instruct):
            return await process_line(item, client, config, instruct)

        def process_item(item, item_type, index):
            """Run a single item synchronously via asyncio."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(run_item(item, client, config, instruct))
                return result
            finally:
                loop.close()

        all_items = (
            [(item, "hw", i) for i, item in enumerate(hw_list) if i in selected_hw] +
            [(item, "sw", i) for i, item in enumerate(sw_list) if i in selected_sw]
        )

        if not all_items:
            yield sse("pipeline-error", {"error": "No valid selected items were found for processing."})
            return

        for item, item_type, index in all_items:
            original_name = item if isinstance(item, str) else item.get("Name", str(item))
            if item_type == "hw":
                name = hw_name_overrides.get(index, original_name)
            else:
                name = sw_name_overrides.get(index, original_name)

            cache_key = f"{item_type}:{name.strip().lower()}"

            # ── Cache hit: skip the API call entirely ──────────────────────
            if cache_key in _results_cache:
                yield sse("item-done", {
                    "name": name, "type": item_type, "index": index,
                    "result": _results_cache[cache_key], "cached": True
                })
                processed += 1
                continue

            # ── Cache miss: call the API ───────────────────────────────────
            yield sse("item-start", {"name": name, "type": item_type, "index": index})

            try:
                result = process_item(name, item_type, index)
                if result is None:
                    yield sse("item-error", {"name": name, "type": item_type, "index": index, "error": "No result returned"})
                else:
                    processed += 1
                    _results_cache[cache_key] = result     # store for next run
                    yield sse("item-done", {"name": name, "type": item_type, "index": index, "result": result})
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


@app.route('/pipeline-cache')
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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3000, threaded=True)