# Воспроизводимость и проверка

Python 3.10+; только стандартная библиотека. Основные команды из корня signal_harbor_data:

```
python tools/validate_dataset.py .
python tools/test_validator_mutations.py . <отдельный_временный_каталог>
```

Первый validator читает сохранённые sources и metadata, не импортирует генератор, создаёт validation_report.csv, monthly_control_totals.csv и validation_summary.json. Exit code0=PASS,1=FAIL. Второй создаёт временные копии CSV в указанном scratch, проверяет 8 семантических искажений и записывает mutation report; исходные sources не меняет. Не используйте существующий чужой каталог как scratch.

Для воспроизведения source extracts отдельно, с тем же seed:

```
python tools/run_build.py --output <новая_папка_для_воспроизведения>
python tools/validate_dataset.py <новая_папка_для_воспроизведения>
```

Генератор публикует sources и базовые metadata. Документация, illustrative examples и ZIP уже поставлены в основном пакете; они не создаются командой rebuild. Для сравнения source bytes используйте SHA-256 из исходного metadata/file_manifest.csv. Не запускайте rebuild поверх вашей Claude-модели/изменённых raw sources. Новая пустая папка позволяет сравнить воспроизводимость без перезаписи результатов.
