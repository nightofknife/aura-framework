import csv
import pandas as pd
import numpy as np
import re
import json
import requests
from bs4 import BeautifulSoup
import urllib.request, urllib.error
import heapq



import resource.function.base_action as base


class count_price():
    def __init__(self):
        with open("resource/setting/price_inf.json", "r", encoding="utf-8") as f:
            self.product_inf = json.load(f)

        self.city_tired_map = np.array(pd.read_csv("resource/setting/城市路程疲劳表.csv", header=None).values.tolist())
        self.city_sell_map = np.array(pd.read_csv("resource/setting/商品售出价格表.csv", header=None).values.tolist())
        self.city_buy_map = np.array(pd.read_csv("resource/setting/商品收购价格表.csv", header=None).values.tolist())
        self.city_num_map = np.array(pd.read_csv("resource/setting/商品数量价格表.csv", header=None).values.tolist())

        self.usecity = ["修格里城", "淘金乐园", "铁盟哨站", "荒原站", "曼德矿场", '澄明数据中心', "7号自由港",
                        "阿妮塔战备工厂", "阿妮塔能源研究所", "阿妮塔发射中心"]

        self.product = []
        self.product = [i["name"] for i in self.product_inf if i["name"] not in self.product]

        self.product_sell_map = np.zeros((len(self.product) + 1, len(self.usecity) + 1)).astype(str)
        self.product_sell_map[0, 0] = "cat"
        self.product_sell_map[1:, 0] = self.product
        self.product_sell_map[0, 1:] = self.usecity

        self.product_buy_map = np.zeros((len(self.product) + 1, len(self.usecity) + 1)).astype(str)
        self.product_buy_map[0, 0] = "cat"
        self.product_buy_map[1:, 0] = self.product
        self.product_buy_map[0, 1:] = self.usecity

        self.product_num_map = np.zeros((len(self.product) + 1, len(self.usecity) + 1)).astype(str)
        self.product_num_map[0, 0] = "cat"
        self.product_num_map[1:, 0] = self.product
        self.product_num_map[0, 1:] = self.usecity

        self.city_buy_inf = {i: [] for i in self.usecity}

    def update_product_inf(self):
        try:
            HEADERS = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0'
            }
            # 注意请求不要太频繁
            self.product_inf = requests.get(
                'https://reso-data.kmou424.moe/api/fetch/goods_info?uuid=5d9b7836-6474-4e44-881c-78ea9e116334',
                headers=HEADERS
            ).json()
        except:
            print("获取更新失败，使用上次更新数据")
            with open("resource/setting/price_inf.json", "r", encoding="utf-8") as f:
                self.product_inf = json.load(f)

    def update_product_map(self):

        if not self.product_inf:
            with open("resource/setting/price_inf.json", "r", encoding="utf-8") as f:
                self.product_inf = json.load(f)

        for i in self.product_inf:
            if i["station"] not in self.usecity:
                continue
            if i["type"] == "buy":
                self.product_sell_map[self.product.index(i["name"]) + 1][self.usecity.index(i["station"]) + 1] = i[
                    "price"]

            elif i["type"] == "sell":
                self.product_num_map[self.product.index(i["name"]) + 1][self.usecity.index(i["station"]) + 1] = i[
                    "stock"]
                self.product_buy_map[self.product.index(i["name"]) + 1][self.usecity.index(i["station"]) + 1] = i[
                    "price"]
                self.city_buy_inf[i["station"]].append(i["name"])

    def write_inf(self):
        pd.DataFrame(self.product_num_map).to_csv(path_or_buf="resource/setting/商品售出价格表.csv", header=None,
                                                  index=None)
        pd.DataFrame(self.product_sell_map).to_csv(path_or_buf="resource/setting/商品收购价格表.csv", header=None,
                                                   index=None)
        pd.DataFrame(self.product_num_map).to_csv(path_or_buf="resource/setting/商品数量价格表.csv", header=None,
                                                  index=None)

        with open("resource/setting/price_inf.json", "w", encoding="utf-8") as f:
            json.dump(self.product_inf, f, ensure_ascii=False)
        with open("resource/setting/city_buy_inf.json", "w", encoding="utf-8") as f:
            json.dump(self.city_buy_inf, f, ensure_ascii=False)

    def temp(self):
        # 货车的容量
        CAPACITY = 1000

        # 货车的最大行驶疲劳
        MAX_FATIGUE = 600

        BUY_LOT_MODIFIER = 3  # 买入时的数量调整系数（声望）
        GENERAL_TAX = 0.05  # 假设买卖时的税率一样

        # FATIGUE 无向图，城市之间的疲劳，对称矩阵
        FATIGUE = self.city_tired_map[1:, 1:].astype(float).astype(int)
        CITIY_NUM = len(FATIGUE)  # 9

        # 可买入的产品数量，第一维是产品，第二维是城市
        PRODUCT_LOTS = self.city_num_map.astype(float).astype(int)
        PRODUCT_NUM = len(PRODUCT_LOTS)  # 74

        # 产品的买入和卖出价格，第一维是产品，第二维是城市
        PRODUCT_BUY_PRICES = self.product_sell_map.astype(float).astype(int)
        PRODUCT_SELL_PRICES = self.product_buy_map.astype(float).astype(int)

        print(CITIY_NUM, PRODUCT_NUM, PRODUCT_SELL_PRICES[1, 2])

        # 问题描述：
        # 有 CITIY_NUM 个城市，一个含有 PRODUCT_NUM 件商品的列表，一个容量为 CAPACITY 的货车。
        # 任意两个城市之间均可达，并存在疲劳 FATIGUE[i][j]。
        # 商品列表列出了第i个商品在第j个城市的：可买入数量 PRODUCT_LOTS[i][j]、购入价 PRODUCT_BUY_PRICES[i][j]、卖出价 PRODUCT_SELL_PRICES[i][j]。
        # 找到这样的一个顶点和一条路径与买卖行动列表，使得移动总疲劳小于 MAX_FATIGUE 时，总利润 profit 最大，并且（总利润 profit /总疲劳 fatigue）最大。
        # 额外的约束条件：货车每次到站时，必须卖出所有商品并尽可能买入商品。

        # 预先计算每两个城市之间可以买卖的商品利润总额，PROFIT[i][j]表示从i城市买入到j城市卖出的总利润
        PROFIT = np.zeros((CITIY_NUM, CITIY_NUM), dtype=int)
        BUYS = []  # 从i城市买入到j城市卖出的商品列表和数量
        for i in range(CITIY_NUM):
            BUYS.append([])
            for j in range(CITIY_NUM):
                if i == j:
                    BUYS[i].append([])
                    continue
                profits = []
                for k in range(PRODUCT_NUM):
                    if PRODUCT_LOTS[k][i] > 0:
                        s_profit = PRODUCT_SELL_PRICES[k][j] - PRODUCT_BUY_PRICES[k][i]
                        s_profit -= s_profit * GENERAL_TAX  # 卖出时的税
                        s_profit -= PRODUCT_BUY_PRICES[k][i] * GENERAL_TAX  # 买入时的花费
                        profits.append((k, s_profit))
                profits.sort(key=lambda x: x[1], reverse=True)
                profit = 0
                cap = CAPACITY
                for idx, p in profits:
                    if p > 0:
                        buy = min(cap, int(PRODUCT_LOTS[idx][i] * BUY_LOT_MODIFIER))
                        profit += p * buy
                        cap -= buy
                        BUYS[i].append((idx, buy))
                        if cap == 0:
                            break
                PROFIT[i][j] = profit
        # print(PROFIT)

        # 计算每单位疲劳的利润
        PROFIT_PER_DISTANCE = np.zeros((CITIY_NUM, CITIY_NUM), dtype=float)
        for i in range(CITIY_NUM):
            for j in range(CITIY_NUM):
                if i == j:
                    continue
                PROFIT_PER_DISTANCE[i][j] = PROFIT[i][j] / FATIGUE[i][j]

        # 找到最大单次利润，理论上界
        profit_upper_bound = np.max(PROFIT_PER_DISTANCE)
        profit_lower_bound = 0
        print(f"start with [{profit_lower_bound}, {profit_upper_bound}]")

        # 设定（总利润/总疲劳）最大的路径上的（总利润/总疲劳）为 r
        # 则有 r <= max_profit_per_fatigue
        # 由则问题转化为寻找一条路径 sum p / sum f >= r, 变形为 sum p - r * sum f >= 0
        # 设定新图的权重为 w = p - r * f,
        # 假设经过的城市数量 N > ||V||, 则问题转化为寻找权重最大环路

        def bellman_ford(W, r):
            fatigue = np.zeros(CITIY_NUM, dtype=float)
            predecessor = -1 * np.ones(CITIY_NUM, dtype=int)
            fatigue[0] = 0
            for i in range(1, CITIY_NUM - 1):
                fatigue[i] = np.inf
            # relax edges repeatedly
            for _ in range(CITIY_NUM - 1):
                for u in range(CITIY_NUM):
                    for v in range(CITIY_NUM):
                        if fatigue[u] + W[u][v] < fatigue[v]:
                            fatigue[v] = fatigue[u] + W[u][v]
                            predecessor[v] = u
            # check for negative-weight cycles
            for u in range(CITIY_NUM):
                for v in range(CITIY_NUM):
                    if u != v and fatigue[u] + W[u][v] < fatigue[v]:
                        cycle = []
                        # trace back the cycle
                        for _ in range(CITIY_NUM):
                            v = predecessor[v]
                        cycle_vertex = v
                        while True:
                            cycle.append(cycle_vertex)
                            cycle_vertex = predecessor[cycle_vertex]
                            if cycle_vertex == v or cycle_vertex == -1:
                                break
                        cycle.reverse()

                        # 计算环路的总利润
                        cycle_profit = 0
                        for i in range(len(cycle) - 1):
                            cycle_profit += PROFIT[cycle[i]][cycle[i + 1]]
                        cycle_profit += PROFIT[cycle[-1]][cycle[0]]

                        # 计算环路的总疲劳
                        cycle_fatigue = 0
                        for i in range(len(cycle) - 1):
                            cycle_fatigue += FATIGUE[cycle[i]][cycle[i + 1]]
                        cycle_fatigue += FATIGUE[cycle[-1]][cycle[0]]

                        # 计算环路的总利润/总疲劳
                        cycle_profit_per_fatigue = cycle_profit / cycle_fatigue

                        if cycle_profit_per_fatigue >= r:
                            return cycle, cycle_profit, cycle_fatigue, cycle_profit_per_fatigue
            return None

        # 二分查找最大利润 r
        EPS = 1
        cycle_result = None
        while profit_upper_bound - profit_lower_bound > EPS:
            r = (profit_upper_bound + profit_lower_bound) / 2

            # 构造新图
            # 新图的权重为 w = r * d - p
            # 问题转化为求负权环
            W = r * np.array(FATIGUE, dtype=float) - PROFIT

            # 快速检查是否不存在负权
            if not np.any(W < 0):
                profit_upper_bound = r
                continue

            # Bellman-Ford算法求解负权环
            result = bellman_ford(W, r)
            if result:
                cycle_result = result
                profit_lower_bound = r
            else:
                profit_upper_bound = r

        print('基于以下参数搜索：')
        print(f"容量: {CAPACITY}, 买入时数量调整系数: {BUY_LOT_MODIFIER}, 税率: {GENERAL_TAX}")
        print('最佳环路', '->'.join([self.usecity[i] for i in cycle_result[0]]))
        print(f"总利润: {cycle_result[1]}, 总疲劳: {cycle_result[2]}, 单位利润: {cycle_result[3]}")
        print([self.usecity[i] for i in cycle_result[0]])
        return [self.usecity[i] for i in cycle_result[0]], cycle_result[1], cycle_result[2], cycle_result[3]


