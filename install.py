import os
from pathlib import Path

extension_dir = Path(__file__).parent

scripts_dir = extension_dir / "scripts"
scripts_dir.mkdir(exist_ok=True)

javascript_dir = extension_dir / "javascript"
javascript_dir.mkdir(exist_ok=True)

config_file = extension_dir / "config.json"
if not config_file.exists():
    config_file.write_text('{"tracking_enabled": false, "retention_days": 0}')

jobs_file = extension_dir / "jobs.json"
if not jobs_file.exists():
    jobs_file.write_text('[]')

images_dir = extension_dir / "images"
images_dir.mkdir(exist_ok=True)
