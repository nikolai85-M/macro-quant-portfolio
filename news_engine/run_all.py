# run_all.py — Автоматический запуск всего pipeline (v3)
"""
Правильный порядок:
1. macro_collector.py       → макро + история
2. scanner_clean.py         → СВЕЖИЕ сигналы сканера
3. news_collector.py        → RSS + БКС + форумы по тикерам
4. calendar_collector.py    → календарь событий
5. ticker_news_collector.py → фильтрация новостей по тикерам
6. news_engine.py           → LLM-анализ → final_strategy.json
7. signal_saver.py          → сохранение в signals_history/{mode}/{date}.json

Режимы:
    python run_all.py --mode morning    → утренний прогон (08:00)
    python run_all.py --mode evening    → вечерний прогон (18:00)

Изменения v3:
- Добавлен аргумент --mode morning|evening
- После news_engine.py вызывается signal_saver.save_signals(mode)
- Signal_saver вызывается через import (не subprocess)
"""

import os
import sys
import argparse
import subprocess
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(SCRIPT_DIR)

SCRIPTS = [
    ('macro_collector.py', '📊 Макро-данные'),
    ('scanner_clean.py', '🔍 Сканер блоков'),
    ('news_collector.py', '📰 Новости + форумы'),
    ('calendar_collector.py', '📅 Календарь'),
    ('ticker_news_collector.py', '📊 Новости по тикерам'),
    ('news_engine.py', '🧠 LLM-анализ'),
]


def run_script(script_name, timeout=600):
    """Запускает скрипт через subprocess."""
    script_path = os.path.join(SCRIPT_DIR, script_name)
    
    if not os.path.exists(script_path):
        print(f"   ❌ {script_name} не найден")
        return False
    
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            cwd=SCRIPT_DIR,
            timeout=timeout,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"   ⏱️ {script_name} — таймаут ({timeout}с)")
        return False
    except Exception as e:
        print(f"   ❌ {script_name} — {type(e).__name__}: {e}")
        return False


def run_signal_saver(mode):
    """Вызывает signal_saver.save_signals(mode) через import."""
    try:
        from signal_saver import save_signals
        result = save_signals(mode=mode)
        return result is not None
    except Exception as e:
        print(f"   ❌ signal_saver — {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['morning', 'evening'], default='morning',
                        help='Режим запуска: morning (08:00) или evening (18:00)')
    args = parser.parse_args()
    
    mode = args.mode
    
    print("="*70)
    print(f"🚀 ЗАПУСК PIPELINE v3 ({mode.upper()})")
    print(f"⏰ Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    print()
    
    start_time = datetime.now()
    
    # Шаги 1-6: обычные скрипты
    for i, (script, label) in enumerate(SCRIPTS, 1):
        print(f"\n[{i}/{len(SCRIPTS)+1}] {label} ({script})")
        print("-"*70)
        
        step_start = datetime.now()
        
        # Сканер — дольше
        timeout = 600 if 'scanner' in script else 300
        
        success = run_script(script, timeout=timeout)
        step_duration = (datetime.now() - step_start).total_seconds()
        
        if success:
            print(f"   ✅ Готово за {step_duration:.0f}с")
        else:
            print(f"   ❌ Ошибка за {step_duration:.0f}с")
            print(f"\n⚠️ Pipeline остановлен на шаге {i}: {script}")
            
            response = input("\nПродолжить? (y/n): ").strip().lower()
            if response != 'y':
                return 1
    
    # Шаг 7: signal_saver — через import
    print(f"\n[{len(SCRIPTS)+1}/{len(SCRIPTS)+1}] 💾 Сохранение сигналов (signal_saver.py)")
    print("-"*70)
    
    step_start = datetime.now()
    success = run_signal_saver(mode)
    step_duration = (datetime.now() - step_start).total_seconds()
    
    if success:
        print(f"   ✅ Готово за {step_duration:.0f}с")
    else:
        print(f"   ❌ Ошибка за {step_duration:.0f}с")
    
    total_duration = (datetime.now() - start_time).total_seconds()
    
    print("\n" + "="*70)
    print(f"✅ PIPELINE ЗАВЕРШЁН ({mode.upper()})")
    print(f"   Общее время: {total_duration/60:.1f} мин")
    print(f"   Результаты:")
    print(f"     - data/macro_data.json")
    print(f"     - data/macro_history.json")
    print(f"     - data/scanner_signals.json")
    print(f"     - data/news_feed.json")
    print(f"     - data/calendar.json")
    print(f"     - data/ticker_news/")
    print(f"     - data/final_strategy.json")
    print(f"     - data/signals_history/{mode}/{{date}}.json")
    print("="*70)
    return 0


if __name__ == "__main__":
    sys.exit(main())