def t6(product_list, book, cargo_limit):
    new_product_list = [0, []]
    if book == 0:
        return product_list
    for i in product_list[1]:
        if cargo_limit > 0:
            new_product_list[0] += min(i[1] * book, cargo_limit) * i[2]
            new_product_list[1].append([i[0], min(i[1] * book, cargo_limit), i[2]])
            cargo_limit -= min(i[1] * book, cargo_limit)
        else:
            return new_product_list
    return new_product_list


def t5(city_list, product_map, book=0, cargo_limit=0):
    if city_list == 0:
        print("无书方案")
        return False

    def partition_sum(sum, n):
        """
        将整数 sum 分成 n 份的所有可能组合。

        Args:
            sum (int): 要分割的整数总和。
            n (int): 分割的份数。

        Returns:
            List[List[int]]: 包含所有可能组合的列表。
        """

        def helper(remaining_sum, remaining_parts, current_partition):
            if remaining_parts == 0:
                if remaining_sum == 0:
                    result.append(current_partition[:])
                return
            for i in range(remaining_sum + 1):
                current_partition.append(i)
                helper(remaining_sum - i, remaining_parts - 1, current_partition)
                current_partition.pop()

        result = []
        helper(sum, n, [])

        return result

    new_product_list = []
    scheme = partition_sum(book, len(city_list))

    max = 0
    max_scheme = []
    max_choose = None
    for i in scheme:
        sum = 0
        temp_scheme = []
        print("检索方案：", i, end="  ")
        for j in range(len(i)):
            temp_project = t6(product_map[j], i[j], cargo_limit)
            sum += temp_project[0]
            temp_scheme.append(temp_project)
        if max < sum:
            max = sum
            max_scheme = temp_scheme
            max_choose = i
        print("利润为", sum)

    return max, max_choose, max_scheme


