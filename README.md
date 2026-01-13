# Job Tracker

An Automatic1111 Stable Diffusion WebUI extension that tracks all image generations made through the API by assigning unique 8-character alphanumeric IDs to each job.

**Auto-cleanup**: Jobs and images are automatically purged every 6 hours based on your retention settings.

## Features

- **Job Tracking**: Automatically assigns unique IDs to API requests (`/sdapi/v1/txt2img` and `/sdapi/v1/img2img`)
- **Connection Loss Recovery**: Job ID is sent via HTTP header `X-Job-ID` before generation starts, allowing image recovery even if connection is interrupted
- **Job Retrieval**: Retrieve images later using the job ID via `/sdapi/v1/job/{id}`
- **Auto-cleanup**: Configurable retention period (30/7/3/1 days or off) with automatic purge every 6 hours
- **Secure**: Uses A1111's native API authentication (`--api-auth`)

## Installation

1. Navigate to your A1111 extensions folder:

   ```
   cd stable-diffusion-webui/extensions
   ```

2. Clone or copy this extension:

   ```
   git clone <repository-url> ajt-sd-webui
   ```

3. Restart A1111

## Usage

### Enable Tracking

1. Go to the "Job Tracker" tab in A1111
2. Check "Enable Tracking"
3. Configure retention period if desired

### API Authentication

This extension uses A1111's native API authentication. Configure it when launching A1111:

```
python launch.py --api --api-auth username:password
```

### Environment Variables

You can configure the Job Tracker via environment variables (useful for headless/API-only mode):

| Variable            | Values                        | Description                    |
| ------------------- | ----------------------------- | ------------------------------ |
| `TRACKER_ENABLED`   | `1`, `true`, `yes`, `on`      | Enable job tracking on startup |
| `TRACKER_RETENTION` | Any number (e.g., 7, 30, 365) | Set retention period in days   |

**Examples:**

```bash
# Linux/Mac - webui-user.sh
export TRACKER_ENABLED=1
export TRACKER_RETENTION=30
export COMMANDLINE_ARGS="--port 3000 --api --nowebui --listen"

# Windows - webui-user.bat
set TRACKER_ENABLED=1
set TRACKER_RETENTION=30
set COMMANDLINE_ARGS=--port 3000 --api --nowebui --listen

# Docker/RunPod
TRACKER_ENABLED=1 TRACKER_RETENTION=30 python launch.py --api --nowebui
```

**Priority:** Environment variables override `config.json` settings.

### Making API Requests

When tracking is enabled, all API requests to `/sdapi/v1/txt2img` and `/sdapi/v1/img2img` will:

1. Receive a `X-Job-ID` header in the response immediately
2. Be logged in the tracking table
3. Have their images stored with the job ID

### Retrieving Jobs

**Get a specific job:**

```
GET /sdapi/v1/job/{job_id}
```

Response:

```json
{
  "id": "A3f9K2xY",
  "prompt": "beautiful landscape...",
  "status": "Completed",
  "timestamp": 1736712000,
  "images": [
    "base64_encoded_png_1...",
    "base64_encoded_png_2...",
    "base64_encoded_png_3..."
  ]
}
```

**Note:** The `images` array contains all images generated in a single batch (e.g., if `batch_size=4`, you'll get 4 images).

**List jobs:**

```
GET /sdapi/v1/jobs?ip=192.168.1.100&status=completed&limit=50
```

### Connection Loss Recovery

If your connection is interrupted during generation:

1. The `X-Job-ID` header is sent BEFORE generation starts
2. Your client should capture this header immediately
3. Use `GET /sdapi/v1/job/{id}` to retrieve the image once generation completes

## Configuration

### UI Options

- **Enable Tracking**: Toggle API request tracking
- **Retention**: Auto-delete jobs older than 30/7/3/1 days (or Off) - automatic cleanup runs every 6 hours
- **Purge Now**: Manually trigger cleanup based on retention setting

### Files

- `config.json`: Extension settings
- `jobs.json`: Job metadata storage
- `images/`: Tracked images storage

## API Endpoints

| Endpoint             | Method | Description                     |
| -------------------- | ------ | ------------------------------- |
| `/sdapi/v1/job/{id}` | GET    | Get job details and image by ID |
| `/sdapi/v1/jobs`     | GET    | List jobs with optional filters |

### Query Parameters for `/sdapi/v1/jobs`

- `ip`: Filter by client IP
- `status`: Filter by status (Pending, Processing, Completed, Failed)
- `after`: Filter jobs after timestamp
- `limit`: Maximum number of results (default: 50)

## Job Status Values

- `Pending`: Job created, waiting to process
- `Processing`: Image generation in progress
- `Completed`: Image generated successfully
- `Failed`: Generation failed

## Response Headers

All tracked API requests include:

```
X-Job-ID: A3f9K2xY
```

## Security

- All endpoints require API authentication when configured via `--api-auth`
- Job IDs are 8 characters (A-Z, a-z, 0-9) with collision detection
- Jobs are only accessible with valid API credentials

## Requirements

- Automatic1111 Stable Diffusion WebUI
- Python 3.8+
- No external dependencies (uses Python standard library)

## License

MIT License
