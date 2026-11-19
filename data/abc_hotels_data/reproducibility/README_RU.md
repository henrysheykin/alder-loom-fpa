# Проверка и воспроизводимость

Python3.11+, standard library. Никаких реальных аккаунтов/API/секретов.

Из корня распакованного juniper_quay_data:

```
python reproducibility/verify_dataset.py .
python reproducibility/test_core.py
```

Verifier не импортирует генератор, source data читает с диска; выводит exit0 только при0 failures и пересоздаёт validation report/controls. Во время проверки не меняйте source CSV. Полный прогон может занять несколько минут.

Для новой сборки источников: `python reproducibility/build_dataset.py`. Default destination — соседняя папка juniper_quay_rebuilt. Для собственного destination задайте task-specific environment variable JQ_OUTPUT_DIR; all original sources deterministic seed20261119. Генератор не удаляет неизвестные stale files: для изменённого сценария используйте новую пустую destination. Затем запустите verifier с путём к новой папке. Rebuilding sources alone не создаёт ZIP/docs; write_deliverable_docs.py после verifier использует тот же JQ_OUTPUT_DIR.

test_core.py проверяет half-up cents, allocation conservation, checkout-exclusive cutoff и rejection unbalanced journal. mutation_smoke.py принимает путь dataset, создаёт отдельную scratch копию и проверяет, что сохранённый economic mismatch обнаружен независимо от обновлённого manifest. Он не нужен для обычного импорта данных.

Scripts исходно находились в work/ отдельного чата; никаких файлов других чатов они не меняют. Native API/export schemas не гарантируются.
