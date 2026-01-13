import json
import os
import time
import random
import string
import threading
import base64
import shutil
from pathlib import Path
from typing import Optional

import gradio as gr
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.requests import Request as StarletteRequest

from modules import script_callbacks, shared

EXTENSION_DIR = Path(__file__).parent.parent
CONFIG_FILE = EXTENSION_DIR / "config.json"
JOBS_FILE = EXTENSION_DIR / "jobs.json"
JOBS_BACKUP_FILE = EXTENSION_DIR / "jobs.json.bak"
JOBS_TEMP_FILE = EXTENSION_DIR / "jobs.json.tmp"
IMAGES_DIR = EXTENSION_DIR / "images"

jobs_lock = threading.Lock()
active_job = {"id": None, "images": []}
cleanup_timer = None

def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {"tracking_enabled": False, "retention_days": 0}
    
    env_enabled = os.environ.get("TRACKER_ENABLED", "").lower()
    if env_enabled in ("1", "true", "yes", "on"):
        config["tracking_enabled"] = True
    elif env_enabled in ("0", "false", "no", "off"):
        config["tracking_enabled"] = False
    
    env_retention = os.environ.get("TRACKER_RETENTION")
    if env_retention is not None:
        try:
            config["retention_days"] = int(env_retention)
        except ValueError:
            pass
    
    return config

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

