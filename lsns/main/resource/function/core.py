import json
import time
# import rich
from rich.console import Console
from rich.table import Column, Table
from rich import box
from win10toast import ToastNotifier

import resource.function.city_guide as guide
import resource.function.trade_action as trade
import resource.function.game_action as game
import resource.function.battle_action as battle
import resource.function.travel_action as travel
import resource.function.base_action as base
import resource.function.count_price as count

TN = ToastNotifier()



def program_plan():
    # todo:    "先读设置" √
    #     "可选部分更新"√
    #     "启动用户界面""不着急做"×
    #     "根据用户输入启动服务"√
    #     "计算方案"√
    #     "目前起码得有获取价格的工具，识别体力的部分，识别商品的部分，跑商启动条件 利润/疲劳大于 或者总利润大于某个数，或者疲劳要满了"“识别商品直接不做了，全部卖了”
    #     "清理澄明度要不默认清理，要不就得到固定城市刷材料""体力基本花在铁案局任务"
    #     “交给用户”
    #

    # todo 完成基础ui
    setting = inf_update()

    user_inf = setting["user_inf"]
    mission = setting["mission"]

    loc_city = setting["user_inf"]["loc_city"]
    #
    # while setting["user_inf"]["fatigue_limit"] - setting["user_inf"]["fatigue"] > 300 or setting["user_inf"][
    #     "fatigue"] < 50:
    #     business_traffic(setting, times=1)
    #     setting = inf_update(setting=setting, type=2)
    #     print(setting["user_inf"]["fatigue"])
    # while True:
    #     print("!")
    #     business_traffic(setting = setting, proposal=None)

    #
    daily_work(loc_city=loc_city, parm=3)
    setting = inf_update()
    game.clean_trade_mission(loc_city, setting["mission"]["human_transport"],
                             setting["mission"]["freight_transport"], setting["mission"]["purchase_transport"])


def program_plan_test():
    """
    todo 作为一个长时间的挂机测试函数，要求功能，全自动吃药，满足条件的跑商，自动清理任务,等胖虎有产能了再说
    :return:
    """
    # 开始部分，初始化基本用户参数
    setting = game.read_setting()

    # 进行用户信息更新
    setting = inf_update()
    user_inf = setting["user_inf"]
    mission = setting["mission"]
    sign = setting["sign"]

    while True:

        # if sign["daily_work"] and user_inf["san"] > 240 and user_inf["fatigue"] > 150 and user_inf["fatigue_limit"] - \
        #         user_inf["fatigue"] < 100:
        print("A")
        daily_work(loc_city=user_inf["loc_city"], parm=3)
        setting = inf_update()
        game.clean_trade_mission(setting["user_inf"]["loc_city"], setting["mission"]["human_transport"],
                                 setting["mission"]["freight_transport"], setting["mission"]["purchase_transport"])
        setting = inf_update()

        if count.temp() > 2200 and user_inf["fatigue"] < 500:
            print("B")
            business_traffic(setting, proposal=None)
            setting = inf_update()

        if (not sign["daily_work"]) and user_inf["san_limit"] - user_inf["san"] < 20 and base.get_city_inf(
                city=setting["user_inf"]["loc_city"], information="is_main"):
            print("C")
            battle.sell_and_buy(times=1, enemy=2, difficult=3)

        # base.sleep(600)


def inf_update(setting=None, type=3):  # 这个函数要移到game库里面
    if not setting:
        setting = game.read_setting()
    if type == 3:
        setting["user_inf"] = game.update_user_inf()
        setting["mission"] = game.update_mission_inf()
    elif type == 2:
        setting["user_inf"] = game.update_user_inf()
    elif type == 1:
        setting["mission"] = game.update_mission_inf()

    setting["time"] = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())

    with open("resource/setting/setting.json", "w", encoding="utf-8") as f:
        json.dump(setting, f, ensure_ascii=False)
    return setting


