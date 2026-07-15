# region imports
from AlgorithmImports import *
import numpy as np
# endregion

class AdjustedWeightsTest(QCAlgorithm):
    """
    ============================================================================
    R2-测试2: 调整权重版 —— 趋势信号主导 + 降低BULL阈值
    ============================================================================

    验证问题: "给趋势信号更多话语权，降低BULL门槛，会不会更准？"

    权重变更:
    - Trend:  0.15 → 0.40 (SPY均线系统应该最直接反映牛熊)
    - Rate:   0.40 → 0.25
    - Curve:  0.25 → 0.20
    - PMI:    0.20 → 0.15 (代理信号噪音大，降低权重)

    阈值变更:
    - BULL:   > +0.20 → > +0.10 (降低门槛)
    - BEAR:   < -0.20 → < -0.10
    - 中性区间收窄，减少"犹豫不决"的次数

    对比:
    - Test1 (原权重): 61.17%
    - 如果本版本 > 61.17% → 新权重+新阈值更优
    ============================================================================
    """

    def initialize(self):
        self.set_start_date(2019, 1, 1)
        self.set_end_date(2026, 7, 14)
        self.set_cash(100000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
        self.set_warm_up(252)

        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.set_benchmark(self.spy)

        self.tlt = self.add_equity("TLT", Resolution.DAILY).symbol
        self.shy = self.add_equity("SHY", Resolution.DAILY).symbol
        self.add_equity("XLI", Resolution.DAILY)
        self.add_equity("XLU", Resolution.DAILY)
        self.add_data(FredRate, "FEDFUNDS", Resolution.DAILY)

        self.schedule.on(
            self.date_rules.month_start("SPY"),
            self.time_rules.after_market_open("SPY", 90),
            self.monthly_macro_check
        )

        self.market_direction = "NEUTRAL"
        self.direction_score = 0.0
        self.rate_direction = "STEADY"
        self.yield_curve = "NORMAL"
        self.pmi_proxy = 50.0
        self.fed_rate = 0.05
        self.last_check_month = -1

        self.debug("="*60)
        self.debug("R2-TEST2: Adjusted Weights + Lower Threshold")
        self.debug(f"  Weights: Trend=0.40 Rate=0.25 Curve=0.20 PMI=0.15")
        self.debug(f"  Threshold: BULL>0.10 BEAR<-0.10")
        self.debug("="*60)

    # ========================================================================
    #  信号计算 (逻辑同 Test1，输出权重在 determine 时调整)
    # ========================================================================
    def get_rate_direction_signal(self):
        tlt_hist = self.history(self.tlt, 120, Resolution.DAILY)
        shy_hist = self.history(self.shy, 120, Resolution.DAILY)

        if tlt_hist.empty or shy_hist.empty or len(tlt_hist) < 60:
            if self.fed_rate > 0.04:
                self.rate_direction = "HIKING"
                return -0.5
            elif self.fed_rate < 0.02:
                self.rate_direction = "CUTTING"
                return +0.5
            self.rate_direction = "STEADY"
            return 0.0

        tlt_ret_60 = tlt_hist['close'].iloc[-1] / tlt_hist['close'].iloc[-60] - 1
        shy_ret_60 = shy_hist['close'].iloc[-1] / shy_hist['close'].iloc[-60] - 1
        tlt_ret_20 = tlt_hist['close'].iloc[-1] / tlt_hist['close'].iloc[-20] - 1
        shy_ret_20 = shy_hist['close'].iloc[-1] / shy_hist['close'].iloc[-20] - 1

        bond_spread_60 = tlt_ret_60 - shy_ret_60
        bond_spread_20 = tlt_ret_20 - shy_ret_20

        if bond_spread_60 > 0.03:
            self.rate_direction = "CUTTING"
            return +1.0
        elif bond_spread_60 < -0.03:
            self.rate_direction = "HIKING"
            return -1.0
        elif bond_spread_20 > 0.01:
            self.rate_direction = "CUTTING_SOON"
            return +0.5
        elif bond_spread_20 < -0.01:
            self.rate_direction = "HIKING_SOON"
            return -0.5
        else:
            self.rate_direction = "STEADY"
            return 0.0

    def get_yield_curve_signal(self):
        tlt_hist = self.history(self.tlt, 250, Resolution.DAILY)
        shy_hist = self.history(self.shy, 250, Resolution.DAILY)

        if tlt_hist.empty or shy_hist.empty or len(tlt_hist) < 60:
            self.yield_curve = "UNKNOWN"
            return 0.0

        tlt_price = tlt_hist['close'].iloc[-1]
        shy_price = shy_hist['close'].iloc[-1]
        ratio = tlt_price / shy_price
        ratio_60 = tlt_hist['close'].iloc[-60] / shy_hist['close'].iloc[-60]
        ratio_change = ratio / ratio_60 - 1

        if ratio_change < -0.08:
            self.yield_curve = "INVERTED"
            return -1.0
        elif ratio_change < -0.03:
            self.yield_curve = "FLAT"
            return -0.5
        elif ratio_change > 0.03:
            self.yield_curve = "STEEPENING"
            return +1.0
        else:
            self.yield_curve = "NORMAL"
            return 0.0

    def get_pmi_signal(self):
        xli_symbol = self.securities["XLI"].symbol
        xlu_symbol = self.securities["XLU"].symbol
        xli_hist = self.history(xli_symbol, 120, Resolution.DAILY)
        xlu_hist = self.history(xlu_symbol, 120, Resolution.DAILY)

        if xli_hist.empty or xlu_hist.empty or len(xli_hist) < 60:
            self.pmi_proxy = 50.0
            return 0.0

        xli_ret_60 = xli_hist['close'].iloc[-1] / xli_hist['close'].iloc[-60] - 1
        xlu_ret_60 = xlu_hist['close'].iloc[-1] / xlu_hist['close'].iloc[-60] - 1
        xli_ret_20 = xli_hist['close'].iloc[-1] / xli_hist['close'].iloc[-20] - 1
        xlu_ret_20 = xlu_hist['close'].iloc[-1] / xlu_hist['close'].iloc[-20] - 1

        diff_60 = xli_ret_60 - xlu_ret_60
        diff_20 = xli_ret_20 - xlu_ret_20
        self.pmi_proxy = 50 + diff_60 * 100 + diff_20 * 50

        if diff_60 > 0.05 and diff_20 > 0.01:
            return +1.0
        elif diff_60 < -0.05 and diff_20 < -0.01:
            return -1.0
        elif diff_60 > 0.02:
            return +0.5
        elif diff_60 < -0.02:
            return -0.5
        else:
            return 0.0

    def get_trend_signal(self):
        spy_hist = self.history(self.spy, 250, Resolution.DAILY)
        if spy_hist.empty or len(spy_hist) < 200:
            return 0.0

        closes = spy_hist['close'].values
        ma50 = closes[-50:].mean()
        ma200 = closes[-200:].mean()
        spot = closes[-1]

        golden_cross = ma50 > ma200
        above_ma200 = spot > ma200
        dist_from_ma200 = spot / ma200 - 1

        if golden_cross and above_ma200 and dist_from_ma200 > 0.03:
            return +1.0
        elif golden_cross and above_ma200:
            return +0.5
        elif not above_ma200 and not golden_cross:
            return -1.0
        elif not above_ma200:
            return -0.5
        else:
            return 0.0

    def determine_market_direction(self):
        rate_signal = self.get_rate_direction_signal()
        curve_signal = self.get_yield_curve_signal()
        pmi_signal = self.get_pmi_signal()
        trend_signal = self.get_trend_signal()

        # ★ 核心改动: 新权重
        score = trend_signal * 0.40 + rate_signal * 0.25 + curve_signal * 0.20 + pmi_signal * 0.15

        # ★ 核心改动: 降低阈值
        if score > 0.10:
            direction = "BULL"
        elif score < -0.10:
            direction = "BEAR"
        else:
            direction = "NEUTRAL"

        self.market_direction = direction
        self.direction_score = score

        self.debug(f"\n[{self.time.date()}] DIRECTION: {direction} | Score: {score:+.2f} "
                  f"| Trend: {trend_signal:+.0f} Rate: {rate_signal:+.0f} "
                  f"Curve: {curve_signal:+.0f} PMI: {pmi_signal:+.0f}")
        return direction, score

    def monthly_macro_check(self):
        current_month = self.time.month
        if current_month == self.last_check_month:
            return
        self.last_check_month = current_month

        direction, score = self.determine_market_direction()

        portfolio_value = self.portfolio.total_portfolio_value
        spy_price = self.securities["SPY"].price
        if spy_price <= 0:
            return

        current_spy_val = self.portfolio["SPY"].holdings_value

        if direction == "BULL":
            target_val = portfolio_value * 0.95
        elif direction == "BEAR":
            target_val = 0
        else:
            target_val = portfolio_value * 0.50

        diff = target_val - current_spy_val

        if abs(diff) > 500:
            if diff > 0:
                qty = int(diff / spy_price)
                if qty > 0:
                    self.market_order(self.spy, qty)
                    self.debug(f"  [BUY] SPY x{qty} @ ${spy_price:.2f}")
            else:
                qty = int(abs(diff) / spy_price)
                if qty > 0:
                    self.market_order(self.spy, -qty)
                    self.debug(f"  [SELL] SPY x{qty} @ ${spy_price:.2f}")

    def on_data(self, data):
        if self.fed_rate == 0.05:
            if "FEDFUNDS" in data and data["FEDFUNDS"] is not None:
                self.fed_rate = data["FEDFUNDS"].value / 100.0


class FredRate(PythonData):
    def get_source(self, config, date, is_live_mode):
        return SubscriptionDataSource(
            "https://raw.githubusercontent.com/jamesmcmahon/fred-data/main/data/FEDFUNDS.csv",
            SubscriptionTransportMedium.REMOTE_FILE
        )

    def reader(self, config, line, date, is_live_mode):
        if line is None or line.strip() == "" or line.startswith("DATE"):
            return None
        data = line.split(',')
        if len(data) < 2:
            return None
        rate = FredRate()
        rate.symbol = config.symbol
        rate.time = datetime.strptime(data[0].strip(), "%Y-%m-%d")
        rate.value = float(data[1].strip())
        return rate
