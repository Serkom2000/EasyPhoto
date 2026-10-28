# Проверка EasyPhoto на Windows — 28 октября 2026

## Окружение

Windows 11 Pro, NVIDIA GeForce RTX 4060 Laptop GPU (8 ГБ VRAM), 32 ГБ RAM.
ComfyUI Portable 0.43.0, Python 3.12.10, PyTorch 2.14.1+cu126.
Лаунчер установил движок, Python и библиотеки; повторный запуск использует runtime.

## Реальная генерация

Проверки выполнены через API приложения с настоящим ComfyUI и CUDA,
без имитации модели. Время включает опрос результата и переключение весов;
это единичные замеры, а не сравнительный бенчмарк.

| Сценарий | Модель | Размер | Шаги | Время |
| --- | --- | --- | --- | --- |
| Создание фотографии | SDXL Base 1.0 | 1024 × 1024 | 20 | 22,92 с |
| Изменение всего снимка, сила 55% | SDXL | 1024 × 1024 | 20 | 16,81 с |
| Изменение по маске, сила 85% | SDXL | 1024 × 1024 | 20 | 35,70 с |
| Переключение на вторую модель и создание | DreamShaper 8 | 512 × 512 | 20 | 20,58 с |
| Переключение обратно и создание | SDXL | 1024 × 1024 | 4 | 21,19 с |

Все пять заданий завершились с PNG ожидаемого размера и записью в истории.
Попиксельное сравнение подтвердило: область вне маски полностью совпадает с
исходным изображением, внутри маски пиксели изменились. Ошибок нехватки VRAM
в этих сценариях не было.

В браузере проверены доступность обеих моделей, отсутствие скачивания моделей,
автоматическая смена форматов 1024/512, генерация кнопкой, импорт полного файла
DreamShaper (2 132 625 894 байта), переход к редактированию и сообщение о пустой маске.

## Автономный комплект

По решению пользователя скачивание моделей удалено из интерфейса и API.
Модели лежат в models/checkpoints, их размеры и SHA-256 сверены с manifest.json.
Сохранено добавление своих файлов .safetensors. Основной scripts/build-installer.ps1 включает приложение и модели; движок
установщик скачивает отдельно с GitHub. Нативный EXE, оформленное окно установки
и окно первого запуска работают через встроенные средства Windows.
Папка data и пользовательские input/output/temp/user движка исключены из сборки.

15 автоматических тестов проходят. Проверены синтаксис Python, JavaScript и
PowerShell, отказ в доступе с неверным токеном/Host, некорректные параметры,
повторный импорт, ошибки движка, запрет упаковки отсутствующих/повреждённых весов.

## Ограничения

Изменение цвета или объекта по описанию остаётся вероятностным: успешное
выполнение задания не означает точного исполнения каждой команды. Например,
img2img с умеренной силой может сохранить исходный цвет кружки.
Сохранение личности, автоматический перевод, выделение фона и извлечение позы
из обычного фото не реализованы. Реальный ControlNet/OpenPose не проверялся:
в комплекте нет весов ControlNet. Произвольные архитектуры, LoRA и FLUX текущими
workflow не поддерживаются. Другой компьютер и другая видеокарта требуют
отдельной проверки; системный драйвер NVIDIA устанавливается отдельно.

## Последующие изменения установщика и инструкции

Добавлены собственный EXE-хост, интерфейс установки и первый запуск, ярлык на
рабочем столе, повторное использование готового runtime, вывод мегабайт и скорости,
блокировка повторного запуска установки во время работы, защищённое завершение
сервера. Исправлено определение режима Setup независимо от регистра имени EXE.
Инструкция проверена в браузере на широком экране и при ширине 390 px, пример
переносится в студию кнопкой. Ширина документа 375 px при клиентской ширине
375 px: горизонтального переполнения в инструкции не обнаружено.

Ограничение проверки сети: скорость загрузок менялась от нормальной до десятков
КБ/с. Успешная проверка установки на этом компьютере не гарантирует доступность
GitHub у каждого получателя. Контрольная сумма движка проверяется до распаковки.


## 0.2 — model profiles and incremental updates (2026-10-29)

- Regression on RTX 4060 Laptop 8GB: DreamShaper SD1.5 create, SDXL create, SD1.5 image edit returned persisted output PNGs. 512px / 4 steps smoke parameters check execution, not image quality.
- FLUX Dev/Schnell and SD/SDXL Turbo: actual ComfyUI 0.43.0 object_info schema/required inputs/enums/socket types checked using placeholder component names. Their weights are absent, so GPU generation for these families is unverified.
- Native Updater.exe compiled with Windows .NET Framework and opened a responding Russian WPF window. All PowerShell sources parse with Windows PowerShell 5.1. Full updater UI automation was unavailable: node_repl computer-use helper failed to write kernel assets. Remote Windows 10 device was not accessible.
- Headless installed Chrome browser exercised normal model readiness, blocked missing FLUX components, family copy, update POST, 390px overflow and JavaScript errors. Visual reviewer scored the five scoped fixes resolved. New controls preserve the incumbent paper/olive design.
- Updater tests use real temporary files: changed-only/no-op, bad SHA, local edit conflict, injected apply failure rollback, crash recovery, protected weights/settings/outputs, downgrade, forbidden paths/foreign URL, concurrent lock, tampered journal and real Windows junction rejection.
- New HTTP contracts cover selected category import, saved sets and profile persistence; original create/edit/mask/pose/history/auth contracts retained. No full model package rebuilt or downloaded.


Public release verification: 39 tests passed. GitHub reported SHA-256 matches for all 18 release assets (206819 bytes total). Downloaded the public v0.2.0 bootstrap, applied the public latest manifest to a temporary v0.1 source baseline: 13 changed files / 163677 downloaded bytes; second run 0 files / 0 bytes. Model/runtime/settings/profile/output sentinel bytes stayed unchanged. Updated app launched from that installation and returned version 0.2.0 and the new families. This is application/update-path verification, not a full reinstall of the large runtime or a test on the remote Windows10 computer.
