"""Скрипт асинхронной загрузки файлов из репозитория gitea."""

import asyncio
import hashlib
import logging
import os
import tempfile

import aiofiles
import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format='{asctime} - {levelname} - {message}',
    style='{',
)
logger = logging.getLogger(__name__)


class GiteaAsyncDownloader:
    """Асинхронная загрузка файлов репозитория из gitea."""

    _gitea_api_url = 'https://gitea.radium.group/api/v1'

    def __init__(self, amount_workers: int):
        """
        Инициализирует класс с заданным количеством воркеров для работы.

        :param amount_workers: Количество одновременных воркеров
            для загрузки файлов.
        """
        self.amount_workers: int = amount_workers
        self._workers: list = []
        self._queue: asyncio.Queue = asyncio.Queue(
            maxsize=self.amount_workers * 2,
        )
        self._aiohttp_session: aiohttp.ClientSession | None = None
        self._url_repository: str | None = None
        self._url_file_pattern: str | None = None
        self._file_paths: list[str] | None = None

    async def download_files(
        self,
        repository: str,
        branch: str,
        directory: str,
    ) -> None:
        """
        Основной метод для скачивания файлов из репозитория.

        :param repository: Название репозитория
            (например, 'radium/project-configuration')
        :param branch: Ветка репозитория
            (например, 'master')
        :param directory: Директория, в которую будут сохранены скачанные файлы

        """
        self._url_repository = (
            '{base_url}/repos/{repo}/git/trees/{branch}?recursive=1'
        ).format(
            base_url=self._gitea_api_url,
            repo=repository,
            branch=branch,
        )
        self._url_file_pattern = (
            '{base_url}/repos/{repo}/raw/{branch}/'
        ).format(
            base_url=self._gitea_api_url,
            repo=repository,
            branch=branch,
        )

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60),
        ) as session:
            self._aiohttp_session = session
            await self._fetch_all_file_paths()

            # Запуск фиксированного количества задач (workers)
            for worker_index in range(self.amount_workers):
                worker_name = 'worker-{index}'.format(index=worker_index + 1)
                worker_task = self._start_worker(worker_name, directory)
                self._workers.append(asyncio.create_task(worker_task))

            # Ждем, пока все пути к файлам не попадут в очередь
            await self._enqueue_file_paths()
            # Ждем, пока все задачи в очереди будут выполнены
            await self._queue.join()

            # Остановка задач (workers)
            for _ in range(self.amount_workers):
                self._queue.put_nowait(None)
            await asyncio.gather(*self._workers)
            logger.info('All workers have been stopped.')
            logger.info(
                '{amount} files downloaded'.format(
                    amount=len(self._file_paths),
                ),
            )

    async def _fetch_all_file_paths(self) -> None:
        """
        Получает все пути к файлам в репозитории.

        Сохраняет их в self.file_paths
        """
        try:
            async with self._aiohttp_session.get(
                self._url_repository,
            ) as response:
                response.raise_for_status()
                files_info = await response.json()
                self._file_paths = [
                    file_info['path']
                    for file_info in files_info['tree']
                    if file_info['type'] == 'blob'
                ]
                logger.info(
                    'Amount files to download: {amount}'.format(
                        amount=len(self._file_paths),
                    ),
                )
        except aiohttp.ClientError as error:
            logger.error(
                'Failed to fetch file paths: {error}'.format(
                    error=error,
                ),
            )
            self._file_paths = []

    async def _fetch_file_data(self, url: str) -> bytes | None:
        """
        Получает данные файла по URL.

        :param url: URL файла
        :return: Содержимое файла
        """
        try:
            async with self._aiohttp_session.get(url) as response:
                response.raise_for_status()
                return await response.read()
        except aiohttp.ClientError as error:
            logger.error(
                'Failed to fetch file data from {url}: {error}'.format(
                    url=url,
                    error=error,
                ),
            )
            return None

    async def _save_data_to_file(
        self,
        file_path: str,
        file_data: bytes,
    ) -> None:
        """
        Сохраняет данные в файл.

        :param file_path: Путь к файлу
        :param file_data: Данные для сохранения
        """
        try:
            async with aiofiles.open(file_path, 'wb') as output_file:
                await output_file.write(file_data)
        except OSError as error:
            logger.error(
                'Failed to save file {file_path}: {error}'.format(
                    file_path=file_path,
                    error=error,
                ),
            )

    async def _start_worker(self, name: str, directory: str) -> None:
        """
        Запускает воркер для обработки задач из очереди.

        :param name: Имя воркера
        :param directory: Директория для сохранения файлов
        """
        logger.info(
            '{name} STARTED'.format(
                name=name,
            ),
        )

        while True:
            file_path = await self._queue.get()

            if file_path is None:
                logger.info(
                    '{name} STOPPED'.format(
                        name=name,
                    ),
                )
                break

            file_url = '{url_file_pattern}{file_path}'.format(
                url_file_pattern=self._url_file_pattern,
                file_path=file_path,
            )
            new_file_path = os.path.join(directory, file_path)
            os.makedirs(os.path.dirname(new_file_path), exist_ok=True)

            file_data = await self._fetch_file_data(file_url)
            if file_data:
                await self._save_data_to_file(new_file_path, file_data)

            self._queue.task_done()
            logger.debug(
                '{name} downloaded {file_path}'.format(
                    name=name,
                    file_path=file_path,
                ),
            )

    async def _enqueue_file_paths(self) -> None:
        """Добавляет все пути к файлам в очередь."""
        for file_path in self._file_paths:
            await self._queue.put(file_path)


