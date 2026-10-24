# update_main_readme.py - adds news_engine section to main README
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
README_PATH = os.path.join(SCRIPT_DIR, 'README.md')

with open(README_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

if 'News Engine (v2)' in content:
    print('Already added, skipping')
    exit(0)

lines = []
lines.append('')
lines.append('---')
lines.append('')
lines.append('## 3. News Engine (v2) - AI-Enhanced Order Block Scanner')
lines.append('')
lines.append('Evolution of stock_scanner: added macro context, news analysis and LLM (DeepSeek) for signal interpretation.')
lines.append('')
lines.append('What is new vs stock_scanner:')
lines.append('- Macro: Brent, IMOEX, CB rate, RVI, USD/RUB')
lines.append('- News: RSS + BCS + SmartLab forums')
lines.append('- LLM: DeepSeek - strategy and explanation')
lines.append('- Forward test: Hit Rate, MFE/MAE, false breakouts')
lines.append('')
lines.append('Architecture:')
lines.append('macro_collector -> scanner_clean -> news_collector -> calendar_collector')
lines.append('-> ticker_news_collector -> news_engine (LLM) -> signal_saver')
lines.append('-> analyze_hits -> hits_report')
lines.append('')
lines.append('Forward test (in progress):')
lines.append('System runs autonomously on VPS since 19.10.2026.')
lines.append('Current results: Hit 1d - 61%, Hit 3d - 60%.')
lines.append('')
lines.append('Example signals: see news_engine/examples/signals/')
lines.append('')
lines.append('Status: forward test in progress. MCP wrapper planned for T-Bank Invest Premarket contest.')
lines.append('')
lines.append('More details: news_engine/README.md')

addition = '\n'.join(lines)

with open(README_PATH, 'a', encoding='utf-8') as f:
    f.write(addition)

print('OK: section added to ' + README_PATH)