def daily_work(loc_city=None, parm=None):
    print("\033c", end="")
    print("开始清理日常（铁悬赏and商会任务")
    if not loc_city:
        print("未知城市，识别一下")
        guide.enter_city()
        loc_city = guide.searchcity()

        guide.backmain()
    if not parm:
        print("无任务参数，不进行执行")
        return False
    dayly_mission_travel = ["freeport", "clarity_data_center_administration_bureau", "shoggolith_city", "mander_mine","anita_rocket_base"]

    coust, travel_list = base.route_planning(start_city=loc_city, city_list=dayly_mission_travel)
    # 前往最近的有商会有悬赏任务的城市
    for i in range(len(travel_list) - 1):
        if travel_list[i] in dayly_mission_travel:
            if parm == 3:
                game.access_mission()
                game.clean_battle_mission(city_name=loc_city)
            elif parm == 2:
                game.access_mission()
            elif parm == 1:
                game.clean_battle_mission(city_name=loc_city)

            print("购买临时商品填补空缺")
            count.update_product_inf()
            temp_buy_list = count.t4(start_city=loc_city, end_city=travel_list[i])
            guide.enter_city()  # 开始购买商品
            guide.enter_exchange(cityname=loc_city)
            trade.sell_and_buy(buylist=[i[0] for i in temp_buy_list], buybook=0)

        travel.city_travel(startcity=travel_list[i], endcity=travel_list[i + 1])  # 导航到目标城市
        loc_city = travel_list[i + 1]

    setting = inf_update()

    game.clean_trade_mission(loc_city, setting["mission"]["human_transport"],
                             setting["mission"]["freight_transport"], setting["mission"]["purchase_transport"])


def business_traffic(setting=None, book=0, fatigue_limit=500):
    print("\033c", end="")
    if not setting:
        print("no setting")
        setting = inf_update()

    loc_city = setting["user_inf"]["loc_city"]

    money_real = setting["user_inf"]["money"]
    fatigue_real = setting["user_inf"]["fatigue"]
    income_expect = 0
    fatigue_expect = 0

    while setting["user_inf"]["fatigue"] < fatigue_limit:
        print("开始计算新一轮跑商方案")
        # 创建对应参数表
        travel_list, scheme, income, fatigue, income_each_fatigue = count.calculation_scheme(book)
        print("计算方案完成")

        city_list = [i[0] for i in travel_list]
        city_list_CN = [base.city_name_transition(i) for i in city_list]
        book_list = [i[1] for i in travel_list]
        product_map = [i[1] for i in scheme]
        product_list = [[j[0] for j in i] for i in product_map]

        income_expect += sum([i[0] for i in scheme])
        fatigue_expect += fatigue

        console = Console()
        table = Table(show_header=True, header_style="bold magenta", box=box.ASCII2, show_lines=True, expand=True)
        table.add_column("购买城市")
        table.add_column("购买商品")
        table.add_column("用书数量")
        table.add_column("预期收益")

        print("检索到方案：" + "->".join(city_list_CN) + "\n", "最高利润为:" + str(income) + "\n",
              "单位利润为:" + str(int(income_each_fatigue)) + "\n")
        print("商品购买详情↓")
        for i, j, k, h in zip([base.city_name_transition(i) for i in city_list], book_list,
                              [[j[0] for j in i[1]] for i in scheme], [i[0] for i in scheme]):
            table.add_row(str(i), " ".join(k), str(j), str(h))
        console.print(table)
        print("")
        print("5秒后开始行动")
        time.sleep(5)
        # 找一个最近的城市开始循环
        if loc_city not in city_list:
            print("开始导航到起始城市")
            aim_city = base.count_nearest_city(city=loc_city, citylist=city_list)
            buy_list = count.t4(start_city=loc_city, end_city=aim_city)  # 计算购买商品
            print("购买途中商品")
            guide.enter_city()  # 开始购买商品
            guide.enter_exchange(cityname=loc_city)
            trade.sell_and_buy(buylist=[i[0] for i in buy_list], buybook=0)
            travel.city_travel(startcity=loc_city, endcity=aim_city)  # 导航到目标城市
            loc_city = aim_city

        offset = city_list.index(loc_city)  # 计算后续循环偏移量
        for i in range(len(city_list)):
            print("购买以下商品：", product_list[i])
            guide.enter_city()  # 开始购买商品
            guide.enter_exchange(cityname=loc_city)

            trade.sell_and_buy(buylist=product_list[(i + offset) % len(city_list)],
                               buybook=book_list[(i + offset) % len(city_list)])

            print("购买完成，前往后续城市：", city_list[(i + 1 + offset) % len(city_list)])

            travel.city_travel(startcity=city_list[(i + offset) % len(city_list)],
                               endcity=city_list[(i + 1 + offset) % len(city_list)])

            loc_city = city_list[(i + 1 + offset) % len(city_list)]

        setting = inf_update(type=2)
        loc_city = setting["user_inf"]["loc_city"]

    else:
        guide.enter_city()  # 售出最后一批商品
        guide.enter_exchange(cityname=loc_city)
        trade.sellall()
        guide.backmain()



    setting = inf_update(type=2)
    money_release = setting["user_inf"]["money"]
    fatigue_release = setting["user_inf"]["fatigue"]
    print("\033c", end="")

    print("原预计消耗", fatigue_expect, "体力;", "预计赚取", income_expect, "铁盟币;",
          "利疲比为", income_expect / fatigue_expect)
    print("实际消耗", fatigue_release - fatigue_real, "体力;", "实际赚取", money_release - money_real, "铁盟币;",
          "利疲比为", (money_release - money_real) / (fatigue_release - fatigue_real))

    print(f"实际消耗疲劳比为：{((fatigue_release - fatigue_real) / fatigue_expect):.2f}%")
    print(f"实际赚取利润比为{((money_release - money_real) / income_expect):.2f}%")
    print(f"实际利疲比为{(((money_release - money_real) / (fatigue_release - fatigue_real)) / (income_expect / fatigue_expect)):.2f}%")
    input("按下任何键以继续")


