# services/github_backup_service.py
import logging
import shutil
import base64
import aiohttp
from pathlib import Path
from datetime import datetime

class GitHubBackupService:
    def __init__(self, settings):
        self.logger = logging.getLogger(__name__)
        self.settings = settings
        # Add these to your settings file:
        # GITHUB_TOKEN = "your_personal_access_token" 
        # GITHUB_REPO = "username/backup-repo-name"
        self.token = getattr(settings, 'GITHUB_TOKEN', None)
        self.repo = getattr(settings, 'GITHUB_REPO', None)
        self.base_url = "https://api.github.com"

    def is_ready(self) -> bool:
        if not self.token:
            self.logger.warning("GitHub token not configured")
            return False
        if not self.repo:
            self.logger.warning("GitHub repository not configured")
            return False
        return True

    async def perform_backup(self) -> bool:
        """Create zip backup and upload to GitHub repository"""
        if not self.is_ready():
            return False
            
        zip_filepath = None
        try:
            # Create zip file
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
            zip_filename = f"tika_backup_{timestamp}"
            zip_path_base = Path(f"./{zip_filename}")
            
            shutil.make_archive(str(zip_path_base), 'zip', self.settings.DATA_DIR)
            zip_filepath = Path(f"{zip_filename}.zip")
            
            if not zip_filepath.exists():
                raise FileNotFoundError("Failed to create zip archive")

            # Read and encode file
            with open(zip_filepath, 'rb') as f:
                content = base64.b64encode(f.read()).decode('utf-8')

            # Upload to GitHub
            file_path = f"backups/{zip_filepath.name}"
            url = f"{self.base_url}/repos/{self.repo}/contents/{file_path}"
            
            headers = {
                'Authorization': f'token {self.token}',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            data = {
                'message': f'Automated backup - {timestamp}',
                'content': content,
                'branch': 'main'
            }

            async with aiohttp.ClientSession() as session:
                async with session.put(url, headers=headers, json=data) as response:
                    if response.status == 201:
                        self.logger.info(f"Successfully uploaded backup to GitHub: {file_path}")
                        return True
                    else:
                        error_text = await response.text()
                        self.logger.error(f"GitHub upload failed: {response.status} - {error_text}")
                        return False

        except Exception as e:
            self.logger.error(f"Backup failed: {e}")
            return False
        finally:
            if zip_filepath and zip_filepath.exists():
                zip_filepath.unlink()

    async def list_backups(self) -> list:
        """List all backup files in the repository"""
        if not self.is_ready():
            return []
            
        try:
            url = f"{self.base_url}/repos/{self.repo}/contents/backups"
            headers = {
                'Authorization': f'token {self.token}',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        files = await response.json()
                        return [f for f in files if f['name'].startswith('tika_backup_')]
                    return []
                    
        except Exception as e:
            self.logger.error(f"Failed to list backups: {e}")
            return []