def t4(data=None, start_city=None, end_city=None, city_sell_map=None, city_buy_map=None, city_num_map=None):
    if not (start_city and end_city):
        print("无起终点数据")
        return False
    if not data:
        with open("resource/setting/city_buy_inf.json", "r", encoding="utf-8") as f:
            data = json.load(f)

    if not (city_sell_map and city_buy_map and city_num_map):
        city_sell_map = np.array(pd.read_csv("resource/setting/商品售出价格表.csv", header=None).values.tolist())
        city_buy_map = np.array(pd.read_csv("resource/setting/商品收购价格表.csv", header=None).values.tolist())
        city_num_map = np.array(pd.read_csv("resource/setting/商品数量价格表.csv", header=None).values.tolist())

    buy_product = data[base.city_name_transition(start_city)]
    start_city = base.city_name_transition(start_city)
    end_city = base.city_name_transition(end_city)

    product = city_sell_map[1:, 0].tolist()

    product_sell_map = city_sell_map[1:, 1:].astype(float).astype(int)
    product_buy_map = city_buy_map[1:, 1:].astype(float).astype(int)
    product_num_map = city_num_map[1:, 1:].astype(float).astype(int)

    usecity = ["修格里城", "淘金乐园", "铁盟哨站", "荒原站", "曼德矿场", '澄明数据中心', "7号自由港", "阿妮塔战备工厂",
               "阿妮塔能源研究所", "阿妮塔发射中心"]

    trade_list = []
    income = 0
    for i in buy_product:
        dis = product_buy_map[product.index(i)][usecity.index(end_city)] - product_sell_map[product.index(i)][
            usecity.index(start_city)]
        if dis > 0:
            trade_list.append([i, dis])
            income += product_num_map[product.index(i)][usecity.index(end_city)] * dis

    trade_list = sorted(trade_list, reverse=True, key=lambda x: x[1])
    # print(trade_list)
    return trade_list


