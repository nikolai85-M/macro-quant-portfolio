# News Engine (v2) - AI-усиленный сканер ордер-блоков

Эволюция stock_scanner: добавлены макро-контекст, новостной анализ и LLM (DeepSeek) для интерпретации сигналов.

## Что нового по сравнению со stock_scanner

| Компонент | stock_scanner (v1) | news_engine (v2) |
|-----------|-------------------|------------------|
| Ордер-блоки | Да | Да |
| Stoch RSI | Да | Да |
| Объёмы | Да | Да |
| Макро-фон | Нет | Да - Brent, IMOEX, ставка ЦБ, RVI, USD/RUB |
| Новости | Нет | Да - RSS + БКС + SmartLab форумы |
| LLM | Нет | Да - DeepSeek стратегия и объяснение |
| Форвард-тест | Нет | Да - Hit Rate, MFE/MAE, ложные пробои |

## Архитектура

1. macro_collector.py - макро + история за 2 года
2. scanner_clean.py - ордер-блоки (LuxAlgo) + Stoch
3. news_collector.py - RSS + БКС + SmartLab форумы
4. calendar_collector.py - события на 7 дней
5. ticker_news_collector.py - фильтрация по тикерам
6. news_engine.py - LLM: макро + стратегия
7. signal_saver.py - сохранение в signals_history

Результат: final_strategy.json -> analyze_hits.py -> hits_report.py

## Пример сигнала

См. examples/signals/2026-10-24.json

Ключевые поля: signal_id, ticker, direction, entry, stop, target, block_low, block_high, stoch, r_r, quality, final_rating, entry_zone, context

## Форвард-тест (в процессе)

Система работает автономно на VPS с 19.10.2026:
- Утро (08:00) - pipeline, сигналы на день
- Вечер (18:00) - pipeline, сигналы на вечер
- Анализ (20:00) - Hit Rate по всем сигналам

Текущие результаты (на 24.10, 6 дней):
- Hit 1д: 61%
- Hit 3д: 60%
- Hit 5д: 20% (в процессе)

Данные обновляются ежедневно.

## Статус и планы

Текущий статус: форвард-тест в процессе.

Планы:
- Обёртка в MCP для конкурса Инвест. Премаркет (Т-Банк)
- AI-агент для анализа портфеля через T-Invest API
- Тональность новостей в реальном времени

## Запуск

Установка зависимостей:
pip install pandas numpy requests python-dotenv feedparser beautifulsoup4 openai
pip install playwright
playwright install chromium

Настройка .env:
cp .env.example .env
Добавить AITUNNEL_API_KEY и TINKOFF_TOKEN

Полный pipeline:
python run_all.py --mode morning

Анализ:
python analyze_hits.py --mode morning
python hits_report.py --mode morning

## Технологии

- Python 3.10+
- pandas, numpy - анализ данных
- openai (DeepSeek через AITunnel) - LLM
- feedparser, beautifulsoup4 - новости
- playwright - БКС Экспресс
- Tinkoff Invest API - свечи и цены
- python-dotenv - конфигурация