class AsyncHashSha256Calculator:
    """Асинхронный подсчет хэшей файлов в директории."""

    _chunk_size = 4096

    def __init__(self, amount_workers: int):
        """
        Инициализирует класс с заданным количеством воркеров для работы.

        :param amount_workers: Количество одновременных воркеров
            для подсчета хэшей файлов.
        """
        self.amount_workers: int = amount_workers
        self._workers: list = []
        self._queue: asyncio.Queue = asyncio.Queue(
            maxsize=self.amount_workers * 2,
        )
        self._directory: str | None = None
        self._file_paths: list[str] | None = None
        self._sha256_hashes: dict[str, str] = {}

    async def get_hash_files_in_directory(self, directory):
        """
        Основной метод для подсчета хэшей sha256 файлов.

        :param directory: Директория для подсчета
        """
        self._directory = directory
        await self._fetch_all_file_paths()

        for worker_index in range(self.amount_workers):
            worker_name = 'worker-{index}'.format(index=worker_index + 1)
            worker_task = self._start_worker(worker_name)
            self._workers.append(asyncio.create_task(worker_task))

        # Ждем, пока все пути к файлам не попадут в очередь
        await self._enqueue_file_paths()
        # Ждем, пока все задачи в очереди будут выполнены
        await self._queue.join()

        # Остановка задач (workers)
        for _ in range(self.amount_workers):
            self._queue.put_nowait(None)
        await asyncio.gather(*self._workers)
        logger.info('All workers have been stopped.')
        logger.info(
            '{amount} file hashes calculated'.format(
                amount=len(self._file_paths),
            ),
        )

        return self._sha256_hashes

    async def _fetch_all_file_paths(self) -> None:
        """
        Получает все пути к файлам в директории.

        Сохраняет их в self.file_paths
        """
        self._file_paths = []
        for root, _dirs, files in os.walk(self._directory):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                self._file_paths.append(file_path)
        logger.info(
            'Amount files to calculate: {amount}'.format(
                amount=len(self._file_paths),
            ),
        )

    async def _calculate_sha256(self, file_path):
        sha256 = hashlib.sha256()
        try:
            async with aiofiles.open(file_path, 'rb') as file_obj:
                await self._update_hash_of_file(sha256, file_obj)
        except Exception as error:
            logger.error(
                'Error reading file {file_path}: {error}'.format(
                    file_path=file_path,
                    error=error,
                ),
            )
            return None
        return sha256.hexdigest()

    async def _update_hash_of_file(self, sha256, file_obj):
        while True:
            block = await file_obj.read(self._chunk_size)
            if not block:
                break
            sha256.update(block)
        return sha256.hexdigest()

    async def _start_worker(self, name: str) -> None:
        """
        Запускает воркер для обработки задач из очереди.

        :param name: Имя воркера
        """
        logger.info(
            '{name} STARTED'.format(
                name=name,
            ),
        )

        while True:
            file_path = await self._queue.get()

            if file_path is None:
                logger.info(
                    '{name} STOPPED'.format(
                        name=name,
                    ),
                )
                break

            file_hash = await self._calculate_sha256(file_path)
            if file_hash:
                sub_path = file_path[len(self._directory) + 1:]
                self._sha256_hashes[sub_path] = file_hash

            self._queue.task_done()
            logger.debug(
                '{name} calculated sha256 hash of {file_path}'.format(
                    name=name,
                    file_path=file_path,
                ),
            )

    async def _enqueue_file_paths(self) -> None:
        """Добавляет все пути к файлам в очередь."""
        for file_path in self._file_paths:
            await self._queue.put(file_path)


async def calculate_hash_files(directory):
    """
    Функция запуска подсчета хэшей файлов в директории.

    :param directory: Путь до директории
    """
    hasher = AsyncHashSha256Calculator(amount_workers=3)
    sha256_hashes = await hasher.get_hash_files_in_directory(directory)
    for file_path, file_hash in sha256_hashes.items():
        logger.info(
            '{file_path}: {file_hash}'.format(
                file_path=file_path,
                file_hash=file_hash,
            ),
        )


def create_temp_directory():
    """Функция создания временной директории."""
    temp_dir = tempfile.mkdtemp()
    logger.info('Created temp directory: {directory}'.format(
        directory=temp_dir,
    ))
    return temp_dir


async def main():
    """Функция запуска скрипта."""
    temp_dir = create_temp_directory()

    downloader = GiteaAsyncDownloader(amount_workers=3)

    await downloader.download_files(
        repository='radium/project-configuration',
        branch='master',
        directory=temp_dir,
    )

    await calculate_hash_files(temp_dir)


if __name__ == '__main__':
    asyncio.run(main())
