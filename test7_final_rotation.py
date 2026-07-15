# region imports
from AlgorithmImports import *
import numpy as np
# endregion

class FinalRotationStrategy(QCAlgorithm):
    """
    ============================================================================
    R3-测试1: 终极策略 —— 最优择时(4信号双周) + 行业轮动

    验证结论:
      最优择时: Trend 0.40, Rate 0.25, Curve 0.20, PMI 0.15, BULL>0.10
      调仓频率: 双周(1号和15号)
      行业轮动: 60日动量×0.4 + 20日动量×0.3 + 成交量变化×0.2 - 波动率×0.1
                MA200过滤: 价格低于MA200扣0.3分

    对比基准:
      - 原版完整策略: 94.03% (月频, 原来权重)
      - Test6 纯SPY双周: 94.51% (不轮动, 只买SPY)
      - 本策略应该 > Test6, 因为择时+轮动叠加

    ============================================================================
    """

    # 11个行业ETF
    SECTOR_ETFS = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK",
                   "XLP", "XLRE", "XLU", "XLV", "XLY"]

    def initialize(self):
        self.set_start_date(2019, 1, 1)
        self.set_end_date(2026, 7, 14)
        self.set_cash(100000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
        self.set_warm_up(252)

        # ====== 订阅数据 ======
        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.set_benchmark(self.spy)

        self.tlt = self.add_equity("TLT", Resolution.DAILY).symbol
        self.shy = self.add_equity("SHY", Resolution.DAILY).symbol
        self.sector_symbols = {}
        for etf in self.SECTOR_ETFS:
            self.add_equity(etf, Resolution.DAILY)
            self.sector_symbols[etf] = self.securities[etf].symbol

        self.add_data(FredRate, "FEDFUNDS", Resolution.DAILY)

        # ====== 双周调仓 ======
        self.schedule.on(
            self.date_rules.month_start("SPY"),
            self.time_rules.after_market_open("SPY", 90),
            self.biweekly_rebalance
        )
        self.schedule.on(
            self.date_rules.month_start(15),
            self.time_rules.after_market_open("SPY", 90),
            self.biweekly_rebalance
        )

        # ====== 状态变量 ======
        self.market_direction = "NEUTRAL"
        self.direction_score = 0.0
        self.rate_direction = "STEADY"
        self.yield_curve = "NORMAL"
        self.pmi_proxy = 50.0
        self.fed_rate = 0.05
        self.last_check_day = -1

        self.debug("=" * 60)
        self.debug("R3-TEST1: Final Strategy (Macro Timing + Sector Rotation)")
        self.debug(f"  Timing: Trend=0.40 Rate=0.25 Curve=0.20 PMI=0.15")
        self.debug(f"  Threshold: BULL>0.10 BEAR<-0.10 | Biweekly")
        self.debug(f"  BULL->Top5(95%) NEUTRAL->Top3(50%) BEAR->Cash")
        self.debug("=" * 60)

    # ========================================================================
    #  信号计算 (同 Test6)
    # ========================================================================
    def get_rate_direction_signal(self):
        tlt_hist = self.history(self.tlt, 120, Resolution.DAILY)
        shy_hist = self.history(self.shy, 120, Resolution.DAILY)
        if tlt_hist.empty or shy_hist.empty or len(tlt_hist) < 60:
            if self.fed_rate > 0.04:
                self.rate_direction = "HIKING"; return -0.5
            elif self.fed_rate < 0.02:
                self.rate_direction = "CUTTING"; return +0.5
            self.rate_direction = "STEADY"; return 0.0

        tlt_ret_60 = tlt_hist['close'].iloc[-1] / tlt_hist['close'].iloc[-60] - 1
        shy_ret_60 = shy_hist['close'].iloc[-1] / shy_hist['close'].iloc[-60] - 1
        tlt_ret_20 = tlt_hist['close'].iloc[-1] / tlt_hist['close'].iloc[-20] - 1
        shy_ret_20 = shy_hist['close'].iloc[-1] / shy_hist['close'].iloc[-20] - 1
        bond_spread_60 = tlt_ret_60 - shy_ret_60
        bond_spread_20 = tlt_ret_20 - shy_ret_20

        if bond_spread_60 > 0.03:
            self.rate_direction = "CUTTING"; return +1.0
        elif bond_spread_60 < -0.03:
            self.rate_direction = "HIKING"; return -1.0
        elif bond_spread_20 > 0.01:
            self.rate_direction = "CUTTING_SOON"; return +0.5
        elif bond_spread_20 < -0.01:
            self.rate_direction = "HIKING_SOON"; return -0.5
        else:
            self.rate_direction = "STEADY"; return 0.0

    def get_yield_curve_signal(self):
        tlt_hist = self.history(self.tlt, 250, Resolution.DAILY)
        shy_hist = self.history(self.shy, 250, Resolution.DAILY)
        if tlt_hist.empty or shy_hist.empty or len(tlt_hist) < 60:
            self.yield_curve = "UNKNOWN"; return 0.0

        tlt_price = tlt_hist['close'].iloc[-1]
        shy_price = shy_hist['close'].iloc[-1]
        ratio = tlt_price / shy_price
        ratio_60 = tlt_hist['close'].iloc[-60] / shy_hist['close'].iloc[-60]
        ratio_change = ratio / ratio_60 - 1

        if ratio_change < -0.08:
            self.yield_curve = "INVERTED"; return -1.0
        elif ratio_change < -0.03:
            self.yield_curve = "FLAT"; return -0.5
        elif ratio_change > 0.03:
            self.yield_curve = "STEEPENING"; return +1.0
        else:
            self.yield_curve = "NORMAL"; return 0.0

    def get_pmi_signal(self):
        xli_symbol = self.sector_symbols["XLI"]
        xlu_symbol = self.sector_symbols["XLU"]
        xli_hist = self.history(xli_symbol, 120, Resolution.DAILY)
        xlu_hist = self.history(xlu_symbol, 120, Resolution.DAILY)
        if xli_hist.empty or xlu_hist.empty or len(xli_hist) < 60:
            self.pmi_proxy = 50.0; return 0.0

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
        rate_signal   = self.get_rate_direction_signal()
        curve_signal  = self.get_yield_curve_signal()
        pmi_signal    = self.get_pmi_signal()
        trend_signal  = self.get_trend_signal()

        score = trend_signal * 0.40 + rate_signal * 0.25 + curve_signal * 0.20 + pmi_signal * 0.15

        if score > 0.10:
            direction = "BULL"
        elif score < -0.10:
            direction = "BEAR"
        else:
            direction = "NEUTRAL"

        self.market_direction = direction
        self.direction_score = score

        self.debug(f"\n[{self.time.date()}] DIRECTION: {direction} | Score: {score:+.2f} "
                   f"| T:{trend_signal:+.0f} R:{rate_signal:+.0f} C:{curve_signal:+.0f} P:{pmi_signal:+.0f}")
        return direction

    # ========================================================================
    #  行业评分
    # ========================================================================
    def score_sector(self, etf_name):
        """对单个行业ETF打分: 动量×0.4 + 短期动量×0.3 + 成交量×0.2 - 波动率×0.1 - MA200惩罚"""
        sym = self.sector_symbols[etf_name]
        hist = self.history(sym, 250, Resolution.DAILY)
        if hist.empty or len(hist) < 60:
            return -999, {}

        closes = hist['close'].values
        volumes = hist['volume'].values

        spot = closes[-1]
        mom_60  = spot / closes[-60]  - 1 if len(closes) >= 60  else 0
        mom_20  = spot / closes[-20]  - 1 if len(closes) >= 20  else 0
        vol_chg = volumes[-20:].mean() / max(volumes[-60:].mean(), 1) - 1

        returns_20 = closes[-21:].copy()
        returns_20 = (returns_20[1:] / returns_20[:-1]) - 1
        volatility = returns_20.std() if len(returns_20) > 0 else 0.05

        ma200 = closes[-200:].mean() if len(closes) >= 200 else closes.mean()
        below_ma200_penalty = -0.3 if spot < ma200 else 0.0

        score = mom_60 * 0.4 + mom_20 * 0.3 + vol_chg * 0.2 - volatility * 0.1 + below_ma200_penalty

        info = {
            'mom60': mom_60, 'mom20': mom_20, 'vol_chg': vol_chg,
            'volatility': volatility, 'ma200_ok': spot >= ma200,
            'price': spot, 'ma200': ma200
        }
        return score, info

    def get_top_sectors(self, n):
        """返回评分前n名的行业ETF列表"""
        scores = []
        for etf in self.SECTOR_ETFS:
            s, info = self.score_sector(etf)
            if s > -99:
                scores.append((etf, s, info))

        scores.sort(key=lambda x: x[1], reverse=True)
        return [x[0] for x in scores[:n]], scores

    # ========================================================================
    #  双周调仓入口
    # ========================================================================
    def biweekly_rebalance(self):
        if self.is_warming_up:
            return
        current_day = self.time.day
        if current_day not in [1, 15]:
            return
        if current_day == self.last_check_day:
            return
        self.last_check_day = current_day

        # 1. 判定市场方向
        direction = self.determine_market_direction()

        portfolio_value = self.portfolio.total_portfolio_value

        if direction == "BEAR":
            # 全部清仓
            self.debug(f"  [BEAR] Liquidating all positions")
            for etf in self.SECTOR_ETFS:
                self.liquidate(etf)
            return

        # 2. 行业评分 + 选股
        n_top = 5 if direction == "BULL" else 3
        target_pct = 0.95 if direction == "BULL" else 0.50
        top_etfs, all_scores = self.get_top_sectors(n_top)

        target_val_per = (portfolio_value * target_pct) / n_top

        self.debug(f"  [{direction}] Top{n_top} ETFs: {', '.join(top_etfs)} | Target each: ${target_val_per:.0f}")

        # 3. 卖出不在Top N里的持仓
        for etf in self.SECTOR_ETFS:
            if etf not in top_etfs:
                self.liquidate(etf)

        # 4. 调整Top N的仓位
        for etf in top_etfs:
            if not self.securities[etf].has_data:
                continue
            price = self.securities[etf].price
            if price <= 0:
                continue
            current_val = self.portfolio[etf].holdings_value
            diff = target_val_per - current_val
            if abs(diff) > 300:
                qty = int(diff / price)
                if qty > 0:
                    self.market_order(etf, qty)
                    self.debug(f"    BUY  {etf:5s} x{qty:4d} @ ${price:.2f}")
                elif qty < 0:
                    self.market_order(etf, qty)
                    self.debug(f"    SELL {etf:5s} x{abs(qty):4d} @ ${price:.2f}")

        # 5. 打印行业排名（调试）
        for i, (etf, s, info) in enumerate(all_scores[:5]):
            tag = "*" if etf in top_etfs else " "
            self.debug(f"    {tag}{i+1}. {etf:5s} Score:{s:+.3f} | M60:{info['mom60']:+.1%} M20:{info['mom20']:+.1%} MA200:{'Y' if info['ma200_ok'] else 'N'}")

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
