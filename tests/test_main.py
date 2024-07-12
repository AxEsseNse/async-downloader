"""Тесты для асинхронной загрузки файлов и подсчета хэшей."""
import hashlib
import os
import tempfile
from unittest import mock

import aiofiles
import aiohttp
import pytest
from aioresponses import aioresponses

from main import (
    AsyncHashSha256Calculator,
    GiteaAsyncDownloader,
    calculate_hash_files,
    create_temp_directory,
    main,
)

TEST_FILE_NAME = 'test.txt'
TEST_CONTENT = 'test content'
TEST_BYTE_CONTENT = b'test content'
MOCKED_CLIENT_ERROR_TEXT = 'mocked ClientError'
MOCKED_URL = 'http://mocked_url'


@pytest.fixture
def mock_logger():
    with mock.patch('main.logger') as mock_logger:
        yield mock_logger


class TestMain:
    """Содержит тесты функции main и создания директории."""

    @pytest.mark.asyncio
    async def test_main(self):
        """Тестирует функцию main."""
        with mock.patch(
            'main.create_temp_directory',
            return_value='mock_temp_dir',
        ):
            with mock.patch('main.GiteaAsyncDownloader') as mock_downloader:
                downloader_instance = mock_downloader.return_value
                with mock.patch(
                    'main.calculate_hash_files',
                    new_callable=mock.AsyncMock,
                ) as mock_calculate_hash_files:
                    downloader_instance.download_files = mock.AsyncMock(
                        return_value=True,
                    )

                    await main()

                    mock_downloader.assert_called_once_with(amount_workers=3)
                    downloader_instance.download_files.assert_called_once_with(
                        repository='radium/project-configuration',
                        branch='master',
                        directory='mock_temp_dir',
                    )
                    mock_calculate_hash_files.assert_called_once_with(
                        'mock_temp_dir',
                    )

    def test_create_temp_directory(self, mock_logger):
        """
        Тестирует метод create_temp_directory.

        :param mock_logger: Мокнутый логер для проверки логов.
        """
        temp_dir = create_temp_directory()
        assert os.path.exists(temp_dir)
        assert os.path.isdir(temp_dir)

        # Проверка, что лог содержит ожидаемые сообщения
        mock_logger.info.assert_called_once_with(
            'Created temp directory: {directory}'.format(
                directory=temp_dir,
            ),
        )


