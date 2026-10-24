# fix_main_readme_ru.py - rewrites news_engine section in Russian
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
README_PATH = os.path.join(SCRIPT_DIR, 'README.md')

with open(README_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove English section if exists
if '## 3. News Engine (v2)' in content:
    idx = content.find('## 3. News Engine (v2)')
    content = content[:idx].rstrip()
    print('Removed English section')

lines = []
lines.append('')
lines.append('---')
lines.append('')
lines.append('## 3. News Engine (v2) - AI-усиленный сканер ордер-блоков')
lines.append('')
lines.append('Эволюция stock_scanner: добавлены макро-контекст, новостной анализ и LLM (DeepSeek) для интерпретации сигналов.')
lines.append('')
lines.append('Что нового по сравнению со stock_scanner:')
lines.append('- Макро: Brent, IMOEX, ставка ЦБ, RVI, USD/RUB')
lines.append('- Новости: RSS + БКС + SmartLab форумы')
lines.append('- LLM: DeepSeek - стратегия и объяснение')
lines.append('- Форвард-тест: Hit Rate, MFE/MAE, ложные пробои')
lines.append('')
lines.append('Архитектура:')
lines.append('macro_collector -> scanner_clean -> news_collector -> calendar_collector')
lines.append('-> ticker_news_collector -> news_engine (LLM) -> signal_saver')
lines.append('-> analyze_hits -> hits_report')
lines.append('')
lines.append('Форвард-тест (в процессе):')
lines.append('Система работает автономно на VPS с 19.10.2026.')
lines.append('Текущие результаты: Hit 1д - 61%, Hit 3д - 60%.')
lines.append('')
lines.append('Примеры сигналов: см. news_engine/examples/signals/')
lines.append('')
lines.append('Статус: форвард-тест в процессе. Планируется MCP-обёртка для конкурса Т-Банк.')
lines.append('')
lines.append('Подробнее: news_engine/README.md')

addition = '\n'.join(lines)

with open(README_PATH, 'w', encoding='utf-8') as f:
    f.write(content + addition)

print('OK: Russian section added to ' + README_PATH)