def t4_update(data=None, start_city=None, end_city=None, city_sell_map=None, city_buy_map=None, city_num_map=None):
    if not (start_city and end_city):
        print("无起终点数据")
        return False
    if not data:
        with open("resource/setting/city_buy_inf.json", "r", encoding="utf-8") as f:
            data = json.load(f)

    if not (city_sell_map and city_buy_map and city_num_map):
        city_sell_map = np.array(pd.read_csv("resource/setting/商品售出价格表.csv", header=None).values.tolist())
        city_buy_map = np.array(pd.read_csv("resource/setting/商品收购价格表.csv", header=None).values.tolist())
        city_num_map = np.array(pd.read_csv("resource/setting/商品数量价格表.csv", header=None).values.tolist())

    buy_product = data[base.city_name_transition(start_city)]
    start_city = base.city_name_transition(start_city)
    end_city = base.city_name_transition(end_city)

    product = city_sell_map[1:, 0].tolist()

    product_sell_map = city_sell_map[1:, 1:].astype(float).astype(int)
    product_buy_map = city_buy_map[1:, 1:].astype(float).astype(int)
    product_num_map = city_num_map[1:, 1:].astype(float).astype(int)

    usecity = ["修格里城", "淘金乐园", "铁盟哨站", "荒原站", "曼德矿场", '澄明数据中心', "7号自由港", "阿妮塔战备工厂",
               "阿妮塔能源研究所", "阿妮塔发射中心"]

    trade_list = []
    income = 0
    for i in buy_product:
        dis = product_buy_map[product.index(i)][usecity.index(end_city)] - product_sell_map[product.index(i)][
            usecity.index(start_city)]
        if dis > 0:
            num = product_num_map[product.index(i)][usecity.index(start_city)] * 3
            trade_list.append([i, num, dis])
            income += num * dis

    trade_list = sorted(trade_list, reverse=True, key=lambda x: x[2])
    # print(trade_list)
    return [income, trade_list]


