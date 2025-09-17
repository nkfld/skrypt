#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skrypt obsługi kodów kreskowych dla Odoo Community - wersja macOS
Obsługuje tryby dodawania i zdejmowania towarów z magazynu
Używa wbudowanego odtwarzacza macOS (afplay)
"""

import xmlrpc.client
import time
import sys
import os
import subprocess
import threading
from datetime import datetime

# =============================================================================
# KONFIGURACJA - USTAW TUTAJ SWOJE DANE
# =============================================================================
CONFIG = {
    'url': 'http://212.244.158.38:8071',
    'database': 'odoo17_prod',
    'username': 'admin',
    'password': 'admin',
    'sounds': {
        'add_mode': 'skrypt/sounds/dodawanie.mp3',
        'remove_mode': 'skrypt/sounds/zdejmowanie.mp3',
        'item_removed': 'skrypt/sounds/zdjeto.mp3',
        
        # Nowe dźwięki trybów ilości
        'single_mode': 'skrypt/sounds/trybpojed.mp3',
        'multi_mode': 'skrypt/sounds/trybwiele.mp3',
        
        # Nowe dźwięki dodawania
        'added_one': 'skrypt/sounds/dodawanie.mp3',
        'added_many': 'skrypt/sounds/dodanowiele.mp3',
        
        # Nowe dźwięki zdejmowania
        'removed_one': 'skrypt/sounds/zdjelam.mp3',
        'removed_many': 'skrypt/sounds/zdjwiele.mp3'
    }
}
# =============================================================================

class OdooBarcode:
    def __init__(self, url, db, username, password, sound_paths=None):
        """
        Inicjalizacja połączenia z Odoo
        
        Args:
            url (str): URL serwera Odoo (np. 'http://212.244.158.38:8071')
            db (str): Nazwa bazy danych
            username (str): Nazwa użytkownika
            password (str): Hasło
            sound_paths (dict): Ścieżki do plików dźwiękowych
        """
        self.url = url
        self.db = db
        self.username = username
        self.password = password
        self.uid = None
        self.models = None
        self.mode = None  # 'add' lub 'remove'
        self.location_id = None  # ID lokalizacji magazynowej
        
        # Kody kreskowe do przełączania trybu
        self.ADD_MODE_BARCODE = "dodajetowar"
        self.REMOVE_MODE_BARCODE = "zdejmujetowar"
        self.MULTI_MODE_BARCODE = "wiele"  # Nowy tryb wielokrotności
        self.UNDO_BARCODE = "cofnij"  # Nowy kod cofania
        
        # Produkty które uruchamiają proces produkcyjny
        self.PRODUCTION_PRODUCTS = {
            "202500000076": 1  # Kod kreskowy: BOM ID
        }
        
        # Flagi trybów
        self.multi_mode = False  # Czy pytać o ilość
        
        # Historia operacji (do cofania)
        self.operation_history = []
        
        # Ścieżki do plików dźwiękowych
        self.sound_paths = sound_paths or {}
        self.sound_add_mode = self.sound_paths.get('add_mode', '')
        self.sound_remove_mode = self.sound_paths.get('remove_mode', '')
        self.sound_item_removed = self.sound_paths.get('item_removed', '')
        
        # Nowe dźwięki
        self.sound_single_mode = self.sound_paths.get('single_mode', '')
        self.sound_multi_mode = self.sound_paths.get('multi_mode', '')
        self.sound_added_one = self.sound_paths.get('added_one', '')
        self.sound_added_many = self.sound_paths.get('added_many', '')
        self.sound_removed_one = self.sound_paths.get('removed_one', '')
        self.sound_removed_many = self.sound_paths.get('removed_many', '')
        
        print("✓ Skaner zainicjalizowany dla macOS")
        self.connect()
    
    def play_sound(self, sound_type):
        """
        Odtwarza dźwięk w osobnym wątku używając Linux/HDMI
        
        Args:
            sound_type (str): typ dźwięku do odtworzenia
        """
        def play_sound_thread():
            try:
                sound_file = self.sound_paths.get(sound_type)
                if not sound_file or not os.path.exists(sound_file):
                    return
                
                # Sprawdź dostępne odtwarzacze audio
                players = ['mpv', 'mplayer', 'aplay', 'paplay']
                available_player = None
                
                for player in players:
                    try:
                        subprocess.run(['which', player], capture_output=True, check=True)
                        available_player = player
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue
                
                if not available_player:
                    print("⚠ Nie znaleziono odtwarzacza audio!")
                    return
                
                # Odtwórz dźwięk z wymuszonym wyjściem HDMI
                if available_player == 'mpv':
                    # MPV - najlepszy dla HDMI
                    os.system(f'mpv --no-video --volume=80 "{sound_file}" >/dev/null 2>&1 &')
                elif available_player == 'mplayer':
                    # MPlayer z wymuszeniem HDMI
                    os.system(f'mplayer -ao alsa:device=hw=0,3 -volume 80 "{sound_file}" >/dev/null 2>&1 &')
                elif available_player == 'paplay':
                    # PulseAudio
                    os.system(f'paplay "{sound_file}" &')
                elif available_player == 'aplay' and sound_file.endswith('.wav'):
                    # APLAY tylko dla WAV
                    os.system(f'aplay -D hw:0,3 "{sound_file}" &')
                        
            except Exception as e:
                print(f"⚠ Nie można odtworzyć dźwięku: {e}")
        
        # Uruchom w osobnym wątku żeby nie blokować głównego programu
        valid_sounds = ['add_mode', 'remove_mode', 'item_removed', 'single_mode', 'multi_mode', 
                       'added_one', 'added_many', 'removed_one', 'removed_many']
        if sound_type in valid_sounds:
            thread = threading.Thread(target=play_sound_thread)
            thread.daemon = True
            thread.start()
    
    def connect(self):
        """Nawiązuje połączenie z Odoo"""
        try:
            print(" Łączenie z Odoo...")
            common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            self.uid = common.authenticate(self.db, self.username, self.password, {})
            
            if not self.uid:
                raise Exception("Błąd uwierzytelniania")
            
            self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
            print(f"✓ Połączono z Odoo (User ID: {self.uid})")
            
            # Pobierz domyślną lokalizację magazynową
            self.get_default_location()
            
        except Exception as e:
            print(f"✗ Błąd połączenia: {e}")
            sys.exit(1)
    
    def get_default_location(self):
        """Pobiera domyślną lokalizację magazynową"""
        try:
            # Szukaj lokalizacji typu 'internal' (magazyn)
            locations = self.models.execute_kw(
                self.db, self.uid, self.password,
                'stock.location', 'search_read',
                [[['usage', '=', 'internal']]],
                {'fields': ['id', 'name'], 'limit': 1}
            )
            
            if locations:
                self.location_id = locations[0]['id']
                print(f"✓ Domyślna lokalizacja: {locations[0]['name']} (ID: {self.location_id})")
            else:
                print("⚠ Nie znaleziono lokalizacji magazynowej")
                
        except Exception as e:
            print(f"✗ Błąd pobierania lokalizacji: {e}")
    
    def find_product_by_barcode(self, barcode):
        """
        Wyszukuje produkt po kodzie kreskowym i pobiera aktualny stan
        
        Args:
            barcode (str): Kod kreskowy produktu
            
        Returns:
            dict: Dane produktu lub None
        """
        try:
            products = self.models.execute_kw(
                self.db, self.uid, self.password,
                'product.product', 'search_read',
                [[['barcode', '=', barcode]]],
                {'fields': ['id', 'name', 'barcode']}
            )
            
            if products:
                product = products[0]
                
                # Pobierz aktualny stan magazynowy dla tej lokalizacji
                quants = self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'stock.quant', 'search_read',
                    [[['product_id', '=', product['id']], ['location_id', '=', self.location_id]]],
                    {'fields': ['quantity']}
                )
                
                # Zsumuj ilości ze wszystkich quantów
                total_qty = sum(quant['quantity'] for quant in quants)
                product['qty_available'] = total_qty
                
                return product
            return None
            
        except Exception as e:
            print(f"✗ Błąd wyszukiwania produktu: {e}")
            return None
    
    def add_to_history(self, operation_type, operation_id, product_name, quantity):
        """
        Dodaje operację do historii dla możliwości cofnięcia
        
        Args:
            operation_type (str): 'production', 'stock_move_in', 'stock_move_out'
            operation_id (int): ID operacji w Odoo
            product_name (str): Nazwa produktu
            quantity (float): Ilość
        """
        self.operation_history.append({
            'type': operation_type,
            'id': operation_id,
            'product_name': product_name,
            'quantity': quantity,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
        # Zachowaj tylko ostatnie 10 operacji
        if len(self.operation_history) > 10:
            self.operation_history.pop(0)
    
    def undo_last_operation(self):
        """
        Cofa ostatnią operację
        """
        if not self.operation_history:
            print("⚠ Brak operacji do cofnięcia")
            return False
        
        last_op = self.operation_history.pop()
        
        try:
            if last_op['type'] == 'production':
                # Cofnij zlecenie produkcyjne
                try:
                    # Spróbuj anulować zlecenie
                    self.models.execute_kw(
                        self.db, self.uid, self.password,
                        'mrp.production', 'action_cancel',
                        [last_op['id']]
                    )
                    print(f" Cofnięto produkcję: {last_op['quantity']} szt. {last_op['product_name']}")
                except:
                    # Jeśli nie można anulować, ustaw stan na cancel
                    self.models.execute_kw(
                        self.db, self.uid, self.password,
                        'mrp.production', 'write',
                        [last_op['id'], {'state': 'cancel'}]
                    )
                    print(f" Anulowano produkcję: {last_op['quantity']} szt. {last_op['product_name']}")
                
            elif last_op['type'] in ['stock_move_in', 'stock_move_out']:
                # Cofnij operację magazynową
                try:
                    # Spróbuj anulować picking
                    self.models.execute_kw(
                        self.db, self.uid, self.password,
                        'stock.picking', 'action_cancel',
                        [last_op['id']]
                    )
                    operation_name = "przyjęcie" if last_op['type'] == 'stock_move_in' else "wydanie"
                    print(f" Cofnięto {operation_name}: {last_op['quantity']} szt. {last_op['product_name']}")
                except:
                    # Jeśli nie można anulować, ustaw stan na cancel
                    self.models.execute_kw(
                        self.db, self.uid, self.password,
                        'stock.picking', 'write',
                        [last_op['id'], {'state': 'cancel'}]
                    )
                    operation_name = "przyjęcie" if last_op['type'] == 'stock_move_in' else "wydanie"
                    print(f" Anulowano {operation_name}: {last_op['quantity']} szt. {last_op['product_name']}")
            
            return True
            
        except Exception as e:
            print(f"✗ Błąd cofania operacji: {e}")
            # Przywróć operację do historii jeśli cofnięcie się nie powiodło
            self.operation_history.append(last_op)
            return False
    
    def create_production_order(self, product_id, bom_id, quantity):
        """
        Tworzy zlecenie produkcyjne w Odoo
        
        Args:
            product_id (int): ID produktu do wyprodukowania
            bom_id (int): ID BOM (Bill of Materials)
            quantity (float): Ilość do wyprodukowania
        """
        try:
            # Pobierz informacje o produkcie
            product_info = self.models.execute_kw(
                self.db, self.uid, self.password,
                'product.product', 'read',
                [product_id], {'fields': ['name', 'uom_id']}
            )
            
            if not product_info:
                print(f"✗ Nie znaleziono produktu ID: {product_id}")
                return False
            
            product_name = product_info[0]['name']
            product_uom = product_info[0]['uom_id'][0] if product_info[0]['uom_id'] else 1
            
            # Tworzymy zlecenie produkcyjne
            production_vals = {
                'product_id': product_id,
                'product_qty': quantity,
                'product_uom_id': product_uom,
                'bom_id': bom_id,
                'location_src_id': self.location_id,  # Lokalizacja surowców
                'location_dest_id': self.location_id,  # Lokalizacja produktów gotowych
                'origin': f'Skaner - Produkcja - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                'state': 'draft',
            }
            
            # Utwórz zlecenie produkcyjne
            production_id = self.models.execute_kw(
                self.db, self.uid, self.password,
                'mrp.production', 'create',
                [production_vals]
            )
            
            # Potwierdź zlecenie
            self.models.execute_kw(
                self.db, self.uid, self.password,
                'mrp.production', 'action_confirm',
                [production_id]
            )
            
            # Przypisz dostępność surowców
            try:
                self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'mrp.production', 'action_assign',
                    [production_id]
                )
            except Exception as e:
                print(f"⚠ Nie udało się przypisać surowców: {e}")
            
            # Rozpocznij produkcję
            try:
                self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'mrp.production', 'button_plan',
                    [production_id]
                )
            except:
                # Fallback - ustaw stan na 'progress'
                self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'mrp.production', 'write',
                    [production_id, {'state': 'progress'}]
                )
            
            # Zakończ produkcję automatycznie
            try:
                self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'mrp.production', 'button_mark_done',
                    [production_id]
                )
                print(f"Zlecenie produkcyjne {production_id} ukończone!")
            except Exception as e:
                print(f"Zlecenie produkcyjne {production_id} utworzone (wymaga ręcznego ukończenia)")
                print(f"   Szczegóły: {e}")
            
            print(f"Wyprodukowano {quantity} szt. {product_name}")
            
            # Dodaj do historii
            self.add_to_history('production', production_id, product_name, quantity)
            
            return True
            
        except Exception as e:
            print(f"✗ Błąd tworzenia zlecenia produkcyjnego: {e}")
            import traceback
            print(f"Szczegóły błędu: {traceback.format_exc()}")
            return False
    
    def create_stock_move(self, product_id, quantity, move_type='in'):
        """
        Tworzy przyjęcie lub wydanie w Odoo - wersja uproszczona
        
        Args:
            product_id (int): ID produktu
            quantity (float): Ilość
            move_type (str): 'in' dla przyjęcia, 'out' dla wydania
        """
        try:
            if move_type == 'in':
                # PRZYJĘCIE - z lokalizacji dostawcy do magazynu
                source_location = self.get_supplier_location()
                dest_location = self.location_id
                picking_type = self.get_picking_type('incoming')
                operation_name = "Przyjęcie"
            else:
                # WYDANIE - z magazynu do lokalizacji klienta
                source_location = self.location_id
                dest_location = self.get_customer_location()
                picking_type = self.get_picking_type('outgoing')
                operation_name = "Wydanie"
            
            # Pobierz informacje o produkcie dla jednostki miary
            product_info = self.models.execute_kw(
                self.db, self.uid, self.password,
                'product.product', 'read',
                [product_id], {'fields': ['uom_id', 'name']}
            )
            product_uom = product_info[0]['uom_id'][0] if product_info[0]['uom_id'] else 1
            
            # Tworzymy dokument magazynowy (picking)
            picking_vals = {
                'picking_type_id': picking_type,
                'location_id': source_location,
                'location_dest_id': dest_location,
                'origin': f'Skaner - {operation_name} - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                'state': 'draft',
            }
            
            picking_id = self.models.execute_kw(
                self.db, self.uid, self.password,
                'stock.picking', 'create',
                [picking_vals]
            )
            
            # Tworzymy linię ruchu magazynowego
            move_vals = {
                'name': f'{operation_name}: {product_info[0]["name"]}',
                'product_id': product_id,
                'product_uom_qty': quantity,
                'product_uom': product_uom,
                'picking_id': picking_id,
                'location_id': source_location,
                'location_dest_id': dest_location,
                'state': 'draft',
            }
            
            move_id = self.models.execute_kw(
                self.db, self.uid, self.password,
                'stock.move', 'create',
                [move_vals]
            )
            
            # Potwierdzamy dokument
            self.models.execute_kw(
                self.db, self.uid, self.password,
                'stock.picking', 'action_confirm',
                [picking_id]
            )
            
            # Ustawmy na ruch magazynowy, że ma być "dostępny"
            self.models.execute_kw(
                self.db, self.uid, self.password,
                'stock.move', 'write',
                [move_id, {'state': 'assigned'}]
            )
            
            # Użyj metody _action_done bezpośrednio na ruchu
            try:
                self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'stock.move', '_action_done',
                    [move_id]
                )
            except:
                # Fallback - spróbuj z action_done na stock.move
                try:
                    self.models.execute_kw(
                        self.db, self.uid, self.password,
                        'stock.move', 'action_done',
                        [move_id]
                    )
                except:
                    # Fallback - użyj button_validate na picking
                    try:
                        self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'stock.picking', 'button_validate',
                            [picking_id]
                        )
                    except:
                        # Ostateczny fallback - ustaw stany ręcznie
                        self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'stock.picking', 'write',
                            [picking_id, {'state': 'done'}]
                        )
                        self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'stock.move', 'write',
                            [move_id, {'state': 'done'}]
                        )
            
            print(f"📋 Utworzono dokument {operation_name} ID: {picking_id}")
            
            # Dodaj do historii
            history_type = 'stock_move_in' if move_type == 'in' else 'stock_move_out'
            self.add_to_history(history_type, picking_id, product_info[0]['name'], quantity)
            
            return True
            
        except Exception as e:
            print(f"✗ Błąd tworzenia dokumentu magazynowego: {e}")
            # Szczegółowy błąd dla debugowania
            import traceback
            print(f"Szczegóły błędu: {traceback.format_exc()}")
            return False
    
    def get_supplier_location(self):
        """Pobiera ID lokalizacji dostawcy"""
        try:
            locations = self.models.execute_kw(
                self.db, self.uid, self.password,
                'stock.location', 'search',
                [[['usage', '=', 'supplier']]],
                {'limit': 1}
            )
            return locations[0] if locations else 8  # Domyślne ID lokalizacji dostawcy
        except:
            return 8
    
    def get_customer_location(self):
        """Pobiera ID lokalizacji klienta"""
        try:
            locations = self.models.execute_kw(
                self.db, self.uid, self.password,
                'stock.location', 'search',
                [[['usage', '=', 'customer']]],
                {'limit': 1}
            )
            return locations[0] if locations else 9  # Domyślne ID lokalizacji klienta
        except:
            return 9
    
    def get_picking_type(self, operation_type):
        """
        Pobiera typ operacji magazynowej
        
        Args:
            operation_type (str): 'incoming' lub 'outgoing'
        """
        try:
            picking_types = self.models.execute_kw(
                self.db, self.uid, self.password,
                'stock.picking.type', 'search',
                [[['code', '=', operation_type]]],
                {'limit': 1}
            )
            return picking_types[0] if picking_types else 1
        except:
            return 1
    
    def process_barcode(self, barcode):
        """
        Przetwarza zeskanowany kod kreskowy
        
        Args:
            barcode (str): Kod kreskowy
        """
        barcode = barcode.strip()
        
        # Sprawdź czy to kod przełączania trybu
        if barcode == self.ADD_MODE_BARCODE:
            self.mode = 'add'
            print(" Tryb: DODAWANIE towarów")
            self.play_sound('add_mode')  # Odtwórz dźwięk trybu dodawania
            return
        elif barcode == self.REMOVE_MODE_BARCODE:
            self.mode = 'remove'
            print(" Tryb: ZDEJMOWANIE towarów")
            self.play_sound('remove_mode')  # Odtwórz dźwięk trybu zdejmowania
            return
        elif barcode == self.MULTI_MODE_BARCODE:
            self.multi_mode = not self.multi_mode  # Przełącz tryb wielokrotności
            if self.multi_mode:
                print("Tryb WIELE: Będę pytać o ilość")
                self.play_sound('multi_mode')  # Dźwięk trybu wiele
            else:
                print("Tryb POJEDYNCZY: Domyślnie 1 sztuka")
                self.play_sound('single_mode')  # Dźwięk trybu pojedynczego
            return
        elif barcode == self.UNDO_BARCODE:
            # Cofnij ostatnią operację
            success = self.undo_last_operation()
            if success:
                remaining = len(self.operation_history)
                print(f" Pozostało {remaining} operacji do cofnięcia")
            return
        
        # Sprawdź czy tryb został ustawiony
        if not self.mode:
            print("Najpierw zeskanuj kod wyboru trybu!")
            return
        
        # Wyszukaj produkt
        product = self.find_product_by_barcode(barcode)
        if not product:
            print(f"Nie znaleziono produktu o kodzie: {barcode}")
            return
        
        # Pobierz ilość do przetworzenia
        if self.multi_mode:
            # Tryb wielokrotności - pytaj o ilość
            try:
                quantity = float(input(f"Podaj ilość dla {product['name']}: "))
                if quantity <= 0:
                    print("Ilość musi być większa od 0")
                    return
            except ValueError:
                print("Nieprawidłowa ilość")
                return
        else:
            # Tryb pojedynczy - domyślnie 1 sztuka
            quantity = 1.0
            print(f"{product['name']} - ilość: {quantity} szt. (dostępne: {product['qty_available']} szt.)")
        
        # Wykonaj operację magazynową
        if self.mode == 'add':
            # Sprawdź czy to produkt produkcyjny
            if barcode in self.PRODUCTION_PRODUCTS:
                bom_id = self.PRODUCTION_PRODUCTS[barcode]
                success = self.create_production_order(product['id'], bom_id, quantity)
                if success:
                    print(f"Rozpoczęto produkcję {quantity} szt. {product['name']}")
                    # Odtwórz odpowiedni dźwięk dodawania
                    if quantity == 1:
                        self.play_sound('added_one')
                    else:
                        self.play_sound('added_many')
                else:
                    print(f"✗ Błąd uruchomienia produkcji")
            else:
                # Zwykłe przyjęcie towaru
                success = self.create_stock_move(product['id'], quantity, 'in')
                if success:
                    print(f"Dodano {quantity} szt. {product['name']}")
                    # Odtwórz odpowiedni dźwięk dodawania
                    if quantity == 1:
                        self.play_sound('added_one')
                    else:
                        self.play_sound('added_many')
                else:
                    print(f"Błąd dodawania towaru")
        elif self.mode == 'remove':
            # Sprawdź dostępność towaru
            if product['qty_available'] < quantity:
                print(f"Niewystarczająca ilość w magazynie. Dostępne: {product['qty_available']}")
                confirm = input("Czy kontynuować? (t/n): ")
                if confirm.lower() not in ['t', 'tak', 'y', 'yes']:
                    return
            
            success = self.create_stock_move(product['id'], quantity, 'out')
            if success:
                print(f"Zdjęto {quantity} szt. {product['name']}")
                # Odtwórz odpowiedni dźwięk zdejmowania
                if quantity == 1:
                    self.play_sound('removed_one')
                else:
                    self.play_sound('removed_many')
            else:
                print(f"✗ Błąd zdejmowania towaru")
    
    def run(self):
        """Główna pętla programu"""
        print("\n" + "="*50)
        print("     SKANER KODÓW KRESKOWYCH - ODOO (macOS)")
        print("="*50)
        print(f"Kod dodawania: {self.ADD_MODE_BARCODE}")
        print(f"Kod zdejmowania: {self.REMOVE_MODE_BARCODE}")
        print(f"Kod wielokrotności: {self.MULTI_MODE_BARCODE}")
        print(f"Kod cofania: {self.UNDO_BARCODE}")
        print("Tryby:")
        print("• Domyślnie: 1 sztuka na skan")
        print("• 'wiele' → pytaj o ilość")
        print("• 'wiele' ponownie → powrót do 1 sztuki")
        print("• 'cofnij' → cofa ostatnią operację")
        print(" Produkty produkcyjne:")
        print("• 202500000076 → uruchamia proces produkcyjny")
        print("\nAby zakończyć, wpisz 'exit' lub 'quit'")
        print("="*50)
        
        while True:
            try:
                barcode = input("\nZeskanuj kod kreskowy: ").strip()
                
                if barcode.lower() in ['exit', 'quit', 'wyjście']:
                    print(" Zamykanie programu...")
                    break
                
                if not barcode:
                    continue
                
                self.process_barcode(barcode)
                
            except KeyboardInterrupt:
                print(" Program zakończony przez użytkownika")
                break
            except Exception as e:
                print(f"Nieoczekiwany błąd: {e}")

def main():
    """Funkcja główna"""
    print("===  SCANNER ===")
    
    # Sprawdź czy chcesz użyć domyślnej konfiguracji
    use_config = input(f"Użyć domyślnej konfiguracji? (t/n) [URL: {CONFIG['url']}, DB: {CONFIG['database']}]: ").strip().lower()
    
    if use_config in ['t', 'tak', 'y', 'yes', '']:
        # Użyj konfiguracji z góry pliku
        URL = CONFIG['url']
        DB = CONFIG['database']
        USERNAME = CONFIG['username']
        PASSWORD = CONFIG['password']
        
        print(f"connecting to:")
        print(f"  URL: {URL}")
        print(f"  Baza: {DB}")
        print(f"  User: {USERNAME}")
        
        # Sprawdź ścieżki dźwięków
        sound_paths = {}
        for sound_type, path in CONFIG['sounds'].items():
            full_path = os.path.expanduser(f"~/{path}")  # Rozwiń ścieżkę z ~
            if os.path.exists(full_path):
                sound_paths[sound_type] = full_path
                print(f"Dźwięk {sound_type}: {full_path}")
            else:
                print(f"Nie znaleziono: {full_path}")
    
    else:
        # Pytaj o dane ręcznie
        print("Konfiguracja połączenia z Odoo:")
        URL = input("URL serwera Odoo (np. http://localhost:8069): ").strip()
        DB = input("Nazwa bazy danych: ").strip()
        USERNAME = input("Nazwa użytkownika: ").strip()
        PASSWORD = input("Hasło: ").strip()
        
        if not all([URL, DB, USERNAME, PASSWORD]):
            print("Wszystkie pola są wymagane!")
            sys.exit(1)
        
        # Konfiguracja dźwięków
        print("\nKonfiguracja dźwięków MP3:")
        sound_add_mode = input("Ścieżka do dźwięku trybu DODAWANIA (Enter aby pominąć): ").strip()
        sound_remove_mode = input("Ścieżka do dźwięku trybu ZDEJMOWANIA (Enter aby pominąć): ").strip()
        sound_item_removed = input("Ścieżka do dźwięku po ZDJĘCIU towaru (Enter aby pominąć): ").strip()
        
        # Sprawdź czy pliki istnieją
        sound_paths = {}
        if sound_add_mode and os.path.exists(sound_add_mode):
            sound_paths['add_mode'] = sound_add_mode
            print(f"Dźwięk trybu dodawania: {sound_add_mode}")
        elif sound_add_mode:
            print(f"Nie znaleziono pliku: {sound_add_mode}")
        
        if sound_remove_mode and os.path.exists(sound_remove_mode):
            sound_paths['remove_mode'] = sound_remove_mode
            print(f"Dźwięk trybu zdejmowania: {sound_remove_mode}")
        elif sound_remove_mode:
            print(f"Nie znaleziono pliku: {sound_remove_mode}")
        
        if sound_item_removed and os.path.exists(sound_item_removed):
            sound_paths['item_removed'] = sound_item_removed
            print(f"Dźwięk po zdjęciu towaru: {sound_item_removed}")
        elif sound_item_removed:
            print(f"Nie znaleziono pliku: {sound_item_removed}")
    
    # Uruchom skaner
    scanner = OdooBarcode(URL, DB, USERNAME, PASSWORD, sound_paths)
    scanner.run()

if __name__ == "__main__":
    main()
