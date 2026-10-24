# hits_report.py — Агрегация и отчёты по Hit Rate (v1)
"""
Читает:
- data/hits_analysis/morning_detailed.json
- data/hits_analysis/evening_detailed.json

Считает агрегаты:
- Hit Rate по горизонтам
- Разбивка по source / direction / phase / sector / zone / trigger / r_r
- MFE/MAE статистика
- Ложные пробои, уровни, скорость

Сохраняет:
- data/hits_analysis/morning_report.json
- data/hits_analysis/evening_report.json
- data/hits_analysis/all_report.json (объединённый)

Запуск:
    python hits_report.py
    python hits_report.py --mode morning
    python hits_report.py --mode evening
"""

import os
import json
import argparse
from datetime import datetime
from collections import defaultdict

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

os.makedirs(HITS_ANALYSIS_DIR, exist_ok=True)

HORIZONS = [1, 3, 5, 10]


# ==============================================================================
# ЗАГРУЗКА
# ==============================================================================

def load_detailed(mode):
    filepath = os.path.join(HITS_ANALYSIS_DIR, f'{mode}_detailed.json')
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log(f"⚠️ Ошибка чтения {filepath}: {e}")
        return None


# ==============================================================================
# ХЕЛПЕРЫ
# ==============================================================================

def safe_avg(values):
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return round(sum(valid) / len(valid), 2)


def safe_pct(part, total):
    if total == 0:
        return None
    return round(part / total * 100, 1)


def get_sector(ticker):
    """Определяет сектор тикера."""
    try:
        from news_engine import TICKER_TO_SECTOR
        return TICKER_TO_SECTOR.get(ticker, 'unknown')
    except Exception:
        return 'unknown'


# ==============================================================================
# АГРЕГАЦИЯ
# ==============================================================================

def calc_hit_rate_by_horizon(results, horizon):
    """Hit Rate для горизонта."""
    total = 0
    hits = 0
    for r in results:
        hit = r['summary'].get(f'hit_{horizon}d')
        if hit is not None:
            total += 1
            if hit:
                hits += 1
    return {
        'total': total,
        'hits': hits,
        'rate_pct': safe_pct(hits, total),
    }


def calc_group_stats(results, group_func, group_name):
    """
    Группирует сигналы по group_func(r) и считает метрики.
    """
    groups = defaultdict(list)
    for r in results:
        key = group_func(r)
        groups[key].append(r)
    
    output = {}
    for key, group in groups.items():
        if key is None:
            key = 'unknown'
        
        stats = {
            'count': len(group),
            'hit_1d': calc_hit_rate_by_horizon(group, 1),
            'hit_3d': calc_hit_rate_by_horizon(group, 3),
            'hit_5d': calc_hit_rate_by_horizon(group, 5),
            'hit_10d': calc_hit_rate_by_horizon(group, 10),
            'avg_mfe_pct': safe_avg([r['summary'].get('max_mfe_pct') for r in group]),
            'avg_mae_pct': safe_avg([r['summary'].get('max_mae_pct') for r in group]),
            'stop_hit_count': sum(1 for r in group if r['summary'].get('stop_hit')),
            'false_breakout_count': sum(1 for r in group if r['summary'].get('false_breakout')),
            'avg_levels_reached': safe_avg([r['summary'].get('levels_reached_max') for r in group]),
        }
        output[str(key)] = stats
    
    return output


