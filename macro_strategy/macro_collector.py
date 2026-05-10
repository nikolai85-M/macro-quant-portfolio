import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os
import json
import warnings
import requests
from dotenv import load_dotenv
from pathlib import Path
import logging
import sys
import yaml

def load_config(config_path="config.yaml"):
    """Загружает конфигурацию из YAML-файла."""
    # Сначала ищем в текущей папке
    if not os.path.exists(config_path):
        # Пробуем на уровень выше (там где обычно лежит config.yaml)
        parent_config = os.path.join(os.path.dirname(__file__), '..', config_path)
        if os.path.exists(parent_config):
            config_path = parent_config
        else:
            raise FileNotFoundError(
                f"config.yaml не найден. Искали в:\n"
                f"  - {os.path.join(os.getcwd(), config_path)}\n"
                f"  - {parent_config}"
            )
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config

# Загружаем конфиг
CONFIG = load_config()

# Загружаем конфиг
CONFIG = load_config()

# ================== НАСТРОЙКА ЛОГИРОВАНИЯ ==================
def setup_logging():
    """Настраивает систему логирования"""
    
    # Создаём папку для логов, если её нет
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Настройка форматирования
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # Настройка корневого логгера
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.FileHandler(log_dir / "macro_strategy.log", encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Подавляем излишние логи от библиотек
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    
    return logging.getLogger(__name__)

# Инициализируем логгер
logger = setup_logging()

# ================== ОТКЛЮЧАЕМ ПРЕДУПРЕЖДЕНИЯ ==================
warnings.filterwarnings('ignore')

# ================== НАСТРОЙКА ГРАФИКОВ ==================
def setup_matplotlib():
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams['axes.titleweight'] = 'bold'

setup_matplotlib()

# Загружаем .env для API
load_dotenv()
TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
BASE_URL = "https://invest-public-api.tinkoff.ru/rest"

# ================== 1. ЖЁСТКИЕ ДАННЫЕ СТАВКИ ЦБ ==================
keyrate_data = pd.DataFrame({
    'date_start': pd.to_datetime([
        '2021-01-01', '2021-03-22', '2021-04-26', '2021-06-15', '2021-07-26',
        '2021-09-13', '2021-10-25', '2021-12-20', '2022-02-14', '2022-02-28',
        '2022-04-11', '2022-05-04', '2022-05-27', '2022-06-14', '2022-07-25',
        '2022-09-19', '2023-07-24', '2023-08-15', '2023-09-18', '2023-10-30',
        '2023-12-18', '2024-07-29', '2024-09-16', '2024-10-28', '2024-12-23',
        '2025-04-25', '2025-06-06', '2025-07-25', '2025-09-01', '2025-10-24',
        '2025-12-22', '2025-12-30', '2026-02-13', '2026-02-19'
    ]),
    'date_end': pd.to_datetime([
        '2021-03-21', '2021-04-25', '2021-06-14', '2021-07-25', '2021-09-12',
        '2021-10-24', '2021-12-19', '2022-02-13', '2022-02-27', '2022-04-10',
        '2022-05-03', '2022-05-26', '2022-06-13', '2022-07-24', '2022-09-18',
        '2023-07-23', '2023-08-14', '2023-09-17', '2023-10-29', '2023-12-17',
        '2024-07-28', '2024-09-15', '2024-10-27', '2024-12-22', '2025-04-24',
        '2025-06-05', '2025-07-24', '2025-08-31', '2025-10-23', '2025-12-21',
        '2025-12-29', '2026-02-12', '2026-02-18', '2026-12-31'
    ]),
    'rate': [
        4.25, 4.50, 5.00, 5.50, 6.50, 6.75, 7.50, 8.50, 9.50, 20.00,
        17.00, 14.00, 11.00, 9.50, 8.00, 7.50, 8.50, 12.00, 13.00, 15.00,
        16.00, 18.00, 19.00, 21.00, 21.00, 21.00, 20.00, 18.00, 17.00,
        16.50, 16.00, 16.00, 15.50, 15.50
    ]
})

# ================== 2. ЖЁСТКИЕ ДАННЫЕ СТАВКИ ФРС ==================
fed_data = [
    ['2026-12-09', 3.75], ['2026-10-28', 3.75], ['2026-09-16', 3.75],
    ['2026-07-29', 3.75], ['2026-06-17', 3.75], ['2026-04-29', 3.75],
    ['2026-03-18', 3.75], ['2026-01-28', 3.75], ['2025-12-10', 3.75],
    ['2025-10-29', 4.0], ['2025-09-17', 4.25], ['2025-07-30', 4.5],
    ['2025-06-18', 4.5], ['2025-05-07', 4.5], ['2025-03-19', 4.5],
    ['2025-01-29', 4.5], ['2024-12-18', 4.5], ['2024-11-07', 4.75],
    ['2024-09-18', 5.0], ['2024-07-31', 5.5], ['2024-06-12', 5.5],
    ['2024-05-01', 5.5], ['2024-03-20', 5.5], ['2024-01-31', 5.5],
    ['2023-12-13', 5.5], ['2023-11-01', 5.5], ['2023-09-20', 5.5],
    ['2023-07-26', 5.5], ['2023-06-14', 5.25], ['2023-05-03', 5.25],
    ['2023-03-22', 5.0], ['2023-02-01', 4.75], ['2022-12-14', 4.5],
    ['2022-11-02', 4.0], ['2022-09-21', 3.25], ['2022-07-27', 2.5],
    ['2022-06-15', 1.75], ['2022-05-04', 1.0], ['2022-03-16', 0.5],
    ['2022-01-26', 0.25], ['2021-12-15', 0.25], ['2021-11-03', 0.25],
    ['2021-09-22', 0.25], ['2021-07-28', 0.25], ['2021-06-16', 0.25],
    ['2021-04-28', 0.25], ['2021-03-17', 0.25], ['2021-01-27', 0.25],
    ['2020-12-16', 0.25], ['2020-11-05', 0.25], ['2020-09-16', 0.25],
    ['2020-07-29', 0.25], ['2020-06-10', 0.25], ['2020-04-29', 0.25],
    ['2020-03-16', 0.25], ['2020-03-03', 1.25], ['2020-01-29', 1.75],
    ['2019-12-11', 1.75], ['2019-10-30', 1.75], ['2019-09-18', 2.0]
]
fed = pd.DataFrame(fed_data, columns=['DATE', 'FED_RATE'])
fed['DATE'] = pd.to_datetime(fed['DATE'])

# ================== 3. ЗАГРУЗКА ФОНДОВ ==================
def load_finam_data(filename, col_name):
    df = pd.read_csv(filename + '.csv', sep=';', encoding='utf-8')
    df['DATE'] = pd.to_datetime(df['<DATE>'].astype(str), format='%y%m%d')
    df = df[['DATE', '<CLOSE>']].rename(columns={'<CLOSE>': col_name})
    return df

logger.info("Загрузка данных...")
tbru = load_finam_data('TBRU_210713_260214', 'TBRU')
tgld = load_finam_data('TGLD_210901_260214', 'TGLD')
tmos = load_finam_data('TMOS_210901_260214', 'TMOS')
si = load_finam_data('Si_210901_260214', 'USD_RUB')
brent = load_finam_data('BZ_210901_260214', 'BRENT')
xau = load_finam_data('GC_210901_260214', 'XAUUSD')
dxy = load_finam_data('INDUSDX_210901_260214', 'DXY')
rvi = load_finam_data('RVI_210901_260214', 'RVI')

# Загрузка US10Y с очисткой
logger.info("Загрузка US10Y с очисткой...")
try:
    with open('US10Y_210901_260214.csv', 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace('"', '')
    lines = content.strip().split('\n')
    data = []
    for line in lines[1:]:
        if line.strip():
            line = line.rstrip(',')
            parts = line.split(',')
            if len(parts) >= 2:
                date_str = parts[0].strip()
                value_str = parts[1].strip().replace(',', '.')
                for fmt in ['%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%d']:
                    try:
                        date = pd.to_datetime(date_str, format=fmt)
                        break
                    except:
                        continue
                else:
                    continue
                data.append([date, value_str])
    us10y = pd.DataFrame(data, columns=['DATE', 'US10Y'])
    us10y = us10y.drop_duplicates(subset=['DATE'], keep='last')
    us10y = us10y.sort_values('DATE')
    us10y['US10Y'] = pd.to_numeric(us10y['US10Y'], errors='coerce')
    logger.info(f"US10Y загружено: {len(us10y)} записей")
except Exception as e:
    logger.warning(f"Ошибка загрузки US10Y: {e}")
    us10y = pd.DataFrame(columns=['DATE', 'US10Y'])

# ================== 4. СБОРКА В ЕДИНЫЙ DF ==================
start_date = pd.to_datetime('2021-09-02')
end_date = pd.to_datetime('2026-02-14')
dates = pd.date_range(start=start_date, end=end_date, freq='D')
df = pd.DataFrame(index=dates)
df.index.name = 'DATE'

def add_to_df(data_df, col_name):
    if data_df is not None and len(data_df) > 0:
        df[col_name] = data_df.set_index('DATE').reindex(dates)[col_name]

add_to_df(tbru, 'TBRU')
add_to_df(tgld, 'TGLD')
add_to_df(tmos, 'TMOS')
add_to_df(si, 'USD_RUB')
add_to_df(brent, 'BRENT')
add_to_df(xau, 'XAUUSD')
add_to_df(dxy, 'DXY')
add_to_df(rvi, 'RVI')
add_to_df(us10y, 'US10Y')
add_to_df(fed, 'FED_RATE')

for col in df.columns:
    df[col] = df[col].interpolate(method='linear', limit_direction='both').ffill().bfill()

def get_cbr_rate(date):
    for _, row in keyrate_data.iterrows():
        if row['date_start'] <= date <= row['date_end']:
            return row['rate']
    return keyrate_data.iloc[-1]['rate']
df['CBR_RATE'] = df.index.map(get_cbr_rate)

# ================== 5. ПРАВИЛЬНЫЙ РАСЧЁТ TMON ==================
logger.info("="*80)
logger.info("ПРАВИЛЬНЫЙ РАСЧЁТ TMON КАК ДЕПОЗИТА")
logger.info("="*80)

tmon_values = [100]
for i in range(1, len(df.index)):
    prev_date = df.index[i-1]
    curr_date = df.index[i]
    prev_rate = df.loc[prev_date, 'CBR_RATE']
    days = (curr_date - prev_date).days
    annual_rate = (prev_rate - 2) / 100
    daily_rate = annual_rate / 365
    new_value = tmon_values[-1] * (1 + daily_rate * days)
    tmon_values.append(new_value)

df['TMON'] = tmon_values

# ================== 6. МЕТРИКИ ЭФФЕКТИВНОСТИ ==================
def annual_return(cumulative):
    years = (cumulative.index[-1] - cumulative.index[0]).days / 365.25
    return (cumulative.iloc[-1] / cumulative.iloc[0]) ** (1/years) - 1

def max_drawdown(cumulative):
    rolling_max = cumulative.expanding().max()
    drawdown = (cumulative - rolling_max) / rolling_max
    return drawdown.min()

def sharpe_ratio(returns, rf=0):
    return (returns.mean() - rf/252) / returns.std() * np.sqrt(252) if returns.std() != 0 else 0

# ================== 7. БАЗОВАЯ БИНАРНАЯ СТРАТЕГИЯ ==================
emergency_mode = False
last_emergency_date = None

def get_weights_binary_original(row):
    global emergency_mode, last_emergency_date
    
    active_funds = []
    reasons = []
    current_date = row.name if hasattr(row, 'name') else None
    
    if (row['CBR_RATE'] > 20 and row['USD_RUB'] > 100) or row['RVI'] > 45:
        emergency_mode = True
        last_emergency_date = current_date
        reasons.append(f"ЭКСТРЕННЫЙ ВЫХОД: CBR={row['CBR_RATE']:.1f}%, RVI={row['RVI']:.1f}")
        return {'TMOS': 0, 'TGLD': 0, 'TBRU': 0, 'TMON': 1.0}, reasons
    
    if emergency_mode:
        days_in_emergency = (current_date - last_emergency_date).days if current_date and last_emergency_date else 0
        if (days_in_emergency > 30) or (row['RVI'] < 35 and row['CBR_RATE'] < 19):
            emergency_mode = False
            reasons.append(f"ВЫХОД ИЗ ЭКСТРЕННОГО РЕЖИМА")
        else:
            return {'TMOS': 0, 'TGLD': 0, 'TBRU': 0, 'TMON': 1.0}, reasons
    
    if row['CBR_RATE'] < 15:
        active_funds.append('TMOS')
        reasons.append(f"TMOS в портфеле: ставка {row['CBR_RATE']:.1f}% < 15%")
    
    if row['DXY'] < 103:
        active_funds.append('TGLD')
        reasons.append(f"TGLD в портфеле: DXY {row['DXY']:.1f} < 103")
    
    if row['CBR_RATE'] > 8:
        active_funds.append('TBRU')
        reasons.append(f"TBRU в портфеле: ставка {row['CBR_RATE']:.1f}% > 8%")
    
    active_funds.append('TMON')
    
    weight = 1.0 / len(active_funds)
    weights = {fund: weight if fund in active_funds else 0 for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']}
    
    return weights, reasons

# ================== 8. ТЕХНИЧЕСКИЙ АНАЛИЗАТОР ==================
class TechnicalAnalyzer:
    def __init__(self, prices):
        self.prices = prices
        self.window_rsi = 14
        self.window_ma = 50
        
    def calculate_rsi(self, fund, current_date):
        dates_list = list(self.prices.index)
        if current_date not in dates_list:
            return 50
        idx = dates_list.index(current_date)
        if idx < self.window_rsi:
            return 50
        prices = self.prices[fund].iloc[idx-self.window_rsi:idx+1]
        changes = prices.diff().dropna()
        if len(changes) == 0:
            return 50
        gains = changes[changes > 0].mean() if any(changes > 0) else 0
        losses = -changes[changes < 0].mean() if any(changes < 0) else 0
        if losses == 0:
            return 100 if gains > 0 else 50
        rs = gains / losses
        return 100 - (100 / (1 + rs))
    
    def get_ma_trend(self, fund, current_date):
        dates_list = list(self.prices.index)
        if current_date not in dates_list:
            return "neutral"
        idx = dates_list.index(current_date)
        if idx < self.window_ma:
            return "neutral"
        ma_20 = self.prices[fund].iloc[idx-20:idx].mean()
        ma_50 = self.prices[fund].iloc[idx-50:idx].mean()
        current = self.prices[fund].iloc[idx]
        if pd.isna(ma_20) or pd.isna(ma_50) or pd.isna(current):
            return "neutral"
        if current > ma_20 > ma_50:
            return "strong_up"
        elif current > ma_20:
            return "up"
        elif current < ma_20 < ma_50:
            return "strong_down"
        elif current < ma_20:
            return "down"
        return "neutral"
    
    def get_momentum(self, fund, current_date, periods=[5, 20]):
        dates_list = list(self.prices.index)
        if current_date not in dates_list:
            return {f"{p}d": 0 for p in periods}
        idx = dates_list.index(current_date)
        momentum = {}
        for p in periods:
            if idx >= p:
                prev = self.prices[fund].iloc[idx-p]
                current = self.prices[fund].iloc[idx]
                momentum[f"{p}d"] = (current / prev - 1) * 100 if not pd.isna(prev) else 0
            else:
                momentum[f"{p}d"] = 0
        return momentum
    
    def get_phase(self, fund, current_date):
        rsi = self.calculate_rsi(fund, current_date)
        trend = self.get_ma_trend(fund, current_date)
        momentum = self.get_momentum(fund, current_date)
        if rsi > 70 and trend in ["strong_up", "up"] and momentum["5d"] > 5:
            phase = "ПЕРЕКУПЛЕННОСТЬ"
        elif rsi < 30 and trend in ["strong_down", "down"] and momentum["5d"] < -5:
            phase = "ПЕРЕПРОДАННОСТЬ"
        elif trend == "strong_up":
            phase = "ВОСХОДЯЩИЙ ТРЕНД"
        elif trend == "strong_down":
            phase = "НИСХОДЯЩИЙ ТРЕНД"
        else:
            phase = "БОКОВИК"
        return {
            'phase': phase,
            'rsi': rsi,
            'trend': trend,
            'momentum_5d': momentum["5d"],
            'momentum_20d': momentum["20d"]
        }

# ================== 9. УМНЫЙ ЛИДЕР ==================
def get_weights_technical_leader(row, current_date, tech_analyzer):
    base_weights, reasons = get_weights_binary_original(row)
    active_funds = [f for f in base_weights if base_weights[f] > 0]
    if len(active_funds) <= 2:
        return base_weights, reasons
    
    fund_analysis = {}
    for fund in active_funds:
        if fund != 'TMON':
            analysis = tech_analyzer.get_phase(fund, current_date)
            fund_analysis[fund] = analysis
            reasons.append(f"{fund}: {analysis['phase']} (RSI={analysis['rsi']:.0f}, моментум={analysis['momentum_5d']:.1f}%)")
    
    fundamental_leader = None
    fundamental_reason = ""
    if row['CBR_RATE'] < 13 and 'TMOS' in active_funds:
        fundamental_leader = 'TMOS'
        fundamental_reason = f"фундаментально (CBR={row['CBR_RATE']:.1f}% < 13%)"
    elif row['DXY'] < 98 and 'TGLD' in active_funds:
        fundamental_leader = 'TGLD'
        fundamental_reason = f"фундаментально (DXY={row['DXY']:.1f} < 98)"
    elif row['CBR_RATE'] > 12 and 'TBRU' in active_funds:
        fundamental_leader = 'TBRU'
        fundamental_reason = f"фундаментально (CBR={row['CBR_RATE']:.1f}% > 12%)"
    
    if fundamental_leader and fundamental_leader in fund_analysis:
        tech = fund_analysis[fundamental_leader]
        if tech['phase'] == "ПЕРЕКУПЛЕННОСТЬ":
            reasons.append(f"{fundamental_leader} в перекупленности - равные веса")
            weight = 1.0 / len(active_funds)
            return {fund: weight if fund in active_funds else 0 for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']}, reasons
        if tech['trend'] in ["strong_up", "up"]:
            reasons.append(f"{fundamental_leader} {fundamental_reason} + технически силён → 50%")
            if fundamental_leader == 'TMOS':
                weights = {'TMOS': 0.5, 'TGLD': 0.25, 'TBRU': 0.25, 'TMON': 0}
            elif fundamental_leader == 'TGLD':
                weights = {'TMOS': 0, 'TGLD': 0.5, 'TBRU': 0.25, 'TMON': 0.25}
            elif fundamental_leader == 'TBRU':
                weights = {'TMOS': 0, 'TGLD': 0.25, 'TBRU': 0.5, 'TMON': 0.25}
            return weights, reasons
        else:
            reasons.append(f"{fundamental_leader} {fundamental_reason}, но технически слаб - равные веса")
    
    weight = 1.0 / len(active_funds)
    reasons.append("Равные веса (нет явного лидера)")
    return {fund: weight if fund in active_funds else 0 for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']}, reasons

# ================== 10. СТРАЖ СТРАТЕГИИ ==================
class StrategyGuard:
    def __init__(self, window=90):
        self.window = window
        self.history = []
        self.errors = 0
        self.warnings = 0
        self.peak_value = 0
        
    def add_checkpoint(self, date, leader_choice, weights, portfolio_value, prices):
        checkpoint = {
            'date': date,
            'leader': leader_choice,
            'weights': weights.copy(),
            'value': portfolio_value,
            'prices': {fund: prices[fund] for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']}
        }
        self.history.append(checkpoint)
        self.peak_value = max(self.peak_value, portfolio_value)
    
    def check_drawdown(self, current_value, threshold=0.1):
        if self.peak_value == 0:
            return True, ""
        drawdown = (self.peak_value - current_value) / self.peak_value
        if drawdown > threshold:
            self.errors += 1
            return False, f"КРИТИЧЕСКАЯ ПРОСАДКА: {drawdown:.1%}"
        elif drawdown > threshold * 0.5:
            self.warnings += 1
            return False, f"Просадка {drawdown:.1%}"
        return True, ""
    
    def get_status(self):
        if self.errors > 2:
            return "КРИТИЧЕСКИЙ РЕЖИМ"
        elif self.warnings > 5:
            return "ПОВЫШЕННОЕ ВНИМАНИЕ"
        else:
            return "НОРМАЛЬНЫЙ РЕЖИМ"

# ================== 11. МЕНЕДЖЕР ДАННЫХ ==================
class DataManager:
    def __init__(self):
        self.prices = None
        self.api_available = self._check_api()
        
    def _check_api(self):
        if not TINKOFF_TOKEN:
            logger.warning("Токен TINKOFF_TOKEN не найден, API недоступен")
            return False
        return True
    
    def _load_from_api(self, fund_name, date_from, date_to):
        figi_map = {
            'TMOS': 'TCS60A101X76',
            'TGLD': 'TCS80A101X50',
            'TBRU': 'TCS60A1039N1',
        }
        if fund_name not in figi_map:
            return None
        url = f"{BASE_URL}/tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles"
        headers = {"Authorization": f"Bearer {TINKOFF_TOKEN}", "Content-Type": "application/json"}
        from_str = date_from.strftime('%Y-%m-%dT%H:%M:%SZ')
        to_str = date_to.strftime('%Y-%m-%dT%H:%M:%SZ')
        payload = {"figi": figi_map[fund_name], "from": from_str, "to": to_str, "interval": "CANDLE_INTERVAL_DAY"}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            if 'candles' in data and data['candles']:
                df_list = []
                for c in data['candles']:
                    date_str = c['time'].replace('Z', '')
                    date = pd.to_datetime(date_str)
                    if hasattr(date, 'tz'):
                        date = date.tz_localize(None)
                    df_list.append({'DATE': date, fund_name: float(c['close']['units']) + float(c['close']['nano'])/1e9})
                if df_list:
                    return pd.DataFrame(df_list).set_index('DATE').sort_index()
            return None
        except Exception as e:
            logger.error(f"Ошибка загрузки {fund_name} через API: {e}")
            return None
    
    def _recalculate_tmon(self):
        cbr_rates = pd.Series(index=self.prices.index)
        for date in self.prices.index:
            cbr_rates[date] = get_cbr_rate(date)
        tmon_values = [100]
        for i in range(1, len(cbr_rates)):
            days = (cbr_rates.index[i] - cbr_rates.index[i-1]).days
            annual_rate = (cbr_rates.iloc[i-1] - 2) / 100
            daily_rate = annual_rate / 365
            new_value = tmon_values[-1] * (1 + daily_rate * days)
            tmon_values.append(new_value)
        self.prices['TMON'] = tmon_values
    
    def _check_freshness(self):
        last_date = self.prices.index[-1]
        days_old = (datetime.now() - last_date).days
        print("\n" + "="*80)
        print("📊 СТАТУС ДАННЫХ")
        print("="*80)
        print(f"   Последняя дата: {last_date.date()}")
        print(f"   Дней с последнего обновления: {days_old}")
        if days_old > 7:
            print("   ⚠️ ВНИМАНИЕ: Данным больше недели!")
        elif days_old > 1:
            print(f"   ✅ Данные актуальны (от {days_old} дней назад)")
        else:
            print("   ✅ Данные абсолютно свежие!")
        print("\n💰 ТЕКУЩИЕ ЦЕНЫ ФОНДОВ:")
        for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']:
            if fund in self.prices.columns:
                price = self.prices[fund].values[-1]
                if pd.isna(price):
                    print(f"   {fund}: данные загружаются...")
                else:
                    print(f"   {fund}: {price:.2f}")
    
    def load_all_data(self):
        global df
        print("\n" + "="*80)
        print("🔄 ЗАГРУЗКА ДАННЫХ")
        print("="*80)
        self.prices = df.copy()
        print("\n🔧 ПРОВЕРКА ДАННЫХ...")
        for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']:
            if fund in self.prices.columns:
                missing = self.prices[fund].isna().sum()
                if missing > 0:
                    self.prices[fund] = self.prices[fund].ffill()
                    print(f"   {fund}: заполнено {missing} пропусков")
                else:
                    print(f"   {fund}: OK, {len(self.prices[fund].dropna())} дней")
        print("\n📊 ЗАГРУЗКА МАКРОДАННЫХ...")
        self.prices['CBR_RATE'] = pd.Series(index=self.prices.index)
        for date in self.prices.index:
            self.prices.loc[date, 'CBR_RATE'] = get_cbr_rate(date)
        print(f"   CBR_RATE: загружено {self.prices['CBR_RATE'].count()} дней")
        macro_cols = ['DXY', 'RVI', 'FED_RATE', 'USD_RUB', 'BRENT', 'XAUUSD', 'US10Y']
        for col in macro_cols:
            if col in df.columns:
                self.prices[col] = df[col]
                print(f"   {col}: загружено {self.prices[col].count()} дней")
        df = self.prices.copy()
        if self.api_available:
            print("\n📡 ЗАГРУЗКА НОВЫХ ДАННЫХ ЧЕРЕЗ API...")
            last_date = self.prices.index[-1]
            today = datetime.now()
            if last_date.date() < today.date():
                print(f"   Последние данные: {last_date.date()}")
                print(f"   Сегодня: {today.date()}")
                print(f"   Загружаем {(today - last_date).days} дней...")
                for fund in ['TMOS', 'TGLD', 'TBRU']:
                    print(f"\n   Загрузка {fund}...")
                    new_data = self._load_from_api(fund, last_date + timedelta(days=1), today)
                    if new_data is not None and len(new_data) > 0:
                        for date, row in new_data.iterrows():
                            self.prices.loc[date, fund] = row[fund]
                        print(f"      ✅ {fund}: +{len(new_data)} дней")
                        last_price = self.prices[fund].values[-1]
                        print(f"      📊 Последняя цена {fund}: {last_price:.2f}")
                    else:
                        print(f"      ⚠️ {fund}: не удалось загрузить данные")
                self.prices = self.prices.sort_index()
                self._recalculate_tmon()
        self._check_freshness()
        return self.prices

# ================== 12. ЗАГРУЗКА ДАННЫХ ==================
data_manager = DataManager()
prices = data_manager.load_all_data()

if prices is None:
    logger.error("❌ Ошибка загрузки данных")
    exit(1)

funds = ['TMOS', 'TGLD', 'TBRU', 'TMON']
tech_analyzer = TechnicalAnalyzer(prices)
guard = StrategyGuard()

# ================== 13. РАСЧЁТ СТРАТЕГИЙ ==================
print("\n" + "="*80)
print("📊 РАСЧЁТ СТРАТЕГИЙ")
print("="*80)

dates = prices.index
all_rebalance_candidates = pd.date_range(start=dates[0], end=dates[-1], freq='MS')
rebalance_dates = [d for d in all_rebalance_candidates if d in dates]

# Базовая бинарная
binary_portfolio = {fund: 25000 / prices[fund].iloc[0] for fund in funds}
binary_values = []
for i, current_date in enumerate(dates):
    current_prices = prices.loc[current_date]
    if current_date in rebalance_dates:
        if current_date in df.index:
            row = df.loc[current_date]
            weights, _ = get_weights_binary_original(row)
            value = sum(binary_portfolio[fund] * current_prices[fund] for fund in funds)
            if value > 0:
                for fund in funds:
                    binary_portfolio[fund] = (value * weights[fund]) / current_prices[fund]
    value = sum(binary_portfolio[fund] * current_prices[fund] for fund in funds)
    binary_values.append(value)

binary_cumulative = pd.Series(binary_values, index=dates)
binary_returns = binary_cumulative.pct_change(fill_method=None)
binary_final = binary_cumulative.iloc[-1]
binary_return = (binary_final / 100000 - 1) * 100
binary_annual = annual_return(binary_cumulative) * 100
binary_sharpe = sharpe_ratio(binary_returns.dropna())
binary_dd = max_drawdown(binary_cumulative) * 100

# Пассивная
passive_portfolio = {fund: 25000 / prices[fund].iloc[0] for fund in funds}
passive_values = []
for current_date in dates:
    current_prices = prices.loc[current_date]
    value = sum(passive_portfolio[fund] * current_prices[fund] for fund in funds)
    passive_values.append(value)

passive_cumulative = pd.Series(passive_values, index=dates)
passive_returns = passive_cumulative.pct_change(fill_method=None)
passive_final = passive_cumulative.iloc[-1]
passive_return = (passive_final / 100000 - 1) * 100
passive_annual = annual_return(passive_cumulative) * 100
passive_sharpe = sharpe_ratio(passive_returns.dropna())
passive_dd = max_drawdown(passive_cumulative) * 100

# Технический лидер с DCA
tech_portfolio = {fund: 25000 / prices[fund].iloc[0] for fund in funds}
tech_values = []
total_deposits = 100000

for i, current_date in enumerate(dates):
    current_prices = prices.loc[current_date]
    if current_date.day == 1 and i > 0:
        for fund in funds:
            tech_portfolio[fund] += (10000 / 4) / current_prices[fund]
        total_deposits += 10000
    if current_date in rebalance_dates:
        if current_date in df.index:
            row = df.loc[current_date]
            weights, reasons = get_weights_technical_leader(row, current_date, tech_analyzer)
            value = sum(tech_portfolio[fund] * current_prices[fund] for fund in funds)
            leader = None
            if weights['TMOS'] == 0.5:
                leader = 'TMOS'
            elif weights['TGLD'] == 0.5:
                leader = 'TGLD'
            elif weights['TBRU'] == 0.5:
                leader = 'TBRU'
            guard.add_checkpoint(current_date, leader, weights, value, {
                'TMOS': current_prices['TMOS'],
                'TGLD': current_prices['TGLD'],
                'TBRU': current_prices['TBRU'],
                'TMON': current_prices['TMON']
            })
            drawdown_ok, drawdown_msg = guard.check_drawdown(value)
            if not drawdown_ok and guard.errors > 2:
                weights = {'TMOS': 0, 'TGLD': 0, 'TBRU': 0, 'TMON': 1.0}
            if value > 0:
                for fund in funds:
                    tech_portfolio[fund] = (value * weights[fund]) / current_prices[fund]
    value = sum(tech_portfolio[fund] * current_prices[fund] for fund in funds)
    tech_values.append(value)

tech_cumulative = pd.Series(tech_values, index=dates)
tech_returns = tech_cumulative.pct_change(fill_method=None)
tech_final = tech_cumulative.iloc[-1]
tech_dd = max_drawdown(tech_cumulative) * 100
tech_sharpe = sharpe_ratio(tech_returns.dropna())

total_months = len([d for d in pd.date_range(start=dates[0], end=dates[-1], freq='MS') if d in dates])
weighted_capital = 100000
for month in range(1, total_months):
    months_worked = total_months - month
    weight = months_worked / total_months
    weighted_capital += 10000 * weight

tech_real_return = (tech_final / weighted_capital - 1) * 100
tech_real_annual = (tech_final / weighted_capital) ** (1/((dates[-1]-dates[0]).days/365.25)) - 1

# ================== 14. ВЫВОД СРАВНЕНИЯ ==================
print("\n" + "="*80)
print("СРАВНЕНИЕ СТРАТЕГИЙ (100 000 ₽)")
print("="*80)
print("-" * 120)
print(f"{'Стратегия':<40} {'Финальная стоимость':>20} {'Доходность':>12} {'Годовая':>10} {'Шарп':>8} {'Просадка':>10}")
print("-" * 120)

print(f"{'1. Бинарная (базовая):':<40} {binary_final:>18.0f} ₽ {binary_return:>11.1f}% {binary_annual:>9.1f}% {binary_sharpe:>7.2f} {binary_dd:>9.1f}%")
print(f"{'2. Пассивная (25%×4):':<40} {passive_final:>18.0f} ₽ {passive_return:>11.1f}% {passive_annual:>9.1f}% {passive_sharpe:>7.2f} {passive_dd:>9.1f}%")
print(f"{'3. Технический лидер + DCA:':<40} {tech_final:>18.0f} ₽ {tech_real_return:>11.1f}%* {tech_real_annual*100:>9.1f}%* {tech_sharpe:>7.2f} {tech_dd:>9.1f}%")
print(f"{'   Вложено:':<40} {total_deposits:>18.0f} ₽ {'Ср.капитал:':>12} {weighted_capital:>7.0f} ₽")
print(f"{'   Прибыль:':<40} {tech_final - total_deposits:>18.0f} ₽ {'*с учётом пополнений':>20}")

print("\nСТАТИСТИКА СТРАЖА:")
print(f"   Статус: {guard.get_status()}")
print(f"   Предупреждений: {guard.warnings}")
print(f"   Ошибок: {guard.errors}")
print(f"   Пиковая стоимость: {guard.peak_value:,.0f} ₽")

# ================== 15. ГРАФИКИ ==================
plt.figure(figsize=(16, 12))

plt.subplot(2, 2, 1)
plt.plot(dates, passive_cumulative, label='Пассивная', linewidth=2, color='black', alpha=0.5)
plt.plot(dates, binary_cumulative, label='Бинарная', linewidth=2, color='blue')
plt.plot(dates, tech_cumulative, label='Технический лидер + DCA', linewidth=2, color='green')
plt.title('Сравнение стратегий', fontsize=14, fontweight='bold')
plt.ylabel('Стоимость (₽)')
plt.legend()
plt.grid(True, alpha=0.3)
plt.axhline(y=100000, color='gray', linestyle='--', alpha=0.3)

plt.subplot(2, 2, 2)
excess_binary = binary_cumulative - passive_cumulative
excess_tech = tech_cumulative - passive_cumulative
plt.plot(dates, excess_binary, label='Бинарная - Пассивная', color='blue', alpha=0.7)
plt.plot(dates, excess_tech, label='Техлидер - Пассивная', color='green', linewidth=2)
plt.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
plt.title('Превышение над пассивной', fontsize=14, fontweight='bold')
plt.ylabel('Разница (₽)')
plt.legend()
plt.grid(True, alpha=0.3)

plt.subplot(2, 2, 3)
for fund in funds:
    norm_price = prices[fund] / prices[fund].iloc[0] * 100000
    plt.plot(norm_price.index, norm_price, label=fund, linewidth=1.5)
plt.title('Динамика фондов', fontsize=14, fontweight='bold')
plt.ylabel('Стоимость (₽)')
plt.legend()
plt.grid(True, alpha=0.3)

plt.subplot(2, 2, 4)
plt.plot(dates, tech_cumulative, label='Стратегия', color='green', linewidth=2)
plt.axhline(y=total_deposits, color='red', linestyle='--', label=f'Вложено: {total_deposits:,.0f} ₽')
plt.fill_between(dates, total_deposits, tech_cumulative, 
                 where=(tech_cumulative > total_deposits), color='green', alpha=0.2)
plt.title('Рост капитала с пополнениями', fontsize=14, fontweight='bold')
plt.ylabel('Стоимость (₽)')
plt.legend()
plt.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('technical_strategy.png', dpi=150)
plt.show()

logger.info("Графики сохранены в technical_strategy.png")

# ================== 16. ИТОГОВЫЕ ВЫВОДЫ ==================
print("\n" + "="*80)
print("ИТОГОВЫЕ ВЫВОДЫ И РЕКОМЕНДАЦИИ")
print("="*80)

print(f"""
РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ (2021-2026):
----------------------------------------------------------------------
🥇 ТЕХНИЧЕСКИЙ ЛИДЕР + DCA:  {tech_real_return:.1f}% доходности, {tech_real_annual*100:.1f}% годовых
    Прибыль: {tech_final - total_deposits:,.0f} ₽ при вложениях {total_deposits:,.0f} ₽

🥈 БИНАРНАЯ СТРАТЕГИЯ:         {binary_return:.1f}% доходности, {binary_annual:.1f}% годовых
🥉 ПАССИВНАЯ (25%×4):          {passive_return:.1f}% доходности, {passive_annual:.1f}% годовых

СТАТУС ЗАЩИТЫ: {guard.get_status()}
   • Предупреждений: {guard.warnings}
   • Ошибок: {guard.errors}
   • Макс. просадка: {tech_dd:.1f}%
""")

# ================== 17. КАЛЬКУЛЯТОР ПОПОЛНЕНИЯ ==================
def rebalance_calculator():
    """Калькулятор для пополнения и ребалансировки портфеля"""
    
    print("\n" + "="*80)
    print("🧮 КАЛЬКУЛЯТОР ПОПОЛНЕНИЯ И РЕБАЛАНСИРОВКИ")
    print("="*80)
    
    try:
        # 1. Вводим текущие суммы
        print("\n📊 ВВЕДИТЕ ТЕКУЩИЕ СУММЫ ПО КАЖДОМУ ФОНДУ:")
        current_amounts = {}
        total_current = 0
        
        for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']:
            amount_str = input(f"Сумма в {fund} (₽): ").replace(',', '').replace(' ', '')
            amount = float(amount_str) if amount_str else 0
            current_amounts[fund] = amount
            total_current += amount
        
        print(f"\n💰 ИТОГО ПОРТФЕЛЬ: {total_current:,.0f} ₽")
        
        # 2. Показываем текущие веса
        print("\n📊 ТЕКУЩАЯ СТРУКТУРА ПОРТФЕЛЯ:")
        for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']:
            weight = (current_amounts[fund] / total_current) * 100 if total_current > 0 else 0
            print(f"   {fund}: {current_amounts[fund]:,.0f} ₽ ({weight:.1f}%)")
        
        # 3. Вводим целевые веса
        print("\n🎯 ВВЕДИТЕ ЦЕЛЕВЫЕ ВЕСА ИЗ СТРАТЕГИИ (в %, например: 25, 50, 25):")
        target_weights = {}
        total_target = 0
        
        for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']:
            weight_str = input(f"Целевой вес {fund} (%): ").replace(',', '.').strip()
            if weight_str:
                weight = float(weight_str)
            else:
                weight = 0
            target_weights[fund] = weight / 100
            total_target += weight / 100
        
        print(f"\n📊 СУММА ВВЕДЁННЫХ ВЕСОВ: {total_target:.1%}")
        
        if abs(total_target - 1.0) > 0.01:
            print(f"⚠️ Сумма весов {total_target:.1%} - должно быть 100%")
            print("   Пожалуйста, введите веса заново (например: 33.3, 33.3, 33.4)")
            return
        
        # 4. Вводим пополнение
        deposit_str = input("\n💵 Сумма пополнения (₽): ").replace(',', '').replace(' ', '')
        deposit = float(deposit_str) if deposit_str else 0
        
        # 5. Берём актуальные цены
        print("\n📈 АКТУАЛЬНЫЕ ЦЕНЫ ФОНДОВ:")
        prices_input = {}
        for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']:
            price = prices[fund].iloc[-1]
            prices_input[fund] = price
            print(f"   {fund}: {price:.2f} ₽")
        
        # 6. Рассчитываем новую сумму портфеля
        new_total = total_current + deposit
        
        print("\n" + "★" * 80)
        print("📊 РЕЗУЛЬТАТЫ РАСЧЁТА")
        print("★" * 80)
        
        print(f"\n💰 Было: {total_current:,.0f} ₽")
        if deposit > 0:
            print(f"➕ Пополнение: {deposit:,.0f} ₽")
        print(f"💰 Стало: {new_total:,.0f} ₽")
        
        print("\n📋 ЧТО НУЖНО СДЕЛАТЬ:")
        print("-" * 60)
        
        # 7. Считаем и выводим действия по каждому фонду
        for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']:
            current_amount = current_amounts[fund]
            target_amount = new_total * target_weights[fund]
            diff = target_amount - current_amount
            
            if diff > 0.01:
                units = diff / prices_input[fund]
                print(f"\n➕ {fund}: НУЖНО КУПИТЬ")
                print(f"   • Сумма: {diff:,.0f} ₽")
                print(f"   • Количество: {units:.2f} шт")
                print(f"   • По цене: {prices_input[fund]:.2f} ₽")
            elif diff < -0.01:
                units = -diff / prices_input[fund]
                print(f"\n➖ {fund}: НУЖНО ПРОДАТЬ")
                print(f"   • Сумма: {-diff:,.0f} ₽")
                print(f"   • Количество: {units:.2f} шт")
                print(f"   • По цене: {prices_input[fund]:.2f} ₽")
            else:
                print(f"\n✅ {fund}: ничего не менять (отклонение {diff:,.0f} ₽)")
        
        # 8. Показываем новую структуру
        print("\n📊 НОВАЯ СТРУКТУРА ПОРТФЕЛЯ:")
        print("-" * 60)
        for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']:
            new_amount = new_total * target_weights[fund]
            print(f"   {fund}: {new_amount:,.0f} ₽ ({target_weights[fund]:.1%})")
        
        # 9. Сохраняем расчёт
        if not os.path.exists('calculations'):
            os.makedirs('calculations')
        
        calc_file = f'calculations/rebalance_{datetime.now().strftime("%Y%m%d_%H%M")}.json'
        with open(calc_file, 'w', encoding='utf-8') as f:
            json.dump({
                'date': str(datetime.now()),
                'current_amounts': current_amounts,
                'total_current': total_current,
                'deposit': deposit,
                'target_weights': target_weights,
                'prices': prices_input,
                'result': {fund: new_total * target_weights[fund] for fund in funds}
            }, f, ensure_ascii=False, indent=2)
        
        print(f"\n📊 Расчёт сохранён в {calc_file}")
        
    except Exception as e:
        logger.error(f"Ошибка в калькуляторе: {e}")
        import traceback
        traceback.print_exc()

# ================== 18. ИНТЕРАКТИВНЫЙ КАЛЬКУЛЯТОР ==================
def interactive_calculator():
    print("\n📋 ВВЕДИТЕ ТЕКУЩИЕ ЗНАЧЕНИЯ:")
    print("-" * 60)
    try:
        cbr = float(input("Ставка ЦБ РФ (%): ").replace(',', '.'))
        brent = float(input("Нефть Brent ($): ").replace(',', '.'))
        usd = float(input("Курс USD/RUB: ").replace(',', '.'))
        rvi = float(input("Индекс RVI: ").replace(',', '.'))
        dxy = float(input("Индекс доллара DXY: ").replace(',', '.'))
        us10y = float(input("Доходность US10Y (%): ").replace(',', '.'))
        fed = float(input("Ставка ФРС (%): ").replace(',', '.'))
        xau = float(input("Золото XAUUSD ($): ").replace(',', '.'))
        row_dict = {
            'CBR_RATE': cbr,
            'BRENT': brent,
            'USD_RUB': usd,
            'RVI': rvi,
            'DXY': dxy,
            'US10Y': us10y,
            'FED_RATE': fed,
            'XAUUSD': xau
        }
        print(f"\n📊 Анализ на основе введённых макроданных до {datetime.now().date()}")
        weights, reasons = get_weights_technical_leader(row_dict, datetime.now(), tech_analyzer)
        print("\n" + "★" * 80)
        print("💡 РЕКОМЕНДАЦИЯ ПО ПОРТФЕЛЮ")
        print("★" * 80)
        if reasons:
            print("\n📋 ОБОСНОВАНИЕ:")
            for r in reasons[-8:]:
                print(f"   {r}")
        print("\n📈 РЕКОМЕНДУЕМЫЕ ВЕСА:")
        print("-" * 40)
        total = 0
        for fund, weight in weights.items():
            if weight > 0:
                print(f"   {fund}: {weight:.1%}")
                total += weight
        print("-" * 40)
        print(f"   ИТОГО: {total:.1%}")
        print("\n📊 ТЕКУЩАЯ СИТУАЦИЯ:")
        print(f"   Ставка ЦБ: {cbr:.1f}%")
        print(f"   Индекс DXY: {dxy:.2f}")
        print(f"   Индекс RVI: {rvi:.2f}")
        print(f"   Курс USD/RUB: {usd:.2f}")
        print("\n💰 АКТУАЛЬНЫЕ ЦЕНЫ ФОНДОВ:")
        for fund in ['TMOS', 'TGLD', 'TBRU', 'TMON']:
            price = prices[fund].iloc[-1]
            print(f"   {fund}: {price:.2f} ₽")
        if not os.path.exists('history'):
            os.makedirs('history')
        history_file = f'history/portfolio_{datetime.now().strftime("%Y%m%d_%H%M")}.json'
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump({
                'date': str(datetime.now()),
                'input_data': row_dict,
                'weights': weights,
                'reasons': reasons
            }, f, ensure_ascii=False, indent=2)
        print(f"\n📊 Данные сохранены в {history_file}")
        return weights
    except Exception as e:
        logger.error(f"Ошибка в интерактивном калькуляторе: {e}")
        return None

# ================== 19. ГЛАВНОЕ МЕНЮ ==================
if __name__ == "__main__":
    while True:
        print("\n" + "="*80)
        print("🤖 ГЛАВНОЕ МЕНЮ")
        print("="*80)
        print("1. 📊 Интерактивный расчёт (с вводом макроданных)")
        print("2. 🧮 Калькулятор пополнения/ребалансировки")
        print("3. 📈 Показать проверку данных (графики)")
        print("4. 🚪 Выход")
        choice = input("\nВыберите действие (1-4): ").strip()
        if choice == '1':
            interactive_calculator()
        elif choice == '2':
            rebalance_calculator()
        elif choice == '3':
            # Здесь можно добавить вызов validate_data
            print("📈 Графики сохранены в technical_strategy.png")
        elif choice == '4':
            print("\n" + "="*80)
            print("✅ РАБОТА ЗАВЕРШЕНА")
            print("   Удачных инвестиций! 🚀")
            print("="*80)
            break
        else:
            print("❌ Неверный выбор")