# watchlist_manager.py
import json
import os
from datetime import datetime, timedelta

class WatchlistManager:
    """
    Управление списком перспективных сигналов (группа Б)
    """
    def __init__(self, filename="watchlist.json"):
        self.filename = filename
        self.watchlist = []
        self.load()
    
    def load(self):
        """Загружает watchlist из файла"""
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.watchlist = data.get('watchlist', [])
                    print(f"📋 Загружен watchlist: {len(self.watchlist)} перспективных сигналов")
            except Exception as e:
                print(f"⚠️ Ошибка загрузки watchlist: {e}")
                self.watchlist = []
        else:
            self.watchlist = []
    
    def save(self):
        """Сохраняет watchlist в файл"""
        data = {
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'watchlist': self.watchlist
        }
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def add(self, ticker, quality, sector, signal_type, details=""):
        """Добавляет сигнал в watchlist"""
        # Проверяем, нет ли уже
        for item in self.watchlist:
            if item['ticker'] == ticker:
                return False
        
        self.watchlist.append({
            'ticker': ticker,
            'quality': quality,
            'sector': sector,
            'signal_type': signal_type,  # LONG/SHORT
            'added': datetime.now().strftime('%Y-%m-%d'),
            'details': details,
            'status': 'waiting'  # waiting, approached, entered
        })
        self.save()
        return True
    
    def remove(self, ticker):
        """Удаляет сигнал из watchlist"""
        self.watchlist = [item for item in self.watchlist if item['ticker'] != ticker]
        self.save()
    
    def update_status(self, ticker, status):
        """Обновляет статус сигнала"""
        for item in self.watchlist:
            if item['ticker'] == ticker:
                item['status'] = status
                self.save()
                return True
        return False
    
    def get_active(self):
        """Возвращает активные сигналы (waiting и approached)"""
        return [item for item in self.watchlist if item['status'] in ['waiting', 'approached']]
    
    def print_watchlist(self):
        """Выводит текущий watchlist"""
        if not self.watchlist:
            print("\n📋 Перспективный список пуст")
            return
        
        print("\n" + "="*80)
        print("📋 ПЕРСПЕКТИВНЫЙ СПИСОК (группа Б из прошлых сканов)")
        print("="*80)
        
        # Сортируем по качеству
        sorted_list = sorted(self.watchlist, key=lambda x: x['quality'], reverse=True)
        
        for item in sorted_list:
            days_waiting = (datetime.now() - datetime.strptime(item['added'], '%Y-%m-%d')).days
            status_emoji = "⏳" if item['status'] == 'waiting' else "📍" if item['status'] == 'approached' else "✅"
            
            print(f"\n{status_emoji} {item['ticker']} | Качество: {item['quality']} | {item['sector']} | {item['signal_type']}")
            print(f"   В списке с {item['added']} ({days_waiting} дн.)")
            if item.get('details'):
                print(f"   📊 {item['details']}")
    
    def sync_with_signals(self, signals, min_quality=60):
        """
        Синхронизирует watchlist с текущими сигналами
        - Добавляет новые качественные сигналы группы Б
        - Удаляет те, которые перешли в группу А
        """
        # Находим новые качественные сигналы группы Б
        new_signals = []
        for s in signals:
            if s.get('group') == 'B' and s.get('Качество', 0) >= min_quality:
                new_signals.append(s)
        
        # Добавляем новые
        added = 0
        for s in new_signals:
            if self.add(s['Тикер'], s['Качество'], s.get('sector_name', 'Неизвестно'), 
                       'LONG' if 'LONG' in s['Сигнал'] else 'SHORT',
                       s.get('fundamental_reasons', '')):
                added += 1
                print(f"  ➕ Добавлен в watchlist: {s['Тикер']} (качество {s['Качество']})")
        
        if added:
            print(f"\n📋 Добавлено {added} новых перспективных сигналов")
        
        # Проверяем, не перешли ли сигналы в группу А
        removed = []
        for item in self.watchlist:
            # Ищем сигнал в текущих
            for s in signals:
                if s['Тикер'] == item['ticker'] and s.get('group') == 'A':
                    removed.append(item['ticker'])
                    break
        
        for ticker in removed:
            self.remove(ticker)
            print(f"  ✅ Удален из watchlist: {ticker} (перешел в группу А)")
        
        return added, len(removed)