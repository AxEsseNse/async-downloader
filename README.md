# async-downloader
Async downloader of Gitea repositories

## Содержание
- [Инструкция по установке](#инструкция-по-установке)
- [Запуск](#запуск)
- [Тестирование](#тестирование)
- [Проверка линтером](#проверка-линтером)

## Инструкция по установке

1. Откройте терминал.
2. Создайте папку для проекта и перейдите в неё:

    ```sh
    mkdir komkad-test-sinitskiy
    cd komkad-test-sinitskiy
    ```

3. Скачайте репозиторий:

    ```sh
    git clone https://github.com/AxEsseNse/async-downloader.git
    cd async-downloader
    ```

4. Создайте виртуальное окружение:

    ```sh
    python -m venv venv
    ```

5. Активируйте виртуальное окружение:

    ```sh
    .\.venv\Scripts\Activate.ps1  # для Windows PowerShell
    source venv/bin/activate  # для Unix
    ```

6. Установите зависимости:

    ```sh
    pip install -r requirements.txt
    ```

## Запуск

1. Запуск скрипта.

    ```sh
    python main.py
    ```

## Тестирование

1. Запуск тестов.

    ```sh
    pytest
    ```

2. Оценка покрытия тестами. Последняя команда создает html для наглядности

    ```sh
    coverage run -m pytest
    coverage report
    coverage html
    ```

## Проверка линтером

1. Проверка wemake-python-styleguide

    ```sh
    flake8 .\main.py
    flake8 .\tests\test_main.py
    ```
