from AlgorithmImports import *
from collections import defaultdict, deque
from datetime import timedelta
from QuantConnect.Indicators import RollingWindow
import time

class SimplifiedSectorGrowthMACDStrategy(QCAlgorithm):
    def Initialize(self):
        self.setup_strategy_parameters()
        self.define_symbols()
        self.register_symbols()
        self.initialize_indicators()
        self.debug_queue = deque()
        self.last_debug_time = datetime.now()
        self.initial_purchase_price = {}

    def register_symbols(self):
        for symbol in self.symbols:
            self.AddEquity(symbol, Resolution.Minute)

    def setup_strategy_parameters(self):
        self.SetStartDate(2020, 1, 1)  # Set Start Date
        self.SetCash(10000)  # Set Strategy Cash
        self.spySymbol = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage, AccountType.Margin)

    def define_symbols(self):
        tech_ai_symbols = ["AAPL", "GOOG", "MSFT", "AMZN", "FB", "NVDA", "TSLA", "AMD", "INTC", "CRM",
                           "ORCL", "CSCO", "IBM", "ADBE", "QCOM", "TXN", "SHOP", "SAP", "TWTR", "UBER"]
        tech_leveraged_etfs = ["TQQQ", "SOXL", "UPRO", "SPXL", "TECL", "FNGU"]
        self.symbols = tech_ai_symbols + tech_leveraged_etfs

    def initialize_indicators(self):
        macd_fast, macd_slow, macd_signal = 120, 130, 45
        self.macd_indicators = {}
        self.macd_windows = defaultdict(lambda: RollingWindow[float](10))
        self.macd_slopes = defaultdict(lambda: RollingWindow[float](10))
        self.macd_slope_ema = {}
        self.max_portfolio_value = {symbol: 0 for symbol in self.symbols}
        self.has_logged_drawdown = {symbol: False for symbol in self.symbols}
        self.lastLogged = {symbol: self.Time for symbol in self.symbols}
        self.significant_drawdown = 0.10  # 10% drawdown threshold
        self.rsi_indicators = {symbol: self.RSI(symbol, 14, MovingAverageType.Wilders, Resolution.Minute) for symbol in self.symbols}
        self.volume_windows = defaultdict(lambda: RollingWindow[float](10))  # Adjust the window size as needed
        self.average_volume = {}

        for symbol in self.symbols:
            asset = self.AddEquity(symbol, Resolution.Minute)
            asset.SetDataNormalizationMode(DataNormalizationMode.Adjusted)
            self.macd_indicators[symbol] = self.MACD(symbol, macd_fast, macd_slow, macd_signal, MovingAverageType.Wilders, Resolution.Minute)

    def update_volume_metrics(self, symbol):
        volume = self.Securities[symbol].Volume
        self.volume_windows[symbol].Add(volume)
        if self.volume_windows[symbol].Count > 0:
            self.average_volume[symbol] = sum(self.volume_windows[symbol]) / self.volume_windows[symbol].Count

    def OnData(self, data):
        for symbol in self.symbols:
            macd = self.macd_indicators[symbol]
            holding = self.Portfolio[symbol]
            self.update_volume_metrics(symbol)
            self.update_macd_metrics(symbol, macd)
            if self.should_sell(symbol, holding):
                self.sell_security(symbol)
            elif self.should_buy(symbol, macd, holding):
                self.buy_security(symbol, holding)
            self.rate_limited_debug()

    def update_macd_metrics(self, symbol, macd):
        price = self.Portfolio[symbol].Price
        quantity = self.Portfolio[symbol].Quantity
        self.max_portfolio_value[symbol] = max(self.max_portfolio_value[symbol], quantity * price)
        self.macd_windows[symbol].Add(macd.Current.Value)
        if self.macd_windows[symbol].Count > 1:
            current_macd = self.macd_windows[symbol][0]
            previous_macd = self.macd_windows[symbol][1]
            current_slope = current_macd - previous_macd
            self.macd_slopes[symbol].Add(current_slope)
            if self.macd_slopes[symbol].Count >= 10:
                self.macd_slope_ema[symbol] = self.CalculateEMA(self.macd_slopes[symbol], 10)

    #quantconnect doesn't like it if we log too much -- should probably switch to a log file
    def rate_limited_debug(self):
            current_time = datetime.now()
            time_difference = (current_time - self.last_debug_time).total_seconds()

            # Check if at least half a second has passed since the last debug message
            if time_difference >= 0.5:
                messages_to_print = min(2, len(self.debug_queue))  # Determine how many messages to print, up to 2
                for _ in range(messages_to_print):
                    if self.debug_queue:
                        message = self.debug_queue.popleft()
                        self.Debug(message)

                # Update the last debug time only if messages were printed
                if messages_to_print > 0:
                    self.last_debug_time = current_time

    def queue_debug_message(self, message):
        self.debug_queue.append(message)

    def should_sell(self, symbol, holding):
        # Ensure that we have a positive quantity of the asset
        if not holding.Invested:
            return False

        macd = self.macd_indicators[symbol]
        rsi = self.rsi_indicators[symbol].Current.Value
        price = self.Securities[symbol].Price
        volume = self.Securities[symbol].Volume

        # Check for overbought condition and divergence
        if rsi > 70 and volume > self.average_volume[symbol] * 1.2:
            self.queue_debug_message(f"Selling {symbol} due to overbought RSI and high volume.")
            return True
        
        # Enhanced MACD condition
        if self.macd_slope_ema.get(symbol, 1) <= 0: #and volume > self.average_volume[symbol] * 1.2:
            self.queue_debug_message(f"Selling {symbol} due to negative MACD slope and high volume.")
            return True

        return False

    def should_buy(self, symbol, macd, holding):
        rsi = self.rsi_indicators[symbol].Current.Value
        volume = self.Securities[symbol].Volume
        # Check if MACD line has crossed above the Signal line for a bullish signal
        is_bullish_cross = macd.Current.Value > macd.Signal.Current.Value and macd.Current.Value - macd.Signal.Current.Value > 0
        if not holding.Invested and is_bullish_cross and rsi < 30 and volume > self.average_volume[symbol] * 1.2:
            self.queue_debug_message(f"Buying {symbol} due to bullish MACD crossover, low RSI, and high volume.")
            return True
        return False
    
    def sell_security(self, symbol, reason=""):
        self.SetHoldings(symbol, 0)
        # Capture the current price for logging
        current_price = self.Securities[symbol].Price
        # Assuming you have a way to calculate gain/loss in $ and %, you can add it to the message
        self.queue_debug_message(f"Selling {symbol} at ${current_price:.2f} due to {reason}. Detailed gain/loss metrics will be calculated upon order fill.")

    def buy_security(self, symbol, holding, reason=""):
        max_investment_size = self.Portfolio.TotalPortfolioValue * 0.20
        cashToInvest = min(self.Portfolio.Cash, max_investment_size - (holding.Quantity * holding.Price))
        quantity = self.CalculateOrderQuantity(symbol, cashToInvest / self.Portfolio.TotalPortfolioValue)
        if quantity > 0:
            self.MarketOrder(symbol, quantity)
            # Capture the current price for logging
            current_price = self.Securities[symbol].Price
            self.initial_purchase_price[symbol] = current_price
            self.queue_debug_message(f"Buy order for {symbol}: Quantity: {quantity} at ${current_price:.2f}. Reason: {reason}.")


    def CalculateEMA(self, rolling_window, period):
        k = 2 / (period + 1)
        ema = rolling_window[0]  # Initialize EMA with the most recent value from the rolling window
        for i in range(1, rolling_window.Count):  # Iterate over the rolling window
            value = rolling_window[i]
            ema = value * k + ema * (1 - k)
        return ema

    def IsStrongUpwardCross(self, macd, symbol):
        if self.macd_windows[symbol].Count > 1:
            previous_macd = self.macd_windows[symbol][1]
            previous_signal = macd.Signal.Current.Value
            current_macd = macd.Current.Value
            current_signal = macd.Signal.Current.Value
            if previous_macd < previous_signal and current_macd > current_signal:
                current_slope = self.macd_slopes[symbol][0] if self.macd_slopes[symbol].Count > 0 else 0
                previous_slope = self.macd_slopes[symbol][1] if self.macd_slopes[symbol].Count > 1 else 0
                if current_slope > 0 and current_slope > previous_slope:
                    history = self.History([symbol], 2, Resolution.Daily)
                    if not history.empty:
                        # Check if the symbol is present in the DataFrame's index
                        if symbol in history.index.get_level_values('symbol').unique():
                            volume = history.loc[symbol, 'volume']
                            average_volume = volume.mean() if len(volume) > 1 else volume.iloc[0]
                            current_volume = volume.iloc[-1]
                            volume_factor = 1.2
                            if current_signal != 0:
                                cross_margin = (current_macd - current_signal) / current_signal
                                cross_margin_threshold = 0.02
                                if cross_margin > cross_margin_threshold and current_volume > volume_factor * average_volume:
                                    return True
        return False

    def OnOrderEvent(self, orderEvent):
        if orderEvent.Status == OrderStatus.Filled:
            symbol = orderEvent.Symbol.Value
            fill_price = orderEvent.FillPrice
            quantity = orderEvent.FillQuantity
            direction = "bought" if quantity > 0 else "sold"
            initial_price = self.initial_purchase_price.get(symbol, fill_price)
            gain_loss_dollars = (fill_price - initial_price) * abs(quantity)
            gain_loss_percent = ((fill_price / initial_price) - 1) * 100 if initial_price != 0 else 0
            self.queue_debug_message(f"Order filled: {symbol} {direction}, Quantity: {quantity}, Fill Price: {fill_price}. Gain/Loss: ${gain_loss_dollars:.2f} ({gain_loss_percent:.2f}%).")


    def log_symbol_status(self, symbol):
        holding = self.Portfolio[symbol]
        if holding.Invested:
            current_value, max_value = holding.Quantity * holding.Price, self.max_portfolio_value[symbol]
            drawdown = 0 if max_value == 0 else (max_value - current_value) / max_value
            self.queue_debug_message(f"Symbol: {symbol}, Holdings: {holding.Quantity}, Current Value: ${current_value:.2f}, Drawdown: {drawdown * 100:.2f}%, Monitoring for portfolio optimization.")
        else:
            self.queue_debug_message(f"Symbol: {symbol}, Holdings: 0, Currently not invested. Awaiting favorable market conditions.")

