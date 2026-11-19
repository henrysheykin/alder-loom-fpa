# Воспроизведение и независимая проверка

Python 3.11+; только стандартная библиотека, установка зависимостей не нужна. Генерация проверена в Python 3.13.9.

Проверить распакованные источники из любого каталога:

```powershell
python "PATH/cedar_bend_auto_data/reproducibility/verify_dataset.py" --root "PATH/cedar_bend_auto_data"
```

Сгенерировать отдельную копию, не перезаписывая поставку:

```powershell
python "PATH/cedar_bend_auto_data/reproducibility/build_dataset.py" --output "PATH/work/rebuilt_cedar_bend_auto_data"
python "PATH/cedar_bend_auto_data/reproducibility/verify_dataset.py" --root "PATH/work/rebuilt_cedar_bend_auto_data"
```

`build_dataset.py` создаёт economic events, source CSV и исходные metadata. `verify_dataset.py` НЕ импортирует генератор и повторно читает сохранённые файлы. Его checks/controls не используются для создания фактов. `prepare_delivery.py` — служебный скрипт авторской рабочей папки для каталогов, traces и ZIP; его пути предполагают исходную структуру work/ и outputs/, он не нужен для проверки.

Для повторной проверки моста RO margin → GL:

```powershell
python "PATH/cedar_bend_auto_data/reproducibility/add_margin_controls.py" --root "PATH/cedar_bend_auto_data"
```

Этот скрипт также читает только сохранённые CSV и останавливается при расхождении на один цент.

Идентификаторы детерминированы, fixed PRNG seeds; одинаковый Python и код дают одинаковые source bytes. Изменение assumptions — новый synthetic scenario; не выдавайте пересчитанные данные за полученный факт. Полный ZIP содержит проверенный снимок CSV, документацию, независимый verifier и исходный генератор.
