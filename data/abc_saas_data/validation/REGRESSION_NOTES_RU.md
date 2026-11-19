# Дополнительные проверки экономической хронологии

Проверка не ограничивалась balanced GL. Независимый review нашёл и воспроизвёл четыре класса ошибок в промежуточной генерации: goodwill с будущими seats, несогласованный first workflow event, слишком большие advertising trial claims и однокопеечные остатки после dunning.

В финальном наборе они исправлены на уровне источника генерации. Добавленные regression checks перечитывают CSV: commercial state на incident date; earliest positive workflow day versus first-run event; platform claims versus observed trial pool; нулевое net service recognition в последующие месяцы после прекращения service.

Промежуточный regression run воспроизвёл ошибки; после исправления отдельный regression run проверил 3 038 условий без ошибок. Финальный полный прогон, включая эти проверки, отражён в validation_report.csv и summary.json. Промежуточные испорченные CSV не входят в поставку.