def t3(FATIGUE, PRODUCT_BUY_PRICES, PRODUCT_SELL_PRICES, PRODUCTS_IDX_TO_NAME, CITY_LIST, GET_PRODUCT_LOTS):
    """

    :param FATIGUE: 无向图，城市之间的疲劳，对称矩阵
    :param PRODUCT_BUY_PRICES: 产品的买入价格，第一维是产品，第二维是城市
    :param PRODUCT_SELL_PRICES: 产品的卖出价格，第一维是产品，第二维是城市
    :param PRODUCTS_IDX_TO_NAME:
    :param CITY_LIST: 城市列表
    :param GET_PRODUCT_LOTS: 可买入的产品数量，第一维是产品，第二维是城市
    :return:
    """

    # 货车的容量
    CAPACITY = 600

    # 货车的最大行驶疲劳
    MAX_FATIGUE = 600

    BUY_LOT_MODIFIER = 3  # 买入时的数量调整系数（声望）
    GENERAL_TAX = 0.065  # 假设买卖时的税率一样

    # FATIGUE 无向图，城市之间的疲劳，对称矩阵
    FATIGUE = FATIGUE.astype(float).astype(int)
    CITIY_NUM = len(FATIGUE)  # 9

    # 可买入的产品数量，第一维是产品，第二维是城市
    PRODUCT_LOTS = GET_PRODUCT_LOTS.astype(float).astype(int)
    PRODUCT_NUM = len(PRODUCT_LOTS)  # 74

    # 产品的买入和卖出价格，第一维是产品，第二维是城市
    PRODUCT_BUY_PRICES = PRODUCT_BUY_PRICES.astype(float).astype(int)
    PRODUCT_SELL_PRICES = PRODUCT_SELL_PRICES.astype(float).astype(int)

    # print(CITIY_NUM, PRODUCT_NUM, PRODUCT_SELL_PRICES[1, 2])

    # 问题描述：
    # 有 CITIY_NUM 个城市，一个含有 PRODUCT_NUM 件商品的列表，一个容量为 CAPACITY 的货车。
    # 任意两个城市之间均可达，并存在疲劳 FATIGUE[i][j]。
    # 商品列表列出了第i个商品在第j个城市的：可买入数量 PRODUCT_LOTS[i][j]、购入价 PRODUCT_BUY_PRICES[i][j]、卖出价 PRODUCT_SELL_PRICES[i][j]。
    # 找到这样的一个顶点和一条路径与买卖行动列表，使得移动总疲劳小于 MAX_FATIGUE 时，总利润 profit 最大，并且（总利润 profit /总疲劳 fatigue）最大。
    # 额外的约束条件：货车每次到站时，必须卖出所有商品并尽可能买入商品。

    # 预先计算每两个城市之间可以买卖的商品利润总额，PROFIT[i][j]表示从i城市买入到j城市卖出的总利润
    PROFIT = np.zeros((CITIY_NUM, CITIY_NUM), dtype=int)
    BUYS = []  # 从i城市买入到j城市卖出的商品列表和数量
    for i in range(CITIY_NUM):
        BUYS.append([])
        for j in range(CITIY_NUM):
            if i == j:
                BUYS[i].append([])
                continue
            profits = []
            for k in range(PRODUCT_NUM):
                if PRODUCT_LOTS[k][i] > 0:
                    s_profit = PRODUCT_SELL_PRICES[k][j] - PRODUCT_BUY_PRICES[k][i]
                    s_profit -= s_profit * GENERAL_TAX  # 卖出时的税
                    s_profit -= PRODUCT_BUY_PRICES[k][i] * GENERAL_TAX  # 买入时的花费
                    profits.append((k, s_profit))
            profits.sort(key=lambda x: x[1], reverse=True)
            profit = 0
            cap = CAPACITY
            for idx, p in profits:
                if p > 0:
                    buy = min(cap, int(PRODUCT_LOTS[idx][i] * BUY_LOT_MODIFIER))
                    profit += p * buy
                    cap -= buy
                    BUYS[i].append((idx, buy))
                    if cap == 0:
                        break
            PROFIT[i][j] = profit
    # print(PROFIT)

    # 计算每单位疲劳的利润
    PROFIT_PER_DISTANCE = np.zeros((CITIY_NUM, CITIY_NUM), dtype=float)
    for i in range(CITIY_NUM):
        for j in range(CITIY_NUM):
            if i == j:
                continue
            PROFIT_PER_DISTANCE[i][j] = PROFIT[i][j] / FATIGUE[i][j]

    # 找到最大单次利润，理论上界
    profit_upper_bound = np.max(PROFIT_PER_DISTANCE)
    profit_lower_bound = 0
    print(f"start with [{profit_lower_bound}, {profit_upper_bound}]")

    # 设定（总利润/总疲劳）最大的路径上的（总利润/总疲劳）为 r
    # 则有 r <= max_profit_per_fatigue
    # 由则问题转化为寻找一条路径 sum p / sum f >= r, 变形为 sum p - r * sum f >= 0
    # 设定新图的权重为 w = p - r * f,
    # 假设经过的城市数量 N > ||V||, 则问题转化为寻找权重最大环路

    def bellman_ford(W, r):
        fatigue = np.zeros(CITIY_NUM, dtype=float)
        predecessor = -1 * np.ones(CITIY_NUM, dtype=int)
        fatigue[0] = 0
        for i in range(1, CITIY_NUM - 1):
            fatigue[i] = np.inf
        # relax edges repeatedly
        for _ in range(CITIY_NUM - 1):
            for u in range(CITIY_NUM):
                for v in range(CITIY_NUM):
                    if fatigue[u] + W[u][v] < fatigue[v]:
                        fatigue[v] = fatigue[u] + W[u][v]
                        predecessor[v] = u
        # check for negative-weight cycles
        for u in range(CITIY_NUM):
            for v in range(CITIY_NUM):
                if u != v and fatigue[u] + W[u][v] < fatigue[v]:
                    cycle = []
                    # trace back the cycle
                    for _ in range(CITIY_NUM):
                        v = predecessor[v]
                    cycle_vertex = v
                    while True:
                        cycle.append(cycle_vertex)
                        cycle_vertex = predecessor[cycle_vertex]
                        if cycle_vertex == v or cycle_vertex == -1:
                            break
                    cycle.reverse()

                    # 计算环路的总利润
                    cycle_profit = 0
                    for i in range(len(cycle) - 1):
                        cycle_profit += PROFIT[cycle[i]][cycle[i + 1]]
                    cycle_profit += PROFIT[cycle[-1]][cycle[0]]

                    # 计算环路的总疲劳
                    cycle_fatigue = 0
                    for i in range(len(cycle) - 1):
                        cycle_fatigue += FATIGUE[cycle[i]][cycle[i + 1]]
                    cycle_fatigue += FATIGUE[cycle[-1]][cycle[0]]

                    # 计算环路的总利润/总疲劳
                    cycle_profit_per_fatigue = cycle_profit / cycle_fatigue

                    if cycle_profit_per_fatigue >= r:
                        return cycle, cycle_profit, cycle_fatigue, cycle_profit_per_fatigue
        return None

    # 二分查找最大利润 r
    EPS = 1
    cycle_result = None
    while profit_upper_bound - profit_lower_bound > EPS:
        r = (profit_upper_bound + profit_lower_bound) / 2

        # 构造新图
        # 新图的权重为 w = r * d - p
        # 问题转化为求负权环
        W = r * np.array(FATIGUE, dtype=float) - PROFIT

        # 快速检查是否不存在负权
        if not np.any(W < 0):
            profit_upper_bound = r
            continue

        # Bellman-Ford算法求解负权环
        result = bellman_ford(W, r)
        if result:
            cycle_result = result
            profit_lower_bound = r
        else:
            profit_upper_bound = r

    # print('基于以下参数搜索：')
    # print(f"容量: {CAPACITY}, 买入时数量调整系数: {BUY_LOT_MODIFIER}, 税率: {GENERAL_TAX}")
    # print('最佳环路', '->'.join([CITY_LIST[i] for i in cycle_result[0]]))
    # print(f"总利润: {cycle_result[1]}, 总疲劳: {cycle_result[2]}, 单位利润: {cycle_result[3]}")
    # print([CITY_LIST[i] for i in cycle_result[0]])
    return [CITY_LIST[i] for i in cycle_result[0]], cycle_result[1], cycle_result[2], cycle_result[3]