def monitor_data_notice(book=0, income_set=-1, income_each_fatigue_set=4000):
    while True:
        print("开始计算跑商方案")
        # 创建对应参数表
        travel_list, scheme, income, fatigue, income_each_fatigue = count.calculation_scheme(book)
        print("计算方案完成")

        city_list = [i[0] for i in travel_list]
        city_list_CN = [base.city_name_transition(i) for i in city_list]

        notice = ""
        if income > income_set != -1:
            notice += "当前最高利润为:" + str(income) + "\n"
        if income_each_fatigue > income_each_fatigue_set  != 0:
            notice += "当前最高单位利润为:" + str(income_each_fatigue) + "\n"
        if notice != "":
            notice = "检索到方案：" + "->".join(city_list_CN) + "\n" + str(notice)
            print("当前最高利润为:" + str(income) + "\n", "当前最高单位利润为:" + str(income_each_fatigue) + "\n")
            TN.show_toast(title="跑商通知", msg=notice, icon_path="resource/template/action/favicon.ico", duration=10)
            break
        base.sleep(600)


def monitor_data(book=0):
    print("\033c", end="")

    print("开始计算跑商方案")
    # 创建对应参数表
    travel_list, scheme, income, fatigue, income_each_fatigue = count.calculation_scheme(book)
    print("计算方案完成")

    city_list = [i[0] for i in travel_list]
    city_list_CN = [base.city_name_transition(i) for i in city_list]
    book_list = [i[1] for i in travel_list]
    product_map = [i[1] for i in scheme]
    product_list = [[j[0] for j in i] for i in product_map]

    console = Console()
    table = Table(show_header=True, header_style="bold magenta", box=box.ASCII2, show_lines=True, expand=True)
    table.add_column("购买城市")
    table.add_column("购买商品")
    table.add_column("用书数量")
    table.add_column("预期收益")

    print("\033c", end="")
    print("检索到方案：" + "->".join(city_list_CN) + "\n", "最高利润为:" + str(income) + "\n",
          "单位利润为:" + str(int(income_each_fatigue)) + "\n")
    print("商品购买详情↓")
    for i, j, k, h in zip([base.city_name_transition(i) for i in city_list], book_list,
                          [[j[0] for j in i[1]] for i in scheme], [i[0] for i in scheme]):
        table.add_row(str(i), " ".join(k), str(j), str(h))
    console.print(table)
    input("按下任何键以继续")


def show_user_inf(setting=None):
    #包含理智，疲劳，金钱，有多少药，
    print("正在更新")
    if not setting:
        setting = inf_update()
    print("更新完成")
    console = Console()
    table = Table(show_header=True, header_style="bold magenta", box=box.ASCII2, show_lines=True, expand=True)
    table.add_column("类别")
    table.add_column("值")
    table.add_row("等级",str(setting["user_inf"]["lv"]))
    table.add_row("澄明度",str(setting["user_inf"]["san"])+"/"+str(setting["user_inf"]["san_limit"]))
    table.add_row("疲劳",str(setting["user_inf"]["fatigue"])+"/"+str(setting["user_inf"]["fatigue_limit"]))
    table.add_row("金钱",str(setting["user_inf"]["money"]))
    table.add_row("当前城市", str(base.city_name_transition(setting["user_inf"]["loc_city"])))
    table.add_row("仙人掌(小，中，大)",":".join([str(i) for i in setting["user_inf"]["fatigue_medicine"]]))
    table.add_row("口香糖(小，中，大)",":".join([str(i) for i in setting["user_inf"]["san_medicine"]]))
    if setting["mission"]["human_transport"]!=[]:
        table.add_row("人员运输任务：", setting["mission"]["human_transport"][0])
    if setting["mission"]["freight_transport"] != []:
        table.add_row("人员运输任务：", setting["mission"]["freight_transport"][0])
    if setting["mission"]["purchase_transport"] != []:
        table.add_row("人员运输任务：", setting["mission"]["purchase_transport"][0])
    print("\033c", end="")
    console.print(table)
    input("按下任何键以继续")