def calc_mfe_mae_stats(results):
    """Общая статистика MFE/MAE."""
    mfe_values = [r['summary'].get('max_mfe_pct') for r in results if r['summary'].get('max_mfe_pct') is not None]
    mae_values = [r['summary'].get('max_mae_pct') for r in results if r['summary'].get('max_mae_pct') is not None]
    
    if not mfe_values:
        return None
    
    mfe_values_sorted = sorted(mfe_values)
    
    return {
        'avg_mfe_pct': safe_avg(mfe_values),
        'max_mfe_pct': round(max(mfe_values), 2),
        'median_mfe_pct': round(mfe_values_sorted[len(mfe_values_sorted)//2], 2),
        'avg_mae_pct': safe_avg(mae_values),
        'max_mae_pct': round(max(mae_values), 2) if mae_values else None,
        'positive_mfe_count': sum(1 for v in mfe_values if v > 0),
        'zero_mfe_count': sum(1 for v in mfe_values if v == 0),
    }


def calc_levels_stats(results):
    """Статистика по уровням."""
    level_counts = defaultdict(int)
    
    for r in results:
        max_levels = r['summary'].get('levels_reached_max', 0)
        level_counts[max_levels] += 1
    
    total = len(results)
    
    output = {}
    for level in range(0, 5):
        count = level_counts.get(level, 0)
        output[f'level_{level}'] = {
            'count': count,
            'pct': safe_pct(count, total),
        }
    
    return output


def calc_speed_stats(results):
    """Скорость достижения уровней (в часах)."""
    hours_1 = []
    hours_2 = []
    
    for r in results:
        for key in ['1d', '3d', '5d', '10d']:
            data = r['results'].get(key, {})
            if 'hours_to_level_1' in data and data['hours_to_level_1'] is not None:
                hours_1.append(data['hours_to_level_1'])
            if 'hours_to_level_2' in data and data['hours_to_level_2'] is not None:
                hours_2.append(data['hours_to_level_2'])
    
    return {
        'avg_hours_to_level_1': safe_avg(hours_1),
        'median_hours_to_level_1': round(sorted(hours_1)[len(hours_1)//2], 2) if hours_1 else None,
        'avg_hours_to_level_2': safe_avg(hours_2),
        'median_hours_to_level_2': round(sorted(hours_2)[len(hours_2)//2], 2) if hours_2 else None,
    }


def build_report(results):
    """Строит полный отчёт по результатам."""
    if not results:
        return None
    
    report = {
        'generated_at': datetime.now().isoformat(),
        'total_signals': len(results),
        
        # Общий Hit Rate
        'hit_rate': {
            '1d': calc_hit_rate_by_horizon(results, 1),
            '3d': calc_hit_rate_by_horizon(results, 3),
            '5d': calc_hit_rate_by_horizon(results, 5),
            '10d': calc_hit_rate_by_horizon(results, 10),
        },
        
        # MFE/MAE
        'mfe_mae': calc_mfe_mae_stats(results),
        
        # Уровни
        'levels': calc_levels_stats(results),
        
        # Скорость
        'speed': calc_speed_stats(results),
        
        # Разбивки
        'by_source': calc_group_stats(results, lambda r: r.get('source', 'selected'), 'source'),
        'by_direction': calc_group_stats(results, lambda r: r.get('direction'), 'direction'),
        'by_phase': calc_group_stats(results, lambda r: (r.get('context') or {}).get('market_phase'), 'phase'),
        'by_sector': calc_group_stats(results, lambda r: get_sector(r.get('ticker')), 'sector'),
        'by_entry_zone': calc_group_stats(
            results,
            lambda r: (r.get('entry_zone') or {}).get('zone') if r.get('entry_zone') else None,
            'entry_zone'
        ),
        'by_trigger_quality': calc_group_stats(
            results,
            lambda r: (r.get('trigger_analysis') or {}).get('quality') if r.get('trigger_analysis') else None,
            'trigger_quality'
        ),
            'by_rr': calc_group_stats(results, lambda r: _rr_bucket(r.get('r_r')), 'r_r'),
        
        # 🔥 НОВЫЕ РАЗБИВКИ
        'by_brent': calc_group_stats(
            results,
            lambda r: _brent_bucket(_get_macro(r, 'brent')),
            'brent'
        ),
        'by_imoex_position': calc_group_stats(
            results,
            lambda r: _imoex_position_bucket(_get_macro(r, 'imoex_position')),
            'imoex_position'
        ),
        'by_news_tone': calc_group_stats(
            results,
            lambda r: _get_news_tone_overall(r),
            'news_tone'
        ),
        'by_focus_match': calc_group_stats(
            results,
            lambda r: _focus_match(r),
            'focus_match'
        ),
        'by_critical_events': calc_group_stats(
            results,
            lambda r: _has_critical_events(r),
            'critical_events'
        ),
        'by_direction_phase': calc_group_stats(
            results,
            lambda r: _long_short_phase(r),
            'direction_phase'
        ),
    }
    
    return report


def _rr_bucket(rr):
    """Группирует R:R в категории."""
    if rr is None:
        return None
    if rr >= 7:
        return '>7'
    elif rr >= 5:
        return '5-7'
    elif rr >= 3:
        return '3-5'
    else:
        return '<3'

def _brent_bucket(brent):
    """Группирует Brent в диапазоны."""
    if brent is None:
        return None
    if brent < 100:
        return '<100'
    elif brent < 110:
        return '100-110'
    else:
        return '>110'


def _imoex_position_bucket(pos):
    """Группирует позицию IMOEX."""
    if pos is None:
        return None
    if pos < 33:
        return '0-33 (низ)'
    elif pos < 66:
        return '33-66 (середина)'
    else:
        return '66-100 (верх)'


def _news_tone_bucket(tone):
    """Группирует тональность новостей."""
    if tone is None:
        return None
    if isinstance(tone, dict):
        return tone.get('overall') or tone.get('label')
    return str(tone)


def _focus_match(r):
    """Проверяет, совпадает ли сигнал с фокусным направлением LLM."""
    ctx = r.get('context') or {}
    direction = r.get('direction')
    focus_direction = ctx.get('focus_direction')
    
    if focus_direction is None:
        return 'no_focus'
    if direction == focus_direction:
        return 'matches'
    else:
        return 'against'


def _has_critical_events(r):
    """Были ли критические события."""
    ctx = r.get('context') or {}
    critical = ctx.get('critical_events') or []
    if not critical:
        return 'нет'
    return 'есть'


def _long_short_phase(r):
    """Комбинация direction + phase."""
    direction = r.get('direction', '?')
    ctx = r.get('context') or {}
    phase = ctx.get('market_phase', '?')
    return f"{direction}_{phase}"


def _get_macro(r, key):
    """Достаёт поле из context.macro."""
    ctx = r.get('context') or {}
    macro = ctx.get('macro') or {}
    return macro.get(key)


def _get_news_tone_overall(r):
    """Достаёт overall тональность из context.news_tone."""
    ctx = r.get('context') or {}
    tone = ctx.get('news_tone')
    if isinstance(tone, dict):
        return tone.get('overall')
    return None

# ==============================================================================
# ВЫВОД
# ==============================================================================

def print_report(report, mode_label):
    """Печатает отчёт в консоль."""
    if not report:
        log(f"\n⚠️ {mode_label}: нет данных")
        return
    
    log(f"\n{'='*70}")
    log(f"📊 ОТЧЁТ: {mode_label}")
    log(f"{'='*70}")
    
    log(f"\n📌 Всего сигналов: {report['total_signals']}")
    
    # Hit Rate
    log(f"\n📈 HIT RATE:")
    for h in HORIZONS:
        hr = report['hit_rate'][f'{h}d']
        if hr['total'] > 0:
            log(f"   {h:2}д: {hr['hits']}/{hr['total']} ({hr['rate_pct']}%)")
        else:
            log(f"   {h:2}д: нет данных")
    
    # MFE/MAE
    mfe_mae = report.get('mfe_mae')
    if mfe_mae:
        log(f"\n💰 MFE/MAE:")
        log(f"   Средний MFE: {mfe_mae['avg_mfe_pct']}%")
        log(f"   Медиана MFE: {mfe_mae['median_mfe_pct']}%")
        log(f"   Максимум MFE: {mfe_mae['max_mfe_pct']}%")
        log(f"   Средний MAE: {mfe_mae['avg_mae_pct']}%")
        log(f"   Максимум MAE: {mfe_mae['max_mae_pct']}%")
    
    # Скорость
    speed = report.get('speed')
    if speed and speed.get('avg_hours_to_level_1'):
        log(f"\n⚡ СКОРОСТЬ:")
        log(f"   До уровня 1: в среднем {speed['avg_hours_to_level_1']}ч")
        if speed.get('avg_hours_to_level_2'):
            log(f"   До уровня 2: в среднем {speed['avg_hours_to_level_2']}ч")
    
    # По source
    log(f"\n📊 ПО ИСТОЧНИКУ:")
    for src, stats in report['by_source'].items():
        hr = stats['hit_1d']
        hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
        log(f"   {src:12} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")
    
    # По направлению
    log(f"\n📊 ПО НАПРАВЛЕНИЮ:")
    for d, stats in report['by_direction'].items():
        hr = stats['hit_1d']
        hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
        log(f"   {d:6} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")
    
    # По фазе
    log(f"\n📊 ПО ФАЗЕ:")
    for phase, stats in report['by_phase'].items():
        hr = stats['hit_1d']
        hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
        log(f"   {phase:12} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")
    
    # По секторам
    log(f"\n📊 ПО СЕКТОРАМ:")
    for sector, stats in sorted(report['by_sector'].items(), key=lambda x: -x[1]['count']):
        hr = stats['hit_1d']
        hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
        log(f"   {sector:12} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")
    
    # По зоне входа
    log(f"\n📊 ПО ЗОНЕ ВХОДА:")
    for zone, stats in report['by_entry_zone'].items():
        hr = stats['hit_1d']
        hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
        log(f"   {zone:15} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")
    
    # По качеству триггера
    log(f"\n📊 ПО КАЧЕСТВУ ТРИГГЕРА:")
    for q, stats in report['by_trigger_quality'].items():
        hr = stats['hit_1d']
        hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
        log(f"   {q:10} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")
    
    # По R:R
    log(f"\n📊 ПО R:R:")
    for rr, stats in report['by_rr'].items():
        hr = stats['hit_1d']
        hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
        log(f"   {rr:6} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")
    
    # 🔥 НОВЫЕ РАЗБИВКИ
    
    # По Brent
    if report.get('by_brent'):
        log(f"\n📊 ПО BRENT:")
        for brent, stats in report['by_brent'].items():
            hr = stats['hit_1d']
            hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
            log(f"   {brent:10} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")
    
    # По IMOEX позиции
    if report.get('by_imoex_position'):
        log(f"\n📊 ПО IMOEX ПОЗИЦИИ:")
        for pos, stats in report['by_imoex_position'].items():
            hr = stats['hit_1d']
            hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
            log(f"   {pos:20} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")
    
    # По тональности новостей
    if report.get('by_news_tone'):
        log(f"\n📊 ПО ТОНАЛЬНОСТИ НОВОСТЕЙ:")
        for tone, stats in report['by_news_tone'].items():
            hr = stats['hit_1d']
            hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
            log(f"   {tone:15} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")
    
    # По фокусу LLM
    if report.get('by_focus_match'):
        log(f"\n📊 ПО ФОКУСУ LLM:")
        for match, stats in report['by_focus_match'].items():
            hr = stats['hit_1d']
            hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
            log(f"   {match:12} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")
    
    # По критическим событиям
    if report.get('by_critical_events'):
        log(f"\n📊 ПО КРИТИЧЕСКИМ СОБЫТИЯМ:")
        for ev, stats in report['by_critical_events'].items():
            hr = stats['hit_1d']
            hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
            log(f"   {ev:6} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")
    
    # По direction × phase
    if report.get('by_direction_phase'):
        log(f"\n📊 ПО DIRECTION × PHASE:")
        for combo, stats in report['by_direction_phase'].items():
            hr = stats['hit_1d']
            hr_str = f"{hr['rate_pct']}%" if hr['rate_pct'] is not None else "—"
            log(f"   {combo:20} | {stats['count']:3} сигналов | Hit 1д: {hr_str} | MFE: {stats['avg_mfe_pct']}%")

# ==============================================================================
# ЗАПУСК
# ==============================================================================

def process_mode(mode):
    log(f"\n{'='*70}")
    log(f"📊 АГРЕГАЦИЯ: {mode.upper()}")
    log(f"{'='*70}")
    
    detailed = load_detailed(mode)
    if not detailed:
        log(f"   ⚠️ Нет данных: {mode}_detailed.json")
        return None
    
    results = detailed.get('results', [])
    if not results:
        log(f"   ⚠️ Пустой список результатов")
        return None
    
    log(f"   Сигналов: {len(results)}")
    
    report = build_report(results)
    
    output_file = os.path.join(HITS_ANALYSIS_DIR, f'{mode}_report.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    log(f"   💾 Сохранено: {output_file}")
    
    print_report(report, mode.upper())
    
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['morning', 'evening', 'both'], default='both')
    args = parser.parse_args()
    
    log("="*70)
    log("📊 АГРЕГАЦИЯ HIT RATE (hits_report.py)")
    log(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("="*70)
    
    modes = ['morning', 'evening'] if args.mode == 'both' else [args.mode]
    
    all_results = []
    for mode in modes:
        detailed = load_detailed(mode)
        if detailed:
            all_results.extend(detailed.get('results', []))
        process_mode(mode)
    
    # Объединённый отчёт
    if all_results and len(modes) > 1:
        log(f"\n{'='*70}")
        log(f"📊 ОБЪЕДИНЁННЫЙ ОТЧЁТ (все режимы)")
        log(f"{'='*70}")
        
        combined_report = build_report(all_results)
        
        output_file = os.path.join(HITS_ANALYSIS_DIR, 'all_report.json')
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(combined_report, f, indent=2, ensure_ascii=False)
        
        log(f"   💾 Сохранено: {output_file}")
        print_report(combined_report, 'ВСЕ РЕЖИМЫ')
    
    log("\n" + "="*70)
    log("✅ ГОТОВО")
    log("="*70)


if __name__ == "__main__":
    main()