def t3_test(FATIGUE=None, PRODUCT_BUY_PRICES=None, PRODUCT_SELL_PRICES=None, CITY_LIST=None, GET_PRODUCT_LOTS=None,
            BOOK=0, CAPACITY=600,
            BUY_LOT_MODIFIER=3, GENERAL_TAX=0.05):
    # todo 完成新的跑商方案计算算法

    # 问题描述：有如下参数：
    # FATIGUE: 无向图，城市之间的疲劳，对称矩阵
    # PRODUCT_BUY_PRICES: 产品的买入价格，第一维是产品，第二维是城市。城市顺序与FATIGUE图城市顺序一致
    # PRODUCT_SELL_PRICES: 产品的卖出价格，第一维是产品，第二维是城市。城市顺序与FATIGUE图城市顺序一致
    # GET_PRODUCT_LOTS: 可买入的产品数量，第一维是产品，第二维是城市
    # CITY_LIST: 能够到达的城市列表，与FATIGUE图城市顺序一致
    # BOOK: 购买券数量
    # CAPACITY: 货舱大小
    # BUY_LOT_MODIFIER :购买数量修正参数
    # GENERAL_TAX ：手续费修正参数
    # 问题简述：有N个城市，每个城市有一定种类的商品售卖，现在求取一个环路使得此环路上的商品售卖收益最高
    # 限制条件：
    # 1：在购买一个城市商品时可以使用任意数量的购买券，一张购买券可以使得原本数量为num单位的商品存货增加num个单位
    # 2：一个城市的商品数量等于可买入的产品数量*购买数量修正参数*（使用的购买券的数量+1）
    # 3：在到达一个城市后需要卖出已有的全部商品
    # 4：商品的总的购买数量，不能超过货舱大小
    # 5：求取结果的环路所使用的购买券恰好等于设定的购买券数量
    # 6：商品售卖收益等于（（商品卖出价格-商品购买价格）*商品数量）*（1-手续费修正参数）/消耗疲劳

    """

    :param FATIGUE: 无向图，城市之间的疲劳，对称矩阵
    :param PRODUCT_BUY_PRICES: 产品的买入价格，第一维是产品，第二维是城市
    :param PRODUCT_SELL_PRICES: 产品的卖出价格，第一维是产品，第二维是城市
    :param CITY_LIST: 城市列表
    :param GET_PRODUCT_LOTS: 可买入的产品数量，第一维是产品，第二维是城市
    :param BOOK: 用几本书
    :param CAPACITY: 货舱大小
    :param BUY_LOT_MODIFIER :购买数量修正参数
    :param GENERAL_TAX ：手续费修正参数
    :return:
    """

    # part 1 构建对于无向图
    usecity = ["修格里城", "淘金乐园", "铁盟哨站", "荒原站", "曼德矿场", '澄明数据中心', "7号自由港",
               "阿妮塔战备工厂",
               "阿妮塔能源研究所", "阿妮塔发射中心"]
    with open("resource/setting/city_buy_inf.json", "r", encoding="utf-8") as f:
        city_product_recode = json.load(f)

    if not (PRODUCT_SELL_PRICES and PRODUCT_BUY_PRICES and GET_PRODUCT_LOTS and FATIGUE and CITY_LIST):
        CITY_LIST = ["修格里城", "淘金乐园", "铁盟哨站", "荒原站", "曼德矿场", '澄明数据中心', "7号自由港",
                     "阿妮塔战备工厂",
                     "阿妮塔能源研究所", "阿妮塔发射中心"]
        FATIGUE = np.array(pd.read_csv("resource/setting/城市路程疲劳表.csv", header=None).values.tolist())
        PRODUCT_SELL_PRICES = np.array(pd.read_csv("resource/setting/商品售出价格表.csv", header=None).values.tolist())
        PRODUCT_BUY_PRICES = np.array(pd.read_csv("resource/setting/商品收购价格表.csv", header=None).values.tolist())
        GET_PRODUCT_LOTS = np.array(pd.read_csv("resource/setting/商品数量价格表.csv", header=None).values.tolist())

    all_product_list = PRODUCT_SELL_PRICES[1:, 0].tolist()

    city_fatigue_map = FATIGUE[1:, 1:].astype(float).astype(int)
    product_sell_map = PRODUCT_SELL_PRICES[1:, 1:].astype(float).astype(int)
    product_buy_map = PRODUCT_BUY_PRICES[1:, 1:].astype(float).astype(int)
    product_num_map = GET_PRODUCT_LOTS[1:, 1:].astype(float).astype(int)

    def init_base_map(book=0, capacity=650):
        """
        此函数用于生成城市之间最高售卖收益的无向图（有书
        :param book: 用书量
        :param capacity: 载货限制
        :return: 城市之间最高售卖收益的无向图,整数部分为利润，小数部分为消耗疲劳
        """
        base_map = np.zeros([len(usecity), len(usecity)])

        for numi, i in enumerate(usecity):
            for numj, j in enumerate(usecity):
                if i == j:
                    base_map[numi][numj] = 0
                    continue
                product_list = []
                for k in city_product_recode[i]:
                    dis = ((product_buy_map[all_product_list.index(k)][usecity.index(j)] -
                            product_sell_map[all_product_list.index(k)][usecity.index(i)]))
                    buy_num = int(product_num_map[all_product_list.index(k)][usecity.index(i)])
                    if dis > 0:
                        product_list.append([k, buy_num, dis])
                else:
                    product_list.sort(key=lambda i: i[2], reverse=True)
                    # print(product_list)
                    income = 0
                    capacity = 0
                    for l in product_list:
                        if CAPACITY <= capacity:
                            break
                        income += l[2] * min(CAPACITY - capacity, l[1] * (book + 1) * BUY_LOT_MODIFIER)
                        capacity += min(CAPACITY - capacity, l[1] * (book + 1) * BUY_LOT_MODIFIER)
                # base_map[numi][numj] = int(income / city_fatigue_map[usecity.index(i)][usecity.index(j)])
                base_map[numi][numj] = float(f"{income}.{city_fatigue_map[usecity.index(i)][usecity.index(j)]}")
        return base_map

    def init_all_map(book_num):
        """
        此函数用于遍历生成所有用书可能的城市间最高收益无向图
        :param book_num: 用书量
        :return: list列表，元素为从book为0到book_num的所有城市间最高收益无向图
        """
        all_base_map = []
        for temp in range(book_num + 1):
            all_base_map.append(init_base_map(book=temp))
            np.savetxt(f"data_{temp}.csv", init_base_map(book=temp), delimiter=",", fmt='%.2f')
        return all_base_map


    def baoli(path_list=None):
        if path_list is None:
            path_list = []
        for i in usecity:
            temp_list = path_list.copy()
            if len(temp_list) >= 5 or len(temp_list) == 1:
                continue
            if i not in temp_list:
                temp_list.append(i)
                baoli(temp_list)
            elif i == temp_list[0]:
                all_result.append(temp_list)
                print(temp_list)
            else:
                continue

    def djk(matrix):
        new_matrix = np.matrix(np.ones((len(usecity),len(usecity)))*np.inf)
        new_matrix[0][0]=matrix[0][0]
        arrived_city = [0]
        arriving_city = []
      


    all_result = []
    matrix = init_base_map()
    print(matrix)




