# compare_modes.py — Сравнение morning vs evening (v1)
"""
Читает:
- data/hits_analysis/morning_report.json
- data/hits_analysis/evening_report.json

Сравнивает по всем метрикам.
Выдаёт вердикт: какой режим лучше.

Сохраняет:
- data/hits_analysis/comparison.json

Запуск:
    python compare_modes.py
"""

import os
import json
from datetime import datetime

import sys
import io



# === AUTO-PATCHED LOGGING ===
import sys as _sys
import io as _io
from datetime import datetime as _dt

# UTF-8 для stdout/stderr
if _sys.stdout.encoding and _sys.stdout.encoding.lower() != 'utf-8':
    _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace')
if _sys.stderr.encoding and _sys.stderr.encoding.lower() != 'utf-8':
    _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace')

_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bat', 'run_log.txt')

def log(*args, **kwargs):
    """Печатает в консоль + пишет в bat/run_log.txt (UTF-8)."""
    msg = ' '.join(str(a) for a in args)
    print(*args, **kwargs)
    try:
        os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
        with open(_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{_dt.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

# === END AUTO-PATCHED ===


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
HITS_ANALYSIS_DIR = os.path.join(DATA_DIR, 'hits_analysis')

HORIZONS = [1, 3, 5, 10]


def load_report(mode):
    filepath = os.path.join(HITS_ANALYSIS_DIR, f'{mode}_report.json')
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def compare_hit_rates(m_report, e_report):
    """Сравнивает Hit Rate по горизонтам."""
    comparison = {}
    
    for h in HORIZONS:
        m_hr = m_report['hit_rate'][f'{h}d']
        e_hr = e_report['hit_rate'][f'{h}d']
        
        m_rate = m_hr['rate_pct']
        e_rate = e_hr['rate_pct']
        
        if m_rate is None and e_rate is None:
            winner = 'no_data'
        elif m_rate is None:
            winner = 'evening'
        elif e_rate is None:
            winner = 'morning'
        elif m_rate > e_rate:
            winner = 'morning'
            diff = round(m_rate - e_rate, 1)
        elif e_rate > m_rate:
            winner = 'evening'
            diff = round(e_rate - m_rate, 1)
        else:
            winner = 'tie'
            diff = 0
        
        comparison[f'{h}d'] = {
            'morning': {'rate': m_rate, 'total': m_hr['total'], 'hits': m_hr['hits']},
            'evening': {'rate': e_rate, 'total': e_hr['total'], 'hits': e_hr['hits']},
            'winner': winner,
            'diff_pct': diff if winner != 'no_data' else None,
        }
    
    return comparison


def compare_metrics(m_report, e_report):
    """Сравнивает MFE/MAE и другие метрики."""
    comparison = {}
    
    m_mfe = m_report.get('mfe_mae') or {}
    e_mfe = e_report.get('mfe_mae') or {}
    
    for metric in ['avg_mfe_pct', 'median_mfe_pct', 'avg_mae_pct']:
        m_val = m_mfe.get(metric)
        e_val = e_mfe.get(metric)
        
        if m_val is None and e_val is None:
            continue
        
        if metric == 'avg_mae_pct':
            # Для MAE меньше = лучше
            if m_val is not None and e_val is not None:
                winner = 'morning' if m_val < e_val else 'evening' if e_val < m_val else 'tie'
            else:
                winner = 'no_data'
        else:
            # Для MFE больше = лучше
            if m_val is not None and e_val is not None:
                winner = 'morning' if m_val > e_val else 'evening' if e_val > m_val else 'tie'
            else:
                winner = 'no_data'
        
        comparison[metric] = {
            'morning': m_val,
            'evening': e_val,
            'winner': winner,
        }
    
    return comparison


def compare_by_source(m_report, e_report):
    """Сравнивает по source (selected/alternative)."""
    comparison = {}
    
    for source in ['selected', 'alternative']:
        m_stats = m_report.get('by_source', {}).get(source)
        e_stats = e_report.get('by_source', {}).get(source)
        
        if not m_stats and not e_stats:
            continue
        
        m_rate = m_stats['hit_1d']['rate_pct'] if m_stats else None
        e_rate = e_stats['hit_1d']['rate_pct'] if e_stats else None
        
        if m_rate is None and e_rate is None:
            winner = 'no_data'
        elif m_rate is None:
            winner = 'evening'
        elif e_rate is None:
            winner = 'morning'
        elif m_rate > e_rate:
            winner = 'morning'
        elif e_rate > m_rate:
            winner = 'evening'
        else:
            winner = 'tie'
        
        comparison[source] = {
            'morning': {'rate': m_rate, 'count': m_stats['count'] if m_stats else 0},
            'evening': {'rate': e_rate, 'count': e_stats['count'] if e_stats else 0},
            'winner': winner,
        }
    
    return comparison


def make_verdict(comparison, metrics_comparison, source_comparison):
    """Выдаёт общий вердикт."""
    morning_wins = 0
    evening_wins = 0
    
    # По горизонтам
    for h, data in comparison.items():
        if data['winner'] == 'morning':
            morning_wins += 1
        elif data['winner'] == 'evening':
            evening_wins += 1
    
    # По метрикам
    for metric, data in metrics_comparison.items():
        if data['winner'] == 'morning':
            morning_wins += 1
        elif data['winner'] == 'evening':
            evening_wins += 1
    
    # По source
    for source, data in source_comparison.items():
        if data['winner'] == 'morning':
            morning_wins += 1
        elif data['winner'] == 'evening':
            evening_wins += 1
    
    total = morning_wins + evening_wins
    if total == 0:
        return {
            'winner': 'no_data',
            'morning_wins': 0,
            'evening_wins': 0,
            'reasoning': 'Недостаточно данных для сравнения',
        }
    
    if morning_wins > evening_wins:
        winner = 'morning'
        reason = f"Утренний режим побеждает в {morning_wins} из {total} метрик"
    elif evening_wins > morning_wins:
        winner = 'evening'
        reason = f"Вечерний режим побеждает в {evening_wins} из {total} метрик"
    else:
        winner = 'tie'
        reason = f"Ничья: {morning_wins} vs {evening_wins}"
    
    return {
        'winner': winner,
        'morning_wins': morning_wins,
        'evening_wins': evening_wins,
        'reasoning': reason,
    }


def print_comparison(comparison, metrics_comparison, source_comparison, verdict):
    """Печатает сравнение в консоль."""
    log(f"\n{'='*70}")
    log(f"⚖️ СРАВНЕНИЕ: MORNING vs EVENING")
    log(f"{'='*70}")
    
    log(f"\n📈 HIT RATE:")
    log(f"   {'Горизонт':10} | {'Morning':15} | {'Evening':15} | {'Победитель':10}")
    log(f"   {'-'*60}")
    for h in HORIZONS:
        data = comparison[f'{h}d']
        m = data['morning']
        e = data['evening']
        m_str = f"{m['rate']}% ({m['hits']}/{m['total']})" if m['rate'] is not None else "нет данных"
        e_str = f"{e['rate']}% ({e['hits']}/{e['total']})" if e['rate'] is not None else "нет данных"
        log(f"   {h}д{'':8} | {m_str:15} | {e_str:15} | {data['winner']}")
    
    log(f"\n💰 MFE/MAE:")
    for metric, data in metrics_comparison.items():
        m = data['morning']
        e = data['evening']
        log(f"   {metric:20} | M: {m} | E: {e} | {data['winner']}")
    
    log(f"\n📊 ПО SOURCE:")
    for source, data in source_comparison.items():
        m = data['morning']
        e = data['evening']
        m_str = f"{m['rate']}% ({m['count']})" if m['rate'] is not None else "—"
        e_str = f"{e['rate']}% ({e['count']})" if e['rate'] is not None else "—"
        log(f"   {source:12} | M: {m_str:12} | E: {e_str:12} | {data['winner']}")
    
    log(f"\n{'='*70}")
    log(f"🎯 ВЕРДИКТ: {verdict['winner'].upper()}")
    log(f"   {verdict['reasoning']}")
    log(f"   Morning wins: {verdict['morning_wins']}, Evening wins: {verdict['evening_wins']}")
    log(f"{'='*70}")


def main():
    log("="*70)
    log("⚖️ СРАВНЕНИЕ РЕЖИМОВ (compare_modes.py)")
    log(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("="*70)
    
    m_report = load_report('morning')
    e_report = load_report('evening')
    
    if not m_report and not e_report:
        log("❌ Нет отчётов для сравнения")
        return
    
    if not m_report:
        log("⚠️ Нет отчёта morning — пропускаем сравнение")
        return
    
    if not e_report:
        log("⚠️ Нет отчёта evening — пропускаем сравнение")
        return
    
    comparison = compare_hit_rates(m_report, e_report)
    metrics_comparison = compare_metrics(m_report, e_report)
    source_comparison = compare_by_source(m_report, e_report)
    verdict = make_verdict(comparison, metrics_comparison, source_comparison)
    
    output = {
        'generated_at': datetime.now().isoformat(),
        'hit_rates': comparison,
        'metrics': metrics_comparison,
        'by_source': source_comparison,
        'verdict': verdict,
    }
    
    output_file = os.path.join(HITS_ANALYSIS_DIR, 'comparison.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print_comparison(comparison, metrics_comparison, source_comparison, verdict)
    
    log(f"\n💾 Сохранено: {output_file}")
    log("\n" + "="*70)
    log("✅ ГОТОВО")
    log("="*70)


if __name__ == "__main__":
    main()