class TestGiteaAsyncDownloader:
    """Содержит тесты методов класса GiteaAsyncDownloader."""

    @pytest.mark.asyncio
    async def test_download_files(self, mock_logger):  # noqa: WPS210
        """
        Тестирует метод download_files.

        :param mock_logger: Мокнутый логер для проверки логов.
        """
        with aioresponses() as mocked_responses:
            repo_url = (
                'https://gitea.radium.group/api/v1/repos/radium' +
                '/project-configuration/git/trees/master?recursive=1'
            )
            file_url = (
                'https://gitea.radium.group/api/v1/repos/radium' +
                '/project-configuration/raw/master/test.txt'
            )

            mocked_responses.get(repo_url, payload={
                'tree': [
                    {'path': TEST_FILE_NAME, 'type': 'blob'},
                ],
            })
            mocked_responses.get(file_url, body=TEST_BYTE_CONTENT)

            with tempfile.TemporaryDirectory() as temp_dir:
                downloader = GiteaAsyncDownloader(amount_workers=3)

                await downloader.download_files(
                    repository='radium/project-configuration',
                    branch='master',
                    directory=temp_dir,
                )

                downloaded_file_path = os.path.join(temp_dir, TEST_FILE_NAME)
                assert os.path.isfile(downloaded_file_path)

                async with aiofiles.open(
                    downloaded_file_path,
                    'r',
                ) as file_obj:
                    file_data = await file_obj.read()
                    assert file_data == TEST_CONTENT

                # Проверка, что лог содержит ожидаемые сообщения
                mock_logger.info.assert_any_call(
                    'All workers have been stopped.',
                )
                mock_logger.info.assert_any_call(
                    '{amount} files downloaded'.format(
                        amount=1,
                    ),
                )

    @pytest.mark.asyncio
    async def test_fetch_all_file_paths(self, mock_logger):
        """
        Тестирует метод _fetch_all_file_paths.

        :param mock_logger: Мокнутый логер для проверки логов.
        """
        downloader = GiteaAsyncDownloader(amount_workers=1)
        downloader._url_repository = MOCKED_URL  # noqa: WPS437
        downloader._aiohttp_session = aiohttp.ClientSession()  # noqa: WPS437

        # Ожидаемые данные
        mock_response = {
            'other': 'other_data',
            'tree': [
                {'path': 'test_path_1', 'type': 'blob', 'data': 'test_data_1'},
                {'path': 'test_path_2', 'type': 'blob', 'data': 'test_data_2'},
            ],
        }

        async with aiohttp.ClientSession() as session:
            downloader._aiohttp_session = session  # noqa: WPS437

            with aioresponses() as mocked_responses:
                mocked_responses.get(
                    downloader._url_repository,  # noqa: WPS437
                    payload=mock_response,
                )
                await downloader._fetch_all_file_paths()  # noqa: WPS437

                # Проверка, что лог содержит ожидаемые сообщения
                mock_logger.info.assert_called_once_with(
                    'Amount files to download: {amount}'.format(
                        amount=2,
                    ),
                )

        assert downloader._file_paths == [  # noqa: WPS437
            'test_path_1',
            'test_path_2',
        ]

    @pytest.mark.asyncio
    async def test_fetch_all_file_paths_exception(self, mock_logger):
        """
        Тестирует поведение метода _fetch_all_file_paths.

        При ошибке

        :param mock_logger: Мокнутый логер для проверки логов.
        """
        downloader = GiteaAsyncDownloader(amount_workers=1)

        with mock.patch(
            'aiohttp.ClientSession.get',
            side_effect=aiohttp.ClientError(MOCKED_CLIENT_ERROR_TEXT),
        ):
            async with aiohttp.ClientSession() as session:
                downloader._aiohttp_session = session  # noqa: WPS437

                await downloader._fetch_all_file_paths()  # noqa: WPS437
                assert not downloader._file_paths  # noqa: WPS437

                # Проверка, что лог содержит ожидаемые сообщения
                mock_logger.error.assert_called_once_with(
                    'Failed to fetch file paths: {error}'.format(
                        error=MOCKED_CLIENT_ERROR_TEXT,
                    ),
                )

    @pytest.mark.asyncio
    async def test_fetch_file_data(self):
        """Тестирует метод _fetch_file_data."""
        downloader = GiteaAsyncDownloader(amount_workers=1)
        expected_data = b'test_data'

        async with aiohttp.ClientSession() as session:
            downloader._aiohttp_session = session  # noqa: WPS437

            with aioresponses() as mocked_responses:
                mocked_responses.get(MOCKED_URL, body=expected_data)
                file_data = await downloader._fetch_file_data(  # noqa: WPS437
                    MOCKED_URL,
                )

        assert file_data == expected_data

    @pytest.mark.asyncio
    async def test_fetch_file_data_exception(self, mock_logger):
        """
        Тестирует поведение метода _fetch_file_data.

        При ошибке

        :param mock_logger: Мокнутый логер для проверки логов.
        """
        downloader = GiteaAsyncDownloader(amount_workers=1)

        with mock.patch(
            'aiohttp.ClientSession.get',
            side_effect=aiohttp.ClientError(MOCKED_CLIENT_ERROR_TEXT),
        ):
            async with aiohttp.ClientSession() as session:
                downloader._aiohttp_session = session  # noqa: WPS437

                file_data = await downloader._fetch_file_data(  # noqa: WPS437
                    MOCKED_URL,
                )
                assert file_data is None

                # Проверка, что лог содержит ожидаемые сообщения
                mock_logger.error.assert_called_once_with(
                    'Failed to fetch file data from {url}: {error}'.format(
                        url=MOCKED_URL,
                        error=MOCKED_CLIENT_ERROR_TEXT,
                    ),
                )

    @pytest.mark.asyncio
    async def test_save_data_to_file(self):
        """Тестирует метод _save_data_to_file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file_path = os.path.join(temp_dir, TEST_FILE_NAME)

            downloader = GiteaAsyncDownloader(amount_workers=1)

            await downloader._save_data_to_file(  # noqa: WPS437
                test_file_path,
                TEST_BYTE_CONTENT,
            )

            assert os.path.exists(test_file_path)
            assert os.path.isfile(test_file_path)

            # Проверка, что данные в файле соответствуют ожидаемым
            with open(test_file_path, 'rb') as file_obj:
                file_data = file_obj.read()
                assert file_data == TEST_BYTE_CONTENT

    @pytest.mark.asyncio
    async def test_save_data_to_file_exception(self, mock_logger):
        """
        Тестирует поведение метода _save_data_to_file.

        При ошибке

        :param mock_logger: Мокнутый логер для проверки логов.
        """
        downloader = GiteaAsyncDownloader(amount_workers=3)

        with mock.patch(
            'aiofiles.open',
            side_effect=OSError('mocked OSError'),
        ):
            file_path = 'mock_file_path'
            file_data = b'mock_data'
            await downloader._save_data_to_file(  # noqa: WPS437
                file_path,
                file_data,
            )

            # Проверка, что лог содержит ожидаемые сообщения
            mock_logger.error.assert_called_once_with(
                'Failed to save file {file_path}: {error}'.format(
                    file_path=file_path,
                    error='mocked OSError',
                ),
            )


class TestAsyncHashSha256Calculator:
    """Содержит тесты методов класса AsyncHashSha256Calculator."""

    @pytest.mark.asyncio
    async def test_calculate_hash_files(self, mock_logger):
        """
        Тестирует метод calculate_hash_files.

        :param mock_logger: Мокнутый логер для проверки логов.
        """
        expected_hash = hashlib.sha256(TEST_BYTE_CONTENT).hexdigest()
        with mock.patch(
            'main.AsyncHashSha256Calculator.get_hash_files_in_directory',
        ) as mock_get_hash_files:
            mock_get_hash_files.return_value = {TEST_FILE_NAME: expected_hash}

            await calculate_hash_files('test_dir')

            # Проверка, что функция get_hash_files_in_directory вызвана
            mock_get_hash_files.assert_called_once_with('test_dir')

            # Проверка, что лог содержит ожидаемые сообщения
            mock_logger.info.assert_any_call(
                '{file_path}: {file_hash}'.format(
                    file_path=TEST_FILE_NAME,
                    file_hash=expected_hash,
                ),
            )

    @pytest.mark.asyncio
    async def test_get_hash_files_in_directory(  # noqa: WPS210
        self,
        mock_logger,
    ):
        """
        Тестирует метод get_hash_files_in_directory.

        :param mock_logger: Мокнутый логер для проверки логов.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file_path = os.path.join(temp_dir, TEST_FILE_NAME)
            with open(test_file_path, 'w') as file_obj:
                file_obj.write(TEST_CONTENT)

            hasher = AsyncHashSha256Calculator(amount_workers=1)

            sha256_hashes = await hasher.get_hash_files_in_directory(temp_dir)
            expected_hash = hashlib.sha256(TEST_BYTE_CONTENT).hexdigest()

            assert sha256_hashes[TEST_FILE_NAME] == expected_hash

            # Проверка, что лог содержит ожидаемые сообщения
            mock_logger.info.assert_any_call('All workers have been stopped.')
            mock_logger.info.assert_any_call(
                '{amount} file hashes calculated'.format(
                    amount=1,
                ),
            )

    @pytest.mark.asyncio
    async def test_calculate_sha256_exception(self, mock_logger):
        """
        Тестирует поведение метода _calculate_sha256.

        При ошибке

        :param mock_logger: Мокнутый логер для проверки логов.
        """
        calculator = AsyncHashSha256Calculator(amount_workers=3)
        with mock.patch(
            'aiofiles.open',
            side_effect=Exception('mocked exception'),
        ):
            hash_result = await calculator._calculate_sha256(  # noqa: WPS437
                'mock_file_path',
            )
            assert hash_result is None

            # Проверка, что лог содержит ожидаемые сообщения
            mock_logger.error.assert_called_once_with(
                'Error reading file {file_path}: {error}'.format(
                    file_path='mock_file_path',
                    error='mocked exception',
                ),
            )
