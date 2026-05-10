# fundamental_loader.py
import os
import pandas as pd
import json
from datetime import datetime

class FundamentalDataLoader:
    """
    Базовый класс для загрузки и управления фундаментальными данными
    """
    def __init__(self, base_path='fundamental_data'):
        self.base_path = base_path
        self.auto_path = os.path.join(base_path, 'auto')
        self.manual_path = os.path.join(base_path, 'manual')
        self.news_path = os.path.join(base_path, 'news')
        self.config_path = os.path.join(base_path, 'config')
        
        # Словарь для хранения загруженных данных
        self.data = {}
        
        # Загружаем конфигурацию если есть
        self.load_config()
    
    def load_config(self):
        """Загружает конфигурацию"""
        config_file = os.path.join(self.config_path, 'settings.json')
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        else:
            self.config = {
                'last_update': {},
                'sources': {},
                'sectors': ['oil_gas', 'metals', 'finance', 'consumer', 'tech']
            }
            self.save_config()
    
    def save_config(self):
        """Сохраняет конфигурацию"""
        config_file = os.path.join(self.config_path, 'settings.json')
        os.makedirs(self.config_path, exist_ok=True)
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    def load_csv(self, filepath):
        """Загружает CSV файл"""
        if os.path.exists(filepath):
            try:
                df = pd.read_csv(filepath, parse_dates=['date'])
                return df
            except Exception as e:
                print(f"⚠️ Ошибка загрузки {filepath}: {e}")
                return None
        return None
    
    def save_csv(self, df, filepath):
        """Сохраняет DataFrame в CSV"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        print(f"💾 Данные сохранены в {filepath}")
    
    def get_macro_data(self, indicator, source='auto'):
        """
        Получает макро-данные по индикатору
        indicator: 'brent', 'usdrub', 'cbr_rate' и т.д.
        source: 'auto' или 'manual'
        """
        if source == 'auto':
            filepath = os.path.join(self.auto_path, 'macro', f'{indicator}.csv')
        else:
            filepath = os.path.join(self.manual_path, 'macro', f'{indicator}.csv')
        
        return self.load_csv(filepath)
    
    def update_auto_data(self, indicator, df):
        """
        Обновляет автоматические данные
        """
        filepath = os.path.join(self.auto_path, 'macro', f'{indicator}.csv')
        
        # Загружаем существующие данные
        existing = self.load_csv(filepath)
        
        if existing is not None:
            # Объединяем и убираем дубликаты
            combined = pd.concat([existing, df]).drop_duplicates('date')
            combined = combined.sort_values('date')
        else:
            combined = df.sort_values('date')
        
        self.save_csv(combined, filepath)
        
        # Обновляем конфиг
        self.config['last_update'][f'auto_{indicator}'] = datetime.now().strftime('%Y-%m-%d %H:%M')
        self.save_config()
        
        return combined
    
    def add_manual_data(self, indicator, data_dict):
        """
        Добавляет ручные данные (одной строкой)
        data_dict: {'date': '2026-03-07', 'value': 15.5, 'note': 'снижение ставки'}
        """
        filepath = os.path.join(self.manual_path, 'macro', f'{indicator}.csv')
        
        # Создаем DataFrame из новых данных
        new_df = pd.DataFrame([data_dict])
        if 'date' in new_df.columns:
            new_df['date'] = pd.to_datetime(new_df['date'])
        
        # Загружаем существующие
        existing = self.load_csv(filepath)
        
        if existing is not None:
            combined = pd.concat([existing, new_df]).drop_duplicates('date')
            combined = combined.sort_values('date')
        else:
            combined = new_df
        
        self.save_csv(combined, filepath)
        
        # Обновляем конфиг
        self.config['last_update'][f'manual_{indicator}'] = datetime.now().strftime('%Y-%m-%d %H:%M')
        self.save_config()
        
        return combined
    
    def get_trend(self, indicator, period=30, source='auto'):
        """
        Определяет тренд индикатора
        Возвращает: -1 (падение), 0 (боковик), 1 (рост)
        """
        df = self.get_macro_data(indicator, source)
        if df is None or len(df) < 2:
            return 0
        
        # Берем последние period дней
        recent = df.tail(min(period, len(df)))
        
        if 'value' in recent.columns:
            values = recent['value'].values
        elif 'close' in recent.columns:
            values = recent['close'].values
        elif 'rate' in recent.columns:
            values = recent['rate'].values
        else:
            # Пробуем найти числовую колонку
            numeric_cols = recent.select_dtypes(include=['float64', 'int64']).columns
            if len(numeric_cols) == 0:
                return 0
            values = recent[numeric_cols[0]].values
        
        if len(values) < 2:
            return 0
        
        change = (values[-1] - values[0]) / values[0]
        
        if change > 0.03:  # рост более 3%
            return 1
        elif change < -0.03:  # падение более 3%
            return -1
        else:
            return 0
    
    def list_available_data(self):
        """
        Показывает все доступные данные
        """
        print("\n📊 ДОСТУПНЫЕ ДАННЫЕ:")
        
        # Автоматические макро-данные
        auto_macro = os.path.join(self.auto_path, 'macro')
        if os.path.exists(auto_macro):
            files = [f for f in os.listdir(auto_macro) if f.endswith('.csv')]
            if files:
                print(f"\n   🤖 Автоматические:")
                for f in files:
                    df = self.load_csv(os.path.join(auto_macro, f))
                    if df is not None:
                        print(f"      {f}: {len(df)} записей")
        
        # Ручные макро-данные
        manual_macro = os.path.join(self.manual_path, 'macro')
        if os.path.exists(manual_macro):
            files = [f for f in os.listdir(manual_macro) if f.endswith('.csv')]
            if files:
                print(f"\n   ✍️ Ручные:")
                for f in files:
                    df = self.load_csv(os.path.join(manual_macro, f))
                    if df is not None:
                        print(f"      {f}: {len(df)} записей")
        
        print(f"\n📅 Последние обновления:")
        for key, value in self.config.get('last_update', {}).items():
            print(f"   {key}: {value}")