def t2(data=None):
    product = []
    city = []
    if not data:
        with open("resource/setting/price_inf.json", "r", encoding="utf-8") as f:
            data = json.load(f)

    product = [i["name"] for i in data if i["name"] not in product]

    usecity = ["修格里城", "淘金乐园", "铁盟哨站", "荒原站", "曼德矿场", '澄明数据中心', "7号自由港", "阿妮塔战备工厂",
               "阿妮塔能源研究所", "阿妮塔发射中心"]

    product_sell_map = np.zeros((len(product) + 1, len(usecity) + 1)).astype(str)
    product_sell_map[0, 0] = "cat"
    product_sell_map[1:, 0] = product
    product_sell_map[0, 1:] = usecity

    product_buy_map = np.zeros((len(product) + 1, len(usecity) + 1)).astype(str)
    product_buy_map[0, 0] = "cat"
    product_buy_map[1:, 0] = product
    product_buy_map[0, 1:] = usecity

    product_num_map = np.zeros((len(product) + 1, len(usecity) + 1)).astype(str)
    product_num_map[0, 0] = "cat"
    product_num_map[1:, 0] = product
    product_num_map[0, 1:] = usecity

    city_buy_inf = {i: [] for i in usecity}

    for i in data:
        if i["station"] not in usecity:
            continue
        if i["type"] == "buy":
            product_sell_map[product.index(i["name"]) + 1][usecity.index(i["station"]) + 1] = i["price"]

        elif i["type"] == "sell":
            product_num_map[product.index(i["name"]) + 1][usecity.index(i["station"]) + 1] = i["stock"]
            product_buy_map[product.index(i["name"]) + 1][usecity.index(i["station"]) + 1] = i["price"]
            city_buy_inf[i["station"]].append(i["name"])

    with open("resource/setting/city_buy_inf.json", "w", encoding="utf-8") as f:
        json.dump(city_buy_inf, f, ensure_ascii=False)

    pd.DataFrame(product_buy_map).to_csv(path_or_buf="resource/setting/商品售出价格表.csv", header=None, index=None)
    pd.DataFrame(product_sell_map).to_csv(path_or_buf="resource/setting/商品收购价格表.csv", header=None, index=None)
    pd.DataFrame(product_num_map).to_csv(path_or_buf="resource/setting/商品数量价格表.csv", header=None, index=None)

    city_tired_map = np.array(pd.read_csv("resource/setting/城市路程疲劳表.csv", header=None).values.tolist())

    # t3(FATIGUE=city_tired_map[1:, 1:], PRODUCT_BUY_PRICES=product_buy_map[1:, 1:],
    #    PRODUCT_SELL_PRICES=product_sell_map[1:, 1:], CITY_LIST=usecity, GET_PRODUCT_LOTS=product_num_map[1:, 1:],
    #    PRODUCTS_IDX_TO_NAME=None)
    return [city_tired_map, product_buy_map, product_sell_map, usecity, product_num_map]


