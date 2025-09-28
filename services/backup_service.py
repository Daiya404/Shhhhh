import logging
import shutil
import base64
import aiohttp
import asyncio
from pathlib import Path
from datetime import datetime
from discord.ext import tasks
from typing import Tuple, List, Dict

class BackupService:
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        # CORRECTED: Access the 'backup' section directly from bot.personalities
        self.personality = self.bot.personalities["backup"]

        # Configuration from the bot instance
        self.token = self.bot.secrets.get("github_token")
        self.repo_name = self.bot.secrets.get("github_repo")
        self.data_dir = self.bot.root_dir / "data"
        self.temp_backup_dir = self.bot.root_dir / "temp_backups"
        self.temp_backup_dir.mkdir(exist_ok=True)
        
        self.base_url = "https://api.github.com"
        self.headers = {
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json'
        }

        if self.is_ready():
            self.automatic_backup.start()
        else:
            self.logger.warning("GitHub token/repo not found. Automatic backups are disabled.")

    def is_ready(self) -> bool:
        """Checks if the service has the necessary configuration to run."""
        return bool(self.token and self.repo_name)

    def cog_unload(self):
        """Called by the bot to stop the task loop."""
        self.automatic_backup.cancel()

    @tasks.loop(hours=6)
    async def automatic_backup(self):
        self.logger.info("Starting scheduled data backup...")
        success, message = await self.perform_backup()
        if not success:
            self.logger.error(f"Scheduled backup failed: {message}")

    async def _create_zip_non_blocking(self, archive_name_base: str) -> Path:
        """Runs the blocking zip operation in a separate thread to not freeze the bot."""
        loop = self.bot.loop
        zip_path_str = await loop.run_in_executor(
            None, shutil.make_archive, archive_name_base, 'zip', self.data_dir
        )
        return Path(zip_path_str)

    async def perform_backup(self) -> Tuple[bool, str]:
        """Creates a zip of the data folder and uploads it to GitHub."""
        if not self.is_ready():
            return False, self.personality["service_not_configured"]
            
        zip_filepath = None
        try:
            if not any(self.data_dir.iterdir()):
                self.logger.info("Data directory is empty. Skipping backup.")
                return True, "Data directory is empty, no backup needed."

            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
            zip_filename_base = self.temp_backup_dir / f"tika_backup_{timestamp}"
            
            zip_filepath = await self._create_zip_non_blocking(str(zip_filename_base))
            
            if not zip_filepath or not zip_filepath.exists():
                raise FileNotFoundError("Failed to create zip archive.")

            with open(zip_filepath, 'rb') as f:
                content_bytes = f.read()

            file_path_in_repo = f"backups/{zip_filepath.name}"
            url = f"{self.base_url}/repos/{self.repo_name}/contents/{file_path_in_repo}"
            
            json_data = {
                'message': f'Automated backup - {timestamp}',
                'content': base64.b64encode(content_bytes).decode('utf-8')
            }

            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.put(url, json=json_data) as response:
                    if response.status == 201:
                        self.logger.info(f"Successfully uploaded backup: {file_path_in_repo}")
                        return True, self.personality["backup_complete"]
                    else:
                        error_text = await response.text()
                        self.logger.error(f"GitHub upload failed: {response.status} - {error_text}")
                        return False, self.personality["backup_failed"]

        except Exception as e:
            self.logger.error(f"Backup failed: {e}", exc_info=True)
            return False, self.personality["backup_failed"]
        finally:
            if zip_filepath and zip_filepath.exists():
                zip_filepath.unlink()

    async def list_backups(self) -> List[Dict]:
        # ... (rest of the file is unchanged)
        if not self.is_ready(): return []
        url = f"{self.base_url}/repos/{self.repo_name}/contents/backups"
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        files = await response.json()
                        backups = [f for f in files if f.get('type') == 'file']
                        return sorted(backups, key=lambda x: x['name'], reverse=True)
                    return []
        except Exception as e:
            self.logger.error(f"Failed to list backups: {e}")
            return []

    async def delete_old_backups(self, keep_count: int = 5) -> int:
        all_backups = await self.list_backups()
        if len(all_backups) <= keep_count:
            return 0
        
        backups_to_delete = all_backups[keep_count:]
        delete_tasks = [self._delete_file(backup['path'], backup['sha']) for backup in backups_to_delete]
        results = await asyncio.gather(*delete_tasks)
        return sum(results)

    async def _delete_file(self, file_path: str, sha: str) -> bool:
        url = f"{self.base_url}/repos/{self.repo_name}/contents/{file_path}"
        json_data = {'message': f'Deleting old backup: {file_path}', 'sha': sha}
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.delete(url, json=json_data) as response:
                    if response.status == 200:
                        self.logger.info(f"Successfully deleted old backup: {file_path}")
                        return True
                    self.logger.warning(f"Failed to delete {file_path}: {response.status}")
                    return False
        except Exception:
            return False

    @automatic_backup.before_loop
    async def before_backup_task(self):
        await self.bot.wait_until_ready()