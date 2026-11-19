# Воспроизводимость

Python 3.10+, только стандартная библиотека. Валидатор полностью независим от генератора и его monetary kernel. Все исходные CSV читаются с UTF-8 BOM. CLI arguments являются локальными путями; никакой доступ к реальным Stripe/CRM/bank аккаунтам не требуется.

Проверить существующий пакет из его корня:

    python scripts/validate_dataset.py --root .

Проверить денежное ядро:

    python -m unittest discover -s scripts/reproduction -p "test_*.py" -v

Пересобрать в НОВУЮ пустую папку, например рядом с распакованным пакетом:

    python scripts/reproduction/build_dataset.py --output ../relaynest_recreated
    python scripts/reproduction/metadata_and_docs.py --root ../relaynest_recreated --metadata-only
    python scripts/validate_dataset.py --root ../relaynest_recreated
    python scripts/reproduction/metadata_and_docs.py --root ../relaynest_recreated

Первая команда сохраняет economic source extracts и первичную schema/config; вторая добавляет source manifests/catalogs/relationships; третья перечитывает сохранённые файлы и создаёт validation controls; четвёртая создаёт Russian handoff, examples и scripts.

Seed 20261031; календарные границы и cutoff зафиксированы в коде. Поля источников не содержат абсолютных путей. Пересборка намеренно требует явный --output; непустая папка отвергается без дополнительного --overwrite. Существующий исходный пакет для воспроизведения менять не нужно.

После повторной валидации можно упаковать новую папку, если приложен pack_dataset.py:

    python scripts/reproduction/pack_dataset.py --root ../relaynest_recreated --archives-dir ../relaynest_recreated_archives

ZIP timestamps не используются как доказательство экономического факта; для сверки данных используйте source SHA-256.