def t1():
    try:
        print("")
        HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0'
        }
        # 注意请求不要太频繁
        data = requests.get(
            'https://reso-data.kmou424.moe/api/fetch/goods_info?uuid=5d9b7836-6474-4e44-881c-78ea9e116334',
            headers=HEADERS
        ).json()
        with open("resource/setting/price_inf.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except:
        print("获取更新失败，使用上次更新数据")
        with open("resource/setting/price_inf.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    return data


def t1_test():
    def askURL(url):
        head = {  # 模拟浏览器头部信息，向豆瓣服务器发送消息
            "User-Agent": "Mozilla / 5.0(Windows NT 10.0; Win64; x64) AppleWebKit / 537.36(KHTML, like Gecko) Chrome / 80.0.3987.122  Safari / 537.36"
        }
        # 用户代理，表示告诉豆瓣服务器，我们是什么类型的机器、浏览器（本质上是告诉浏览器，我们可以接收什么水平的文件内容）

        request = urllib.request.Request(url, headers=head)
        html = ""
        try:
            response = urllib.request.urlopen(request)
            html = response.read().decode("utf-8")
        except urllib.error.URLError as e:
            if hasattr(e, "code"):
                print(e.code)
            if hasattr(e, "reason"):
                print(e.reason)
        return html

    url = "https://www.resonance-columba.com/route"
    html = askURL(url)
    # print(soup)
    print(html)
    soup = BeautifulSoup(html, "html.parser")
    with open("test.html", 'w', encoding='utf-8') as f:
        f.write(html)


def temp():
    data = t1()
    inf = t2(data)
    result = t3(FATIGUE=inf[0][1:, 1:], PRODUCT_BUY_PRICES=inf[1][1:, 1:], PRODUCT_SELL_PRICES=inf[2][1:, 1:],
                CITY_LIST=inf[3], GET_PRODUCT_LOTS=inf[4][1:, 1:], PRODUCTS_IDX_TO_NAME=None)
    return result[3]


def print_scheme(book=0):
    print("开始计算跑商方案")
    # 创建对应参数表
    travel_list, scheme, income, fatigue, income_each_fatigue = calculation_scheme(book)
    print("计算方案完成")

    city_list = [i[0] for i in travel_list]
    city_list_CN = [base.city_name_transition(i) for i in city_list]
    book_list = [i[1] for i in travel_list]
    product_map = [i[1] for i in scheme]

    print("计划跑商方案城市为", "→".join(city_list_CN))
    print("利润：", income, "轮次疲劳消耗：", fatigue, "单位利润：", income_each_fatigue)
    print("具体购买商品↓")
    for i, j, k in zip(city_list, book_list, [[j[0] for j in i[1]] for i in scheme]):
        print("城市：", i, "使用", j, "本书；", "购买商品：", k)


def calculation_scheme(book=0):
    data = t1()

    inf = t2(data)

    result = t3(FATIGUE=inf[0][1:, 1:], PRODUCT_BUY_PRICES=inf[1][1:, 1:], PRODUCT_SELL_PRICES=inf[2][1:, 1:],
                CITY_LIST=inf[3], GET_PRODUCT_LOTS=inf[4][1:, 1:], PRODUCTS_IDX_TO_NAME=None)

    city_list = [base.city_name_transition(i) for i in result[0]]

    product_list = []
    for i in range(len(city_list)):
        product_list.append(
            t4_update(start_city=city_list[i % len(result[0])], end_city=city_list[(i + 1) % len(result[0])]))

    max_income, choose, best_scheme = t5(city_list, product_list, book=book, cargo_limit=650)
    return [[base.city_name_transition(name=i), j] for i, j in zip(result[0], choose)], best_scheme, max_income, result[
        2], max_income / result[2]


def update_product_inf():
    data = t1()
    inf = t2(data)
    return True


def get_columba_scheme():
    # todo 这里需要补充从科伦巴那边的方案
    pass





if __name__ == "__main__":
    t1_test()
