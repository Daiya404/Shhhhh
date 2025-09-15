# services/github_backup_service.py
import logging
import shutil
import base64
import aiohttp
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

class GitHubBackupService:
    # FIX: The constructor no longer requires the loop.
    def __init__(self, settings):
        self.logger = logging.getLogger(__name__)
        self.settings = settings
        self.token = getattr(settings, 'GITHUB_TOKEN', None)
        self.repo = getattr(settings, 'GITHUB_REPO', None)
        self.base_url = "https://api.github.com"
        # The loop will be injected by the cog after initialization.
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def is_ready(self) -> bool:
        if not self.token or not self.repo:
            self.logger.warning("GitHub token or repository not configured.")
            return False
        return True

    async def _create_zip_non_blocking(self, archive_name_base: str) -> Path:
        """Runs the blocking zip operation in a separate thread to not freeze the bot."""
        # FIX: Check if the loop was injected before using it.
        if not self.loop:
            raise RuntimeError("Event loop not set in GitHubBackupService. Cog initialization failed.")
        return await self.loop.run_in_executor(
            None, shutil.make_archive, archive_name_base, 'zip', self.settings.DATA_DIR
        )

    async def perform_backup(self) -> Tuple[bool, str]:
        if not self.is_ready():
            return False, "Backup service is not configured."
            
        zip_filepath = None
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
            zip_filename_base = f"tika_backup_{timestamp}"
            
            created_zip_path_str = await self._create_zip_non_blocking(zip_filename_base)
            zip_filepath = Path(created_zip_path_str)
            
            if not zip_filepath.exists():
                raise FileNotFoundError("Failed to create zip archive in executor.")

            with open(zip_filepath, 'rb') as f:
                content = base64.b64encode(f.read()).decode('utf-8')

            file_path_in_repo = f"backups/{zip_filepath.name}"
            url = f"{self.base_url}/repos/{self.repo}/contents/{file_path_in_repo}"
            headers = {'Authorization': f'token {self.token}', 'Accept': 'application/vnd.github.v3+json'}
            data = {'message': f'Automated backup - {timestamp}', 'content': content, 'branch': 'main'}

            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.put(url, json=data) as response:
                    if response.status == 201:
                        self.logger.info(f"Successfully uploaded backup to GitHub: {file_path_in_repo}")
                        return True, "Backup complete. Your data is safe, I suppose."
                    else:
                        error_text = await response.text()
                        self.logger.error(f"GitHub upload failed: {response.status} - {error_text}")
                        return False, f"GitHub upload failed with status {response.status}."

        except Exception as e:
            self.logger.error(f"Backup failed: {e}", exc_info=True)
            return False, "A critical error occurred during the backup process."
        finally:
            if zip_filepath and zip_filepath.exists():
                zip_filepath.unlink()

    async def list_backups(self) -> list:
        if not self.is_ready(): return []
        try:
            url = f"{self.base_url}/repos/{self.repo}/contents/backups"
            headers = {'Authorization': f'token {self.token}', 'Accept': 'application/vnd.github.v3+json'}
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        files = await response.json()
                        return sorted([f for f in files if f['name'].startswith('tika_backup_')], key=lambda x: x['name'], reverse=True)
                    return []
        except Exception as e:
            self.logger.error(f"Failed to list backups: {e}")
            return []

    async def _delete_file(self, file_path: str, sha: str) -> bool:
        url = f"{self.base_url}/repos/{self.repo}/contents/{file_path}"
        headers = {'Authorization': f'token {self.token}', 'Accept': 'application/vnd.github.v3+json'}
        data = {'message': f'Deleting old backup: {file_path}', 'sha': sha, 'branch': 'main'}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.delete(url, json=data) as response:
                    if response.status == 200:
                        self.logger.info(f"Successfully deleted old backup: {file_path}")
                        return True
                    else:
                        self.logger.warning(f"Failed to delete {file_path}: {response.status}")
                        return False
        except Exception:
            return False

    async def delete_old_backups(self, keep_count: int = 5) -> int:
        all_backups = await self.list_backups()
        if len(all_backups) <= keep_count:
            return 0
        
        backups_to_delete = all_backups[keep_count:]
        delete_tasks = [self._delete_file(backup['path'], backup['sha']) for backup in backups_to_delete]
        results = await asyncio.gather(*delete_tasks)
        return sum(1 for res in results if res)