def load_jobs():
    with jobs_lock:
        try:
            with open(JOBS_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            if JOBS_BACKUP_FILE.exists():
                try:
                    with open(JOBS_BACKUP_FILE, "r") as f:
                        return json.load(f)
                except:
                    pass
            return []

def save_jobs(jobs_data):
    with jobs_lock:
        try:
            with open(JOBS_TEMP_FILE, "w") as f:
                json.dump(jobs_data, f, indent=2)
            if JOBS_FILE.exists():
                shutil.copy(JOBS_FILE, JOBS_BACKUP_FILE)
            JOBS_TEMP_FILE.replace(JOBS_FILE)
        except Exception:
            pass

def generate_job_id():
    existing_ids = {job.get("id") for job in load_jobs()}
    for _ in range(100):
        new_id = "".join(random.choices(string.ascii_uppercase + string.ascii_lowercase + string.digits, k=8))
        if new_id not in existing_ids:
            return new_id
    return "".join(random.choices(string.ascii_uppercase + string.ascii_lowercase + string.digits, k=10))

def add_job(job_id, prompt, ip):
    jobs = load_jobs()
    jobs.append({
        "id": job_id,
        "prompt": prompt,
        "ip": ip,
        "timestamp": int(time.time()),
        "status": "Pending",
        "output_path": None
    })
    save_jobs(jobs)

def update_job_status(job_id, status, output_path=None):
    jobs = load_jobs()
    for job in jobs:
        if job.get("id") == job_id:
            job["status"] = status
            if output_path:
                job["output_path"] = output_path
            break
    save_jobs(jobs)

def get_job_by_id(job_id):
    jobs = load_jobs()
    for job in jobs:
        if job.get("id") == job_id:
            return job
    return None

def cleanup_old_jobs(retention_days):
    if retention_days == 0:
        return 0
    
    current_time = time.time()
    cutoff_time = current_time - (retention_days * 24 * 60 * 60)
    
    jobs = load_jobs()
    jobs_to_keep = []
    deleted_count = 0
    
    for job in jobs:
        if job.get("timestamp", 0) >= cutoff_time:
            jobs_to_keep.append(job)
        else:
            output_path = job.get("output_path")
            if output_path:
                try:
                    path = Path(output_path)
                    if path.exists():
                        path.unlink()
                except:
                    pass
            deleted_count += 1
    
    save_jobs(jobs_to_keep)
    return deleted_count

def get_recent_jobs(limit=10):
    jobs = load_jobs()
    sorted_jobs = sorted(jobs, key=lambda x: x.get("timestamp", 0), reverse=True)
    return sorted_jobs[:limit]

def get_client_ip(request: Request):
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def on_image_saved(params):
    try:
        if active_job["id"] and params.filename:
            active_job["images"].append(params.filename)
    except:
        pass

script_callbacks.on_image_saved(on_image_saved)

def setup_api_middleware(app: FastAPI):
    global original_txt2img_handler, original_img2img_handler
    
    IMAGES_DIR.mkdir(exist_ok=True)
    
    for route in app.routes:
        if hasattr(route, "path"):
            if route.path == "/sdapi/v1/txt2img":
                original_txt2img_handler = route.endpoint
            elif route.path == "/sdapi/v1/img2img":
                original_img2img_handler = route.endpoint
    
    @app.middleware("http")
    async def track_api_requests(request: Request, call_next):
        config = load_config()
        
        if not config.get("tracking_enabled", False):
            return await call_next(request)
        
        path = request.url.path
        
        if path not in ["/sdapi/v1/txt2img", "/sdapi/v1/img2img"]:
            return await call_next(request)
        
        try:
            body = await request.body()
            body_json = json.loads(body) if body else {}
            prompt = body_json.get("prompt", "")
            
            body_json["save_images"] = True
            body = json.dumps(body_json).encode()
        except:
            body = b""
            prompt = ""
        
        job_id = generate_job_id()
        client_ip = get_client_ip(request)
        
        add_job(job_id, prompt, client_ip)
        
        active_job["id"] = job_id
        active_job["images"] = []
        
        update_job_status(job_id, "Processing")
        
        async def receive():
            return {"type": "http.request", "body": body}
        
        new_request = Request(request.scope, receive, request._send)
        
        try:
            response = await call_next(new_request)
            
            if response.status_code == 200:
                response_body = b""
                async for chunk in response.body_iterator:
                    response_body += chunk
                
                if active_job["images"]:
                    update_job_status(job_id, "Completed", active_job["images"][0])
                else:
                    update_job_status(job_id, "Completed")
                
                active_job["id"] = None
                active_job["images"] = []
                
                new_headers = dict(response.headers)
                new_headers["X-Job-ID"] = job_id
                
                return Response(
                    content=response_body,
                    status_code=response.status_code,
                    headers=new_headers,
                    media_type=response.media_type
                )
            else:
                update_job_status(job_id, "Failed")
                active_job["id"] = None
                active_job["images"] = []
                response.headers["X-Job-ID"] = job_id
                return response
                
        except Exception as e:
            update_job_status(job_id, "Failed")
            active_job["id"] = None
            active_job["images"] = []
            raise e
    
    @app.get("/sdapi/v1/job/{job_id}")
    async def get_job(job_id: str):
        job = get_job_by_id(job_id)
        
        if not job:
            return JSONResponse(
                status_code=404,
                content={"error": "Job not found"}
            )
        
        result = {
            "id": job.get("id"),
            "prompt": job.get("prompt"),
            "status": job.get("status"),
            "timestamp": job.get("timestamp"),
            "image": None
        }
        
        if job.get("status") == "Completed" and job.get("output_path"):
            try:
                image_path = Path(job["output_path"])
                if image_path.exists():
                    with open(image_path, "rb") as f:
                        result["image"] = base64.b64encode(f.read()).decode("utf-8")
            except:
                pass
        
        return JSONResponse(content=result)
    
    @app.get("/sdapi/v1/jobs")
    async def list_jobs(ip: Optional[str] = None, status: Optional[str] = None, after: Optional[int] = None, limit: int = 50):
        jobs = load_jobs()
        
        if ip:
            jobs = [j for j in jobs if j.get("ip") == ip]
        if status:
            jobs = [j for j in jobs if j.get("status", "").lower() == status.lower()]
        if after:
            jobs = [j for j in jobs if j.get("timestamp", 0) > after]
        
        jobs = sorted(jobs, key=lambda x: x.get("timestamp", 0), reverse=True)[:limit]
        
        return JSONResponse(content=jobs)

def periodic_cleanup():
    global cleanup_timer
    config = load_config()
    retention_days = config.get("retention_days", 0)
    if retention_days > 0:
        deleted = cleanup_old_jobs(retention_days)
        if deleted > 0:
            print(f"[Job Tracker] Periodic cleanup: {deleted} old jobs removed")
    
    cleanup_timer = threading.Timer(6 * 60 * 60, periodic_cleanup)
    cleanup_timer.daemon = True
    cleanup_timer.start()

def on_app_started(demo: gr.Blocks, app: FastAPI):
    global cleanup_timer
    setup_api_middleware(app)
    
    IMAGES_DIR.mkdir(exist_ok=True)
    
    config = load_config()
    retention_days = config.get("retention_days", 0)
    if retention_days > 0:
        cleanup_old_jobs(retention_days)
    
    cleanup_timer = threading.Timer(6 * 60 * 60, periodic_cleanup)
    cleanup_timer.daemon = True
    cleanup_timer.start()
    
    print(f"[Job Tracker] Extension loaded - Tracking: {config.get('tracking_enabled', False)}, Retention: {config.get('retention_days', 0)} days")

def create_ui():
    def get_jobs_table():
        jobs = get_recent_jobs(10)
        if not jobs:
            return [["", "", "", ""]]
        table_data = []
        for job in jobs:
            prompt = job.get("prompt", "")
            if len(prompt) > 50:
                prompt = prompt[:47] + "..."
            table_data.append([
                job.get("status", "Unknown"),
                prompt,
                job.get("id", ""),
                job.get("ip", "")
            ])
        return table_data
    
    def save_tracking(tracking_value):
        config = load_config()
        config["tracking_enabled"] = (tracking_value == "Enabled")
        save_config(config)
        return "Saved!"
    
    def get_tracking_radio_value():
        return "Enabled" if load_config().get("tracking_enabled", False) else "Disabled"
    
    def update_retention(retention):
        config = load_config()
        days_map = {"30 days": 30, "7 days": 7, "3 days": 3, "1 day": 1, "Off": 0}
        config["retention_days"] = days_map.get(retention, 0)
        save_config(config)
        return retention
    
    def purge_now(retention):
        days_map = {"30 days": 30, "7 days": 7, "3 days": 3, "1 day": 1, "Off": 0}
        days = days_map.get(retention, 0)
        if days == 0:
            return "Purge status: Retention disabled"
        deleted = cleanup_old_jobs(days)
        return f"Purge status: {deleted} jobs removed"
    
    def refresh_table():
        return get_jobs_table()
    
    def get_current_tracking_state():
        return load_config().get("tracking_enabled", False)
    
    def get_current_retention():
        config = load_config()
        retention_map_reverse = {30: "30 days", 7: "7 days", 3: "3 days", 1: "1 day", 0: "Off"}
        return retention_map_reverse.get(config.get("retention_days", 0), "Off")
    
    with gr.Blocks(analytics_enabled=False) as tracker_interface:
        with gr.Row():
            with gr.Column(scale=3):
                gr.Markdown("### Tracking Logs")
                jobs_table = gr.Dataframe(
                    headers=["Status", "Prompt", "ID", "IP"],
                    datatype=["str", "str", "str", "str"],
                    value=get_jobs_table(),
                    interactive=False,
                    elem_id="tracker_jobs_table"
                )
            
            with gr.Column(scale=1):
                gr.Markdown("### Options")
                
                gr.Markdown("**Tracking:**")
                
                tracking_radio = gr.Radio(
                    choices=["Enabled", "Disabled"],
                    value=get_tracking_radio_value(),
                    label="",
                    elem_id="tracker_enable"
                )
                
                with gr.Row():
                    save_tracking_btn = gr.Button("Save", elem_id="tracker_save_btn", size="sm")
                    tracking_status = gr.Markdown("")
                
                gr.Markdown("**Retention:**")
                
                retention_radio = gr.Radio(
                    choices=["30 days", "7 days", "3 days", "1 day", "Off"],
                    value=get_current_retention(),
                    label="",
                    elem_id="tracker_retention"
                )
                
                purge_btn = gr.Button("Purge Now", elem_id="tracker_purge_btn")
                purge_status = gr.Markdown("Purge status: Ready")
                
                refresh_btn = gr.Button("🔄", elem_id="tracker_table_refresh_btn", size="sm")
        
        save_tracking_btn.click(fn=save_tracking, inputs=[tracking_radio], outputs=[tracking_status], show_progress=False)
        retention_radio.change(fn=update_retention, inputs=[retention_radio], outputs=[retention_radio], show_progress=False)
        purge_btn.click(fn=purge_now, inputs=[retention_radio], outputs=[purge_status], show_progress=False)
        refresh_btn.click(fn=refresh_table, inputs=[], outputs=[jobs_table], show_progress=False)
    
    return [(tracker_interface, "Job Tracker", "job_tracker")]

script_callbacks.on_app_started(on_app_started)
script_callbacks.on_ui_tabs(create_ui)
